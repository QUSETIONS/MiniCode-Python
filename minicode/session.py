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
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from minicode.config import MINI_CODE_DIR
from minicode.logging_config import log_session_event
from minicode.session_contract import (
    atomic_write_json,
    build_session_record,
    delete_session_bundle,
    read_session_bundle,
    _valid_session_id,
    write_session_bundle,
)


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
    runtime_summary: str = ""  # Compact runtime timeline, if available
    checkpoint_count: int = 0  # Number of stored rewind checkpoints
    instruction_summary: str = ""
    hook_summary: str = ""
    delegation_summary: str = ""
    extension_summary: str = ""
    readiness_summary: str = ""
    # Rust-compatible session/history fields.  They remain optional so old
    # Python session indexes continue to load without a migration step.
    ended_at: str | None = None
    duration_seconds: int = 0
    model: str | None = None
    turn_count: int = 0
    user_input_count: int = 0
    tool_call_count: int = 0
    status: str = "active"
    memory_summary: str = ""


@dataclass
class FileCheckpoint:
    """Persistent file snapshot captured before a write tool mutates disk."""

    checkpoint_id: str
    created_at: float
    file_path: str
    existed: bool
    previous_content: str
    kind: str = "edit"
    group_id: str = ""


@dataclass
class SessionData:
    """Complete session state that can be persisted and restored."""
    session_id: str
    created_at: float
    updated_at: float
    workspace: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    transcript_entries: list[dict[str, Any]] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    permissions_summary: dict[str, Any] = field(default_factory=dict)
    skills: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    instruction_layers: list[dict[str, Any]] = field(default_factory=list)
    hook_status: dict[str, Any] = field(default_factory=dict)
    delegated_tasks: list[dict[str, Any]] = field(default_factory=list)
    delegation_status: dict[str, Any] = field(default_factory=dict)
    extension_manifests: list[dict[str, Any]] = field(default_factory=list)
    readiness_report: dict[str, Any] = field(default_factory=dict)
    memory_continuity: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[FileCheckpoint] = field(default_factory=list)
    metadata: SessionMetadata = field(default=None)
    
    # Incremental save tracking
    _last_saved_msg_count: int = field(default=0, repr=False)
    _last_saved_transcript_count: int = field(default=0, repr=False)
    _last_saved_checkpoint_count: int = field(default=0, repr=False)
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
                checkpoint_count=len(self.checkpoints),
                instruction_summary=_summarize_instruction_layers(self.instruction_layers),
                hook_summary=_summarize_hook_status(self.hook_status),
                delegation_summary=_summarize_delegation_status(self.delegation_status),
                extension_summary=_summarize_extension_manifests(self.extension_manifests),
                readiness_summary=_summarize_readiness_report(self.readiness_report),
                turn_count=len(self.turns)
                or sum(
                    1 for message in self.messages
                    if isinstance(message, dict) and message.get("role") == "user"
                ),
                user_input_count=sum(
                    1 for message in self.messages
                    if isinstance(message, dict) and message.get("role") == "user"
                ),
                tool_call_count=sum(
                    1 for message in self.messages
                    if isinstance(message, dict)
                    and message.get("role") in {"assistant_tool_call", "tool_result", "tool"}
                ),
                memory_summary=_summarize_memory_continuity(self.memory_continuity),
            )

    def update_metadata(self) -> None:
        """Refresh metadata from current state."""
        self.updated_at = time.time()
        # The legacy payload and Rust-compatible bundle both identify the
        # session from this field.  Keep it aligned even when callers reuse a
        # deserialized SessionMetadata object or mutate session_id in tests.
        self.metadata.session_id = self.session_id
        self.metadata.updated_at = self.updated_at
        self.metadata.message_count = len(self.messages)
        self.metadata.runtime_summary = _runtime_summary_from_transcript_entries(
            self.transcript_entries
        )
        self.metadata.checkpoint_count = len(self.checkpoints)
        self.metadata.instruction_summary = _summarize_instruction_layers(
            self.instruction_layers
        )
        self.metadata.hook_summary = _summarize_hook_status(self.hook_status)
        self.metadata.delegation_summary = _summarize_delegation_status(
            self.delegation_status
        )
        self.metadata.extension_summary = _summarize_extension_manifests(
            self.extension_manifests
        )
        self.metadata.readiness_summary = _summarize_readiness_report(
            self.readiness_report
        )
        user_input_count = sum(
            1 for message in self.messages
            if isinstance(message, dict) and message.get("role") == "user"
        )
        tool_call_count = sum(
            1 for message in self.messages
            if isinstance(message, dict)
            and message.get("role") in {"assistant_tool_call", "tool_result", "tool"}
        )
        self.metadata.turn_count = len(self.turns) or user_input_count
        self.metadata.user_input_count = user_input_count
        self.metadata.tool_call_count = tool_call_count
        self.metadata.memory_summary = _summarize_memory_continuity(
            self.memory_continuity
        )
        self.metadata.duration_seconds = max(
            0, int(self.updated_at - self.created_at)
        )

        # Extract first user message (truncated)
        for msg in self.messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if not isinstance(content, str):
                    content = "" if content is None else str(content)
                self.metadata.first_message = content[:100]
                break

        # Extract last message (truncated) — avoid full reverse iteration
        if self.messages:
            for msg in reversed(self.messages):
                if msg.get("role") in ("user", "assistant"):
                    content = msg.get("content", "")
                    if not isinstance(content, str):
                        content = "" if content is None else str(content)
                    self.metadata.last_message = content[:100]
                    break
    
    @property
    def has_delta(self) -> bool:
        """Check if there are unsaved changes."""
        return (
            len(self.messages) != self._last_saved_msg_count
            or len(self.transcript_entries) != self._last_saved_transcript_count
            or len(self.checkpoints) != self._last_saved_checkpoint_count
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


def _runtime_trace_token_from_entry(entry: dict[str, Any]) -> str | None:
    kind = str(entry.get("runtimeKind") or "").strip().lower()
    category = str(entry.get("category") or "").strip().lower()
    body = str(entry.get("body") or "")

    if category != "runtime" and not kind:
        normalized = " ".join(body.split()).lower()
        if normalized.startswith("runtime phase:"):
            kind = "phase"
        elif normalized.startswith("verification guard:"):
            kind = "guard"
        elif "widened mode is active" in normalized or "widening is now available" in normalized:
            kind = "widening"
        elif normalized.startswith("turn completed") or normalized.startswith("turn complete"):
            kind = "stop"
        else:
            return None

    step = entry.get("runtimeStep")
    step_suffix = f"@{step}" if isinstance(step, int) else ""
    phase = str(entry.get("runtimePhase") or "").strip()
    stop_reason = str(entry.get("runtimeStopReason") or "").strip()
    verify = str(entry.get("runtimeVerificationFocus") or "").strip()

    if kind == "phase":
        return f"phase:{phase or 'unknown'}{step_suffix}"
    if kind == "guard":
        return f"guard:{verify or stop_reason or 'verification'}{step_suffix}"
    if kind == "widening":
        return f"widen:{stop_reason or 'escalation'}{step_suffix}"
    if kind == "stop":
        return f"stop:{stop_reason or 'done'}{step_suffix}"
    if kind == "compaction":
        return f"compact:{phase or 'context'}{step_suffix}"
    if kind == "recovery":
        return f"recover:{stop_reason or 'resume'}{step_suffix}"

    return f"{kind or 'runtime'}{step_suffix}"


def _runtime_summary_from_transcript_entries(entries: list[dict[str, Any]]) -> str:
    tokens: list[str] = []
    for entry in entries:
        token = _runtime_trace_token_from_entry(entry)
        if token and (not tokens or tokens[-1] != token):
            tokens.append(token)
    return " -> ".join(tokens)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _named_list(items: list[Any], *, key: str = "name") -> list[str]:
    names: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            candidate = _safe_text(item.get(key) or item.get("label") or item.get("id"))
            if candidate:
                names.append(candidate)
        else:
            candidate = _safe_text(item)
            if candidate:
                names.append(candidate)
    return names


def _summarize_instruction_layers(layers: list[dict[str, Any]]) -> str:
    names = _named_list(layers)
    if not names:
        return ""
    return f"{len(names)} layer(s): {', '.join(names[:3])}" + ("..." if len(names) > 3 else "")


def _summarize_hook_status(status: dict[str, Any]) -> str:
    if not isinstance(status, dict):
        return ""
    summary = _safe_text(status.get("summary"))
    if summary:
        return summary
    total = int(status.get("total_hooks", 0) or 0)
    enabled = int(status.get("enabled_hooks", 0) or 0)
    return f"{enabled}/{total} hook(s) enabled" if total else ""


def _summarize_delegation_status(status: dict[str, Any]) -> str:
    if not isinstance(status, dict):
        return ""
    summary = _safe_text(status.get("summary"))
    if summary:
        return summary
    running = int(status.get("running_tasks", 0) or 0)
    available = int(status.get("available_slots", 0) or 0)
    return f"{running} running, {available} slot(s) open"


def _summarize_extension_manifests(manifests: list[dict[str, Any]]) -> str:
    names = _named_list(manifests)
    if not names:
        return ""
    return f"{len(names)} extension(s): {', '.join(names[:3])}" + ("..." if len(names) > 3 else "")


def _summarize_readiness_report(report: dict[str, Any]) -> str:
    if not isinstance(report, dict):
        return ""
    summary = _safe_text(report.get("summary"))
    if summary:
        return summary
    status = _safe_text(report.get("status"))
    provider = _safe_text(report.get("provider"))
    if status and provider:
        return f"{status} via {provider}"
    return status or provider


def _summarize_memory_continuity(snapshot: dict[str, Any]) -> str:
    """Return a compact, content-free summary for session listings."""

    if not isinstance(snapshot, dict) or not snapshot:
        return ""
    counts = snapshot.get("scope_counts")
    if isinstance(counts, dict):
        total = sum(value for value in counts.values() if isinstance(value, int))
        return f"{total} memory entr{'y' if total == 1 else 'ies'} tracked"
    return str(snapshot.get("schema") or "memory continuity")


def _format_named_collection(items: list[Any], *, fallback: str = "(none)") -> str:
    names = _named_list(items)
    return ", ".join(names) if names else fallback


def _serialize_checkpoint(checkpoint: FileCheckpoint) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "created_at": checkpoint.created_at,
        "file_path": checkpoint.file_path,
        "existed": checkpoint.existed,
        "previous_content": checkpoint.previous_content,
        "kind": checkpoint.kind,
        "group_id": checkpoint.group_id,
    }


