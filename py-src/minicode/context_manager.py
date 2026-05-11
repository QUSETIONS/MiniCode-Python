"""Context manager for token estimation, message compaction, and progressive compression.

This module implements intelligent context window management to keep conversations
within token limits while preserving critical information for coding tasks.
"""

from __future__ import annotations

import json
import re
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from minicode.logging_config import get_logger
from minicode.working_memory import WorkingMemoryTracker, get_working_memory

logger = get_logger("context_manager")

# ---------------------------------------------------------------------------
# Token estimation utilities
# ---------------------------------------------------------------------------

# Thread-safe LRU cache for token estimation
class _TokenCache:
    """Thread-safe LRU cache for token estimation with periodic cleanup."""

    def __init__(self, max_size: int = 10000, ttl: float = 300.0):
        self._cache: OrderedDict = OrderedDict()
        self._timestamps: dict = {}
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key) -> int | None:
        with self._lock:
            if key in self._cache:
                # Check TTL
                if time.time() - self._timestamps[key] > self._ttl:
                    del self._cache[key]
                    del self._timestamps[key]
                    return None
                # Move to end (LRU)
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key, value: int) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            self._timestamps[key] = time.time()
            # Evict oldest if over limit
            while len(self._cache) > self._max_size:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
                del self._timestamps[oldest]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._timestamps.clear()

    def cleanup_expired(self) -> None:
        """Remove expired entries."""
        now = time.time()
        with self._lock:
            expired = [k for k, ts in self._timestamps.items() if now - ts > self._ttl]
            for k in expired:
                del self._cache[k]
                del self._timestamps[k]

_token_cache = _TokenCache(max_size=10000, ttl=300.0)

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def estimate_tokens(text: str) -> int:
    """Fast token estimation with thread-safe LRU cache.
    
    Heuristic token counting based on character distribution:
    - CJK characters: ~1.5 chars per token
    - ASCII characters: ~4 chars per token
    
    Performance: Uses regex for fast CJK detection + LRU cache with TTL.
    """
    if not text:
        return 0
    
    # Cache lookup (short strings as key, long strings by hash)
    cache_key = text if len(text) < 256 else hash(text)
    cached = _token_cache.get(cache_key)
    if cached is not None:
        return cached
    
    # Use regex for fast CJK detection
    cjk_count = len(_CJK_PATTERN.findall(text))
    ascii_chars = len(text) - cjk_count
    
    result = max(1, int(cjk_count / 1.5 + ascii_chars / 4.0))
    
    _token_cache.put(cache_key, result)
    return result


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens for a single message."""
    tokens = 0
    
    # Role overhead
    role = message.get("role", "")
    if role == "system":
        tokens += 3
    elif role == "user":
        tokens += 4
    elif role == "assistant":
        tokens += 3
    elif role == "assistant_tool_call":
        tokens += 7
    elif role == "tool_result":
        tokens += 6
    elif role == "assistant_progress":
        tokens += 3
    
    # Content tokens
    content = message.get("content", "")
    if isinstance(content, str):
        tokens += estimate_tokens(content)
    
    # Tool call input/output
    if "input" in message:
        input_str = json.dumps(message["input"]) if isinstance(message["input"], dict) else str(message["input"])
        tokens += estimate_tokens(input_str)
    
    return tokens


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of messages."""
    return sum(estimate_message_tokens(msg) for msg in messages)


def clear_token_cache() -> None:
    """Clear the token estimation cache."""
    _token_cache.clear()


@dataclass
class _ExtractedInfo:
    """Information extracted from removed messages during summarization."""
    user_intents: list[str] = field(default_factory=list)
    file_paths: set[str] = field(default_factory=set)
    key_tool_results: list[str] = field(default_factory=list)
    assistant_conclusions: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)


# Tool categories for classification
_EDIT_TOOLS = frozenset({"edit_file", "write_file", "modify_file", "patch_file", "multi_edit"})
_READ_TOOLS = frozenset({"read_file", "list_files", "grep_files", "file_tree"})
_SEARCH_TOOLS = frozenset({"grep_files", "find_symbols", "find_references", "web_search", "web_fetch"})
_COMMAND_TOOLS = frozenset({"run_command", "execute_command", "bash"})

# Regex for extracting code-like content and decisions
_CODE_FENCE_RE = re.compile(r'```[\w]*\n(.{20,300}?)```', re.DOTALL)
_DECISION_KEYWORDS = re.compile(
    r'(?:decided|decision|chose|chosen|will use|using|switching to|'
    r'implemented|fixed|resolved|refactored|migrated|upgraded|'
    r'recommend|should|must|need to|going to|plan to|'
    r'approach:|strategy:|solution:|conclusion:)',
    re.IGNORECASE,
)


