"""Working memory protection for context compaction.

Inspired by Learn Claude Code best practices:
- Preserve key continuity information during context compression
- Protect active task context from being summarized away
- Maintain conversation flow continuity across compaction boundaries

Provides:
- WorkingMemoryTracker: Tracks and protects critical context
- ContinuityMarker: Marks important conversation flow points
- MemoryBudgetAllocator: Allocates token budget for working memory
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from minicode.context_manager import estimate_tokens


@dataclass
class WorkingMemoryEntry:
    """A single working memory entry that should be protected during compaction."""

    content: str
    entry_type: str  # "active_task", "user_intent", "key_decision", "error_context"
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None  # None = no expiry
    importance: float = 1.0  # 0.0 - 1.0, higher = more protected

    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def token_count(self) -> int:
        """Estimate token count for this entry."""
        return estimate_tokens(self.content)


class WorkingMemoryTracker:
    """Tracks and protects critical context during compaction.

    This implements the "working memory protection" pattern from
    Learn Claude Code best practices. During context compression,
    entries in this tracker are preserved to maintain conversation
    continuity and task coherence.
    """

    def __init__(
        self,
        max_entries: int = 15,
        max_tokens: int = 4000,
    ) -> None:
        self._entries: list[WorkingMemoryEntry] = []
        self.max_entries = max_entries
        self.max_tokens = max_tokens

    def add(
        self,
        content: str,
        entry_type: str = "active_task",
        ttl_seconds: float | None = None,
        importance: float = 1.0,
    ) -> WorkingMemoryEntry:
        """Add a working memory entry to be protected.

        Args:
            content: The content to protect
            entry_type: Type of working memory (active_task, user_intent, etc.)
            ttl_seconds: Time-to-live in seconds (None = no expiry)
            importance: Importance score 0.0-1.0 (higher = more protected)
        """
        expires_at = None
        if ttl_seconds is not None:
            expires_at = time.time() + ttl_seconds

        entry = WorkingMemoryEntry(
            content=content,
            entry_type=entry_type,
            expires_at=expires_at,
            importance=importance,
        )

        self._entries.append(entry)
        self._enforce_limits()
        return entry

    def remove(self, entry: WorkingMemoryEntry) -> None:
        """Remove a working memory entry."""
        if entry in self._entries:
            self._entries.remove(entry)

    def clear_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if not e.is_expired()]
        return before - len(self._entries)

    def get_protected_content(self) -> list[str]:
        """Get all non-expired content that should be protected."""
        self.clear_expired()
        return [e.content for e in self._entries]

    def get_protected_tokens(self) -> int:
        """Get total token count of protected content."""
        return sum(e.token_count() for e in self._entries if not e.is_expired())

    def get_stats(self) -> dict[str, Any]:
        """Get working memory statistics."""
        self.clear_expired()
        return {
            "entries": len(self._entries),
            "max_entries": self.max_entries,
            "protected_tokens": self.get_protected_tokens(),
            "max_tokens": self.max_tokens,
            "utilization": self.get_protected_tokens() / self.max_tokens
            if self.max_tokens > 0
            else 0,
        }

    def _enforce_limits(self) -> None:
        """Remove lowest-priority entries if exceeding limits."""
        # Remove expired first
        self.clear_expired()

        # Remove by token budget
        while self.get_protected_tokens() > self.max_tokens and self._entries:
            # Remove lowest importance entry
            self._entries.sort(key=lambda e: e.importance)
            self._entries.pop(0)

        # Remove by entry count
        while len(self._entries) > self.max_entries and self._entries:
            self._entries.sort(key=lambda e: e.importance)
            self._entries.pop(0)

    def format_status(self) -> str:
        """Format working memory status for display."""
        stats = self.get_stats()
        lines = [
            "Working Memory",
            "=" * 50,
            f"Entries: {stats['entries']}/{stats['max_entries']}",
            f"Protected tokens: {stats['protected_tokens']:,}/{stats['max_tokens']:,} ({stats['utilization']*100:.0f}%)",
            "",
        ]

        if self._entries:
            lines.append("Protected Content:")
            for entry in self._entries:
                expires = ""
                if entry.expires_at:
                    remaining = entry.expires_at - time.time()
                    if remaining > 0:
                        expires = f" (expires in {remaining/60:.0f}m)"
                    else:
                        expires = " (EXPIRED)"
                preview = entry.content[:60].replace("\n", " ")
                lines.append(f"  • [{entry.entry_type}] {preview}...{expires}")

        return "\n".join(lines)


@dataclass
class ContinuityMarker:
    """Marks important conversation flow points.

    During compaction, these markers help reconstruct the
    conversation narrative even after messages are summarized.
    """

    marker_type: str  # "task_start", "decision_point", "error_recovered", "user_redirect"
    description: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationContinuityManager:
    """Manages conversation continuity across compaction boundaries.

    When context is compacted, this manager helps reconstruct the
    conversation flow by preserving key transition points.
    """

    def __init__(self, max_markers: int = 20) -> None:
        self._markers: list[ContinuityMarker] = []
        self.max_markers = max_markers

    def add_marker(
        self,
        marker_type: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuityMarker:
        """Add a continuity marker."""
        marker = ContinuityMarker(
            marker_type=marker_type,
            description=description,
            metadata=metadata or {},
        )
        self._markers.append(marker)

        # Enforce limit
        if len(self._markers) > self.max_markers:
            self._markers = self._markers[-self.max_markers:]

        return marker

    def get_recent_markers(self, limit: int = 10) -> list[ContinuityMarker]:
        """Get recent continuity markers."""
        return self._markers[-limit:]

    def get_markers_since(self, timestamp: float) -> list[ContinuityMarker]:
        """Get markers added after a specific timestamp."""
        return [m for m in self._markers if m.timestamp > timestamp]

    def format_continuity_summary(self) -> str:
        """Format conversation continuity for display."""
        if not self._markers:
            return "No continuity markers."

        lines = ["Conversation Continuity", "=" * 50, ""]
        for marker in self._markers[-10:]:  # Last 10 markers
            time_str = time.strftime("%H:%M:%S", time.localtime(marker.timestamp))
            lines.append(f"  [{time_str}] [{marker.marker_type}] {marker.description}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_working_memory = WorkingMemoryTracker()
_continuity_manager = ConversationContinuityManager()


def get_working_memory() -> WorkingMemoryTracker:
    """Get the global working memory tracker."""
    return _working_memory


def get_continuity_manager() -> ConversationContinuityManager:
    """Get the global conversation continuity manager."""
    return _continuity_manager


def protect_context(
    content: str,
    entry_type: str = "active_task",
    ttl_seconds: float | None = None,
) -> WorkingMemoryEntry:
    """Convenience function to protect context during compaction."""
    return _working_memory.add(content, entry_type, ttl_seconds)


def mark_continuity(
    marker_type: str,
    description: str,
    metadata: dict[str, Any] | None = None,
) -> ContinuityMarker:
    """Convenience function to add a continuity marker."""
    return _continuity_manager.add_marker(marker_type, description, metadata)