def _deserialize_checkpoint(data: dict[str, Any]) -> FileCheckpoint:
    return FileCheckpoint(
        checkpoint_id=str(data["checkpoint_id"]),
        created_at=float(data["created_at"]),
        file_path=str(data["file_path"]),
        existed=bool(data["existed"]),
        previous_content=str(data.get("previous_content", "")),
        kind=str(data.get("kind", "edit") or "edit"),
        group_id=str(data.get("group_id", "")),
    )


# ---------------------------------------------------------------------------
# Session file operations
# ---------------------------------------------------------------------------

def _session_file(session_id: str) -> Path:
    """Return path to a session JSON file."""
    if not _valid_session_id(session_id):
        raise ValueError("invalid session id for session path")
    return SESSIONS_DIR / f"{session_id}.json"


def _session_delta_dir(session_id: str) -> Path:
    """Return path to a session's delta directory."""
    if not _valid_session_id(session_id):
        raise ValueError("invalid session id for session path")
    return SESSIONS_DIR / DELTA_DIR_NAME / session_id


def _session_index_file() -> Path:
    """Return path to the session index file."""
    return MINI_CODE_DIR / "sessions_index.json"


def _load_session_index() -> dict[str, SessionMetadata]:
    """Load the session index (lightweight metadata for all sessions)."""
    index_path = _session_index_file()
    if index_path.is_symlink() or not index_path.is_file():
        return {}
    try:
        raw = index_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        valid: dict[str, SessionMetadata] = {}
        for sid, meta in data.items():
            if not _valid_session_id(sid) or not isinstance(meta, dict):
                continue
            metadata_sid = meta.get("session_id")
            if metadata_sid not in {None, sid}:
                continue
            if metadata_sid is None:
                meta = {**meta, "session_id": sid}
            try:
                valid[sid] = SessionMetadata(**meta)
            except (TypeError, ValueError, OverflowError):
                continue
        return valid
    except (json.JSONDecodeError, OSError, TypeError, KeyError, AttributeError):
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
            "runtime_summary": meta.runtime_summary,
            "checkpoint_count": meta.checkpoint_count,
            "instruction_summary": meta.instruction_summary,
            "hook_summary": meta.hook_summary,
            "delegation_summary": meta.delegation_summary,
            "extension_summary": meta.extension_summary,
            "readiness_summary": meta.readiness_summary,
            "ended_at": meta.ended_at,
            "duration_seconds": meta.duration_seconds,
            "model": meta.model,
            "turn_count": meta.turn_count,
            "user_input_count": meta.user_input_count,
            "tool_call_count": meta.tool_call_count,
            "status": meta.status,
            "memory_summary": meta.memory_summary,
        }
        for sid, meta in index.items()
    }
    atomic_write_json(_session_index_file(), serializable)