def _extract_from_messages(messages: list[dict[str, Any]]) -> _ExtractedInfo:
    """Extract structured information from messages for layered summarization."""
    info = _ExtractedInfo()
    
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        if role == "user" and content:
            if len(content) < 200:  # Likely a task or question
                info.user_intents.append(content)
        
        elif role == "assistant" and content:
            # Extract decisions and conclusions
            if _DECISION_KEYWORDS.search(content):
                info.decisions.append(content[:150])
            if len(content) > 100:  # Likely contains conclusions
                info.assistant_conclusions.append(content[-100:])
        
        elif role == "assistant_tool_call":
            tool_name = msg.get("toolName", "")
            if tool_name:
                info.tool_names.append(tool_name)
        
        elif role == "tool_result" and content:
            # Keep successful file operation confirmations
            if not msg.get("isError", False):
                if any(tool in str(content).lower() for tool in ["saved", "created", "updated", "modified"]):
                    info.key_tool_results.append(str(content)[:100])
            
            # Extract code snippets from tool results
            code_matches = _CODE_FENCE_RE.findall(str(content))
            for code in code_matches[:2]:  # Keep up to 2 snippets
                if len(code) < 200:
                    info.code_snippets.append(code)
            
            # Extract file paths
            path_matches = re.findall(r'(?:in|at|from|path:?)\s+([/\w\.\-]+)', str(content))
            info.file_paths.update(path_matches)
    
    return info


# ---------------------------------------------------------------------------
# Context Manager class
# ---------------------------------------------------------------------------

# Compaction levels: level -> target_percentage
_COMPACTION_LEVELS = {0: 0.7, 1: 0.5, 2: 0.3}


@dataclass
class ContextStats:
    """Statistics about the current context."""
    total_tokens: int = 0
    context_window: int = 0
    num_messages: int = 0
    usage_pct: float = 0.0
    should_compact: bool = False
    compaction_level: int = 0


