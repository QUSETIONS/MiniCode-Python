"""Rust-compatible session persistence contract.

The Rust implementation stores a session as three small, project-scoped
artifacts: metadata, conversation/turn records, and input history.  Python
has a richer legacy session file, so this module deliberately acts as a
compatibility layer rather than replacing that file in one step.

The contract is intentionally provider-agnostic.  It records messages,
turns, and memory continuity diagnostics, but never copies environment
variables, credentials, or provider configuration secrets.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping


SESSION_FORMAT_VERSION = "minicode-rust-compatible-v1"
MAX_INPUT_HISTORY = 200


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce untrusted persisted numeric fields without aborting recovery."""

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _optional_text(value: Any) -> str | None:
    text = _text(value).strip()
    return text or None


def _iso_timestamp(value: Any, fallback: float | None = None) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            timestamp = float(value)
        except (TypeError, ValueError, OverflowError):
            timestamp = time.time()
    else:
        try:
            timestamp = float(fallback) if fallback is not None else time.time()
        except (TypeError, ValueError, OverflowError):
            timestamp = time.time()
    if not math.isfinite(timestamp):
        timestamp = time.time()
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat()


def _timestamp_value(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            timestamp = float(value)
            if math.isfinite(timestamp):
                return timestamp
        except (TypeError, ValueError, OverflowError):
            pass
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON with a same-directory temporary file and atomic replace."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _message_role(message: Mapping[str, Any]) -> str:
    return _text(message.get("role")).strip().lower() or "unknown"


def _message_tool_name(message: Mapping[str, Any]) -> str:
    return (
        _text(
            message.get("toolName")
            or message.get("tool_name")
            or message.get("name")
            or (message.get("data") or {}).get("tool_name")
            if isinstance(message.get("data"), Mapping)
            else message.get("toolName") or message.get("tool_name") or message.get("name")
        ).strip()
    )


def _message_is_error(message: Mapping[str, Any]) -> bool:
    data = message.get("data")
    return bool(
        message.get("isError")
        or message.get("is_error")
        or (data.get("is_error") if isinstance(data, Mapping) else False)
    )


def _message_timestamp(message: Mapping[str, Any], fallback: float) -> str:
    return _iso_timestamp(
        message.get("timestamp") or message.get("created_at") or message.get("createdAt"),
        fallback=fallback,
    )


@dataclass(frozen=True, slots=True)
class RustSessionMetadata:
    """Field-compatible representation of Rust ``SessionMetadata``."""

    session_id: str
    created_at: str
    ended_at: str | None
    duration_seconds: int
    model: str | None
    cwd: str
    turn_count: int
    user_input_count: int
    tool_call_count: int
    status: str = "active"
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "model": self.model,
            "cwd": self.cwd,
            "turn_count": self.turn_count,
            "user_input_count": self.user_input_count,
            "tool_call_count": self.tool_call_count,
            "status": self.status,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], session_id: str) -> "RustSessionMetadata":
        return cls(
            session_id=_text(data.get("session_id") or session_id),
            created_at=_iso_timestamp(data.get("created_at")),
            ended_at=_optional_text(data.get("ended_at")),
            duration_seconds=max(0, _safe_int(data.get("duration_seconds", 0))),
            model=_optional_text(data.get("model")),
            cwd=_text(data.get("cwd")),
            turn_count=max(0, _safe_int(data.get("turn_count", 0))),
            user_input_count=max(0, _safe_int(data.get("user_input_count", 0))),
            tool_call_count=max(0, _safe_int(data.get("tool_call_count", 0))),
            status=_text(data.get("status") or "active"),
            updated_at=_optional_text(data.get("updated_at")),
        )


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """One user-centered turn, matching the Rust history schema."""

    turn_id: str
    turn_number: int
    timestamp: str
    input_type: str
    input: str
    tools_used: list[str] = field(default_factory=list)
    duration_ms: int = 0
    status: str = "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "turn_number": self.turn_number,
            "timestamp": self.timestamp,
            "input_type": self.input_type,
            "input": self.input,
            "tools_used": list(self.tools_used),
            "duration_ms": self.duration_ms,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], index: int) -> "TurnRecord":
        tools = data.get("tools_used", [])
        if not isinstance(tools, list):
            tools = []
        return cls(
            turn_id=_text(data.get("turn_id") or f"turn-{index + 1}"),
            turn_number=max(
                1,
                _safe_int(data.get("turn_number", index + 1), index + 1),
            ),
            timestamp=_iso_timestamp(data.get("timestamp")),
            input_type=_text(data.get("input_type") or "user"),
            input=_text(data.get("input")),
            tools_used=[_text(tool) for tool in tools if _text(tool)],
            duration_ms=max(0, _safe_int(data.get("duration_ms", 0))),
            status=_text(data.get("status") or "success"),
        )


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Rust-compatible session plus Python-only continuity extensions."""

    session_id: str
    metadata: RustSessionMetadata
    messages: list[dict[str, Any]]
    turns: list[TurnRecord]
    input_history: list[str] = field(default_factory=list)
    memory_continuity: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)
    format_version: str = SESSION_FORMAT_VERSION


def derive_turn_records(
    messages: list[Mapping[str, Any]],
    *,
    created_at: float = 0.0,
) -> list[TurnRecord]:
    """Group message events into deterministic user-centered turn records."""

    turns: list[TurnRecord] = []
    current: dict[str, Any] | None = None
    turn_number = 0

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        turns.append(TurnRecord(**current))
        current = None

    for message in messages:
        if not isinstance(message, Mapping):
            continue
        role = _message_role(message)
        if role == "system":
            continue

        if role == "user" or current is None:
            flush()
            turn_number += 1
            current = {
                "turn_id": f"turn-{turn_number}",
                "turn_number": turn_number,
                "timestamp": _message_timestamp(message, created_at),
                "input_type": role,
                "input": _text(message.get("content")),
                "tools_used": [],
                "duration_ms": 0,
                "status": "success",
            }

        if role in {"assistant_tool_call", "tool_result", "tool"}:
            tool_name = _message_tool_name(message)
            if tool_name and tool_name not in current["tools_used"]:
                current["tools_used"].append(tool_name)
            if _message_is_error(message):
                current["status"] = "error"

    flush()
    return turns


def build_memory_continuity_snapshot(
    memory_manager: Any | None,
    *,
    workspace: str = "",
    pipeline: Any | None = None,
) -> dict[str, Any]:
    """Build a content-free snapshot used to rehydrate memory diagnostics."""

    snapshot: dict[str, Any] = {
        "schema": "minicode-memory-continuity-v1",
        "workspace": workspace,
        "captured_at": _iso_timestamp(time.time()),
        "state_paths": [
            ".mini-code-memory/memory.json",
            ".mini-code-memory/pipeline_state.json",
            ".mini-code-memory/memory_graph.json",
        ],
    }
    if memory_manager is None:
        return snapshot

    scope_counts: dict[str, int] = {}
    try:
        for scope, memory_file in getattr(memory_manager, "memories", {}).items():
            name = _text(getattr(scope, "value", scope))
            scope_counts[name] = len(getattr(memory_file, "entries", []) or [])
    except (AttributeError, TypeError):
        scope_counts = {}
    snapshot["scope_counts"] = scope_counts

    if pipeline is not None:
        try:
            stats = getattr(pipeline, "stats", {})
            if callable(stats):
                stats = stats()
            if isinstance(stats, Mapping):
                snapshot["pipeline_stats"] = {
                    str(key): value
                    for key, value in stats.items()
                    if isinstance(value, (str, int, float, bool)) or value is None
                }
        except Exception:
            pass
    return snapshot


def build_session_record(session: Any) -> SessionRecord:
    """Project an existing Python session into the Rust-compatible contract."""

    session_id = _text(getattr(session, "session_id", ""))
    created_at = float(getattr(session, "created_at", 0.0) or 0.0)
    updated_at = float(getattr(session, "updated_at", created_at) or created_at)
    messages = [
        dict(message)
        for message in (getattr(session, "messages", []) or [])
        if isinstance(message, Mapping)
    ]
    turns = derive_turn_records(messages, created_at=created_at)
    user_input_count = sum(1 for message in messages if _message_role(message) == "user")
    tool_call_count = sum(
        1
        for message in messages
        if _message_role(message) in {"assistant_tool_call", "tool_result", "tool"}
    )
    runtime_report = getattr(session, "readiness_report", {}) or {}
    model = None
    if isinstance(runtime_report, Mapping):
        model = _optional_text(
            runtime_report.get("model")
            or runtime_report.get("configuredModel")
            or runtime_report.get("configured_model")
        )
    memory_continuity = getattr(session, "memory_continuity", {}) or {}
    if not isinstance(memory_continuity, Mapping):
        memory_continuity = {}
    extensions: dict[str, Any] = {}
    transcript_entries = getattr(session, "transcript_entries", []) or []
    if isinstance(transcript_entries, list):
        extensions["transcript_entries"] = deepcopy(transcript_entries)
    checkpoints = getattr(session, "checkpoints", []) or []
    if isinstance(checkpoints, list):
        extensions["checkpoints"] = [
            {
                "checkpoint_id": _text(getattr(checkpoint, "checkpoint_id", "")),
                "created_at": getattr(checkpoint, "created_at", 0.0),
                "file_path": _text(getattr(checkpoint, "file_path", "")),
                "existed": bool(getattr(checkpoint, "existed", False)),
                "previous_content": _text(getattr(checkpoint, "previous_content", "")),
                "kind": _text(getattr(checkpoint, "kind", "edit") or "edit"),
                "group_id": _text(getattr(checkpoint, "group_id", "")),
            }
            for checkpoint in checkpoints
        ]

    metadata = RustSessionMetadata(
        session_id=session_id,
        created_at=_iso_timestamp(created_at),
        ended_at=_optional_text(getattr(session, "ended_at", None)),
        duration_seconds=max(0, int(updated_at - created_at)),
        model=model,
        cwd=_text(getattr(session, "workspace", "")),
        turn_count=len(turns),
        user_input_count=user_input_count,
        tool_call_count=tool_call_count,
        status=_text(getattr(session, "status", "active") or "active"),
        updated_at=_iso_timestamp(updated_at),
    )
    history = getattr(session, "history", []) or []
    return SessionRecord(
        session_id=session_id,
        metadata=metadata,
        messages=messages,
        turns=turns,
        input_history=[_text(item) for item in history[-MAX_INPUT_HISTORY:]],
        memory_continuity=deepcopy(dict(memory_continuity)),
        extensions=extensions,
    )


def write_session_bundle(session: Any, sessions_dir: Path) -> SessionRecord:
    """Write the three-file Rust-compatible session bundle atomically."""

    record = build_session_record(session)
    if not _valid_session_id(record.session_id):
        raise ValueError("invalid session id for bundle path")
    bundle_dir = Path(sessions_dir) / record.session_id
    metadata = record.metadata.to_dict()
    metadata.update(
        {
            "format_version": record.format_version,
            "memory_continuity": record.memory_continuity,
        }
    )
    atomic_write_json(bundle_dir / "metadata.json", metadata)
    atomic_write_json(
        bundle_dir / "conversation.json",
        {
            "session_id": record.session_id,
            "messages": record.messages,
            "turns": [turn.to_dict() for turn in record.turns],
            "python_extensions": record.extensions,
        },
    )
    atomic_write_json(
        bundle_dir / "input_history.json",
        {"entries": record.input_history},
    )
    return record


def _valid_session_id(session_id: str) -> bool:
    if (
        not isinstance(session_id, str)
        or not session_id
        or session_id in {".", ".."}
        or "/" in session_id
        or "\\" in session_id
    ):
        return False
    path = Path(session_id)
    return path.name == session_id and not path.is_absolute()


def read_session_bundle(session_id: str, sessions_dir: Path) -> SessionRecord | None:
    """Read a Rust-compatible bundle, returning ``None`` on partial/corrupt data."""

    if not _valid_session_id(session_id):
        return None
    bundle_dir = Path(sessions_dir) / session_id
    if bundle_dir.is_symlink() or not bundle_dir.is_dir():
        return None
    metadata = _read_json(bundle_dir / "metadata.json")
    conversation = _read_json(bundle_dir / "conversation.json")
    history = _read_json(bundle_dir / "input_history.json") or {}
    if metadata is None or conversation is None:
        return None

    messages = conversation.get("messages", [])
    if not isinstance(messages, list):
        return None
    raw_turns = conversation.get("turns", [])
    if not isinstance(raw_turns, list):
        raw_turns = []
    turns = [
        TurnRecord.from_dict(item, index)
        for index, item in enumerate(raw_turns)
        if isinstance(item, Mapping)
    ]
    raw_history = history.get("entries", [])
    if not isinstance(raw_history, list):
        raw_history = []
    memory_continuity = metadata.get("memory_continuity", {})
    if not isinstance(memory_continuity, Mapping):
        memory_continuity = {}
    extensions = conversation.get("python_extensions", {})
    if not isinstance(extensions, Mapping):
        extensions = {}
    metadata_session_id = _text(metadata.get("session_id") or session_id)
    if metadata_session_id != session_id:
        return None
    conversation_session_id = _text(conversation.get("session_id") or session_id)
    if conversation_session_id != session_id:
        return None

    return SessionRecord(
        session_id=metadata_session_id,
        metadata=RustSessionMetadata.from_dict(metadata, session_id),
        messages=[dict(item) for item in messages if isinstance(item, Mapping)],
        turns=turns,
        input_history=[_text(item) for item in raw_history[-MAX_INPUT_HISTORY:]],
        memory_continuity=deepcopy(dict(memory_continuity)),
        extensions=deepcopy(dict(extensions)),
        format_version=_text(metadata.get("format_version") or SESSION_FORMAT_VERSION),
    )


def delete_session_bundle(session_id: str, sessions_dir: Path) -> bool:
    """Remove only the validated bundle directory for one session."""

    if not _valid_session_id(session_id):
        return False
    bundle_dir = Path(sessions_dir) / session_id
    if bundle_dir.is_symlink() or not bundle_dir.is_dir():
        return False
    removed = False
    for path in bundle_dir.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed = True
    try:
        bundle_dir.rmdir()
        removed = True
    except OSError:
        pass
    return removed
