from __future__ import annotations
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from minicode.cost_tracker import CostTracker
from minicode.history import load_history_entries, save_history_entries
from minicode.permissions import PermissionManager
from minicode.session import AutosaveManager, SessionData
from minicode.state import AppState, Store
from minicode.tooling import ToolRegistry
from minicode.tui.chrome import _cached_terminal_size, get_permission_prompt_max_scroll_offset
from minicode.tui.transcript import get_transcript_max_scroll_offset
from minicode.tui.types import TranscriptEntry
from minicode.types import ChatMessage, ModelAdapter

# Types
# ---------------------------------------------------------------------------


@dataclass
class TtyAppArgs:
    runtime: dict | None
    tools: ToolRegistry
    model: ModelAdapter
    messages: list[ChatMessage]
    cwd: str
    permissions: PermissionManager


@dataclass
class PendingApproval:
    request: dict[str, Any]
    resolve: Callable[[dict[str, Any]], None]
    details_expanded: bool = False
    details_scroll_offset: int = 0
    selected_choice_index: int = 0
    feedback_mode: bool = False
    feedback_input: str = ""


@dataclass
class AggregatedEditProgress:
    entry_id: int
    tool_name: str
    path: str
    total: int = 1
    completed: int = 0
    errors: int = 0
    last_output: str = ""


@dataclass
class ScreenState:
    input: str = ""
    cursor_offset: int = 0
    transcript: list[TranscriptEntry] = field(default_factory=list)
    transcript_scroll_offset: int = 0
    selected_slash_index: int = 0
    status: str | None = None
    active_tool: str | None = None
    recent_tools: list[dict[str, str]] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    history_index: int = 0
    history_draft: str = ""
    next_entry_id: int = 1
    pending_approval: PendingApproval | None = None
    is_busy: bool = False
    # Session persistence
    session: SessionData | None = None
    autosave: AutosaveManager | None = None
    # State management (Zustand-style)
    app_state: Store[AppState] | None = None
    # Cost tracking
    cost_tracker: CostTracker | None = None
    # Background agent thread
    agent_thread: Any = None
    agent_result: dict | None = None
    agent_lock: Any = None
    # Tool execution时间跟踪
    tool_start_time: float | None = None


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _get_session_stats(args: TtyAppArgs, state: ScreenState) -> dict[str, int]:
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


def _summarize_collapsed_tool_body(output: str) -> str:
    line = next(
        (l.strip() for l in output.split("\n") if l.strip()),
        "output collapsed",
    )
    return line[:140] + "..." if len(line) > 140 else line


def _schedule_tool_auto_collapse(
    state: ScreenState,
    entry_id: int,
    output: str,
    rerender: Callable[[], None],
) -> None:
    """Collapse tool output with a brief animation. Optimized to use a single
    combined delay instead of 3 separate sleep+rerender cycles."""
    summary = _summarize_collapsed_tool_body(output)

    def _do_collapse() -> None:
        # Single delay then jump straight to collapsed state
        # (avoids 3 separate rerender() calls for an animation most users barely see)
        time.sleep(0.25)
        _collapse_tool_entry(state, entry_id, summary)
        rerender()

    t = threading.Thread(target=_do_collapse, daemon=True)
    t.start()


def _get_contextual_help(state: ScreenState, args: TtyAppArgs) -> str | None:
    """根据当前状态提供上下文相关的帮助提示"""
    # 空闲状态 - 显示快速提示
    if not state.is_busy and not state.pending_approval:
        tips = [
            "💡 Tip: Use /skills to see available workflows",
            "💡 Tip: Try '帮我分析这个项目' to get started",
            "💡 Tip: Use Tab to autocomplete commands",
            "💡 Tip: Type /help for all commands",
            "💡 Tip: Use Ctrl+R to search history",
        ]
        return random.choice(tips)
    
    # 工具运行中 - 显示相关提示
    if state.is_busy and state.active_tool:
        return f"⏳ Running {state.active_tool}... Press Ctrl+C to cancel"
    
    # 权限审批中
    if state.pending_approval:
        return "🔒 Permission required. Use arrow keys and Enter to choose"
    
    return None


# ---------------------------------------------------------------------------
# Tool summarization
# ---------------------------------------------------------------------------


