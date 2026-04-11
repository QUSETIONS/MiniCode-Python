"""API retry and exponential backoff for model adapters.

Handles transient failures (429, 5xx) with automatic retry,
exponential backoff, Retry-After header respect, and semantic
error classification with adaptive backoff strategies.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum retry attempts
MAX_RETRIES = 3

# Base backoff in seconds
BASE_BACKOFF = 1.0

# Maximum backoff cap (60 seconds)
MAX_BACKOFF = 60.0

# Jitter factor (0.5 means ±50% randomization)
JITTER_FACTOR = 0.5

# Retryable HTTP status codes
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Semantic error classification
# ---------------------------------------------------------------------------

class ErrorCategory(str, Enum):
    """Semantic classification of API errors.
    
    Each category has different retry characteristics:
    - RATE_LIMIT: Server is overloaded, back off aggressively
    - SERVER_ERROR: Transient server issue, moderate backoff
    - NETWORK_ERROR: Connection issue, quick retry
    - AUTH_ERROR: Credential issue, don't retry (likely permanent)
    - INPUT_ERROR: Bad request, don't retry (will fail again)
    - OVERLOAD: Model/server overloaded, longer backoff
    - UNKNOWN: Unclassified, use default backoff
    """
    RATE_LIMIT = "rate_limit"       # 429
    SERVER_ERROR = "server_error"   # 500, 502, 503, 504
    NETWORK_ERROR = "network_error" # Connection refused, timeout, DNS
    AUTH_ERROR = "auth_error"       # 401, 403
    INPUT_ERROR = "input_error"     # 400, 422
    OVERLOAD = "overload"           # 529, Anthropic-specific
    UNKNOWN = "unknown"


# Category-specific backoff multipliers
_CATEGORY_BACKOFF: dict[ErrorCategory, float] = {
    ErrorCategory.RATE_LIMIT: 2.0,    # Double base backoff for rate limits
    ErrorCategory.SERVER_ERROR: 1.0,  # Standard exponential
    ErrorCategory.NETWORK_ERROR: 0.5, # Quick retry for network glitches
    ErrorCategory.OVERLOAD: 3.0,      # Aggressive backoff for overload
    ErrorCategory.UNKNOWN: 1.0,       # Default
}

# Category-specific max retry overrides
_CATEGORY_MAX_RETRIES: dict[ErrorCategory, int | None] = {
    ErrorCategory.NETWORK_ERROR: 5,   # More retries for transient network issues
    ErrorCategory.OVERLOAD: 5,        # More retries for overload
    ErrorCategory.RATE_LIMIT: 4,      # A few more for rate limits
}

# Patterns in error messages that indicate overload
_OVERLOAD_PATTERNS = re.compile(
    r"(?:overloaded|overload|capacity|too many requests|"
    r"temporarily unavailable|please try again later|"
    r"service is currently unavailable|api is temporarily|"
    r"capacity exceeded|high demand)",
    re.IGNORECASE,
)

# Patterns indicating network-level errors
_NETWORK_ERROR_PATTERNS = re.compile(
    r"(?:connection\s*(?:refused|reset|timeout|aborted)|"
    r"timed?\s*out|dns\s*resolution|name\s*resolution|"
    r"network\s*(?:error|unreachable|down)|"
    r"socket\s*(?:error|closed)|eof\s*occurred|"
    r"ssl\s*error|certificate\s*verify|handshake\s*failed)",
    re.IGNORECASE,
)


def classify_error(error: Exception) -> ErrorCategory:
    """Classify an error into a semantic category for adaptive retry.
    
    Uses both HTTP status codes and error message patterns to determine
    the error category, enabling more intelligent retry decisions.
    """
    # Check HTTP status code first (most reliable)
    status_code = getattr(error, "status_code", None)
    
    if status_code is not None:
        if status_code == 429:
            return ErrorCategory.RATE_LIMIT
        if status_code == 529:
            return ErrorCategory.OVERLOAD
        if status_code in (401, 403):
            return ErrorCategory.AUTH_ERROR
        if status_code in (400, 422, 404, 405, 409, 413, 415):
            return ErrorCategory.INPUT_ERROR
        if status_code in (500, 502, 503, 504):
            # Check for overload in message
            msg = str(error).lower()
            if _OVERLOAD_PATTERNS.search(msg):
                return ErrorCategory.OVERLOAD
            return ErrorCategory.SERVER_ERROR
    
    # Check error message patterns for non-HTTP errors
    msg = str(error)
    if _NETWORK_ERROR_PATTERNS.search(msg):
        return ErrorCategory.NETWORK_ERROR
    if _OVERLOAD_PATTERNS.search(msg):
        return ErrorCategory.OVERLOAD
    
    # Check for common exception types
    error_type_name = type(error).__name__.lower()
    if any(name in error_type_name for name in ("timeout", "connection", "socket")):
        return ErrorCategory.NETWORK_ERROR
    
    return ErrorCategory.UNKNOWN


def is_retryable(category: ErrorCategory) -> bool:
    """Check if an error category is retryable."""
    return category in (
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.SERVER_ERROR,
        ErrorCategory.NETWORK_ERROR,
        ErrorCategory.OVERLOAD,
        ErrorCategory.UNKNOWN,
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class APIRetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""
    
    def __init__(
        self,
        message: str,
        attempts: int,
        last_error: Exception | None = None,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
    ):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error
        self.category = category


# ---------------------------------------------------------------------------
# Backoff calculation
# ---------------------------------------------------------------------------

def calculate_backoff(
    attempt: int,
    retry_after: float | None = None,
    base: float = BASE_BACKOFF,
    max_wait: float = MAX_BACKOFF,
    jitter: float = JITTER_FACTOR,
    category: ErrorCategory | None = None,
) -> float:
    """Calculate backoff duration with exponential backoff and jitter.
    
    Supports adaptive backoff based on error category:
    - RATE_LIMIT: 2x base, respects Retry-After
    - OVERLOAD: 3x base, longer waits
    - NETWORK_ERROR: 0.5x base, quick retries
    - SERVER_ERROR: standard exponential
    - Unknown: standard exponential
    
    Args:
        attempt: Current retry attempt number (0-based)
        retry_after: Retry-After header value in seconds (if provided)
        base: Base backoff duration
        max_wait: Maximum backoff cap
        jitter: Jitter factor for randomization
        category: Error category for adaptive backoff
    
    Returns:
        Seconds to wait before next retry
    """
    # Apply category-specific multiplier to base
    effective_base = base
    if category is not None:
        effective_base = base * _CATEGORY_BACKOFF.get(category, 1.0)
    
    if retry_after is not None and retry_after > 0:
        # Respect Retry-After header, but apply minimum from category
        min_wait = effective_base * (2 ** min(attempt, 2))
        return max(min(retry_after, max_wait), min_wait)
    
    # Exponential backoff: effective_base * 2^attempt
    backoff = effective_base * (2 ** attempt)
    
    # Add jitter: backoff * (1 ± jitter)
    jitter_range = backoff * jitter
    backoff = backoff + random.uniform(-jitter_range, jitter_range)
    
    # Ensure positive and capped
    return max(0.1, min(backoff, max_wait))


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

@dataclass
class RetryState:
    """Tracks retry state for monitoring."""
    attempts: int = 0
    max_attempts: int = MAX_RETRIES
    total_wait_time: float = 0.0
    last_error: str | None = None
    last_category: ErrorCategory = ErrorCategory.UNKNOWN
    category_history: list[ErrorCategory] = field(default_factory=list)
    succeeded: bool = False


def retry_with_backoff(
    func: Callable,
    *args: Any,
    max_retries: int = MAX_RETRIES,
    base_backoff: float = BASE_BACKOFF,
    max_backoff: float = MAX_BACKOFF,
    retryable_errors: set[int] = RETRYABLE_STATUS,
    on_retry: Callable[[RetryState], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Execute function with automatic retry and exponential backoff.
    
    Uses semantic error classification for adaptive retry:
    - Rate limits (429): aggressive backoff, respects Retry-After
    - Server errors (5xx): standard exponential backoff
    - Network errors: quick retry with more attempts
    - Auth/input errors: no retry (permanent)
    - Overload: longest backoff, most retries
    
    Args:
        func: Function to execute
        *args: Positional arguments for func
        max_retries: Maximum retry attempts
        base_backoff: Base backoff duration in seconds
        max_backoff: Maximum backoff cap in seconds
        retryable_errors: Set of HTTP status codes to retry on
        on_retry: Optional callback invoked on each retry
        **kwargs: Keyword arguments for func
    
    Returns:
        Result from successful function call
    
    Raises:
        APIRetryExhaustedError: When all retry attempts are exhausted
    """
    state = RetryState(max_attempts=max_retries)
    
    for attempt in range(max_retries + 1):
        try:
            result = func(*args, **kwargs)
            state.succeeded = True
            state.attempts = attempt + 1
            return result
        
        except HTTPError as e:
            # Classify the error semantically
            category = classify_error(e)
            state.last_category = category
            state.category_history.append(category)
            
            # Check if error category is retryable
            if not is_retryable(category):
                raise
            
            # Check category-specific max retries
            cat_max = _CATEGORY_MAX_RETRIES.get(category)
            effective_max = cat_max if cat_max is not None else max_retries
            
            state.attempts = attempt + 1
            state.last_error = str(e)
            
            if attempt >= effective_max:
                raise APIRetryExhaustedError(
                    f"API call failed after {attempt + 1} attempts "
                    f"(category: {category.value}): {e}",
                    attempts=attempt + 1,
                    last_error=e,
                    category=category,
                )
            
            # Extract Retry-After header if available
            retry_after = getattr(e, "retry_after", None)
            
            # Calculate adaptive backoff based on error category
            wait_time = calculate_backoff(
                attempt,
                retry_after=retry_after,
                base=base_backoff,
                max_wait=max_backoff,
                category=category,
            )
            
            state.total_wait_time += wait_time
            
            # Notify retry callback
            if on_retry:
                on_retry(state)
            
            # Wait before retry
            time.sleep(wait_time)
        
        except Exception as e:
            # Classify non-HTTP errors too
            category = classify_error(e)
            state.last_category = category
            state.category_history.append(category)
            
            if is_retryable(category) and attempt < max_retries:
                state.attempts = attempt + 1
                state.last_error = str(e)
                
                wait_time = calculate_backoff(
                    attempt,
                    base=base_backoff,
                    max_wait=max_backoff,
                    category=category,
                )
                state.total_wait_time += wait_time
                
                if on_retry:
                    on_retry(state)
                
                time.sleep(wait_time)
                continue
            
            # Non-retryable non-HTTP error
            raise