def _save_delta(session: SessionData) -> None:
    """Save only the incremental changes since last full save.
    
    Delta files contain new messages and transcript entries appended
    since the last save point. This is much cheaper than serializing
    the entire session on every autosave.
    """
    delta_dir = _session_delta_dir(session.session_id)
    if delta_dir.is_symlink() or (
        delta_dir.exists() and not delta_dir.is_dir()
    ):
        raise OSError("invalid session delta directory")
    delta_dir.mkdir(parents=True, exist_ok=True)
    
    # Collect new messages since last save
    new_messages = session.messages[session._last_saved_msg_count:]
    new_transcripts = session.transcript_entries[session._last_saved_transcript_count:]
    new_checkpoints = session.checkpoints[session._last_saved_checkpoint_count:]
    
    if not new_messages and not new_transcripts and not new_checkpoints:
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
    if new_checkpoints:
        delta_data["checkpoint_offset"] = session._last_saved_checkpoint_count
        delta_data["checkpoints"] = [_serialize_checkpoint(cp) for cp in new_checkpoints]
    
    # Write delta file with sequential numbering
    delta_num = session._delta_save_count
    delta_path = delta_dir / f"delta_{delta_num:04d}.json"
    atomic_write_json(delta_path, delta_data)
    
    # Update tracking
    session._last_saved_msg_count = len(session.messages)
    session._last_saved_transcript_count = len(session.transcript_entries)
    session._last_saved_checkpoint_count = len(session.checkpoints)
    session._delta_save_count += 1


def _consolidate_deltas(session: SessionData) -> None:
    """Merge all delta files into the full session file and clean up.
    
    This is called periodically to prevent unbounded delta file growth
    and to ensure the full session file stays consistent.
    """
    delta_dir = _session_delta_dir(session.session_id)
    if delta_dir.is_symlink() or not delta_dir.is_dir():
        return
    
    # Deltas are already applied during load_session, so just clean up
    for delta_file in sorted(delta_dir.glob("delta_*.json")):
        if delta_file.is_symlink() or not delta_file.is_file():
            continue
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


def _sync_session_contract(session: SessionData) -> Any:
    """Refresh Rust-compatible turn/metadata fields before persistence."""

    record = build_session_record(session)
    session.turns = [turn.to_dict() for turn in record.turns]
    session.metadata.message_count = len(session.messages)
    session.metadata.updated_at = session.updated_at
    session.metadata.ended_at = record.metadata.ended_at
    session.metadata.duration_seconds = record.metadata.duration_seconds
    session.metadata.model = record.metadata.model
    session.metadata.turn_count = record.metadata.turn_count
    session.metadata.user_input_count = record.metadata.user_input_count
    session.metadata.tool_call_count = record.metadata.tool_call_count
    session.metadata.status = record.metadata.status
    session.metadata.memory_summary = _summarize_memory_continuity(
        session.memory_continuity
    )
    return record