class ContextManager:
    """Manages context window size and progressive message compression.
    
    Implements multi-level compaction with semantic-aware tool pairing:
    - Level 0: 70% of context window (first compaction)
    - Level 1: 50% of context window (second compaction)
    - Level 2+: 30% of context window (deep compaction)
    
    Features incremental token counting and periodic cache cleanup.
    """
    
    _COMPACTION_LEVELS = {0: 0.7, 1: 0.5, 2: 0.3}
    
    def __init__(
        self,
        messages: list[dict[str, Any]],
        context_window: int = 200000,
        working_memory: WorkingMemoryTracker | None = None,
    ):
        self.messages = messages
        self.context_window = context_window
        self._compaction_level = 0
        # Incremental token count
        self._total_tokens: int | None = None
        self._last_compaction_time: float = 0
        self._working_memory = working_memory or get_working_memory()
    
    def get_stats(self) -> ContextStats:
        """Get context statistics with incremental counting."""
        if self._total_tokens is None:
            self._total_tokens = estimate_messages_tokens(self.messages)
        
        usage_pct = self._total_tokens / self.context_window if self.context_window > 0 else 1.0
        
        return ContextStats(
            total_tokens=self._total_tokens,
            context_window=self.context_window,
            num_messages=len(self.messages),
            usage_pct=usage_pct,
            should_compact=usage_pct >= 0.75,
            compaction_level=self._compaction_level,
        )
    
    def _update_token_count(self, delta: int) -> None:
        """Incrementally update token count."""
        if self._total_tokens is not None:
            self._total_tokens += delta
    
    def reset_token_count(self) -> None:
        """Reset incremental token count (forces recalculation)."""
        self._total_tokens = None
    
    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message with incremental token tracking."""
        tokens = estimate_message_tokens(message)
        self.messages.append(message)
        self._update_token_count(tokens)
    
    def remove_message(self, index: int) -> int:
        """Remove a message and return token delta."""
        if 0 <= index < len(self.messages):
            tokens = estimate_message_tokens(self.messages[index])
            del self.messages[index]
            self._update_token_count(-tokens)
            return tokens
        return 0
    
    def compact_messages(self) -> list[dict[str, Any]]:
        """Compact messages to fit within context window.
        
        Multi-level progressive compression with incremental token tracking.
        """
        stats = self.get_stats()
        if not stats.should_compact:
            return self.messages
        
        # Periodic cache cleanup during compaction
        _token_cache.cleanup_expired()
        
        target_pct = self._COMPACTION_LEVELS[min(self._compaction_level, 2)]
        target_tokens = int(self.context_window * target_pct)
        
        # Always keep system prompt
        system_messages = [m for m in self.messages if m.get("role") == "system"]
        other_messages = [m for m in self.messages if m.get("role") != "system"]
        
        # Phase 1: Remove progress messages
        filtered = [
            m for m in other_messages
            if m.get("role") != "assistant_progress"
        ]
        
        self._total_tokens = estimate_messages_tokens(system_messages + filtered)
        if self._total_tokens <= target_tokens:
            return self._finalize_compaction(
                system_messages, other_messages, filtered, stats, target_tokens
            )
        
        # Phase 2: Truncate large tool results
        _READ_TOOL_TRUNCATE = 1500
        _EDIT_TOOL_TRUNCATE = 3000
        _ERROR_TRUNCATE = 4000
        _DEFAULT_TRUNCATE = 2000
        
        for i, m in enumerate(filtered):
            if m.get("role") != "tool_result":
                continue
            content = m.get("content", "")
            if not content or len(content) <= _DEFAULT_TRUNCATE:
                continue
            
            tool_name = m.get("toolName", "")
            is_error = m.get("isError", False)
            
            if is_error:
                threshold = _ERROR_TRUNCATE
            elif tool_name in _EDIT_TOOLS:
                threshold = _EDIT_TOOL_TRUNCATE
            elif tool_name in _READ_TOOLS:
                threshold = _READ_TOOL_TRUNCATE
            else:
                threshold = _DEFAULT_TRUNCATE
            
            if len(content) <= threshold:
                continue
            
            content_lines = content.split("\n")
            head_lines: list[str] = []
            tail_lines: list[str] = []
            head_chars = 0
            
            for line in content_lines:
                if head_chars + len(line) + 1 > threshold * 0.7:
                    break
                head_lines.append(line)
                head_chars += len(line) + 1
            
            tail_chars = 0
            for line in reversed(content_lines):
                if tail_chars + len(line) + 1 > threshold * 0.3:
                    break
                tail_lines.insert(0, line)
                tail_chars += len(line) + 1
            
            omitted = len(content_lines) - len(head_lines) - len(tail_lines)
            truncated_content = "\n".join(head_lines)
            if omitted > 0:
                truncated_content += f"\n... [{omitted} lines truncated for compaction] ...\n"
            truncated_content += "\n".join(tail_lines)
            
            filtered[i] = {**m, "content": truncated_content}
        
        self._total_tokens = estimate_messages_tokens(system_messages + filtered)
        if self._total_tokens <= target_tokens:
            return self._finalize_compaction(
                system_messages, other_messages, filtered, stats, target_tokens
            )
        
        # Phase 3: Compress tool_call + result pairs
        compressed: list[dict[str, Any]] = []
        i = 0
        while i < len(filtered):
            msg = filtered[i]
            
            if (msg.get("role") == "assistant_tool_call" and
                    i + 1 < len(filtered) and
                    filtered[i + 1].get("role") == "tool_result"):
                
                call_msg = msg
                result_msg = filtered[i + 1]
                summary = self._compress_tool_pair(call_msg, result_msg)
                
                compressed.append({
                    "role": "assistant",
                    "content": summary,
                })
                i += 2
            else:
                compressed.append(msg)
                i += 1
        
        self._total_tokens = estimate_messages_tokens(system_messages + compressed)
        if self._total_tokens <= target_tokens:
            return self._finalize_compaction(
                system_messages, other_messages, compressed, stats, target_tokens
            )
        
        # Phase 4: Priority-based removal
        PRIORITY = {
            "user": 0,
            "assistant": 1,
            "assistant_tool_call": 2,
            "tool_result": 3,
        }
        
        PROTECTED_RECENT = 6
        
        while estimate_messages_tokens(compressed) > target_tokens and len(compressed) > MIN_MESSAGES_TO_KEEP:
            removable_end = max(MIN_MESSAGES_TO_KEEP, len(compressed) - PROTECTED_RECENT)
            best_idx = None
            best_priority = -1
            
            for idx in range(removable_end):
                role = compressed[idx].get("role", "")
                priority = PRIORITY.get(role, 1)
                if priority > best_priority:
                    best_priority = priority
                    best_idx = idx
            
            if best_idx is None:
                break
            
            del compressed[best_idx]
        
        return self._finalize_compaction(
            system_messages, other_messages, compressed, stats, target_tokens
        )
    
    @staticmethod
    def _compress_tool_pair(call_msg: dict[str, Any], result_msg: dict[str, Any]) -> str:
        """Compress a tool_call + tool_result pair into a compact inline summary."""
        tool_name = call_msg.get("toolName", "unknown")
        result_content = result_msg.get("content", "")
        is_error = result_msg.get("isError", False)
        
        # Extract key info from tool call
        tool_input = call_msg.get("input", {})
        
        if is_error:
            # For errors, preserve the error message
            error_snippet = str(result_content)[:200]
            return f"[{tool_name}] ERROR: {error_snippet}"
        
        if tool_name in _READ_TOOLS:
            # Read operations: summarize what was read
            file_path = tool_input.get("file_path", tool_input.get("path", "unknown"))
            return f"[{tool_name}] Read: {file_path}"
        
        if tool_name in _EDIT_TOOLS:
            # Edit operations: preserve file path and confirm success
            file_path = tool_input.get("file_path", tool_input.get("path", "unknown"))
            return f"[{tool_name}] Edited: {file_path} (success)"
        
        if tool_name in _COMMAND_TOOLS:
            # Commands: show command and result status
            cmd = tool_input.get("command", "unknown")
            return f"[{tool_name}] Ran: {cmd[:50]}"
        
        # Generic: show tool name and brief result
        result_brief = str(result_content)[:100]
        return f"[{tool_name}] {result_brief}"
    
    def _finalize_compaction(
        self,
        system_messages: list[dict[str, Any]],
        old_messages: list[dict[str, Any]],
        new_messages: list[dict[str, Any]],
        old_stats: ContextStats,
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        """Finalize compaction: update state and log results."""
        final_messages = system_messages + new_messages

        # Inject working memory as a system message to preserve critical context
        protected = self._working_memory.get_protected_content()
        if protected:
            wm_text = "\n".join(protected)
            wm_message = {
                "role": "system",
                "content": f"[Working Memory - Critical context preserved during compaction]\n{wm_text}",
            }
            wm_tokens = estimate_message_tokens(wm_message)
            # Only inject if it fits within target
            current_tokens = estimate_messages_tokens(final_messages)
            if current_tokens + wm_tokens <= target_tokens:
                # Insert after the first system message (or at beginning)
                if final_messages and final_messages[0].get("role") == "system":
                    final_messages.insert(1, wm_message)
                else:
                    final_messages.insert(0, wm_message)
                logger.debug("Injected working memory: %d tokens", wm_tokens)

        # Update incremental token count
        self._total_tokens = estimate_messages_tokens(final_messages)
        self._compaction_level += 1
        self.messages = final_messages
        self._last_compaction_time = time.time()

        # Log compaction results
        new_stats = self.get_stats()
        removed_count = len(old_messages) - len(new_messages)

        logger.info(
            f"Context compaction level {self._compaction_level}: "
            f"Removed {removed_count} messages, "
            f"Tokens: {old_stats.total_tokens} -> {new_stats.total_tokens} "
            f"(target: {target_tokens}, usage: {new_stats.usage_pct:.0%})"
        )

        return final_messages
    
    def force_compact(self) -> list[dict[str, Any]]:
        """Force compaction regardless of usage percentage."""
        # Set compaction level to trigger aggressive compression
        self._compaction_level = max(self._compaction_level, 1)
        return self.compact_messages()


def summarize_for_compaction(
    messages: list[dict[str, Any]],
    target_tokens: int,
) -> str:
    """Create a summary of removed messages to preserve key context.
    
    Extracts user intents, file paths, decisions, and key outcomes
    from messages that are being removed during compaction.
    """
    extracted = _extract_from_messages(messages)
    
    summary_parts: list[str] = []
    
    # Add user intents
    if extracted.user_intents:
        summary_parts.append("User Tasks:")
        for intent in extracted.user_intents:
            summary_parts.append(f"- {intent}")
    
    # Add decisions
    if extracted.decisions:
        summary_parts.append("\nKey Decisions:")
        for decision in extracted.decisions:
            summary_parts.append(f"- {decision}")
    
    # Add file operations
    if extracted.key_tool_results:
        summary_parts.append("\nFile Operations:")
        for result in extracted.key_tool_results:
            summary_parts.append(f"- {result}")
    
    # Add assistant conclusions
    if extracted.assistant_conclusions:
        summary_parts.append("\nConclusions:")
        for conclusion in extracted.assistant_conclusions:
            summary_parts.append(f"- {conclusion}")
    
    # Add code snippets
    if extracted.code_snippets:
        summary_parts.append("\nCode Context:")
        for snippet in extracted.code_snippets:
            summary_parts.append(f"```{snippet}```")
    
    return "\n".join(summary_parts)


def safe_get_claude_config() -> dict[str, Any]:
    """Safely read CLAUDE.md without crashing on encoding errors."""
    cwd = os.getcwd()
    config_path = os.path.join(cwd, "CLAUDE.md")
    
    if not os.path.exists(config_path):
        return {}
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, PermissionError, OSError) as e:
        logger.warning(f"Failed to read CLAUDE.md: {e}")
        return {}
    
    # Validate content
    if not content.strip():
        return {}
    
    # Limit size
    max_chars = 50000
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[... truncated ...]"
    
    return {
        "path": config_path,
        "content": content,
        "chars": len(content),
    }


# Minimum messages to keep (system prompt + at least 1 exchange)
MIN_MESSAGES_TO_KEEP = 3
