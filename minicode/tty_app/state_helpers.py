"""State management helpers for the MiniCode TTY application.

This module provides utility functions for managing transcript entries,
tool execution state, and screen state updates.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from minicode.tty_app.types import AggregatedEditProgress, ScreenState
from minicode.tui.types import TranscriptEntry


# ---------------------------------------------------------------------------
# Transcript entry helpers
# ---------------------------------------------------------------------------


def _get_session_stats(args: Any, state: ScreenState) -> dict[str, int]:
    """Get current session statistics.
    
    Returns a dict with transcript, message, skill, and MCP server counts.
    """
    return {
        "transcriptCount": len(state.transcript),
        "messageCount": len(args.messages),
        "skillCount": len(args.tools.get_skills()),
        "mcpCount": len(args.tools.get_mcp_servers()),
    }


def _push_transcript_entry(state: ScreenState, **kwargs: Any) -> int:
    """Create and append a new transcript entry.
    
    Returns the unique entry ID for later updates.
    """
    entry_id = state.next_entry_id
    state.next_entry_id += 1
    state.transcript.append(TranscriptEntry(id=entry_id, **kwargs))
    return entry_id


def _update_tool_entry(
    state: ScreenState,
    entry_id: int,
    status: str,
    body: str,
) -> None:
    """Update a tool entry's status and output body.
    
    Automatically un-collapses the entry so the new content is visible.
    """
    for entry in state.transcript:
        if entry.id == entry_id and entry.kind == "tool":
            entry.status = status
            entry.body = body
            entry.collapsed = False
            entry.collapsedSummary = None
            entry.collapsePhase = None
            return


def _set_tool_entry_collapse_phase(state: ScreenState, entry_id: int, phase: int) -> None:
    """Set the collapse animation phase for a tool entry."""
    for entry in state.transcript:
        if entry.id == entry_id and entry.kind == "tool" and entry.status != "running":
            entry.collapsePhase = phase
            return


def _collapse_tool_entry(state: ScreenState, entry_id: int, summary: str) -> None:
    """Collapse a tool entry to show only a summary line.
    
    Used for completed tools to reduce visual clutter in the transcript.
    """
    for entry in state.transcript:
        if entry.id == entry_id and entry.kind == "tool" and entry.status != "running":
            entry.collapsePhase = None
            entry.collapsed = True
            entry.collapsedSummary = summary
            return


def _get_running_tool_entries(state: ScreenState) -> list[TranscriptEntry]:
    """Get all transcript entries that are still in 'running' status."""
    return [e for e in state.transcript if e.kind == "tool" and e.status == "running"]


def _mark_running_tools_as_error(state: ScreenState, message: str) -> None:
    """Mark all currently running tools as failed with the given error message.
    
    This is used when a turn ends unexpectedly while tools are still running.
    """
    for entry in state.transcript:
        if entry.kind == "tool" and entry.status == "running":
            entry.status = "error"
            entry.body = message
            entry.collapsed = False
            entry.collapsedSummary = None
            entry.collapsePhase = None
            state.recent_tools.append({"name": entry.toolName or "unknown", "status": "error"})
    if any(e.kind == "tool" and e.status == "error" for e in state.transcript):
        state.active_tool = None


def _finalize_dangling_running_tools(state: ScreenState) -> None:
    """Mark all running tools as errors when a turn ends unexpectedly.
    
    This happens when the model stops responding but tools are still active,
    indicating a potential sync issue or background process.
    """
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


# ---------------------------------------------------------------------------
# Tool summarization
# ---------------------------------------------------------------------------


def _summarize_collapsed_tool_body(output: str) -> str:
    """Generate a one-line summary for a collapsed tool entry."""
    line = next(
        (l.strip() for l in output.split("\n") if l.strip()),
        "output collapsed",
    )
    return line[:140] + "..." if len(line) > 140 else line


def _truncate_for_display(text: str, max_len: int = 180) -> str:
    """Truncate text to max_len with ellipsis if needed."""
    return text[:max_len] + "..." if len(text) > max_len else text


def _summarize_tool_input(tool_name: str, tool_input: Any) -> str:
    """Generate a human-readable summary of tool input."""
    if isinstance(tool_input, str):
        return _truncate_for_display(" ".join(tool_input.split()).strip())

    if isinstance(tool_input, dict):
        path = str(tool_input.get("path", "")).strip()
        path_part = f" path={path}" if path else ""

        if tool_name == "patch_file":
            replacements = tool_input.get("replacements")
            count = len(replacements) if isinstance(replacements, list) else 0
            return f"patch_file{path_part} replacements={count}"
        if tool_name == "edit_file":
            return f"edit_file{path_part}"
        if tool_name == "read_file":
            extras: list[str] = []
            if tool_input.get("offset") is not None:
                extras.append(f"offset={tool_input['offset']}")
            if tool_input.get("limit") is not None:
                extras.append(f"limit={tool_input['limit']}")
            return f"read_file{path_part}{' ' + ' '.join(extras) if extras else ''}"
        if tool_name == "run_command":
            cmd = str(tool_input.get("command", "")).strip()
            return f"run_command{' ' + _truncate_for_display(cmd, 120) if cmd else ''}"
        if path:
            return f"{tool_name}{path_part}"

    try:
        return _truncate_for_display(str(tool_input))
    except Exception:
        return _truncate_for_display(repr(tool_input))


def _is_file_edit_tool(tool_name: str) -> bool:
    """Check if a tool modifies files."""
    return tool_name in ("edit_file", "patch_file", "modify_file", "write_file")


def _extract_path_from_tool_input(tool_input: Any) -> str | None:
    """Extract file path from tool input if present."""
    if not isinstance(tool_input, dict):
        return None
    value = tool_input.get("path")
    return value if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------------------
# Tool auto-collapse
# ---------------------------------------------------------------------------


def _schedule_tool_auto_collapse(
    state: ScreenState,
    entry_id: int,
    output: str,
    rerender: Callable[[], None],
) -> None:
    """Collapse tool output with a brief delay.
    
    Uses a single combined delay instead of multiple sleep+rerender cycles.
    """
    summary = _summarize_collapsed_tool_body(output)

    def _do_collapse() -> None:
        time.sleep(0.25)
        _collapse_tool_entry(state, entry_id, summary)
        rerender()

    import threading
    t = threading.Thread(target=_do_collapse, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Contextual help
# ---------------------------------------------------------------------------


def _get_contextual_help(state: ScreenState, args: Any) -> str | None:
    """Provide context-aware help tips based on current state."""
    if not state.is_busy and not state.pending_approval:
        tips = [
            "💡 Tip: Use /skills to see available workflows",
            "💡 Tip: Try '帮我分析这个项目' to get started",
            "💡 Tip: Use Tab to autocomplete commands",
            "💡 Tip: Type /help for all commands",
            "💡 Tip: Use Ctrl+R to search history",
        ]
        import random
        return random.choice(tips)
    
    if state.is_busy and state.active_tool:
        return f"⏳ Running {state.active_tool}... Press Ctrl+C to cancel"
    
    if state.pending_approval:
        return "🔒 Permission required. Use arrow keys and Enter to choose"
    
    return None
