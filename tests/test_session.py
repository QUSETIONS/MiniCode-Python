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
    cleanup_old_sessions,
    create_new_session,
    delete_session,
    format_session_list,
    format_session_resume,
    get_latest_session,
    list_sessions,
    load_session,
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


def test_format_session_resume(temp_session_dir):
    """Test formatting session info for resume."""
    session = create_new_session(workspace="/tmp/test")
    session.messages = [{"role": "user", "content": "Hello"}]
    
    result = format_session_resume(session)
    assert "Resuming session" in result
    assert session.session_id[:8] in result
    assert "/tmp/test" in result
