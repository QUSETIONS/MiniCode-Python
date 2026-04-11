"""Session persistence and resume module.

Provides session data structures, autosave mechanism, and resume capabilities
to allow MiniCode to save and restore conversation state across restarts.

Uses incremental delta saves to reduce serialization overhead:
- Only new/changed messages are appended since last save
- Full save occurs periodically (every N deltas) for consistency
- Dirty tracking at field level avoids redundant serialization
"""

from __future__ import annotations

import hashlib
import json
import os
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

# Incremental save configuration
DELTA_DIR_NAME = "deltas"        # Subdirectory for delta files
FULL_SAVE_INTERVAL = 10          # Do a full save every N delta saves
MAX_DELTA_FILES = 50             # Maximum delta files before forced consolidation


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
    
    # Incremental save tracking
    _last_saved_msg_count: int = field(default=0, repr=False)
    _last_saved_transcript_count: int = field(default=0, repr=False)
    _delta_save_count: int = field(default=0, repr=False)
    _last_full_save_hash: str = field(default="", repr=False)

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
    
    @property
    def has_delta(self) -> bool:
        """Check if there are unsaved changes."""
        return (
            len(self.messages) != self._last_saved_msg_count
            or len(self.transcript_entries) != self._last_saved_transcript_count
        )
    
    def _compute_content_hash(self) -> str:
        """Compute a quick hash of message content for change detection."""
        h = hashlib.md5(usedforsecurity=False)
        for msg in self.messages[-20:]:  # Hash last 20 messages for speed
            h.update(msg.get("role", "").encode())
            content = msg.get("content", "")
            if isinstance(content, str):
                h.update(content[:500].encode())
        return h.hexdigest()


# ---------------------------------------------------------------------------
# Session file operations
# ---------------------------------------------------------------------------

def _session_file(session_id: str) -> Path:
    """Return path to a session JSON file."""
    return SESSIONS_DIR / f"{session_id}.json"


def _session_delta_dir(session_id: str) -> Path:
    """Return path to a session's delta directory."""
    return SESSIONS_DIR / DELTA_DIR_NAME / session_id


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