def _transcript_entries_from_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create a minimal Python transcript when loading a Rust-only bundle."""

    entries: list[dict[str, Any]] = []
    for index, message in enumerate(messages, 1):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").lower()
        if role == "system":
            continue
        if role == "user":
            kind = "user"
        elif role in {"tool_result", "tool", "assistant_tool_call"}:
            kind = "tool:error" if message.get("isError") or message.get("is_error") else "tool"
        else:
            kind = "assistant"
        content = message.get("content", "")
        if not isinstance(content, str):
            try:
                content = json.dumps(content, ensure_ascii=False)
            except (TypeError, ValueError):
                content = str(content)
        entries.append({"id": index, "kind": kind, "body": content})
    return entries


def _contract_timestamp(value: str | None, fallback: float) -> float:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def _load_session_from_bundle(session_id: str) -> SessionData | None:
    """Load the Rust-compatible bundle when the legacy file is unavailable."""

    record = read_session_bundle(session_id, SESSIONS_DIR)
    if record is None:
        return None

    created_at = _contract_timestamp(record.metadata.created_at, time.time())
    updated_at = _contract_timestamp(record.metadata.updated_at, created_at)
    extensions = record.extensions
    transcript_entries = extensions.get("transcript_entries", [])
    if not isinstance(transcript_entries, list):
        transcript_entries = _transcript_entries_from_messages(record.messages)
    raw_checkpoints = extensions.get("checkpoints", [])
    checkpoints: list[FileCheckpoint] = []
    if isinstance(raw_checkpoints, list):
        for item in raw_checkpoints:
            if not isinstance(item, dict) or not item.get("checkpoint_id"):
                continue
            try:
                checkpoints.append(_deserialize_checkpoint(item))
            except (KeyError, TypeError, ValueError):
                continue
    metadata = SessionMetadata(
        session_id=record.metadata.session_id,
        created_at=created_at,
        updated_at=updated_at,
        message_count=len(record.messages),
        workspace=record.metadata.cwd,
        ended_at=record.metadata.ended_at,
        duration_seconds=record.metadata.duration_seconds,
        model=record.metadata.model,
        turn_count=record.metadata.turn_count,
        user_input_count=record.metadata.user_input_count,
        tool_call_count=record.metadata.tool_call_count,
        status=record.metadata.status,
        memory_summary=_summarize_memory_continuity(record.memory_continuity),
        checkpoint_count=len(checkpoints),
    )
    session = SessionData(
        session_id=record.session_id,
        created_at=created_at,
        updated_at=updated_at,
        workspace=record.metadata.cwd,
        messages=record.messages,
        transcript_entries=transcript_entries,
        turns=[turn.to_dict() for turn in record.turns],
        history=record.input_history,
        memory_continuity=record.memory_continuity,
        checkpoints=checkpoints,
        metadata=metadata,
    )
    session._last_saved_msg_count = len(session.messages)
    session._last_saved_transcript_count = len(session.transcript_entries)
    session._last_saved_checkpoint_count = len(session.checkpoints)
    session._last_full_save_hash = session._compute_content_hash()
    return session


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
    if not _valid_session_id(session.session_id):
        raise ValueError("invalid session id for session path")
    log_session_event("save", details=f"id={session.session_id} force_full={force_full}")
    session.update_metadata()
    _sync_session_contract(session)
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
            "turns": session.turns,
            "history": session.history,
            "permissions_summary": session.permissions_summary,
            "skills": session.skills,
            "mcp_servers": session.mcp_servers,
            "instruction_layers": session.instruction_layers,
            "hook_status": session.hook_status,
            "delegated_tasks": session.delegated_tasks,
            "delegation_status": session.delegation_status,
            "extension_manifests": session.extension_manifests,
            "readiness_report": session.readiness_report,
            "memory_continuity": session.memory_continuity,
            "checkpoints": [_serialize_checkpoint(cp) for cp in session.checkpoints],
            "metadata": {
                "session_id": session.metadata.session_id,
                "created_at": session.metadata.created_at,
                "updated_at": session.metadata.updated_at,
                "first_message": session.metadata.first_message,
                "last_message": session.metadata.last_message,
                "message_count": session.metadata.message_count,
                "workspace": session.metadata.workspace,
                "runtime_summary": session.metadata.runtime_summary,
                "checkpoint_count": session.metadata.checkpoint_count,
                "instruction_summary": session.metadata.instruction_summary,
                "hook_summary": session.metadata.hook_summary,
                "delegation_summary": session.metadata.delegation_summary,
                "extension_summary": session.metadata.extension_summary,
                "readiness_summary": session.metadata.readiness_summary,
                "ended_at": session.metadata.ended_at,
                "duration_seconds": session.metadata.duration_seconds,
                "model": session.metadata.model,
                "turn_count": session.metadata.turn_count,
                "user_input_count": session.metadata.user_input_count,
                "tool_call_count": session.metadata.tool_call_count,
                "status": session.metadata.status,
                "memory_summary": session.metadata.memory_summary,
            },
        }
        atomic_write_json(session_path, serializable)
        
        # Reset delta tracking
        session._last_saved_msg_count = len(session.messages)
        session._last_saved_transcript_count = len(session.transcript_entries)
        session._last_saved_checkpoint_count = len(session.checkpoints)
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

    # Keep a Rust-readable bundle beside the legacy file during migration.
    # The legacy path remains the recovery source when a crash leaves the
    # bundle partially written, while a bundle-only session can be resumed.
    try:
        write_session_bundle(session, SESSIONS_DIR)
    except (OSError, TypeError, ValueError) as exc:
        log_session_event(
            "bundle_write_error",
            details=f"id={session.session_id} error={type(exc).__name__}",
        )


def load_session(session_id: str) -> SessionData | None:
    """Load a session from disk, applying any pending deltas.

    Loading process:
    1. Load the base session file
    2. Scan for delta files
    3. Apply deltas in order (append new messages/transcripts)
    4. Update tracking counters
    """
    if not _valid_session_id(session_id):
        return None
    log_session_event("load", details=f"id={session_id}")
    session_path = _session_file(session_id)
    if session_path.is_symlink() or not session_path.is_file():
        return _load_session_from_bundle(session_id)

    try:
        raw = session_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return _load_session_from_bundle(session_id)
        if data.get("session_id") != session_id:
            return _load_session_from_bundle(session_id)
        metadata_payload = data.get("metadata", {})
        if (
            isinstance(metadata_payload, dict)
            and metadata_payload.get("session_id") not in {None, session_id}
        ):
            return _load_session_from_bundle(session_id)
        metadata = SessionMetadata(**metadata_payload)
        session = SessionData(
            session_id=data["session_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            workspace=data["workspace"],
            messages=data.get("messages", []),
            transcript_entries=data.get("transcript_entries", []),
            turns=data.get("turns", []),
            history=data.get("history", []),
            permissions_summary=data.get("permissions_summary", {}),
            skills=data.get("skills", []),
            mcp_servers=data.get("mcp_servers", []),
            instruction_layers=data.get("instruction_layers", []),
            hook_status=data.get("hook_status", {}),
            delegated_tasks=data.get("delegated_tasks", []),
            delegation_status=data.get("delegation_status", {}),
            extension_manifests=data.get("extension_manifests", []),
            readiness_report=data.get("readiness_report", {}),
            memory_continuity=data.get("memory_continuity", {}),
            checkpoints=[
                _deserialize_checkpoint(item)
                for item in data.get("checkpoints", [])
                if isinstance(item, dict)
            ],
            metadata=metadata,
        )
        
        # Apply any pending deltas
        delta_dir = _session_delta_dir(session_id)
        if not delta_dir.is_symlink() and delta_dir.is_dir():
            delta_files = sorted(delta_dir.glob("delta_*.json"))
            for delta_path in delta_files:
                if delta_path.is_symlink() or not delta_path.is_file():
                    continue
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

                    if "checkpoints" in delta:
                        c_offset = delta.get("checkpoint_offset", len(session.checkpoints))
                        parsed = [
                            _deserialize_checkpoint(item)
                            for item in delta["checkpoints"]
                            if isinstance(item, dict)
                        ]
                        if c_offset >= len(session.checkpoints):
                            session.checkpoints.extend(parsed)
                        elif c_offset + len(parsed) > len(session.checkpoints):
                            overlap = len(session.checkpoints) - c_offset
                            session.checkpoints.extend(parsed[overlap:])
                    
                    session._delta_save_count += 1
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Skip corrupt delta files
                    continue
        
        # Update tracking counters
        session._last_saved_msg_count = len(session.messages)
        session._last_saved_transcript_count = len(session.transcript_entries)
        session._last_saved_checkpoint_count = len(session.checkpoints)
        session._last_full_save_hash = session._compute_content_hash()
        # Deltas can append messages after the base turn list was written.
        # Re-derive the compact turn view so Rust readers and Python resume
        # both observe the same current conversation boundary.
        _sync_session_contract(session)
        
        return session
    except (
        json.JSONDecodeError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        AttributeError,
    ):
        return _load_session_from_bundle(session_id)


def list_sessions(workspace: str | None = None) -> list[SessionMetadata]:
    """List available sessions, newest first.

    When ``workspace`` is provided, only sessions created for that exact
    workspace path are returned. Callers should pass a resolved path when they
    want current-workspace semantics.
    """
    index = _load_session_index()
    sessions = [
        meta
        for meta in index.values()
        if workspace is None or meta.workspace == workspace
    ]
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions


def delete_session(session_id: str) -> bool:
    """Delete a session from disk. Returns True if deleted."""
    if not _valid_session_id(session_id):
        return False
    session_path = _session_file(session_id)
    bundle_path = SESSIONS_DIR / session_id
    bundle_exists = bundle_path.is_dir() and not bundle_path.is_symlink()
    if not session_path.exists() and not bundle_exists:
        return False

    try:
        if session_path.exists():
            session_path.unlink()
        # Clean up orphaned delta files
        delta_dir = _session_delta_dir(session_id)
        if delta_dir.exists():
            import shutil
            shutil.rmtree(delta_dir, ignore_errors=True)
        delete_session_bundle(session_id, SESSIONS_DIR)
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
    log_session_event("create", details=f"id={session_id} workspace={workspace}")
    return SessionData(
        session_id=session_id,
        created_at=now,
        updated_at=now,
        workspace=workspace,
    )


def get_latest_session(workspace: str | None = None) -> SessionData | None:
    """Get the most recent session, optionally filtered by workspace."""
    sessions = list_sessions(workspace=workspace)
    for meta in sessions:
        return load_session(meta.session_id)
    return None


def create_file_checkpoint(
    session: SessionData | None,
    *,
    file_path: str,
    existed: bool,
    previous_content: str,
) -> FileCheckpoint | None:
    """Record a durable rewind snapshot before a file mutation."""
    if session is None:
        return None

    checkpoint = FileCheckpoint(
        checkpoint_id=uuid.uuid4().hex[:12],
        created_at=time.time(),
        file_path=file_path,
        existed=existed,
        previous_content=previous_content,
    )
    session.checkpoints.append(checkpoint)
    save_session(session, force_full=False)
    return checkpoint


def _select_checkpoints_to_rewind(
    session: SessionData,
    *,
    steps: int = 1,
    checkpoint_id: str | None = None,
) -> list[FileCheckpoint]:
    if not session.checkpoints:
        return []
    if checkpoint_id:
        for index in range(len(session.checkpoints) - 1, -1, -1):
            checkpoint = session.checkpoints[index]
            if checkpoint.checkpoint_id == checkpoint_id:
                group_id = checkpoint.group_id
                if group_id:
                    while index > 0 and session.checkpoints[index - 1].group_id == group_id:
                        index -= 1
                return session.checkpoints[index:]
        return []
    if steps <= 0:
        return []
    start_index = max(len(session.checkpoints) - steps, 0)
    tail_group_id = session.checkpoints[-1].group_id
    if tail_group_id:
        group_start = len(session.checkpoints) - 1
        while group_start > 0 and session.checkpoints[group_start - 1].group_id == tail_group_id:
            group_start -= 1
        start_index = min(start_index, group_start)
    return session.checkpoints[start_index:]


def rewind_session_data(
    session: SessionData,
    *,
    steps: int = 1,
    checkpoint_id: str | None = None,
) -> list[FileCheckpoint]:
    """Restore checkpoints against an in-memory session and persist the result."""
    selected = _select_checkpoints_to_rewind(
        session,
        steps=steps,
        checkpoint_id=checkpoint_id,
    )
    if not selected:
        return []

    rewind_group_id = uuid.uuid4().hex[:12]
    rewind_created_at = time.time()
    reverse_checkpoints: list[FileCheckpoint] = []
    captured_paths: set[str] = set()
    for checkpoint in reversed(selected):
        if checkpoint.file_path in captured_paths:
            continue
        target = Path(checkpoint.file_path)
        existed = target.exists()
        previous_content = target.read_text(encoding="utf-8") if existed else ""
        reverse_checkpoints.append(
            FileCheckpoint(
                checkpoint_id=uuid.uuid4().hex[:12],
                created_at=rewind_created_at,
                file_path=checkpoint.file_path,
                existed=existed,
                previous_content=previous_content,
                kind="rewind",
                group_id=rewind_group_id,
            )
        )
        captured_paths.add(checkpoint.file_path)

    for checkpoint in reversed(selected):
        target = Path(checkpoint.file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if checkpoint.existed:
            target.write_text(checkpoint.previous_content, encoding="utf-8")
        elif target.exists():
            target.unlink()

    del session.checkpoints[-len(selected):]
    session.checkpoints.extend(reverse_checkpoints)
    save_session(session, force_full=True)
    return selected


def rewind_session(
    session_id: str,
    *,
    steps: int = 1,
    checkpoint_id: str | None = None,
) -> tuple[SessionData | None, list[FileCheckpoint]]:
    """Restore the latest checkpointed file edits for a saved session."""
    session = load_session(session_id)
    if session is None:
        return session, []

    selected = rewind_session_data(
        session,
        steps=steps,
        checkpoint_id=checkpoint_id,
    )
    return session, selected


def format_rewind_preview(
    session: SessionData,
    *,
    steps: int = 1,
    checkpoint_id: str | None = None,
) -> str:
    """Format a dry-run view of which checkpoints a rewind would restore."""
    selected = _select_checkpoints_to_rewind(
        session,
        steps=steps,
        checkpoint_id=checkpoint_id,
    )
    if not selected:
        return f"No checkpoints available to rewind for session {session.session_id[:8]}."

    unique_files: list[str] = []
    seen_paths: set[str] = set()
    for checkpoint in reversed(selected):
        if checkpoint.file_path not in seen_paths:
            unique_files.append(checkpoint.file_path)
            seen_paths.add(checkpoint.file_path)

    lines = [
        f"Rewind preview for session {session.session_id[:8]}:",
        "",
        f"Would restore {len(selected)} checkpoint(s) across {len(unique_files)} file(s).",
    ]
    if checkpoint_id:
        lines.append(f"Target checkpoint: {checkpoint_id[:8]}")

    if any(checkpoint.kind == "rewind" for checkpoint in selected):
        lines.append("Mode: undo prior rewind safety checkpoints.")
    else:
        lines.append("Mode: restore pre-edit file snapshots.")

    lines.extend(["", "Planned restores:"])
    for index, checkpoint in enumerate(reversed(selected), 1):
        created = _fmt_ts(checkpoint.created_at, "%Y-%m-%d %H:%M:%S")
        status = "existing file" if checkpoint.existed else "new file"
        checkpoint_type = _format_checkpoint_type(checkpoint)
        lines.append(
            f"  {index}. [{checkpoint.checkpoint_id[:8]}] {created} - {checkpoint.file_path}"
        )
        lines.append(f"     Restores: {status}")
        lines.append(f"     Type: {checkpoint_type}")

    return "\n".join(lines)


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

def _fmt_ts(ts: float, fmt: str) -> str:
    """Fast timestamp formatting using datetime (avoids repeated localtime)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(fmt)


