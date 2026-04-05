"""Session persistence and resume module.

Provides session data structures, autosave mechanism, and resume capabilities
to allow MiniCode to save and restore conversation state across restarts.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from minicode.config import MINI_CODE_DIR


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SESSIONS_DIR = MINI_CODE_DIR / "sessions"
AUTOSAVE_INTERVAL_SECONDS = 30  # Minimum seconds between autosaves


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SessionMetadata:
    """Lightweight metadata for session listing."""
    session_id: str
    created_at: float  # Unix timestamp
    updated_at: float  # Unix timestamp
    first_message: str = ""  # Truncated first user message
    last_message: str = ""   # Truncated last message
    message_count: int = 0
    workspace: str = ""      # Working directory when session started


@dataclass
class SessionData:
    """Complete session state that can be persisted and restored."""
    session_id: str
    created_at: float
    updated_at: float
    workspace: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    transcript_entries: list[dict[str, Any]] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    permissions_summary: dict[str, Any] = field(default_factory=dict)
    skills: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    metadata: SessionMetadata = field(default=None)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = SessionMetadata(
                session_id=self.session_id,
                created_at=self.created_at,
                updated_at=self.updated_at,
                message_count=len(self.messages),
                workspace=self.workspace,
            )

    def update_metadata(self) -> None:
        """Refresh metadata from current state."""
        self.updated_at = time.time()
        self.metadata.updated_at = self.updated_at
        self.metadata.message_count = len(self.messages)

        # Extract first user message (truncated)
        for msg in self.messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                self.metadata.first_message = content[:100]
                break

        # Extract last message (truncated)
        for msg in reversed(self.messages):
            if msg.get("role") in ("user", "assistant"):
                content = msg.get("content", "")
                self.metadata.last_message = content[:100]
                break


# ---------------------------------------------------------------------------
# Session file operations
# ---------------------------------------------------------------------------

def _session_file(session_id: str) -> Path:
    """Return path to a session JSON file."""
    return SESSIONS_DIR / f"{session_id}.json"


def _session_index_file() -> Path:
    """Return path to the session index file."""
    return MINI_CODE_DIR / "sessions_index.json"


def _load_session_index() -> dict[str, SessionMetadata]:
    """Load the session index (lightweight metadata for all sessions)."""
    index_path = _session_index_file()
    if not index_path.exists():
        return {}
    try:
        raw = index_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return {
            sid: SessionMetadata(**meta)
            for sid, meta in data.items()
        }
    except (json.JSONDecodeError, TypeError, KeyError):
        return {}


def _save_session_index(index: dict[str, SessionMetadata]) -> None:
    """Save the session index."""
    MINI_CODE_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    serializable = {
        sid: {
            "session_id": meta.session_id,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
            "first_message": meta.first_message,
            "last_message": meta.last_message,
            "message_count": meta.message_count,
            "workspace": meta.workspace,
        }
        for sid, meta in index.items()
    }
    _session_index_file().write_text(
        json.dumps(serializable, indent=2) + "\n",
        encoding="utf-8",
    )


def save_session(session: SessionData) -> None:
    """Persist a complete session to disk."""
    session.update_metadata()
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    # Save full session data
    session_path = _session_file(session.session_id)
    serializable = {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "workspace": session.workspace,
        "messages": session.messages,
        "transcript_entries": session.transcript_entries,
        "history": session.history,
        "permissions_summary": session.permissions_summary,
        "skills": session.skills,
        "mcp_servers": session.mcp_servers,
        "metadata": {
            "session_id": session.metadata.session_id,
            "created_at": session.metadata.created_at,
            "updated_at": session.metadata.updated_at,
            "first_message": session.metadata.first_message,
            "last_message": session.metadata.last_message,
            "message_count": session.metadata.message_count,
            "workspace": session.metadata.workspace,
        },
    }
    session_path.write_text(
        json.dumps(serializable, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Update index
    index = _load_session_index()
    index[session.session_id] = session.metadata
    _save_session_index(index)


def load_session(session_id: str) -> SessionData | None:
    """Load a session from disk. Returns None if not found."""
    session_path = _session_file(session_id)
    if not session_path.exists():
        return None

    try:
        raw = session_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        metadata = SessionMetadata(**data.get("metadata", {}))
        return SessionData(
            session_id=data["session_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            workspace=data["workspace"],
            messages=data.get("messages", []),
            transcript_entries=data.get("transcript_entries", []),
            history=data.get("history", []),
            permissions_summary=data.get("permissions_summary", {}),
            skills=data.get("skills", []),
            mcp_servers=data.get("mcp_servers", []),
            metadata=metadata,
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def list_sessions() -> list[SessionMetadata]:
    """List all available sessions, newest first."""
    index = _load_session_index()
    sessions = list(index.values())
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions


def delete_session(session_id: str) -> bool:
    """Delete a session from disk. Returns True if deleted."""
    session_path = _session_file(session_id)
    if not session_path.exists():
        return False

    try:
        session_path.unlink()
        index = _load_session_index()
        index.pop(session_id, None)
        _save_session_index(index)
        return True
    except OSError:
        return False


def cleanup_old_sessions(max_sessions: int = 50) -> int:
    """Remove oldest sessions beyond max_sessions limit. Returns count deleted."""
    sessions = list_sessions()
    if len(sessions) <= max_sessions:
        return 0

    to_delete = sessions[max_sessions:]
    deleted = 0
    for meta in to_delete:
        if delete_session(meta.session_id):
            deleted += 1
    return deleted


# ---------------------------------------------------------------------------
# Session creation helpers
# ---------------------------------------------------------------------------

def create_new_session(workspace: str) -> SessionData:
    """Create a new empty session."""
    now = time.time()
    session_id = uuid.uuid4().hex[:12]
    return SessionData(
        session_id=session_id,
        created_at=now,
        updated_at=now,
        workspace=workspace,
    )


def get_latest_session(workspace: str | None = None) -> SessionData | None:
    """Get the most recent session, optionally filtered by workspace."""
    sessions = list_sessions()
    for meta in sessions:
        if workspace is None or meta.workspace == workspace:
            return load_session(meta.session_id)
    return None


# ---------------------------------------------------------------------------
# Autosave manager
# ---------------------------------------------------------------------------

class AutosaveManager:
    """Manages automatic session saving with rate limiting."""

    def __init__(self, session: SessionData, interval: int = AUTOSAVE_INTERVAL_SECONDS):
        self.session = session
        self.interval = interval
        self._last_save_time = time.time()  # Initialize to current time
        self._dirty = False

    def mark_dirty(self) -> None:
        """Mark session as needing save."""
        self._dirty = True

    def should_save(self) -> bool:
        """Check if autosave should trigger."""
        if not self._dirty:
            return False
        elapsed = time.time() - self._last_save_time
        return elapsed >= self.interval

    def save_if_needed(self) -> bool:
        """Save if dirty and interval elapsed. Returns True if saved."""
        if self.should_save():
            save_session(self.session)
            self._last_save_time = time.time()
            self._dirty = False
            return True
        return False

    def force_save(self) -> None:
        """Force immediate save regardless of interval."""
        save_session(self.session)
        self._last_save_time = time.time()
        self._dirty = False


# ---------------------------------------------------------------------------
# Session formatting for display
# ---------------------------------------------------------------------------

def format_session_list(sessions: list[SessionMetadata]) -> str:
    """Format sessions as a human-readable list."""
    if not sessions:
        return "No saved sessions found."

    lines = ["Saved sessions:", ""]
    for i, meta in enumerate(sessions, 1):
        created = time.strftime(
            "%Y-%m-%d %H:%M",
            time.localtime(meta.created_at),
        )
        workspace = meta.workspace or "unknown"
        first_msg = meta.first_message or "(empty)"
        count = meta.message_count

        lines.append(
            f"  {i}. [{meta.session_id[:8]}] {created} - {workspace}"
        )
        lines.append(f"     Messages: {count} | First: {first_msg}")
        lines.append("")

    lines.append(f"Total: {len(sessions)} session(s)")
    return "\n".join(lines)


def format_session_resume(session: SessionData) -> str:
    """Format session info for resume confirmation."""
    created = time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.localtime(session.created_at),
    )
    updated = time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.localtime(session.updated_at),
    )
    return (
        f"Resuming session {session.session_id[:8]}\n"
        f"  Created: {created}\n"
        f"  Updated: {updated}\n"
        f"  Messages: {len(session.messages)}\n"
        f"  Workspace: {session.workspace}"
    )