# ---------------------------------------------------------------------------
# HTTP Error wrapper
# ---------------------------------------------------------------------------

class HTTPError(Exception):
    """HTTP error with status code and optional Retry-After header."""
    
    def __init__(
        self,
        message: str,
        status_code: int,
        retry_after: float | None = None,
        response: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.response = response


def raise_for_status(response: Any, error_class: type[HTTPError] = HTTPError) -> None:
    """Check HTTP response status and raise error if needed.
    
    This is a generic wrapper that works with various HTTP libraries.
    Adapts to urllib, requests, httpx, etc.
    """
    status_code = getattr(response, "status", None) or getattr(response, "status_code", None)
    
    if status_code is None:
        return
    
    # Extract Retry-After header
    retry_after = None
    if hasattr(response, "getheader"):
        retry_after_str = response.getheader("Retry-After")
    elif hasattr(response, "headers"):
        retry_after_str = response.headers.get("Retry-After")
    else:
        retry_after_str = None
    
    if retry_after_str:
        try:
            retry_after = float(retry_after_str)
        except (ValueError, TypeError):
            pass
    
    # Check if error status
    if status_code >= 400:
        # Try to get error message from response body
        error_message = str(status_code)
        if hasattr(response, "read"):
            try:
                body = response.read().decode("utf-8", errors="replace")
                error_message = f"{status_code}: {body[:200]}"
            except Exception:
                pass
        elif hasattr(response, "text"):
            error_message = f"{status_code}: {response.text[:200]}"
        
        raise error_class(error_message, status_code, retry_after, response)


# ---------------------------------------------------------------------------
# Async-compatible wrapper (for future use)
# ---------------------------------------------------------------------------

async def retry_with_backoff_async(
    func: Callable,
    *args: Any,
    max_retries: int = MAX_RETRIES,
    base_backoff: float = BASE_BACKOFF,
    max_backoff: float = MAX_BACKOFF,
    retryable_errors: set[int] = RETRYABLE_STATUS,
    on_retry: Callable[[RetryState], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Async version of retry_with_backoff.
    
    Uses asyncio.sleep instead of time.sleep for non-blocking waits.
    Supports the same semantic error classification and adaptive backoff
    as the sync version.
    """
    import asyncio
    
    state = RetryState(max_attempts=max_retries)
    
    for attempt in range(max_retries + 1):
        try:
            # For async functions, await; for sync, just call
            if hasattr(func, "__await__"):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            state.succeeded = True
            state.attempts = attempt + 1
            return result
        
        except HTTPError as e:
            category = classify_error(e)
            state.last_category = category
            state.category_history.append(category)
            
            if not is_retryable(category):
                raise
            
            cat_max = _CATEGORY_MAX_RETRIES.get(category)
            effective_max = cat_max if cat_max is not None else max_retries
            
            state.attempts = attempt + 1
            state.last_error = str(e)
            
            if attempt >= effective_max:
                raise APIRetryExhaustedError(
                    f"API call failed after {attempt + 1} attempts "
                    f"(category: {category.value}): {e}",
                    attempts=attempt + 1,
                    last_error=e,
                    category=category,
                )
            
            retry_after = getattr(e, "retry_after", None)
            wait_time = calculate_backoff(
                attempt,
                retry_after=retry_after,
                base=base_backoff,
                max_wait=max_backoff,
                category=category,
            )
            
            state.total_wait_time += wait_time
            
            if on_retry:
                on_retry(state)
            
            await asyncio.sleep(wait_time)
        
        except Exception as e:
            category = classify_error(e)
            state.last_category = category
            state.category_history.append(category)
            
            if is_retryable(category) and attempt < max_retries:
                state.attempts = attempt + 1
                state.last_error = str(e)
                
                wait_time = calculate_backoff(
                    attempt,
                    base=base_backoff,
                    max_wait=max_backoff,
                    category=category,
                )
                state.total_wait_time += wait_time
                
                if on_retry:
                    on_retry(state)
                
                await asyncio.sleep(wait_time)
                continue
            
            raise


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def is_retryable_error(error: Exception, retryable_codes: set[int] = RETRYABLE_STATUS) -> bool:
    """Check if an error is retryable using semantic classification."""
    if isinstance(error, HTTPError):
        category = classify_error(error)
        return is_retryable(category)
    # Also check non-HTTP errors via classification
    return is_retryable(classify_error(error))


def format_retry_state(state: RetryState) -> str:
    """Format retry state for logging/display."""
    if state.succeeded:
        return f"✓ Succeeded on attempt {state.attempts}"
    
    cat_summary = ""
    if state.category_history:
        from collections import Counter
        counts = Counter(c.value for c in state.category_history)
        cat_summary = f" ({', '.join(f'{k}×{v}' for k, v in counts.most_common(3))})"
    
    return (
        f"✗ Failed after {state.attempts} attempts{cat_summary}, "
        f"waited {state.total_wait_time:.1f}s total"
    )
