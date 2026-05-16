"""Claude Code-style Context Management System for MiniCode.

Implements the three-tier context management architecture:

1. **Pre-request lightweight optimization chain**:
   - Read deduplication (hash-based file content dedup)
   - Tool result budget (large output persistence + preview replacement)
   - Time-based microcompact (old tool result cleanup)

2. **Auto Compact high-water dispatcher**:
   - Session Memory Compact (uses existing memory entries as summary base)
   - Full Compact (model-generated summary with new baseline)
   - Circuit breaker (3 consecutive failures = stop)

3. **Reactive Compact error recovery**:
   - Prompt-too-long recovery path
   - Media-size error recovery
   - Fallback to user-visible error

Architecture reference: compact(5).md (Claude Code source analysis)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------


class CompactTrigger(str, Enum):
    """How the compaction was triggered."""
    MANUAL = "manual"
    AUTO = "auto"
    REACTIVE = "reactive"
    MICROCOMPACT_TIME = "microcompact_time"
    MICROCOMPACT_CACHED = "microcompact_cached"


class CompactStrategy(str, Enum):
    """Compaction strategy used."""
    SESSION_MEMORY = "session_memory"
    FULL = "full"
    PARTIAL = "partial"
    MICROCOMPACT = "microcompact"
    TOOL_BUDGET = "tool_budget"
    READ_DEDUP = "read_dedup"
    REACTIVE = "reactive"


@dataclass
class CompactBoundary:
    """Marks a compaction point in conversation history.

    After compaction, the active context view starts from the last boundary.
    The boundary itself is metadata, not model-visible content.
    """
    trigger: CompactTrigger
    strategy: CompactStrategy
    timestamp: float = field(default_factory=time.time)
    tokens_before: int = 0
    tokens_after: int = 0
    messages_removed: int = 0
    logical_parent_id: str | None = None
    preserved_segment: tuple[int, int] | None = None  # (start, end) message indices kept

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger.value,
            "strategy": self.strategy.value,
            "timestamp": self.timestamp,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "messages_removed": self.messages_removed,
            "logical_parent_id": self.logical_parent_id,
            "preserved_segment": list(self.preserved_segment) if self.preserved_segment else None,
        }


@dataclass
class CompactionResult:
    """Result of a compaction operation."""
    success: bool
    strategy: CompactStrategy
    trigger: CompactTrigger
    messages: list[dict[str, Any]]
    boundary: CompactBoundary | None = None
    tokens_freed: int = 0
    summary_text: str = ""
    error: str = ""

    @property
    def effective(self) -> bool:
        return self.success and self.tokens_freed > 0


@dataclass
class ToolResultPersisted:
    """A tool result that was persisted to disk."""
    original_size: int
    persisted_path: Path
    preview_text: str
    tool_name: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ReadDedupEntry:
    """Tracks a file read for deduplication."""
    file_path: str
    content_hash: str
    timestamp: float
    message_index: int  # Index in messages where full content lives


@dataclass
class MicrocompactState:
    """State for microcompact operations."""
    last_time_based_compact: float = 0.0
    time_based_interval: float = 3600.0  # Default 1 hour
    keep_recent_tool_results: int = 5
    total_tokens_cleared: int = 0


@dataclass
class AutoCompactConfig:
    """Configuration for Auto Compact dispatcher."""
    enabled: bool = True
    threshold_ratio: float = 0.85  # 85% of context window
    circuit_breaker_limit: int = 3
    session_memory_enabled: bool = True
    min_keep_tokens: int = 10000  # At least 10k tokens after compact
    min_keep_messages: int = 5  # At least 5 text messages
    max_expand_tokens: int = 40000  # Max expansion for tail preservation


# ---------------------------------------------------------------------------
# Phase 2: Tool Result Budget
# ---------------------------------------------------------------------------


class ToolResultBudgetManager:
    """Manages tool result size budget with disk persistence.

    When a tool_result exceeds the per-message budget, it is persisted
    to disk and replaced with a preview stub in the context.
    """

    DEFAULT_BUDGET_PER_MESSAGE = 8000  # chars per user message's tool results
    PERSIST_THRESHOLD = 4000  # Persist results larger than this
    PREVIEW_MAX_CHARS = 500

    def __init__(
        self,
        workspace: str | Path | None = None,
        budget_per_message: int = DEFAULT_BUDGET_PER_MESSAGE,
        persist_threshold: int = PERSIST_THRESHOLD,
    ):
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._budget = budget_per_message
        self._persist_threshold = persist_threshold
        self._results_dir = self._workspace / ".mini-code-tool-results"
        self._persisted: dict[str, ToolResultPersisted] = {}

    def check_and_replace(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """Check tool results against budget, persist oversized ones.

        Returns:
            Tuple of (modified_messages, total_bytes_saved)
        """
        if not self._results_dir.exists():
            self._results_dir.mkdir(parents=True, exist_ok=True)

        modified = list(messages)
        bytes_saved = 0

        for i, msg in enumerate(modified):
            if msg.get("role") != "tool_result":
                continue

            content = msg.get("content", "")
            content_size = len(content)

            if content_size <= self._persist_threshold:
                continue

            tool_name = msg.get("toolName", "unknown")
            persisted = self._persist_content(content, tool_name, i)

            preview = self._generate_preview(content, tool_name, persisted.persisted_path)
            modified[i] = {**msg, "content": preview, "_persisted_path": str(persisted.persisted_path)}
            self._persisted[f"{i}-{tool_name}"] = persisted
            bytes_saved += content_size - len(preview)

        return modified, bytes_saved

    def _persist_content(
        self, content: str, tool_name: str, index: int
    ) -> ToolResultPersisted:
        """Persist content to disk atomically."""
        safe_name = f"{tool_name}_{index}_{int(time.time() * 1000)}.txt"
        path = self._results_dir / safe_name

        meta = {
            "tool_name": tool_name,
            "message_index": index,
            "original_size": len(content),
            "timestamp": time.time(),
        }
        header = json.dumps(meta, ensure_ascii=False) + "\n---CONTENT---\n"

        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._results_dir), prefix=".tool_result_", suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(header)
                f.write(content)
            os.replace(tmp_path, str(path))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return ToolResultPersisted(
            original_size=len(content),
            persisted_path=path,
            preview_text="",
            tool_name=tool_name,
        )

    def _generate_preview(
        self, content: str, tool_name: str, path: Path
    ) -> str:
        """Generate preview text for persisted content."""
        lines = content.splitlines()
        head_lines = lines[:8]
        tail_lines = lines[-3:] if len(lines) > 12 else []

        parts = [
            f"[Tool result persisted to disk — {len(content)} chars]",
            f"Tool: {tool_name}",
            f"Path: {path.name}",
            "",
            "--- Preview (first/last lines) ---",
        ]
        parts.extend(head_lines)
        if tail_lines:
            parts.append(f"... ({len(lines) - len(head_lines) - len(tail_lines)} lines omitted) ...")
            parts.extend(tail_lines)

        preview = "\n".join(parts)
        return preview[:self.PREVIEW_MAX_CHARS]

    def get_persisted_count(self) -> int:
        return len(self._persisted)

    def get_total_saved_bytes(self) -> int:
        return sum(r.original_size for r in self._persisted.values())


# ---------------------------------------------------------------------------
# Phase 3: Read Deduplication
# ---------------------------------------------------------------------------


class ReadDedupManager:
    """Hash-based file read deduplication.

    When the same file (same path + same content hash) is read again,
    returns a stub instead of re-injecting full content into context.
    """

    def __init__(self):
        self._entries: dict[str, ReadDedupEntry] = {}  # file_path -> entry
        self._stub_template = (
            "File unchanged since last read. "
            "The content from the earlier Read tool_result "
            "in this conversation is still current — refer to that instead."
        )

    def register_read(
        self, file_path: str, content: str, message_index: int
    ) -> bool:
        """Register a file read. Returns True if this is a new/different read."""
        content_hash = hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()

        existing = self._entries.get(file_path)
        if existing and existing.content_hash == content_hash:
            return False  # Duplicate

        self._entries[file_path] = ReadDedupEntry(
            file_path=file_path,
            content_hash=content_hash,
            timestamp=time.time(),
            message_index=message_index,
        )
        return True  # New or changed

    def should_dedup(self, file_path: str, content: str) -> bool:
        """Check if this read can be deduplicated."""
        content_hash = hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()
        existing = self._entries.get(file_path)
        return existing is not None and existing.content_hash == content_hash

    def get_stub(self, file_path: str) -> str:
        """Get dedup stub for a previously-read file."""
        entry = self._entries.get(file_path)
        if not entry:
            return ""
        return (
            f"[Read deduplicated: {file_path}]\n"
            f"{self._stub_template}\n"
            f"(Original content at message index {entry.message_index})"
        )

    def invalidate(self, file_path: str) -> None:
        """Invalidate cache for a specific file (e.g., after write)."""
        self._entries.pop(file_path, None)

    def clear(self) -> None:
        self._entries.clear()


# ---------------------------------------------------------------------------
# Phase 4: Time-based Microcompact
# ---------------------------------------------------------------------------


class MicrocompactEngine:
    """Lightweight pre-compact optimization.

    Clears old tool results when they're unlikely to be in prompt cache
    anymore (time-based), reducing rewrite cost on next API call.
    """

    def __init__(self, config: MicrocompactState | None = None):
        self._state = config or MicrocompactState()

    def run_time_based_microcompact(
        self,
        messages: list[dict[str, Any]],
        now: float | None = None,
    ) -> CompactionResult:
        """Clear old tool results based on time since last assistant response.

        Does NOT generate summaries. Simply replaces old tool_result
        content with a fixed marker text.
        """
        now = now or time.time()
        elapsed = now - self._state.last_time_based_compact

        if elapsed < self._state.time_based_interval:
            return CompactionResult(
                success=False,
                strategy=CompactStrategy.MICROCOMPACT,
                trigger=CompactTrigger.MICROCOMPACT_TIME,
                messages=messages,
            )

        tool_results = [
            (i, m) for i, m in enumerate(messages)
            if m.get("role") == "tool_result"
            and not m.get("content", "").startswith("[Tool result persisted")
            and not m.get("content", "").startswith("[Old tool result")
        ]

        if len(tool_results) <= self._state.keep_recent_tool_results:
            return CompactionResult(
                success=False,
                strategy=CompactStrategy.MICROCOMPACT,
                trigger=CompactTrigger.MICROCOMPACT_TIME,
                messages=messages,
            )

        modified = list(messages)
        cleared_count = 0
        tokens_cleared = 0

        # Keep recent N, clear older ones
        keep_indices = {idx for idx, _ in tool_results[-self._state.keep_recent_tool_results:]}

        for idx, msg in tool_results:
            if idx in keep_indices:
                continue

            old_content = msg.get("content", "")
            old_size = len(old_content)
            modified[idx] = {
                **msg,
                "content": "[Old tool result content cleared by time-based microcompact]",
                "_microcompacted": True,
            }
            cleared_count += 1
            tokens_cleared += old_size // 4  # Rough token estimate

        self._state.last_time_based_compact = now
        self._state.total_tokens_cleared += tokens_cleared

        logger.info(
            "Time-based microcompact: cleared %d old tool results (~%d tokens)",
            cleared_count,
            tokens_cleared,
        )

        return CompactionResult(
            success=True,
            strategy=CompactStrategy.MICROCOMPACT,
            trigger=CompactTrigger.MICROCOMPACT_TIME,
            messages=modified,
            tokens_freed=tokens_cleared,
        )


# ---------------------------------------------------------------------------
# Phase 5: Session Memory Compact
# ---------------------------------------------------------------------------


class SessionMemoryCompactEngine:
    """Uses existing MemoryManager entries as compaction summary base.

    Instead of calling the model to generate a summary, this leverages
    already-maintained memory entries (project decisions, conventions,
    patterns) to form the compact summary, preserving recent messages
    verbatim as a tail.
    """

    TAIL_MIN_TOKENS = 10000
    TAIL_MIN_MESSAGES = 5
    TAIL_MAX_TOKENS = 40000

    def __init__(self, memory_manager=None):
        self._memory = memory_manager

    def try_session_memory_compact(
        self,
        messages: list[dict[str, Any]],
        context_window: int,
        estimate_fn=None,
        config: AutoCompactConfig | None = None,
    ) -> CompactionResult | None:
        """Attempt session memory compact. Returns None if not applicable."""

        config = config or AutoCompactConfig()

        if not config.session_memory_enabled:
            return None

        if self._memory is None:
            return None

        # Get memory context as summary base
        memory_context = self._memory.get_relevant_context(max_tokens=6000)
        if not memory_context.strip():
            return None  # No memory available, fall back to Full Compact

        # Find where to cut: keep recent tail
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        # Calculate tail from the end
        tail_tokens = 0
        tail_start = len(non_system)
        estimate = estimate_fn or (lambda m: len(str(m)) // 4)

        for i in range(len(non_system) - 1, -1, -1):
            msg_tokens = estimate(non_system[i])
            if tail_tokens + msg_tokens > config.max_expand_tokens and \
               (len(non_system) - i) >= config.min_keep_messages:
                tail_start = i + 1
                break
            tail_tokens += msg_tokens

        if tail_tokens < self.TAIL_MIN_TOKENS:
            tail_start = max(0, len(non_system) - config.min_keep_messages)

        # Ensure we don't cut tool_use/tool_result pairs
        tail_start = self._adjust_for_tool_pair(non_system, tail_start)

        # Build compacted messages
        boundary = CompactBoundary(
            trigger=CompactTrigger.AUTO,
            strategy=CompactStrategy.SESSION_MEMORY,
            tokens_before=sum(estimate(m) for m in messages),
        )

        compacted = []
        compacted.append({
            "role": "system",
            "content": (
                f"[Context compacted at {time.strftime('%H:%M:%S')} via Session Memory]\n"
                f"Messages removed: {tail_start}. Tokens before: ~{boundary.tokens_before}\n\n"
                f"## Project Memory & Context\n\n{memory_context}\n\n"
                "--- Recent conversation continues below ---"
            ),
            "_compact_boundary": True,
        })

        # Add preserved tail
        tail = non_system[tail_start:]
        compacted.extend(tail)

        # Re-add system messages at front
        final = system_msgs + compacted

        boundary.tokens_after = sum(estimate(m) for m in final)
        boundary.messages_removed = len(messages) - len(final)
        boundary.preserved_segment = (tail_start + len(system_msgs), len(final) - 1)

        # Check if compaction actually helped
        if boundary.tokens_after >= boundary.tokens_before * 0.95:
            return None  # Not enough savings

        logger.info(
            "Session Memory Compact: %d → %d tokens (%d freed)",
            boundary.tokens_before,
            boundary.tokens_after,
            boundary.tokens_before - boundary.tokens_after,
        )

        return CompactionResult(
            success=True,
            strategy=CompactStrategy.SESSION_MEMORY,
            trigger=CompactTrigger.AUTO,
            messages=final,
            boundary=boundary,
            tokens_freed=boundary.tokens_before - boundary.tokens_after,
            summary_text=memory_context,
        )

    @staticmethod
    def _adjust_for_tool_pair(messages: list[dict], cut_point: int) -> int:
        """Adjust cut point to avoid breaking tool_use/tool_result pairs."""
        adjusted = cut_point

        # Scan forward from cut for orphaned tool_result
        for i in range(adjusted, len(messages)):
            if messages[i].get("role") == "tool_result":
                # Check if matching tool_use is before cut
                found_match = False
                for j in range(max(0, adjusted - 10), adjusted):
                    if (messages[j].get("role") == "assistant" and
                        isinstance(messages[j].get("content"), list) and
                        any(b.get("type") == "tool_use" for b in messages[j]["content"] if isinstance(b, dict))):
                        found_match = True
                        break
                if not found_match:
                    adjusted = i + 1

        # Scan backward for orphaned tool_use
        for i in range(adjusted - 1, max(0, adjusted - 10), -1):
            msg = messages[i]
            if (msg.get("role") == "assistant" and
                isinstance(msg.get("content"), list) and
                any(b.get("type") == "tool_use" for b in msg["content"] if isinstance(b, dict))):
                # Check if tool_result exists after cut
                has_result = any(
                    m.get("role") == "tool_result"
                    for m in messages[adjusted:]
                )
                if has_result:
                    adjusted = min(adjusted, i)
                    break

        return max(0, adjusted)


# ---------------------------------------------------------------------------
# Phase 6: Auto Compact High-Water Dispatcher
# ---------------------------------------------------------------------------


class AutoCompactDispatcher:
    """High-water mark auto-compaction dispatcher.

    Not a multi-level percentage selector. Instead:
    - Monitors token usage against threshold
    - Tries Session Memory Compact first
    - Falls back to Full Compact
    - Has circuit breaker for consecutive failures
    """

    def __init__(
        self,
        context_window: int = 200000,
        config: AutoCompactConfig | None = None,
        memory_manager=None,
        estimate_fn=None,
    ):
        self._context_window = context_window
        self._config = config or AutoCompactConfig()
        self._memory = memory_manager
        self._estimate = estimate_fn or (lambda m: len(str(m)) // 4)
        self._consecutive_failures = 0
        self._boundaries: list[CompactBoundary] = []
        self._suppressed_until: float = 0.0  # Warning suppression after compact
        self._session_memory_engine = SessionMemoryCompactEngine(memory_manager)
        self._microcompact = MicrocompactEngine()

    @property
    def threshold_tokens(self) -> int:
        return int(self._context_window * self._config.threshold_ratio)

    @property
    def blocking_limit(self) -> int:
        return int(self._context_window * 0.97)

    @property
    def is_tripped(self) -> bool:
        return self._consecutive_failures >= self._config.circuit_breaker_limit

    def should_trigger(
        self,
        messages: list[dict[str, Any]],
        token_usage: int | None = None,
    ) -> bool:
        """Check if auto compact should trigger."""
        if not self._config.enabled:
            return False
        if self.is_tripped:
            return False

        usage = token_usage or sum(self._estimate(m) for m in messages)
        return usage >= self.threshold_tokens

    def dispatch(
        self,
        messages: list[dict[str, Any]],
        token_usage: int | None = None,
        force_full: bool = False,
    ) -> CompactionResult:
        """Run auto compact dispatch: try session memory first, then full."""
        if not self.should_trigger(messages, token_usage) and not force_full:
            return CompactionResult(
                success=False,
                strategy=CompactStrategy.FULL,
                trigger=CompactTrigger.AUTO,
                messages=messages,
            )

        usage = token_usage or sum(self._estimate(m) for m in messages)
        logger.info(
            "Auto Compact dispatch: usage=%d, threshold=%d, circuit_breaker=%s",
            usage,
            self.threshold_tokens,
            "TRIPPED" if self.is_tripped else "OK",
        )

        # Try Session Memory Compact first (unless forced full)
        if not force_full:
            sm_result = self._session_memory_engine.try_session_memory_compact(
                messages,
                self._context_window,
                self._estimate,
                self._config,
            )
            if sm_result and sm_result.effective:
                self._on_success(sm_result.boundary)
                self._suppress_warnings()
                return sm_result

        # Fall back to Full Compact
        return self._run_full_compact(messages, usage)

    def _run_full_compact(
        self, messages: list[dict[str, Any]], usage: int
    ) -> CompactionResult:
        """Full compact: generate summary and create new baseline."""
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if len(non_system) <= self._config.min_keep_messages:
            self._on_failure()
            return CompactionResult(
                success=False,
                strategy=CompactStrategy.FULL,
                trigger=CompactTrigger.AUTO,
                messages=messages,
                error="Too few messages to compact",
            )

        # Generate summary from conversation structure
        summary = self._generate_structured_summary(non_system)

        boundary = CompactBoundary(
            trigger=CompactTrigger.AUTO,
            strategy=CompactStrategy.FULL,
            tokens_before=usage,
        )

        # Build compacted: system + boundary + summary + restored essentials
        compacted = list(system_msgs)
        compacted.append({
            "role": "system",
            "content": (
                f"[Context compacted at {time.strftime('%H:%M:%S')} — Full Compact]\n"
                f"Original: ~{usage} tokens, {len(messages)} messages\n\n"
                f"## Conversation Summary\n\n{summary}"
            ),
            "_compact_boundary": True,
        })

        # Keep recent tail
        tail_size = min(len(non_system) // 3, self._config.min_keep_messages)
        tail = non_system[-tail_size:] if tail_size > 0 else []
        compacted.extend(tail)

        boundary.tokens_after = sum(self._estimate(m) for m in compacted)
        boundary.messages_removed = len(messages) - len(compacted)

        self._on_success(boundary)
        self._suppress_warnings()

        logger.info(
            "Full Compact: %d → %d tokens (%d removed)",
            boundary.tokens_before,
            boundary.tokens_after,
            boundary.messages_removed,
        )

        return CompactionResult(
            success=True,
            strategy=CompactStrategy.FULL,
            trigger=CompactTrigger.AUTO,
            messages=compacted,
            boundary=boundary,
            tokens_freed=boundary.tokens_before - boundary.tokens_after,
            summary_text=summary,
        )

    def _generate_structured_summary(self, messages: list[dict]) -> str:
        """Generate structured summary from message history without LLM call."""
        parts = ["### Summary of conversation so far:\n"]

        # Extract key information patterns
        user_topics = []
        tool_calls_made = set()
        files_mentioned = set()
        errors_seen = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user" and isinstance(content, str) and len(content) > 10:
                topic = content[:100].replace("\n", " ")
                user_topics.append(topic)

            if role == "assistant" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_calls_made.add(block.get("name", "unknown"))
                        input_data = block.get("input", {})
                        if "file_path" in input_data:
                            files_mentioned.add(input_data["file_path"])

            if role == "tool_result":
                err = msg.get("isError")
                if err:
                    errors_seen.append(content[:80] if isinstance(content, str) else str(content)[:80])

        if user_topics:
            parts.append("**Topics discussed:**\n")
            for t in user_topics[:8]:
                parts.append(f"- {t}")
            parts.append("")

        if tool_calls_made:
            parts.append(f"**Tools used:** {', '.join(sorted(tool_calls_made))}\n")

        if files_mentioned:
            parts.append(f"**Files touched:** {', '.join(sorted(files_mentioned)[:10])}\n")

        if errors_seen:
            parts.append("**Errors encountered:**\n")
            for e in errors_seen[:3]:
                parts.append(f"- {e}")
            parts.append("")

        parts.append("\n*Continue from where we left off.*")
        return "\n".join(parts)

    def _on_success(self, boundary: CompactBoundary | None) -> None:
        self._consecutive_failures = 0
        if boundary:
            self._boundaries.append(boundary)

    def _on_failure(self) -> None:
        self._consecutive_failures += 1
        logger.warning(
            "Auto Compact failure #%d/%d (circuit breaker)",
            self._consecutive_failures,
            self._config.circuit_breaker_limit,
        )

    def _suppress_warnings(self, duration: float = 30.0) -> None:
        self._suppressed_until = time.time() + duration

    def is_warning_suppressed(self) -> bool:
        return time.time() < self._suppressed_until

    def reset_circuit_breaker(self) -> None:
        self._consecutive_failures = 0

    def get_history(self) -> list[CompactBoundary]:
        return list(self._boundaries)

    def get_last_boundary(self) -> CompactBoundary | None:
        return self._boundaries[-1] if self._boundaries else None


# ---------------------------------------------------------------------------
# Phase 7: Reactive Compact (Error Recovery)
# ---------------------------------------------------------------------------


class ReactiveCompactEngine:
    """Error recovery compaction for post-API-failure scenarios.

    Triggered when the model API rejects a request due to:
    - prompt too long
    - media size exceeded
    - other recoverable errors
    """

    MAX_RETRIES = 3

    def __init__(
        self,
        auto_compact: AutoCompactDispatcher | None = None,
        estimate_fn=None,
    ):
        self._auto_compact = auto_compact
        self._estimate = estimate_fn or (lambda m: len(str(m)) // 4)
        self._recovery_attempts = 0

    def try_recover_from_overflow(
        self,
        messages: list[dict[str, Any]],
        error_message: str = "",
    ) -> CompactionResult | None:
        """Attempt recovery from prompt-too-long error.

        Strategy:
        1. Force Full Compact with aggressive truncation
        2. If still too long, drop oldest API round groups
        3. Up to MAX_RETRIES attempts
        """
        self._recovery_attempts += 1
        if self._recovery_attempts > self.MAX_RETRIES:
            logger.error("Reactive Compact: max retries (%d) exceeded", self.MAX_RETRIES)
            return None

        logger.info(
            "Reactive Compact attempt %d/%d: recovering from overflow",
            self._recovery_attempts,
            self.MAX_RETRIES,
        )

        # Use auto compact with force_full
        if self._auto_compact:
            # Temporarily reset circuit breaker for recovery
            original_tripped = self._auto_compact.is_tripped
            if original_tripped:
                self._auto_compact.reset_circuit_breaker()

            result = self._auto_compact.dispatch(messages, force_full=True)

            # Check if result is small enough
            result_usage = sum(self._estimate(m) for m in result.messages)
            if result_usage < self._auto_compact.blocking_limit * 0.9:
                self._recovery_attempts = 0  # Reset on success
                return CompactionResult(
                    success=True,
                    strategy=CompactStrategy.REACTIVE,
                    trigger=CompactTrigger.REACTIVE,
                    messages=result.messages,
                    boundary=result.boundary,
                    tokens_freed=result.tokens_freed,
                )

        # Aggressive fallback: truncate oldest messages directly
        # Only attempt if still within retry budget
        if self._recovery_attempts > self.MAX_RETRIES:
            logger.error("Reactive Compact: max retries (%d) exceeded in fallback", self.MAX_RETRIES)
            return None
        return self._aggressive_truncate(messages)

    def _aggressive_truncate(
        self, messages: list[dict[str, Any]]
    ) -> CompactionResult:
        """Aggressively truncate to fit within limits."""
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        # Keep only most recent portion
        keep_ratio = 0.4 - (self._recovery_attempts * 0.1)  # Progressive truncation
        keep_count = max(3, int(len(non_system) * max(keep_ratio, 0.15)))

        truncated = list(system_msgs)
        truncated.append({
            "role": "system",
            "content": (
                f"[Context aggressively truncated for recovery — attempt {self._recovery_attempts}]\n"
                f"Earlier conversation was removed to fit context limits."
            ),
            "_reactive_compact": True,
        })
        truncated.extend(non_system[-keep_count:])

        boundary = CompactBoundary(
            trigger=CompactTrigger.REACTIVE,
            strategy=CompactStrategy.REACTIVE,
            tokens_before=sum(self._estimate(m) for m in messages),
            tokens_after=sum(self._estimate(m) for m in truncated),
            messages_removed=len(messages) - len(truncated),
        )

        return CompactionResult(
            success=True,
            strategy=CompactStrategy.REACTIVE,
            trigger=CompactTrigger.REACTIVE,
            messages=truncated,
            boundary=boundary,
            tokens_freed=boundary.tokens_before - boundary.tokens_after,
        )


# ---------------------------------------------------------------------------
# Unified Context Manager (Orchestrates all phases)
# ---------------------------------------------------------------------------


class ContextCompactor:
    """Unified context management orchestrator.

    Implements the complete Claude Code-style pipeline:

    Step 1: Construct active context (from last boundary)
    Step 2: Apply tool result budget
    Step 3: Read dedup
    Step 4: Microcompact
    Step 5: Auto Compact high-water check
    Step 6: Dispatch (Session Memory → Full)
    Step 7: Reactive recovery (if needed)
    """

    def __init__(
        self,
        context_window: int = 200000,
        workspace: str | Path | None = None,
        memory_manager=None,
        estimate_fn=None,
        config: AutoCompactConfig | None = None,
    ):
        self._context_window = context_window
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._config = config or AutoCompactConfig()

        self._tool_budget = ToolResultBudgetManager(workspace)
        self._read_dedup = ReadDedupManager()
        self._microcompact = MicrocompactEngine()
        self._auto_compact = AutoCompactDispatcher(
            context_window=context_window,
            config=config,
            memory_manager=memory_manager,
            estimate_fn=estimate_fn,
        )
        self._reactive = ReactiveCompactEngine(self._auto_compact, estimate_fn)
        self._estimate = estimate_fn or (lambda m: len(str(m)) // 4)

        self._last_compact_result: CompactionResult | None = None
        self._total_optimization_passes = 0

    def process_request(
        self,
        messages: list[dict[str, Any]],
        *,
        enable_tool_budget: bool = True,
        enable_read_dedup: bool = True,
        enable_microcompact: bool = True,
        enable_auto_compact: bool = True,
    ) -> CompactionResult:
        """Run the full pre-request optimization pipeline.

        This is the main entry point called before each API request.
        """
        self._total_optimization_passes += 1
        current = list(messages)
        total_freed = 0
        steps_taken = []

        # Step 2: Tool Result Budget
        if enable_tool_budget:
            current, budget_saved = self._tool_budget.check_and_replace(current)
            if budget_saved > 0:
                total_freed += budget_saved
                steps_taken.append(f"tool_budget({budget_saved})")

        # Step 3: Read Dedup (handled at tool level, but we track state)
        # Read dedup is primarily used when processing tool results

        # Step 4: Microcompact
        if enable_microcompact:
            mc_result = self._microcompact.run_time_based_microcompact(current)
            if mc_result.effective:
                current = mc_result.messages
                total_freed += mc_result.tokens_freed
                steps_taken.append(f"microcompact({mc_result.tokens_freed})")

        # Step 5+6: Auto Compact high-water dispatch
        if enable_auto_compact and self._auto_compact.should_trigger(current):
            ac_result = self._auto_compact.dispatch(current)
            if ac_result.effective:
                current = ac_result.messages
                total_freed += ac_result.tokens_freed
                steps_taken.append(f"auto_compact({ac_result.strategy.value},{ac_result.tokens_freed})")
                self._last_compact_result = ac_result

        result = CompactionResult(
            success=total_freed > 0,
            strategy=CompactStrategy.FULL,
            trigger=CompactTrigger.AUTO,
            messages=current,
            tokens_freed=total_freed,
            summary_text=f"Optimization steps: {' + '.join(steps_taken)}" if steps_taken else "",
        )

        logger.info(
            "ContextCompactor pass #%d: %d tokens freed across [%s]",
            self._total_optimization_passes,
            total_freed,
            ", ".join(steps_taken) if steps_taken else "none",
        )

        return result

    def reactive_recover(
        self, messages: list[dict[str, Any]], error: str = ""
    ) -> CompactionResult | None:
        """Attempt reactive recovery after API error."""
        return self._reactive.try_recover_from_overflow(messages, error)

    @property
    def tool_budget(self) -> ToolResultBudgetManager:
        return self._tool_budget

    @property
    def read_dedup(self) -> ReadDedupManager:
        return self._read_dedup

    @property
    def auto_compact(self) -> AutoCompactDispatcher:
        return self._auto_compact

    @property
    def reactive(self) -> ReactiveCompactEngine:
        return self._reactive

    @property
    def last_result(self) -> CompactionResult | None:
        return self._last_compact_result

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_passes": self._total_optimization_passes,
            "tool_results_persisted": self._tool_budget.get_persisted_count(),
            "tool_bytes_saved": self._tool_budget.get_total_saved_bytes(),
            "read_dedup_entries": len(self._read_dedup._entries),
            "microcompact_tokens_cleared": self._microcompact._state.total_tokens_cleared,
            "auto_compact_boundaries": len(self._auto_compact.get_history()),
            "circuit_breaker_tripped": self._auto_compact.is_tripped,
            "reactive_recovery_attempts": self._reactive._recovery_attempts,
            "context_window": self._context_window,
            "auto_compact_threshold": self._auto_compact.threshold_tokens,
        }

    def format_pipeline_status(self) -> str:
        stats = self.get_stats()
        lines = [
            "Context Management Pipeline Status",
            "=" * 40,
            f"Optimization passes: {stats['total_passes']}",
            f"Tool results persisted: {stats['tool_results_persisted']} ({stats['tool_bytes_saved']} bytes saved)",
            f"Read dedup cache: {stats['read_dedup_entries']} files",
            f"Microcompact cleared: ~{stats['microcompact_tokens_cleared']} tokens",
            f"Compact boundaries: {stats['auto_compact_boundaries']}",
            f"Circuit breaker: {'TRIPPED' if stats['circuit_breaker_tripped'] else 'OK'}",
            f"Reactive recoveries: {stats['reactive_recovery_attempts']}",
            "",
            f"Context window: {stats['context_window']:,} tokens",
            f"Auto compact threshold: {stats['auto_compact_threshold']:,} tokens ({self._config.threshold_ratio:.0%})",
        ]
        return "\n".join(lines)