def _truncate_for_display(text: str, max_len: int = 180) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def _summarize_tool_input(tool_name: str, tool_input: Any) -> str:
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
    return tool_name in ("edit_file", "patch_file", "modify_file", "write_file")


def _extract_path_from_tool_input(tool_input: Any) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    value = tool_input.get("path")
    return value if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------------------
# Scroll / history / slash
# ---------------------------------------------------------------------------


_HEADER_LINES_ESTIMATE = 11  # banner panel: top border + title + divider + 6 body lines + bottom border
_PROMPT_LINES_ESTIMATE = 7   # prompt panel: top border + title + divider + 3 body + bottom border
_FOOTER_LINES = 1
_GAPS = 3
_TRANSCRIPT_FRAME_LINES = 4  # top/bottom border + title + empty

def _get_transcript_body_lines(args: TtyAppArgs, state: ScreenState) -> int:
    _, rows = _get_terminal_size()
    rows = max(24, rows)
    # Use cached estimates instead of re-rendering header/prompt just to count lines
    chrome_overhead = (
        _HEADER_LINES_ESTIMATE
        + _PROMPT_LINES_ESTIMATE
        + _FOOTER_LINES
        + _GAPS
        + _TRANSCRIPT_FRAME_LINES
    )
    return max(6, rows - chrome_overhead)


def _get_max_transcript_scroll_offset(args: TtyAppArgs, state: ScreenState) -> int:
    return get_transcript_max_scroll_offset(
        state.transcript, _get_transcript_body_lines(args, state)
    )


def _scroll_transcript_by(args: TtyAppArgs, state: ScreenState, delta: int) -> bool:
    max_offset = _get_max_transcript_scroll_offset(args, state)
    next_offset = max(0, min(max_offset, state.transcript_scroll_offset + delta))
    if next_offset == state.transcript_scroll_offset:
        return False
    state.transcript_scroll_offset = next_offset
    return True


def _jump_transcript_to_edge(args: TtyAppArgs, state: ScreenState, target: str) -> bool:
    next_offset = _get_max_transcript_scroll_offset(args, state) if target == "top" else 0
    if next_offset == state.transcript_scroll_offset:
        return False
    state.transcript_scroll_offset = next_offset
    return True


def _scroll_pending_approval_by(state: ScreenState, delta: int) -> bool:
    pending = state.pending_approval
    if not pending or not pending.details_expanded:
        return False
    max_offset = get_permission_prompt_max_scroll_offset(pending.request, expanded=True)
    next_offset = max(0, min(max_offset, pending.details_scroll_offset + delta))
    if next_offset == pending.details_scroll_offset:
        return False
    pending.details_scroll_offset = next_offset
    return True


def _toggle_pending_approval_expand(state: ScreenState) -> bool:
    pending = state.pending_approval
    if not pending or pending.request.get("kind") != "edit":
        return False
    pending.details_expanded = not pending.details_expanded
    pending.details_scroll_offset = 0
    return True


def _move_pending_approval_selection(state: ScreenState, delta: int) -> bool:
    pending = state.pending_approval
    if not pending or pending.feedback_mode:
        return False
    total = len(pending.request.get("choices", []))
    if total <= 0:
        return False
    pending.selected_choice_index = (pending.selected_choice_index + delta + total) % total
    return True


def _history_up(state: ScreenState) -> bool:
    if not state.history or state.history_index <= 0:
        return False
    if state.history_index == len(state.history):
        state.history_draft = state.input
    state.history_index -= 1
    state.input = state.history[state.history_index] if state.history_index < len(state.history) else ""
    state.cursor_offset = len(state.input)
    return True


def _history_down(state: ScreenState) -> bool:
    if state.history_index >= len(state.history):
        return False
    state.history_index += 1
    state.input = (
        state.history_draft
        if state.history_index == len(state.history)
        else (state.history[state.history_index] if state.history_index < len(state.history) else "")
    )
    state.cursor_offset = len(state.input)
    return True


def _get_visible_commands(input_text: str) -> list[Any]:
    if not input_text.startswith("/"):
        return []
    if input_text == "/":
        return SLASH_COMMANDS
    matches = find_matching_slash_commands(input_text)
    return [cmd for cmd in SLASH_COMMANDS if getattr(cmd, "usage", str(cmd)) in matches]


# ---------------------------------------------------------------------------
