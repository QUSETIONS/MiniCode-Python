from __future__ import annotations

import threading
import time
from typing import Any, Callable

from minicode.tui.state import ScreenState
from minicode.tui.tool_helpers import _summarize_collapsed_tool_body
from minicode.tui.types import TranscriptEntry


def _bump_transcript_revision(state: ScreenState) -> None:
    state.transcript_revision += 1


def _push_transcript_entry(state: ScreenState, **kwargs: Any) -> int:
    entry_id = state.next_entry_id
    state.next_entry_id += 1
    state.transcript.append(TranscriptEntry(id=entry_id, **kwargs))
    _bump_transcript_revision(state)
    return entry_id


def _update_transcript_entry(state: ScreenState, entry_id: int, **kwargs: Any) -> bool:
    for entry in state.transcript:
        if entry.id == entry_id:
            changed = False
            for key, value in kwargs.items():
                if hasattr(entry, key) and getattr(entry, key) != value:
                    setattr(entry, key, value)
                    changed = True
            if changed:
                _bump_transcript_revision(state)
            return changed
    return False


def _append_to_transcript_entry(state: ScreenState, entry_id: int, extra_body: str) -> bool:
    for entry in state.transcript:
        if entry.id == entry_id:
            entry.body += extra_body
            _bump_transcript_revision(state)
            return True
    return False


def _mark_running_tools_as_error(state: ScreenState, message: str) -> None:
    changed = False
    for entry in state.transcript:
        if entry.kind == "tool" and entry.status == "running":
            entry.status = "error"
            entry.body = message
            entry.collapsed = False
            entry.collapsedSummary = None
            entry.collapsePhase = None
            state.recent_tools.append({"name": entry.toolName or "unknown", "status": "error"})
            changed = True
    if any(e.kind == "tool" and e.status == "error" for e in state.transcript):
        state.active_tool = None
    if changed:
        _bump_transcript_revision(state)


def _update_tool_entry(state: ScreenState, entry_id: int, status: str, body: str) -> None:
    for entry in state.transcript:
        if entry.id == entry_id and entry.kind == "tool":
            entry.status = status
            entry.body = body
            entry.collapsed = False
            entry.collapsedSummary = None
            entry.collapsePhase = None
            _bump_transcript_revision(state)
            return


def _set_tool_entry_collapse_phase(state: ScreenState, entry_id: int, phase: int) -> None:
    for entry in state.transcript:
        if entry.id == entry_id and entry.kind == "tool" and entry.status != "running":
            entry.collapsePhase = phase
            _bump_transcript_revision(state)
            return


def _collapse_tool_entry(state: ScreenState, entry_id: int, summary: str) -> None:
    for entry in state.transcript:
        if entry.id == entry_id and entry.kind == "tool" and entry.status != "running":
            entry.collapsePhase = None
            entry.collapsed = True
            entry.collapsedSummary = summary
            _bump_transcript_revision(state)
            return


def _get_running_tool_entries(state: ScreenState) -> list[TranscriptEntry]:
    return [e for e in state.transcript if e.kind == "tool" and e.status == "running"]


def _finalize_dangling_running_tools(state: ScreenState) -> None:
    running = _get_running_tool_entries(state)
    if running:
        error_message = (
            f"{running[0].body}\n\n"
            "ERROR: Tool did not report a final result before the turn ended. "
            "This usually means the command kept running in the background "
            "or the tool lifecycle got out of sync."
        )
        _mark_running_tools_as_error(state, error_message)
        state.status = f"Previous turn ended with {len(running)} unfinished tool call(s)."
        _bump_transcript_revision(state)


def _schedule_tool_auto_collapse(
    state: ScreenState,
    entry_id: int,
    output: str,
    rerender: Callable[[], None],
) -> None:
    summary = _summarize_collapsed_tool_body(output)

    def _do_collapse() -> None:
        time.sleep(0.25)
        _collapse_tool_entry(state, entry_id, summary)
        rerender()

    t = threading.Thread(target=_do_collapse, daemon=True)
    t.start()