def format_session_list(sessions: list[SessionMetadata]) -> str:
    """Format sessions as a human-readable list."""
    if not sessions:
        return "No saved sessions found."

    lines = ["Saved sessions:", ""]
    for i, meta in enumerate(sessions, 1):
        created = _fmt_ts(meta.created_at, "%Y-%m-%d %H:%M")
        workspace = meta.workspace or "unknown"
        first_msg = meta.first_message or "(empty)"
        count = meta.message_count

        lines.append(
            f"  {i}. [{meta.session_id[:8]}] {created} - {workspace}"
        )
        lines.append(f"     Messages: {count} | First: {first_msg}")
        if meta.checkpoint_count:
            lines.append(f"     Checkpoints: {meta.checkpoint_count}")
        if meta.runtime_summary:
            lines.append(f"     Runtime: {meta.runtime_summary}")
        lines.append("")

    lines.append(f"Total: {len(sessions)} session(s)")
    return "\n".join(lines)


def format_session_resume(session: SessionData) -> str:
    """Format session info for resume confirmation."""
    created = _fmt_ts(session.created_at, "%Y-%m-%d %H:%M:%S")
    updated = _fmt_ts(session.updated_at, "%Y-%m-%d %H:%M:%S")
    return (
        f"Resuming session {session.session_id[:8]}\n"
        f"  Created: {created}\n"
        f"  Updated: {updated}\n"
        f"  Messages: {len(session.messages)}\n"
        f"  Workspace: {session.workspace}"
        + (
            f"\n  Checkpoints: {session.metadata.checkpoint_count}"
            if session.metadata.checkpoint_count
            else ""
        )
        + (
            f"\n  Recent checkpoints: {_format_checkpoint_summary_details(session)}"
            if session.metadata.checkpoint_count
            else ""
        )
        + (
            f"\n  Runtime: {session.metadata.runtime_summary}"
            if session.metadata.runtime_summary
            else ""
        )
        + (
            f"\n  Readiness: {session.metadata.readiness_summary}"
            if session.metadata.readiness_summary
            else ""
        )
        + (
            f"\n  Instructions: {session.metadata.instruction_summary}"
            if session.metadata.instruction_summary
            else ""
        )
        + (
            f"\n  Hooks: {session.metadata.hook_summary}"
            if session.metadata.hook_summary
            else ""
        )
        + (
            f"\n  Delegation: {session.metadata.delegation_summary}"
            if session.metadata.delegation_summary
            else ""
        )
        + (
            f"\n  Extensions: {session.metadata.extension_summary}"
            if session.metadata.extension_summary
            else ""
        )
    )


