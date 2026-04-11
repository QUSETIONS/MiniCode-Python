from minicode.tui.state import ScreenState
from minicode.tui.tool_lifecycle import (
    _append_to_transcript_entry,
    _push_transcript_entry,
    _update_transcript_entry,
)


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
