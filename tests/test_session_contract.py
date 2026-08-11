"""Tests for the Rust-compatible session bundle and memory continuity layer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from minicode.session import (
    create_new_session,
    delete_session,
    load_session,
    save_session,
)
from minicode.session_contract import (
    build_memory_continuity_snapshot,
    build_session_record,
    read_session_bundle,
    write_session_bundle,
)


def test_session_record_derives_user_turn_and_tool_error() -> None:
    session = create_new_session("/workspace")
    session.messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "update the file"},
        {
            "role": "assistant_tool_call",
            "toolName": "write_file",
            "input": {"path": "a.txt"},
        },
        {
            "role": "tool_result",
            "toolName": "write_file",
            "content": "permission denied",
            "isError": True,
        },
        {"role": "assistant", "content": "I could not update it."},
    ]

    record = build_session_record(session)
    session.update_metadata()

    assert record.metadata.user_input_count == 1
    assert record.metadata.tool_call_count == 2
    assert len(record.turns) == 1
    assert record.turns[0].tools_used == ["write_file"]
    assert record.turns[0].status == "error"
    assert session.metadata.turn_count == 1
    assert session.metadata.tool_call_count == 2


def test_save_emits_rust_bundle_and_memory_continuity(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = create_new_session(str(workspace))
    session.messages = [
        {"role": "user", "content": "inspect the repository"},
        {"role": "assistant", "content": "done"},
    ]
    session.memory_continuity = {
        "schema": "minicode-memory-continuity-v1",
        "scope_counts": {"project": 2},
    }

    with patch("minicode.session.SESSIONS_DIR", sessions_dir), patch(
        "minicode.session.MINI_CODE_DIR", tmp_path
    ):
        save_session(session, force_full=True)

    bundle_dir = sessions_dir / session.session_id
    metadata = json.loads((bundle_dir / "metadata.json").read_text(encoding="utf-8"))
    conversation = json.loads(
        (bundle_dir / "conversation.json").read_text(encoding="utf-8")
    )

    assert metadata["session_id"] == session.session_id
    assert metadata["cwd"] == str(workspace)
    assert metadata["turn_count"] == 1
    assert metadata["memory_continuity"]["scope_counts"]["project"] == 2
    assert len(conversation["turns"]) == 1
    assert conversation["messages"][0]["role"] == "user"
    assert not list(bundle_dir.glob("*.tmp"))


def test_bundle_only_session_can_be_resumed(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session = create_new_session(str(tmp_path / "workspace"))
    session.messages = [{"role": "user", "content": "resume me"}]
    session.history = ["resume me"]
    session.memory_continuity = {"schema": "minicode-memory-continuity-v1"}
    write_session_bundle(session, sessions_dir)

    with patch("minicode.session.SESSIONS_DIR", sessions_dir), patch(
        "minicode.session.MINI_CODE_DIR", tmp_path
    ):
        loaded = load_session(session.session_id)

    assert loaded is not None
    assert loaded.messages == session.messages
    assert loaded.history == session.history
    assert loaded.turns[0]["input"] == "resume me"
    assert loaded.memory_continuity["schema"] == "minicode-memory-continuity-v1"


def test_corrupt_bundle_is_ignored_without_traversing_session_path(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    bundle_dir = sessions_dir / "broken"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "metadata.json").write_text("{", encoding="utf-8")

    assert read_session_bundle("broken", sessions_dir) is None
    assert read_session_bundle("../broken", sessions_dir) is None
    assert read_session_bundle("..", sessions_dir) is None
    assert read_session_bundle(".", sessions_dir) is None


def test_bundle_metadata_must_match_requested_session_id(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    bundle_dir = sessions_dir / "requested"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "metadata.json").write_text(
        json.dumps({"session_id": "different"}),
        encoding="utf-8",
    )
    (bundle_dir / "conversation.json").write_text(
        json.dumps({"session_id": "different", "messages": []}),
        encoding="utf-8",
    )

    assert read_session_bundle("requested", sessions_dir) is None


def test_bundle_conversation_must_match_requested_session_id(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    bundle_dir = sessions_dir / "requested"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "metadata.json").write_text(
        json.dumps({"session_id": "requested"}),
        encoding="utf-8",
    )
    (bundle_dir / "conversation.json").write_text(
        json.dumps({"session_id": "different", "messages": []}),
        encoding="utf-8",
    )

    assert read_session_bundle("requested", sessions_dir) is None


@pytest.mark.parametrize("session_id", ["", ".", "..", "../escape", "nested/id", r"nested\\id"])
def test_write_bundle_rejects_unsafe_session_id(
    tmp_path: Path, session_id: str
) -> None:
    session = create_new_session(str(tmp_path / "workspace"))
    session.session_id = session_id

    with pytest.raises(ValueError, match="invalid session id"):
        write_session_bundle(session, tmp_path / "sessions")

    assert not (tmp_path / "escape").exists()


def test_bundle_with_non_finite_timestamps_is_recovered_safely(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    bundle_dir = sessions_dir / "damaged-time"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "session_id": "damaged-time",
                "created_at": float("nan"),
                "duration_seconds": 1,
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "conversation.json").write_text(
        json.dumps(
            {
                "session_id": "damaged-time",
                "messages": [
                    {"role": "user", "content": "recover"},
                    {"role": "assistant", "timestamp": float("inf"), "content": "ok"},
                ],
            }
        ),
        encoding="utf-8",
    )

    record = read_session_bundle("damaged-time", sessions_dir)

    assert record is not None
    assert record.metadata.created_at


def test_bundle_with_malformed_numeric_fields_is_recovered_safely(
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    bundle_dir = sessions_dir / "damaged"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "session_id": "damaged",
                "created_at": "not-a-timestamp",
                "duration_seconds": "not-a-number",
                "turn_count": "not-a-number",
                "cwd": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "conversation.json").write_text(
        json.dumps(
            {
                "session_id": "damaged",
                "messages": [{"role": "user", "content": "resume safely"}],
                "turns": [
                    {
                        "turn_id": "turn-1",
                        "turn_number": "bad",
                        "duration_ms": "bad",
                        "input": "resume safely",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    record = read_session_bundle("damaged", sessions_dir)

    assert record is not None
    assert record.metadata.duration_seconds == 0
    assert record.metadata.turn_count == 0
    assert record.turns[0].turn_number == 1
    assert record.turns[0].duration_ms == 0


def test_memory_continuity_snapshot_is_content_free() -> None:
    class MemoryFile:
        entries = [object(), object()]

    class MemoryManager:
        memories = {"project": MemoryFile()}

    snapshot = build_memory_continuity_snapshot(
        MemoryManager(), workspace="/workspace"
    )

    assert snapshot["scope_counts"] == {"project": 2}
    assert "memory.json" in snapshot["state_paths"][0]
    assert "content" not in snapshot


def test_delete_session_removes_legacy_file_and_bundle(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session = create_new_session(str(tmp_path))

    with patch("minicode.session.SESSIONS_DIR", sessions_dir), patch(
        "minicode.session.MINI_CODE_DIR", tmp_path
    ):
        save_session(session)
        assert delete_session(session.session_id)

    assert not (sessions_dir / f"{session.session_id}.json").exists()
    assert not (sessions_dir / session.session_id).exists()