def _session_entry_preview(text: str, *, limit: int = 96) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _session_transcript_label(entry: dict[str, Any]) -> str:
    kind = str(entry.get("kind", "entry") or "entry")
    if entry.get("category") == "runtime":
        runtime_kind = str(entry.get("runtimeKind", "") or "").strip()
        return f"runtime:{runtime_kind}" if runtime_kind else "runtime"
    if kind == "tool":
        tool_name = str(entry.get("toolName", "") or "").strip()
        status = str(entry.get("status", "") or "").strip()
        if tool_name and status:
            return f"tool:{tool_name}/{status}"
        if tool_name:
            return f"tool:{tool_name}"
    return kind


def _format_recent_transcript_lines(
    session: SessionData,
    *,
    limit: int = 8,
) -> list[str]:
    if not session.transcript_entries:
        return ["  (none)"]

    lines: list[str] = []
    recent_entries = session.transcript_entries[-limit:]
    for entry in recent_entries:
        label = _session_transcript_label(entry)
        preview = _session_entry_preview(str(entry.get("body", "") or "(empty)"))
        lines.append(f"  - [{label}] {preview}")
    return lines


def _format_recent_history_lines(
    session: SessionData,
    *,
    limit: int = 8,
) -> list[str]:
    if not session.history:
        return ["  (none)"]

    return [
        f"  {index}. {_session_entry_preview(item)}"
        for index, item in enumerate(session.history[-limit:], 1)
    ]