def _save_delta(session: SessionData) -> None:
    """Save only the incremental changes since last full save.
    
    Delta files contain new messages and transcript entries appended
    since the last save point. This is much cheaper than serializing
    the entire session on every autosave.
    """
    delta_dir = _session_delta_dir(session.session_id)
    delta_dir.mkdir(parents=True, exist_ok=True)
    
    # Collect new messages since last save
    new_messages = session.messages[session._last_saved_msg_count:]
    new_transcripts = session.transcript_entries[session._last_saved_transcript_count:]
    
    if not new_messages and not new_transcripts:
        return
    
    # Create delta entry
    delta_data: dict[str, Any] = {
        "ts": time.time(),
        "msg_offset": session._last_saved_msg_count,
        "transcript_offset": session._last_saved_transcript_count,
    }
    if new_messages:
        delta_data["messages"] = new_messages
    if new_transcripts:
        delta_data["transcripts"] = new_transcripts
    
    # Write delta file with sequential numbering
    delta_num = session._delta_save_count
    delta_path = delta_dir / f"delta_{delta_num:04d}.json"
    delta_path.write_text(
        json.dumps(delta_data, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    
    # Update tracking
    session._last_saved_msg_count = len(session.messages)
    session._last_saved_transcript_count = len(session.transcript_entries)
    session._delta_save_count += 1


def _consolidate_deltas(session: SessionData) -> None:
    """Merge all delta files into the full session file and clean up.
    
    This is called periodically to prevent unbounded delta file growth
    and to ensure the full session file stays consistent.
    """
    delta_dir = _session_delta_dir(session.session_id)
    if not delta_dir.exists():
        return
    
    # Deltas are already applied during load_session, so just clean up
    for delta_file in sorted(delta_dir.glob("delta_*.json")):
        try:
            delta_file.unlink()
        except OSError:
            pass
    
    # Try to remove empty delta directory
    try:
        delta_dir.rmdir()
        # Also try to remove parent if empty
        parent = delta_dir.parent
        if parent.name == DELTA_DIR_NAME and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
    
    session._delta_save_count = 0


def save_session(session: SessionData, force_full: bool = False) -> None:
    """Persist session to disk with incremental delta support.
    
    Uses a hybrid strategy:
    - Delta saves: Only append new messages/transcripts (fast, small I/O)
    - Full saves: Serialize entire session (slower, but ensures consistency)
    - Consolidation: Merge deltas into full file periodically
    
    Args:
        session: The session to save
        force_full: Force a full save (e.g., on explicit save command)
    """
    session.update_metadata()
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Decide whether to do a full save or delta save
    should_full_save = (
        force_full
        or session._delta_save_count == 0  # First save is always full
        or session._delta_save_count >= FULL_SAVE_INTERVAL
        or session._delta_save_count >= MAX_DELTA_FILES  # Safety cap
    )
    
    if should_full_save:
        # Full save: serialize everything
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
        
        # Reset delta tracking
        session._last_saved_msg_count = len(session.messages)
        session._last_saved_transcript_count = len(session.transcript_entries)
        session._last_full_save_hash = session._compute_content_hash()
        
        # Consolidate and clean up delta files
        _consolidate_deltas(session)
    else:
        # Delta save: only append new data
        _save_delta(session)
    
    # Update index (always lightweight)
    index = _load_session_index()
    index[session.session_id] = session.metadata
    _save_session_index(index)


def load_session(session_id: str) -> SessionData | None:
    """Load a session from disk, applying any pending deltas.
    
    Loading process:
    1. Load the base session file
    2. Scan for delta files
    3. Apply deltas in order (append new messages/transcripts)
    4. Update tracking counters
    """
    session_path = _session_file(session_id)
    if not session_path.exists():
        return None

    try:
        raw = session_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        metadata = SessionMetadata(**data.get("metadata", {}))
        session = SessionData(
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
        
        # Apply any pending deltas
        delta_dir = _session_delta_dir(session_id)
        if delta_dir.exists():
            delta_files = sorted(delta_dir.glob("delta_*.json"))
            for delta_path in delta_files:
                try:
                    delta_raw = delta_path.read_text(encoding="utf-8")
                    delta = json.loads(delta_raw)
                    
                    # Append delta messages at the correct offset
                    if "messages" in delta:
                        offset = delta.get("msg_offset", len(session.messages))
                        # Ensure we don't duplicate messages
                        if offset >= len(session.messages):
                            session.messages.extend(delta["messages"])
                        elif offset + len(delta["messages"]) > len(session.messages):
                            # Partial overlap — append only the new part
                            overlap = len(session.messages) - offset
                            session.messages.extend(delta["messages"][overlap:])
                    
                    # Append delta transcripts
                    if "transcripts" in delta:
                        t_offset = delta.get("transcript_offset", len(session.transcript_entries))
                        if t_offset >= len(session.transcript_entries):
                            session.transcript_entries.extend(delta["transcripts"])
                        elif t_offset + len(delta["transcripts"]) > len(session.transcript_entries):
                            overlap = len(session.transcript_entries) - t_offset
                            session.transcript_entries.extend(delta["transcripts"][overlap:])
                    
                    session._delta_save_count += 1
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Skip corrupt delta files
                    continue
        
        # Update tracking counters
        session._last_saved_msg_count = len(session.messages)
        session._last_saved_transcript_count = len(session.transcript_entries)
        session._last_full_save_hash = session._compute_content_hash()
        
        return session
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
    """Manages automatic session saving with rate limiting and delta support.
    
    Uses incremental saves for autosave (fast) and full saves for
    explicit save commands (consistent).
    """

    def __init__(self, session: SessionData, interval: int = AUTOSAVE_INTERVAL_SECONDS):
        self.session = session
        self.interval = interval
        self._last_save_time = time.time()  # Initialize to current time
        self._dirty = False
        self._full_save_counter = 0

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
        """Save if dirty and interval elapsed. Uses delta saves for speed.
        
        Returns True if saved.
        """
        if self.should_save():
            # Use incremental delta save for autosave (fast)
            save_session(self.session, force_full=False)
            self._last_save_time = time.time()
            self._dirty = False
            self._full_save_counter += 1
            return True
        return False

    def force_save(self) -> None:
        """Force immediate full save regardless of interval."""
        save_session(self.session, force_full=True)
        self._last_save_time = time.time()
        self._dirty = False
        self._full_save_counter = 0


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
