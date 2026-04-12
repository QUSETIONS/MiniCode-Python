from minicode.tui.renderer import _get_transcript_snapshot
from minicode.tui.state import ScreenState
from minicode.tui.tool_lifecycle import _push_transcript_entry


def test_transcript_snapshot_reuses_list_until_revision_changes() -> None:
    state = ScreenState()
    _push_transcript_entry(state, kind="assistant", body="hello")

    first = _get_transcript_snapshot(state)
    second = _get_transcript_snapshot(state)

    assert second is first

    _push_transcript_entry(state, kind="assistant", body="world")
    third = _get_transcript_snapshot(state)

    assert third is not first
    assert len(third) == 2