def _format_instruction_layer_lines(
    session: SessionData,
    *,
    limit: int = 6,
) -> list[str]:
    if not session.instruction_layers:
        return ["  (none)"]
    lines: list[str] = []
    for layer in session.instruction_layers[:limit]:
        name = _safe_text(layer.get("name")) or "layer"
        scope = _safe_text(layer.get("scope")) or "unknown"
        kind = _safe_text(layer.get("kind")) or "instruction"
        preview = _safe_text(layer.get("preview")) or "(no preview)"
        exists = "present" if layer.get("exists") else "missing"
        lines.append(f"  - {name} [{scope}/{kind}, {exists}] {preview}")
    if len(session.instruction_layers) > limit:
        lines.append(f"  ... {len(session.instruction_layers) - limit} more layer(s)")
    return lines


def _format_hook_status_lines(session: SessionData) -> list[str]:
    if not session.hook_status:
        return ["  (none)"]
    status = session.hook_status
    lines = [
        "  "
        + (
            _safe_text(status.get("summary"))
            or f"{status.get('enabled_hooks', 0)}/{status.get('total_hooks', 0)} hook(s) enabled"
        )
    ]
    hooks = status.get("hooks")
    if isinstance(hooks, list):
        for hook in hooks[:5]:
            lines.append(
                f"  - {hook.get('event', 'hook')} :: {hook.get('last_status', 'idle')}"
                f", calls={hook.get('call_count', 0)}, failures={hook.get('failure_count', 0)}"
            )
    return lines


def _format_delegation_lines(session: SessionData) -> list[str]:
    summary = session.metadata.delegation_summary or _summarize_delegation_status(
        session.delegation_status
    )
    lines = [f"  {summary}"] if summary else []
    if not session.delegated_tasks:
        return lines or ["  (none)"]
    for task in session.delegated_tasks[:5]:
        label = _safe_text(task.get("label") or task.get("task_id") or task.get("id")) or "task"
        status = _safe_text(task.get("status")) or "running"
        lines.append(f"  - {label} :: {status}")
    return lines


def _format_extension_lines(
    session: SessionData,
    *,
    limit: int = 6,
) -> list[str]:
    if not session.extension_manifests:
        return ["  (none)"]
    lines: list[str] = []
    for manifest in session.extension_manifests[:limit]:
        name = _safe_text(manifest.get("name")) or "extension"
        scope = _safe_text(manifest.get("scope")) or "unknown"
        version = _safe_text(manifest.get("version")) or "unversioned"
        enabled = "enabled" if manifest.get("enabled", True) else "disabled"
        description = _safe_text(manifest.get("description")) or "(no description)"
        lines.append(f"  - {name} [{scope}] {version}, {enabled} :: {description}")
    if len(session.extension_manifests) > limit:
        lines.append(
            f"  ... {len(session.extension_manifests) - limit} more extension(s)"
        )
    return lines


def _format_readiness_lines(session: SessionData) -> list[str]:
    if not session.readiness_report:
        return ["  (none)"]
    report = session.readiness_report
    provider = _safe_text(report.get("provider")) or "unknown-provider"
    provider_channel = _safe_text(report.get("provider_channel")) or ""
    status = _safe_text(report.get("status")) or "unknown"
    provider_ready = "ready" if report.get("provider_ready") else "not-ready"
    fallback_candidates = list(report.get("fallback_candidates", []) or [])
    viable_fallbacks = set(str(item) for item in list(report.get("viable_fallbacks", []) or []))
    lines = [f"  {status} via {provider} ({provider_ready})"]
    if provider_channel:
        lines.append(f"  channel: {provider_channel}")
    if fallback_candidates:
        lines.append(
            f"  fallback coverage: {len(viable_fallbacks)}/{len(fallback_candidates)} locally ready"
        )
        for candidate in fallback_candidates[:5]:
            label = "ready" if str(candidate) in viable_fallbacks else "not-ready"
            lines.append(f"  - fallback {candidate} [{label}]")
    guidance = report.get("fallback_guidance")
    if isinstance(guidance, list) and guidance:
        for item in guidance[:3]:
            lines.append(f"  - guidance: {item}")
    issues = report.get("issues")
    if isinstance(issues, list) and issues:
        for issue in issues[:5]:
            lines.append(f"  - {issue}")
    return lines


def _format_checkpoint_summary_details(
    session: SessionData,
    *,
    limit: int = 3,
) -> str:
    if not session.checkpoints:
        return "none"

    items: list[str] = []
    for checkpoint in reversed(session.checkpoints[-limit:]):
        file_name = Path(checkpoint.file_path).name or checkpoint.file_path
        label = " [rewind]" if getattr(checkpoint, "kind", "edit") == "rewind" else ""
        items.append(f"[{checkpoint.checkpoint_id[:8]}] {file_name}{label}")
    return f"{len(session.checkpoints)} saved; latest " + ", ".join(items)


def _format_checkpoint_type(checkpoint: FileCheckpoint) -> str:
    if getattr(checkpoint, "kind", "edit") == "rewind":
        return "rewind safety"
    return "edit"


