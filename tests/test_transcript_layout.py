from minicode.tui.state import ScreenState
from minicode.tui.tool_lifecycle import (
    _append_to_transcript_entry,
    _finalize_dangling_running_tools,
    _push_transcript_entry,
    _update_tool_entry,
    _update_transcript_entry,
)
from minicode.tui.transcript import render_transcript
from minicode.tui.types import TranscriptEntry


def test_transcript_revision_bumps_on_entry_changes() -> None:
    state = ScreenState()
    assert state.transcript_revision == 0

    entry_id = _push_transcript_entry(state, kind="assistant", body="hello")
    assert state.transcript_revision == 1

    changed = _update_transcript_entry(state, entry_id, body="hello world")
    assert changed is True
    assert state.transcript_revision == 2

    appended = _append_to_transcript_entry(state, entry_id, "!")
    assert appended is True
    assert state.transcript_revision == 3


def test_transcript_revision_does_not_bump_on_noop_update() -> None:
    state = ScreenState()
    entry_id = _push_transcript_entry(state, kind="assistant", body="hello")
    assert state.transcript_revision == 1

    changed = _update_transcript_entry(state, entry_id, body="hello")
    assert changed is False
    assert state.transcript_revision == 1


def test_layout_cache_does_not_cross_transcript_lists_with_same_revision() -> None:
    first = [TranscriptEntry(id=1, kind="assistant", body="short")]
    second = [
        TranscriptEntry(
            id=1,
            kind="assistant",
            body="\n".join(f"line {i}" for i in range(12)),
        )
    ]

    render_transcript(first, scroll_offset=0, window_size=20, revision=7)
    rendered = render_transcript(second, scroll_offset=0, window_size=20, revision=7)

    assert "line 11" in rendered


def test_tool_entry_noop_update_does_not_bump_revision() -> None:
    state = ScreenState()
    entry_id = _push_transcript_entry(
        state,
        kind="tool",
        body="done",
        toolName="read_file",
        status="success",
    )
    assert state.transcript_revision == 1

    changed = _update_tool_entry(state, entry_id, "success", "done")

    assert changed is False
    assert state.transcript_revision == 1


def test_finalize_dangling_tool_bumps_revision_once() -> None:
    state = ScreenState()
    _push_transcript_entry(
        state,
        kind="tool",
        body="started",
        toolName="run_command",
        status="running",
    )

    _finalize_dangling_running_tools(state)

    assert state.transcript_revision == 2
