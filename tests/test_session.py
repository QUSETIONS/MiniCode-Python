"""Tests for session persistence and resume functionality."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from minicode.session import (
    AutosaveManager,
    SessionData,
    SessionMetadata,
    _runtime_summary_from_transcript_entries,
    cleanup_old_sessions,
    create_file_checkpoint,
    create_new_session,
    delete_session,
    format_checkpoint_summary_line,
    format_session_inspect,
    format_session_checkpoints,
    format_session_list,
    format_session_replay,
    format_session_resume,
    get_latest_session,
    list_sessions,
    load_session,
    rewind_session_data,
    rewind_session,
    save_session,
)


@pytest.fixture
def temp_session_dir(tmp_path):
    """Create a temporary session directory."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    with patch("minicode.session.SESSIONS_DIR", sessions_dir), \
         patch("minicode.session.MINI_CODE_DIR", tmp_path):
        yield sessions_dir


def test_create_new_session(temp_session_dir):
    """Test creating a new empty session."""
    workspace = "/tmp/test-workspace"
    session = create_new_session(workspace=workspace)
    
    assert session.session_id is not None
    assert len(session.session_id) == 12
    assert session.workspace == workspace
    assert session.messages == []
    assert session.transcript_entries == []
    assert session.created_at > 0
    assert session.updated_at > 0


def test_save_and_load_session(temp_session_dir):
    """Test saving and loading a session."""
    session = create_new_session(workspace="/tmp/test")
    session.messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    session.transcript_entries = [
        {"id": 1, "kind": "user", "body": "Hello"},
        {"id": 2, "kind": "assistant", "body": "Hi there!"},
    ]
    
    save_session(session)
    
    # Verify file was created
    session_file = temp_session_dir / f"{session.session_id}.json"
    assert session_file.exists()
    
    # Load and verify
    loaded = load_session(session.session_id)
    assert loaded is not None
    assert loaded.session_id == session.session_id
    assert len(loaded.messages) == 2
    assert len(loaded.transcript_entries) == 2
    assert loaded.workspace == "/tmp/test"