def format_checkpoint_summary_line(
    session: SessionData | None,
    *,
    limit: int = 3,
) -> str:
    """Format a compact checkpoint summary for TUI and transcript surfaces."""
    if not session or not session.checkpoints:
        return ""
    return f"checkpoint-summary: {_format_checkpoint_summary_details(session, limit=limit)}"


def format_session_inspect(
    session: SessionData,
    *,
    transcript_limit: int = 8,
) -> str:
    """Format a detailed session inspection view for CLI/session replay."""
    created = _fmt_ts(session.created_at, "%Y-%m-%d %H:%M:%S")
    updated = _fmt_ts(session.updated_at, "%Y-%m-%d %H:%M:%S")
    skills = _format_named_collection(session.skills)
    mcp_servers = _format_named_collection(session.mcp_servers)

    lines = [
        f"Session inspect: {session.session_id[:8]}",
        f"  Created: {created}",
        f"  Updated: {updated}",
        f"  Workspace: {session.workspace}",
        f"  Messages: {len(session.messages)}",
        f"  Transcript entries: {len(session.transcript_entries)}",
        f"  History entries: {len(session.history)}",
        f"  Skills: {skills}",
        f"  MCP servers: {mcp_servers}",
        f"  Checkpoints: {session.metadata.checkpoint_count}",
    ]
    if session.metadata.runtime_summary:
        lines.append(f"  Runtime: {session.metadata.runtime_summary}")
    if session.metadata.readiness_summary:
        lines.append(f"  Readiness: {session.metadata.readiness_summary}")
    if session.metadata.instruction_summary:
        lines.append(f"  Instructions: {session.metadata.instruction_summary}")
    if session.metadata.hook_summary:
        lines.append(f"  Hooks: {session.metadata.hook_summary}")
    if session.metadata.delegation_summary:
        lines.append(f"  Delegation: {session.metadata.delegation_summary}")
    if session.metadata.extension_summary:
        lines.append(f"  Extensions: {session.metadata.extension_summary}")

    lines.extend(
        [
            "",
            f"Recent checkpoints: {_format_checkpoint_summary_details(session)}"
            if session.checkpoints
            else "Recent checkpoints: none",
            "",
            "Instruction layers:",
            *_format_instruction_layer_lines(session),
            "",
            "Hook surface:",
            *_format_hook_status_lines(session),
            "",
            "Delegation surface:",
            *_format_delegation_lines(session),
            "",
            "Extensions:",
            *_format_extension_lines(session),
            "",
            "Readiness:",
            *_format_readiness_lines(session),
            "",
            f"Recent transcript ({min(len(session.transcript_entries), transcript_limit)} shown):",
            *_format_recent_transcript_lines(session, limit=transcript_limit),
        ]
    )
    return "\n".join(lines)


def format_session_replay(
    session: SessionData,
    *,
    transcript_limit: int = 16,
    history_limit: int = 8,
    checkpoint_limit: int = 5,
) -> str:
    """Format a replay-oriented historical view for a session."""
    created = _fmt_ts(session.created_at, "%Y-%m-%d %H:%M:%S")
    updated = _fmt_ts(session.updated_at, "%Y-%m-%d %H:%M:%S")
    lines = [
        f"Session replay: {session.session_id[:8]}",
        f"  Workspace: {session.workspace}",
        f"  Created: {created}",
        f"  Updated: {updated}",
        f"  Runtime: {session.metadata.runtime_summary or '(none)'}",
        f"  Checkpoints: {session.metadata.checkpoint_count}",
    ]
    if session.metadata.readiness_summary:
        lines.append(f"  Readiness: {session.metadata.readiness_summary}")
        readiness_details = _format_readiness_lines(session)
        if readiness_details and readiness_details != ["  (none)"]:
            lines.extend(readiness_details[1:])
    if session.metadata.delegation_summary:
        lines.append(f"  Delegation: {session.metadata.delegation_summary}")
    lines.extend(
        [
            "",
            f"Checkpoint trail ({min(len(session.checkpoints), checkpoint_limit)} shown):",
        ]
    )
    if session.checkpoints:
        for checkpoint in reversed(session.checkpoints[-checkpoint_limit:]):
            created_at = _fmt_ts(checkpoint.created_at, "%Y-%m-%d %H:%M:%S")
            file_name = Path(checkpoint.file_path).name or checkpoint.file_path
            checkpoint_type = _format_checkpoint_type(checkpoint)
            lines.append(
                f"  - [{checkpoint.checkpoint_id[:8]}] {created_at} :: {file_name} ({checkpoint_type})"
            )
    else:
        lines.append("  (none)")

    lines.extend(
        [
            "",
            "Instruction layers:",
            *_format_instruction_layer_lines(session, limit=4),
            "",
            "Extensions:",
            *_format_extension_lines(session, limit=4),
            "",
            f"Prompt history ({min(len(session.history), history_limit)} shown):",
            *_format_recent_history_lines(session, limit=history_limit),
            "",
            f"Transcript timeline ({min(len(session.transcript_entries), transcript_limit)} shown):",
            *_format_recent_transcript_lines(session, limit=transcript_limit),
        ]
    )
    return "\n".join(lines)


def format_session_checkpoints(session: SessionData) -> str:
    """Format rewind checkpoints for inspection."""
    if not session.checkpoints:
        return f"No checkpoints saved for session {session.session_id[:8]}."

    lines = [
        f"Checkpoints for session {session.session_id[:8]}:",
        "",
    ]
    for index, checkpoint in enumerate(reversed(session.checkpoints), 1):
        created = _fmt_ts(checkpoint.created_at, "%Y-%m-%d %H:%M:%S")
        status = "existing file" if checkpoint.existed else "new file"
        checkpoint_type = _format_checkpoint_type(checkpoint)
        lines.append(
            f"  {index}. [{checkpoint.checkpoint_id[:8]}] {created} - {checkpoint.file_path}"
        )
        lines.append(f"     Restores: {status}")
        lines.append(f"     Type: {checkpoint_type}")
    lines.append("")
    lines.append(f"Total: {len(session.checkpoints)} checkpoint(s)")
    return "\n".join(lines)
