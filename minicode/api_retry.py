"""API retry and exponential backoff for model adapters.

Handles transient failures (429, 5xx) with automatic retry,
exponential backoff, and Retry-After header respect.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
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
# Exceptions
# ---------------------------------------------------------------------------

class APIRetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""
    
    def __init__(self, message: str, attempts: int, last_error: Exception | None = None):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


# ---------------------------------------------------------------------------
# Backoff calculation
# ---------------------------------------------------------------------------

def calculate_backoff(
    attempt: int,
    retry_after: float | None = None,
    base: float = BASE_BACKOFF,
    max_wait: float = MAX_BACKOFF,
    jitter: float = JITTER_FACTOR,
) -> float:
    """Calculate backoff duration with exponential backoff and jitter.
    
    Args:
        attempt: Current retry attempt number (0-based)
        retry_after: Retry-After header value in seconds (if provided)
        base: Base backoff duration
        max_wait: Maximum backoff cap
        jitter: Jitter factor for randomization
    
    Returns:
        Seconds to wait before next retry
    """
    if retry_after is not None and retry_after > 0:
        # Respect Retry-After header
        return min(retry_after, max_wait)
    
    # Exponential backoff: base * 2^attempt
    backoff = base * (2 ** attempt)
    
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
            status_code = getattr(e, "status_code", None)
            
            # Check if error is retryable
            if status_code not in retryable_errors:
                # Non-retryable error, raise immediately
                raise
            
            state.attempts = attempt + 1
            state.last_error = str(e)
            
            # Check if we have more retries
            if attempt >= max_retries:
                raise APIRetryExhaustedError(
                    f"API call failed after {max_retries + 1} attempts: {e}",
                    attempts=attempt + 1,
                    last_error=e,
                )
            
            # Extract Retry-After header if available
            retry_after = getattr(e, "retry_after", None)
            
            # Calculate backoff
            wait_time = calculate_backoff(
                attempt,
                retry_after=retry_after,
                base=base_backoff,
                max_wait=max_backoff,
            )
            
            state.total_wait_time += wait_time
            
            # Notify retry callback
            if on_retry:
                on_retry(state)
            
            # Wait before retry
            time.sleep(wait_time)
        
        except Exception as e:
            # Non-HTTP error, don't retry
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
            status_code = getattr(e, "status_code", None)
            
            if status_code not in retryable_errors:
                raise
            
            state.attempts = attempt + 1
            state.last_error = str(e)
            
            if attempt >= max_retries:
                raise APIRetryExhaustedError(
                    f"API call failed after {max_retries + 1} attempts: {e}",
                    attempts=attempt + 1,
                    last_error=e,
                )
            
            retry_after = getattr(e, "retry_after", None)
            wait_time = calculate_backoff(
                attempt,
                retry_after=retry_after,
                base=base_backoff,
                max_wait=max_backoff,
            )
            
            state.total_wait_time += wait_time
            
            if on_retry:
                on_retry(state)
            
            await asyncio.sleep(wait_time)
        
        except Exception as e:
            raise


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def is_retryable_error(error: Exception, retryable_codes: set[int] = RETRYABLE_STATUS) -> bool:
    """Check if an error is retryable."""
    if isinstance(error, HTTPError):
        return error.status_code in retryable_codes
    return False


def format_retry_state(state: RetryState) -> str:
    """Format retry state for logging/display."""
    if state.succeeded:
        return f"✓ Succeeded on attempt {state.attempts}"
    else:
        return (
            f"✗ Failed after {state.attempts} attempts, "
            f"waited {state.total_wait_time:.1f}s total"
        )