def test_save_and_load_session_preserves_runtime_summary(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    session.transcript_entries = [
        {
            "id": 1,
            "kind": "progress",
            "category": "runtime",
            "runtimeKind": "phase",
            "runtimeStep": 1,
            "runtimePhase": "explore",
            "body": "Runtime phase: explore.",
        },
        {
            "id": 2,
            "kind": "progress",
            "category": "runtime",
            "runtimeKind": "stop",
            "runtimeStep": 2,
            "runtimeStopReason": "done",
            "body": "Turn complete.",
        },
    ]

    save_session(session)
    loaded = load_session(session.session_id)

    assert loaded is not None
    assert loaded.metadata.runtime_summary == "phase:explore@1 -> stop:done@2"


def test_load_nonexistent_session(temp_session_dir):
    """Test loading a session that doesn't exist."""
    loaded = load_session("nonexistent")
    assert loaded is None


def test_delete_session(temp_session_dir):
    """Test deleting a session."""
    session = create_new_session(workspace="/tmp/test")
    save_session(session)
    
    # Delete
    result = delete_session(session.session_id)
    assert result is True
    
    # Verify file is gone
    session_file = temp_session_dir / f"{session.session_id}.json"
    assert not session_file.exists()
    
    # Try deleting again
    result = delete_session(session.session_id)
    assert result is False


def test_session_path_operations_reject_unsafe_ids(temp_session_dir, tmp_path):
    """Legacy JSON and delta paths must not escape the sessions directory."""
    outside_session = temp_session_dir.parent / "outside.json"
    outside_session.write_text('{"session_id": "outside"}', encoding="utf-8")

    assert load_session("../outside") is None
    assert delete_session("../outside") is False

    session = create_new_session(workspace="/tmp/test")
    session.session_id = "../escape"
    with pytest.raises(ValueError, match="invalid session id"):
        save_session(session)

    assert outside_session.exists()
    assert not (temp_session_dir.parent / "escape.json").exists()


@pytest.mark.parametrize("mismatch_field", ["payload", "metadata"])
def test_load_session_rejects_legacy_payload_id_mismatch(
    temp_session_dir, mismatch_field
):
    """A file name must not make a different serialized session resumable."""
    source = create_new_session(workspace="/tmp/source")
    source.messages = [{"role": "user", "content": "source"}]
    save_session(source, force_full=True)
    payload = json.loads(
        (temp_session_dir / f"{source.session_id}.json").read_text(encoding="utf-8")
    )

    requested_id = "requested"
    payload["session_id"] = (
        source.session_id if mismatch_field == "payload" else requested_id
    )
    payload["metadata"]["session_id"] = (
        source.session_id if mismatch_field == "metadata" else requested_id
    )
    (temp_session_dir / f"{requested_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    assert load_session(requested_id) is None


def test_update_metadata_keeps_session_ids_aligned(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    session.metadata.session_id = "stale-id"

    session.update_metadata()

    assert session.metadata.session_id == session.session_id


def test_load_session_does_not_follow_legacy_symlinks(temp_session_dir, tmp_path):
    """Legacy session and delta readers must stay inside the session store."""
    source = create_new_session(workspace="/tmp/source")
    source.messages = [{"role": "user", "content": "base"}]
    save_session(source, force_full=True)

    linked_path = temp_session_dir / "linked.json"
    linked_path.symlink_to(temp_session_dir / f"{source.session_id}.json")
    assert load_session("linked") is None

    outside_delta_dir = tmp_path / "outside-deltas"
    outside_delta_dir.mkdir()
    (outside_delta_dir / "delta_9999.json").write_text(
        json.dumps(
            {
                "msg_offset": 1,
                "messages": [{"role": "user", "content": "outside"}],
            }
        ),
        encoding="utf-8",
    )
    (temp_session_dir / "deltas").mkdir()
    delta_dir = temp_session_dir / "deltas" / source.session_id
    delta_dir.symlink_to(outside_delta_dir, target_is_directory=True)

    loaded = load_session(source.session_id)

    assert loaded is not None
    assert loaded.messages == source.messages


def test_corrupt_legacy_session_is_rejected_without_raising(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    session_path = temp_session_dir / f"{session.session_id}.json"
    session_path.write_text("[]", encoding="utf-8")

    assert load_session(session.session_id) is None


def test_corrupt_session_index_entries_are_skipped(temp_session_dir):
    index_path = temp_session_dir.parent / "sessions_index.json"
    index_path.write_text(
        json.dumps(
            {
                "../escape": {"session_id": "../escape"},
                "valid": "not-a-metadata-object",
            }
        ),
        encoding="utf-8",
    )

    assert list_sessions() == []


def test_list_sessions(temp_session_dir):
    """Test listing all sessions."""
    # Create multiple sessions
    sessions = []
    for i in range(3):
        session = create_new_session(workspace=f"/tmp/test-{i}")
        session.messages = [{"role": "user", "content": f"Message {i}"}]
        save_session(session)
        sessions.append(session)
    
    # List and verify
    listed = list_sessions()
    assert len(listed) == 3
    
    # Should be sorted by updated_at (newest first)
    assert listed[0].updated_at >= listed[1].updated_at


def test_list_sessions_can_filter_by_workspace(temp_session_dir):
    """Test listing sessions for one workspace."""
    session1 = create_new_session(workspace="/tmp/workspace1")
    session1.messages = [{"role": "user", "content": "Workspace one"}]
    save_session(session1)

    session2 = create_new_session(workspace="/tmp/workspace2")
    session2.messages = [{"role": "user", "content": "Workspace two"}]
    save_session(session2)

    listed = list_sessions(workspace="/tmp/workspace2")

    assert [meta.session_id for meta in listed] == [session2.session_id]
    assert listed[0].workspace == "/tmp/workspace2"


def test_get_latest_session(temp_session_dir):
    """Test getting the most recent session."""
    # Create sessions for different workspaces
    session1 = create_new_session(workspace="/tmp/workspace1")
    save_session(session1)
    
    session2 = create_new_session(workspace="/tmp/workspace2")
    save_session(session2)
    
    # Get latest for workspace2
    latest = get_latest_session(workspace="/tmp/workspace2")
    assert latest is not None
    assert latest.session_id == session2.session_id
    
    # Get latest without filter
    latest_any = get_latest_session()
    assert latest_any is not None


def test_cleanup_old_sessions(temp_session_dir):
    """Test cleanup of old sessions beyond limit."""
    # Create 10 sessions
    for i in range(10):
        session = create_new_session(workspace=f"/tmp/test-{i}")
        save_session(session)
    
    # Cleanup to keep only 5
    deleted = cleanup_old_sessions(max_sessions=5)
    assert deleted == 5
    
    # Verify only 5 remain
    remaining = list_sessions()
    assert len(remaining) == 5


def test_autosave_manager(temp_session_dir):
    """Test autosave manager with rate limiting."""
    session = create_new_session(workspace="/tmp/test")
    manager = AutosaveManager(session, interval=1)
    
    # Initially not dirty
    assert not manager.should_save()
    
    # Mark dirty
    manager.mark_dirty()
    
    # Should not save yet (interval not elapsed)
    assert not manager.should_save()
    
    # Force save
    manager.force_save()
    
    # Verify saved
    loaded = load_session(session.session_id)
    assert loaded is not None


def test_format_session_list(temp_session_dir):
    """Test formatting session list for display."""
    # Empty list
    result = format_session_list([])
    assert "No saved sessions" in result
    
    # With sessions
    session = create_new_session(workspace="/tmp/test")
    session.messages = [{"role": "user", "content": "Hello world"}]
    session.update_metadata()
    
    result = format_session_list([session.metadata])
    assert "Saved sessions:" in result
    assert session.session_id[:8] in result


def test_format_session_list_includes_runtime_summary(temp_session_dir):
    meta = SessionMetadata(
        session_id="abc123456789",
        created_at=1.0,
        updated_at=2.0,
        first_message="hello",
        message_count=3,
        workspace="/tmp/test",
        runtime_summary="phase:verify@2 -> stop:done@3",
    )

    result = format_session_list([meta])

    assert "Runtime: phase:verify@2 -> stop:done@3" in result


def test_format_session_resume(temp_session_dir):
    """Test formatting session info for resume."""
    session = create_new_session(workspace="/tmp/test")
    session.messages = [{"role": "user", "content": "Hello"}]
    
    result = format_session_resume(session)
    assert "Resuming session" in result
    assert session.session_id[:8] in result
    assert "/tmp/test" in result


def test_format_session_resume_includes_runtime_summary(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    session.transcript_entries = [
        {
            "id": 1,
            "kind": "progress",
            "category": "runtime",
            "runtimeKind": "phase",
            "runtimeStep": 2,
            "runtimePhase": "verify",
            "body": "Runtime phase: verify.",
        },
        {
            "id": 2,
            "kind": "progress",
            "category": "runtime",
            "runtimeKind": "stop",
            "runtimeStep": 3,
            "runtimeStopReason": "done",
            "body": "Turn complete.",
        },
    ]
    session.update_metadata()

    result = format_session_resume(session)

    assert "Runtime: phase:verify@2 -> stop:done@3" in result


def test_save_and_load_session_preserves_checkpoints(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    checkpoint = create_file_checkpoint(
        session,
        file_path="/tmp/test/demo.txt",
        existed=True,
        previous_content="before",
    )

    assert checkpoint is not None

    loaded = load_session(session.session_id)
    assert loaded is not None
    assert loaded.metadata.checkpoint_count == 1
    assert len(loaded.checkpoints) == 1
    assert loaded.checkpoints[0].file_path == "/tmp/test/demo.txt"
    assert loaded.checkpoints[0].previous_content == "before"


def test_save_and_load_session_preserves_product_surfaces(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    session.instruction_layers = [
        {
            "name": "project-managed",
            "scope": "project",
            "kind": "managed",
            "path": "/tmp/test/.mini-code/MANAGED.md",
            "exists": True,
            "preview": "Prefer strict verification.",
        }
    ]
    session.hook_status = {
        "total_hooks": 2,
        "enabled_hooks": 1,
        "total_calls": 3,
        "total_duration_ms": 14,
    }
    session.delegated_tasks = [{"label": "lint-worker", "status": "running"}]
    session.delegation_status = {
        "running_tasks": 1,
        "total_tracked": 1,
        "max_slots": 4,
        "available_slots": 3,
        "active_labels": ["lint-worker"],
    }
    session.extension_manifests = [
        {
            "name": "git-helpers",
            "scope": "project",
            "enabled": True,
            "version": "1.2.0",
        }
    ]
    session.readiness_report = {
        "status": "blocked",
        "provider": "anthropic-compatible",
        "provider_ready": False,
        "provider_channel": "anthropic-compatible via baseUrl/authToken",
        "fallback_guidance": [
            "Primary runtime is using a single anthropic-compatible channel from baseUrl/authToken.",
            "Add fallbackModels or anthropicFallbackModels to enable model failover.",
        ],
        "issues": ["Missing provider channel"],
    }
    session.update_metadata()

    save_session(session)
    loaded = load_session(session.session_id)

    assert loaded is not None
    assert loaded.instruction_layers[0]["kind"] == "managed"
    assert loaded.hook_status["total_calls"] == 3
    assert loaded.delegated_tasks[0]["label"] == "lint-worker"
    assert loaded.extension_manifests[0]["name"] == "git-helpers"
    assert loaded.readiness_report["provider"] == "anthropic-compatible"
    assert "project-managed" in loaded.metadata.instruction_summary
    assert "1 running" in loaded.metadata.delegation_summary


def test_rewind_session_restores_latest_file_content(temp_session_dir, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo.txt"
    target.write_text("before", encoding="utf-8")

    session = create_new_session(workspace=str(workspace))
    create_file_checkpoint(
        session,
        file_path=str(target),
        existed=True,
        previous_content="before",
    )
    target.write_text("after", encoding="utf-8")

    rewound, restored = rewind_session(session.session_id)

    assert rewound is not None
    assert len(restored) == 1
    assert target.read_text(encoding="utf-8") == "before"
    assert rewound.metadata.checkpoint_count == 1
    assert len(rewound.checkpoints) == 1
    assert rewound.checkpoints[0].kind == "rewind"
    assert rewound.checkpoints[0].previous_content == "after"


def test_rewind_session_deletes_new_file_for_nonexistent_checkpoint(temp_session_dir, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "created.txt"

    session = create_new_session(workspace=str(workspace))
    create_file_checkpoint(
        session,
        file_path=str(target),
        existed=False,
        previous_content="",
    )
    target.write_text("new file", encoding="utf-8")

    rewound, restored = rewind_session(session.session_id)

    assert rewound is not None
    assert len(restored) == 1
    assert not target.exists()
    assert rewound.metadata.checkpoint_count == 1
    assert rewound.checkpoints[0].kind == "rewind"
    assert rewound.checkpoints[0].previous_content == "new file"


def test_rewind_session_supports_checkpoint_id(temp_session_dir, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo.txt"
    target.write_text("v1", encoding="utf-8")

    session = create_new_session(workspace=str(workspace))
    first = create_file_checkpoint(
        session,
        file_path=str(target),
        existed=True,
        previous_content="v1",
    )
    target.write_text("v2", encoding="utf-8")
    second = create_file_checkpoint(
        session,
        file_path=str(target),
        existed=True,
        previous_content="v2",
    )
    target.write_text("v3", encoding="utf-8")

    rewound, restored = rewind_session(
        session.session_id,
        checkpoint_id=first.checkpoint_id if first else None,
    )

    assert second is not None
    assert rewound is not None
    assert [item.checkpoint_id for item in restored] == [
        first.checkpoint_id,
        second.checkpoint_id,
    ]
    assert target.read_text(encoding="utf-8") == "v1"
    assert len(rewound.checkpoints) == 1
    assert rewound.checkpoints[0].kind == "rewind"
    assert rewound.checkpoints[0].previous_content == "v3"


def test_rewind_session_data_restores_in_memory_session(temp_session_dir, tmp_path):
    target = tmp_path / "demo.txt"
    target.write_text("after", encoding="utf-8")
    session = create_new_session(workspace=str(tmp_path))
    create_file_checkpoint(
        session,
        file_path=str(target),
        existed=True,
        previous_content="before",
    )

    restored = rewind_session_data(session)

    assert [item.file_path for item in restored] == [str(target)]
    assert target.read_text(encoding="utf-8") == "before"
    assert session.metadata.checkpoint_count == 1
    assert len(session.checkpoints) == 1
    assert session.checkpoints[0].kind == "rewind"
    assert session.checkpoints[0].previous_content == "after"


def test_rewind_session_data_allows_undoing_a_prior_rewind(temp_session_dir, tmp_path):
    target = tmp_path / "demo.txt"
    target.write_text("v1", encoding="utf-8")
    session = create_new_session(workspace=str(tmp_path))
    create_file_checkpoint(
        session,
        file_path=str(target),
        existed=True,
        previous_content="v1",
    )
    target.write_text("v2", encoding="utf-8")
    create_file_checkpoint(
        session,
        file_path=str(target),
        existed=True,
        previous_content="v2",
    )
    target.write_text("v3", encoding="utf-8")

    restored = rewind_session_data(session)

    assert len(restored) == 1
    assert target.read_text(encoding="utf-8") == "v2"
    assert session.checkpoints[-1].kind == "rewind"

    undo = rewind_session_data(session)

    assert len(undo) == 1
    assert undo[0].kind == "rewind"
    assert target.read_text(encoding="utf-8") == "v3"
    assert session.checkpoints[-1].kind == "rewind"
    assert session.checkpoints[-1].previous_content == "v2"


def test_rewind_session_data_undoes_latest_rewind_group_atomically(temp_session_dir, tmp_path):
    alpha = tmp_path / "alpha.txt"
    beta = tmp_path / "beta.txt"
    alpha.write_text("a1", encoding="utf-8")
    beta.write_text("b1", encoding="utf-8")
    session = create_new_session(workspace=str(tmp_path))
    create_file_checkpoint(
        session,
        file_path=str(alpha),
        existed=True,
        previous_content="a1",
    )
    alpha.write_text("a2", encoding="utf-8")
    create_file_checkpoint(
        session,
        file_path=str(beta),
        existed=True,
        previous_content="b1",
    )
    beta.write_text("b2", encoding="utf-8")

    restored = rewind_session_data(session, steps=2)

    assert len(restored) == 2
    assert alpha.read_text(encoding="utf-8") == "a1"
    assert beta.read_text(encoding="utf-8") == "b1"
    assert len(session.checkpoints) == 2
    assert {checkpoint.kind for checkpoint in session.checkpoints} == {"rewind"}
    group_ids = {checkpoint.group_id for checkpoint in session.checkpoints}
    assert len(group_ids) == 1

    undo = rewind_session_data(session)

    assert len(undo) == 2
    assert {item.kind for item in undo} == {"rewind"}
    assert alpha.read_text(encoding="utf-8") == "a2"
    assert beta.read_text(encoding="utf-8") == "b2"


def test_format_session_list_includes_checkpoint_count(temp_session_dir):
    meta = SessionMetadata(
        session_id="abc123456789",
        created_at=1.0,
        updated_at=2.0,
        first_message="hello",
        message_count=3,
        workspace="/tmp/test",
        checkpoint_count=2,
    )

    result = format_session_list([meta])

    assert "Checkpoints: 2" in result


def test_format_session_resume_includes_checkpoint_count(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    create_file_checkpoint(
        session,
        file_path="/tmp/test/demo.txt",
        existed=True,
        previous_content="before",
    )

    result = format_session_resume(session)

    assert "Checkpoints: 1" in result


def test_format_session_resume_includes_recent_checkpoints(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    first = create_file_checkpoint(
        session,
        file_path="/tmp/test/alpha.txt",
        existed=True,
        previous_content="before",
    )
    second = create_file_checkpoint(
        session,
        file_path="/tmp/test/beta.txt",
        existed=True,
        previous_content="before",
    )

    result = format_session_resume(session)

    assert first is not None
    assert second is not None
    assert "Recent checkpoints:" in result
    assert f"[{second.checkpoint_id[:8]}] beta.txt" in result
    assert f"[{first.checkpoint_id[:8]}] alpha.txt" in result


def test_format_session_checkpoints_lists_latest_first(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    first = create_file_checkpoint(
        session,
        file_path="/tmp/test/first.txt",
        existed=True,
        previous_content="one",
    )
    second = create_file_checkpoint(
        session,
        file_path="/tmp/test/second.txt",
        existed=False,
        previous_content="",
    )

    result = format_session_checkpoints(session)

    assert first is not None
    assert second is not None
    assert f"[{second.checkpoint_id[:8]}]" in result
    assert f"[{first.checkpoint_id[:8]}]" in result
    assert result.index(second.file_path) < result.index(first.file_path)
    assert "Restores: new file" in result
    assert "Type: edit" in result


def test_format_checkpoint_summary_line_returns_latest_checkpoint_preview(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    first = create_file_checkpoint(
        session,
        file_path="/tmp/test/first.txt",
        existed=True,
        previous_content="one",
    )
    second = create_file_checkpoint(
        session,
        file_path="/tmp/test/second.txt",
        existed=False,
        previous_content="",
    )

    result = format_checkpoint_summary_line(session)

    assert first is not None
    assert second is not None
    assert result.startswith("checkpoint-summary: 2 saved; latest ")
    assert f"[{second.checkpoint_id[:8]}] second.txt" in result
    assert f"[{first.checkpoint_id[:8]}] first.txt" in result


def test_format_checkpoint_summary_line_marks_rewind_safety_entries(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    create_file_checkpoint(
        session,
        file_path="/tmp/test/first.txt",
        existed=True,
        previous_content="one",
    )
    session.checkpoints.append(
        type(session.checkpoints[0])(
            checkpoint_id="rewind123456",
            created_at=2.0,
            file_path="/tmp/test/second.txt",
            existed=True,
            previous_content="two",
            kind="rewind",
            group_id="group-1",
        )
    )
    session.update_metadata()

    result = format_checkpoint_summary_line(session)

    assert "[rewind12] second.txt [rewind]" in result


def test_format_session_inspect_includes_runtime_checkpoints_and_recent_transcript(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    session.history = ["look at logs"]
    session.skills = ["runtime", "rewind"]
    session.mcp_servers = ["memory"]
    create_file_checkpoint(
        session,
        file_path="/tmp/test/demo.txt",
        existed=True,
        previous_content="before",
    )
    session.transcript_entries = [
        {"id": 1, "kind": "assistant", "body": "Initial analysis complete."},
        {
            "id": 2,
            "kind": "progress",
            "category": "runtime",
            "runtimeKind": "phase",
            "runtimeStep": 4,
            "runtimePhase": "verify",
            "body": "Runtime phase: verify.",
        },
        {
            "id": 3,
            "kind": "tool",
            "toolName": "edit_file",
            "status": "success",
            "body": "Patched minicode/session.py",
        },
    ]
    session.update_metadata()

    result = format_session_inspect(session)

    assert f"Session inspect: {session.session_id[:8]}" in result
    assert "Skills: runtime, rewind" in result
    assert "MCP servers: memory" in result
    assert "Checkpoints: 1" in result
    assert "Runtime: phase:verify@4" in result
    assert "Recent checkpoints: 1 saved; latest " in result
    assert "Recent transcript (3 shown):" in result
    assert "- [assistant] Initial analysis complete." in result
    assert "- [runtime:phase] Runtime phase: verify." in result
    assert "- [tool:edit_file/success] Patched minicode/session.py" in result


def test_format_session_inspect_and_replay_include_product_surfaces(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    session.instruction_layers = [
        {
            "name": "project-managed",
            "scope": "project",
            "kind": "managed",
            "path": "/tmp/test/.mini-code/MANAGED.md",
            "exists": True,
            "preview": "Prefer strict verification.",
        }
    ]
    session.hook_status = {
        "total_hooks": 2,
        "enabled_hooks": 1,
        "total_calls": 4,
        "total_duration_ms": 11,
        "failure_count": 1,
        "last_status": "error",
        "last_error": "pytest failed",
    }
    session.delegated_tasks = [{"label": "lint-worker", "status": "running"}]
    session.delegation_status = {
        "running_tasks": 1,
        "total_tracked": 2,
        "max_slots": 4,
        "available_slots": 3,
        "active_labels": ["lint-worker"],
    }
    session.extension_manifests = [
        {
            "name": "git-helpers",
            "scope": "project",
            "enabled": True,
            "version": "1.2.0",
            "description": "Extra git shortcuts",
            "entrypoint": "extensions/git_helpers.py",
        }
    ]
    session.readiness_report = {
        "status": "blocked",
        "provider": "anthropic-compatible",
        "provider_ready": False,
        "provider_channel": "anthropic-compatible via baseUrl/authToken",
        "fallback_guidance": [
            "Primary runtime is using a single anthropic-compatible channel from baseUrl/authToken.",
            "Add fallbackModels or anthropicFallbackModels to enable model failover.",
        ],
        "issues": ["Missing provider channel"],
    }
    session.update_metadata()

    inspect_text = format_session_inspect(session)
    replay_text = format_session_replay(session)

    assert "Instructions:" in inspect_text
    assert "Hooks:" in inspect_text
    assert "Delegation:" in inspect_text
    assert "Extensions:" in inspect_text
    assert "Readiness:" in inspect_text
    assert "Instruction layers:" in inspect_text
    assert "Hook surface:" in inspect_text
    assert "Delegation surface:" in inspect_text
    assert "Extensions:" in inspect_text
    assert "Readiness:" in inspect_text
    assert "project-managed" in inspect_text
    assert "1/2 hook(s) enabled" in inspect_text
    assert "lint-worker" in inspect_text
    assert "git-helpers" in inspect_text
    assert "channel: anthropic-compatible via baseUrl/authToken" in inspect_text
    assert "guidance: Primary runtime is using a single anthropic-compatible channel" in inspect_text
    assert "Missing provider channel" in inspect_text

    assert "Readiness:" in replay_text
    assert "Delegation:" in replay_text
    assert "Instruction layers:" in replay_text
    assert "Extensions:" in replay_text
    assert "blocked via anthropic-compatible" in replay_text
    assert "channel: anthropic-compatible via baseUrl/authToken" in replay_text
    assert "guidance: Primary runtime is using a single anthropic-compatible channel" in replay_text
    assert "project-managed" in replay_text
    assert "git-helpers" in replay_text


def test_format_session_replay_includes_checkpoints_history_and_timeline(temp_session_dir):
    session = create_new_session(workspace="/tmp/test")
    session.history = ["inspect logs", "rerun tests with strict verify"]
    create_file_checkpoint(
        session,
        file_path="/tmp/test/demo.txt",
        existed=True,
        previous_content="before",
    )
    session.transcript_entries = [
        {
            "id": 1,
            "kind": "progress",
            "category": "runtime",
            "runtimeKind": "phase",
            "runtimeStep": 2,
            "runtimePhase": "verify",
            "body": "Runtime phase: verify.",
        },
        {
            "id": 2,
            "kind": "assistant",
            "body": "Collected evidence and prepared final answer.",
        },
    ]
    session.update_metadata()

    result = format_session_replay(session)

    assert f"Session replay: {session.session_id[:8]}" in result
    assert "Runtime: phase:verify@2" in result
    assert "Checkpoint trail (1 shown):" in result
    assert "demo.txt (edit)" in result
    assert "Prompt history (2 shown):" in result
    assert "rerun tests with strict verify" in result
    assert "Transcript timeline (2 shown):" in result
    assert "- [runtime:phase] Runtime phase: verify." in result
    assert "- [assistant] Collected evidence and prepared final answer." in result


def test_runtime_summary_from_transcript_entries_deduplicates_runtime_tokens():
    summary = _runtime_summary_from_transcript_entries(
        [
            {
                "kind": "progress",
                "category": "runtime",
                "runtimeKind": "phase",
                "runtimeStep": 1,
                "runtimePhase": "explore",
                "body": "Runtime phase: explore.",
            },
            {
                "kind": "progress",
                "category": "runtime",
                "runtimeKind": "phase",
                "runtimeStep": 1,
                "runtimePhase": "explore",
                "body": "Runtime phase: explore.",
            },
            {
                "kind": "progress",
                "category": "runtime",
                "runtimeKind": "guard",
                "runtimeStep": 4,
                "runtimeVerificationFocus": "tool_evidence",
                "body": "Verification guard is holding the turn open.",
            },
        ]
    )

    assert summary == "phase:explore@1 -> guard:tool_evidence@4"


# ---------------------------------------------------------------------------
# Deep-dive: delta incremental save/merge robustness (2026-06-16)
# ---------------------------------------------------------------------------


def test_update_metadata_handles_none_content(temp_session_dir):
    """A user/assistant message with content=None must not crash update_metadata
    (called on every save_session). Previously: TypeError on content[:100]."""
    session = create_new_session(workspace="/tmp/test")
    session.messages = [
        {"role": "user", "content": None},
        {"role": "assistant", "content": None},
        {"role": "user", "content": "real prompt"},
    ]
    session.update_metadata()  # must not raise
    assert session.metadata.first_message == ""  # None coerced to ""


def test_delta_roundtrip_preserves_appended_state(temp_session_dir):
    """Full save, then several incremental (delta) appends, then load must
    reconstruct messages/transcripts/checkpoints exactly."""
    session = create_new_session(workspace="/tmp/test")
    session.messages = [{"role": "user", "content": "m0"}]
    session.transcript_entries = [{"id": 0, "kind": "user", "body": "m0"}]
    save_session(session)  # full save (first)

    # Append across multiple delta saves
    for i in range(1, 6):
        session.messages.append({"role": "assistant", "content": f"m{i}"})
        session.transcript_entries.append({"id": i, "kind": "assistant", "body": f"m{i}"})
        save_session(session, force_full=False)  # delta saves

    loaded = load_session(session.session_id)
    assert loaded is not None
    assert [m["content"] for m in loaded.messages] == [f"m{i}" for i in range(6)]
    assert len(loaded.transcript_entries) == 6


def test_delta_save_idempotent_when_nothing_changed(temp_session_dir):
    """Saving with no new data should not create spurious deltas or grow state."""
    session = create_new_session(workspace="/tmp/test")
    session.messages = [{"role": "user", "content": "x"}]
    save_session(session)  # full
    count_after_full = session._delta_save_count
    save_session(session, force_full=False)  # nothing new
    save_session(session, force_full=False)  # nothing new
    assert session._delta_save_count == count_after_full  # no new deltas recorded


def test_save_load_preserves_checkpoints(temp_session_dir, tmp_path):
    """Checkpoint append across a delta save must round-trip exactly."""
    session = create_new_session(workspace=str(tmp_path))
    session.messages = [{"role": "user", "content": "go"}]
    save_session(session)  # full

    cp = create_file_checkpoint(
        session, file_path=str(tmp_path / "f.txt"), existed=True, previous_content="before"
    )
    assert cp is not None
    # create_file_checkpoint already appends to session.checkpoints and delta-saves

    loaded = load_session(session.session_id)
    assert loaded is not None
    assert len(loaded.checkpoints) == 1
    assert loaded.checkpoints[0].checkpoint_id == cp.checkpoint_id
