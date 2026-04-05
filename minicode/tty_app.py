from __future__ import annotations

import os
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from minicode.agent_loop import run_agent_turn
from minicode.background_tasks import list_background_tasks
from minicode.cli_commands import (
    SLASH_COMMANDS,
    find_matching_slash_commands,
    try_handle_local_command,
)
from minicode.cost_tracker import CostTracker
from minicode.history import load_history_entries, save_history_entries
from minicode.local_tool_shortcuts import parse_local_tool_shortcut
from minicode.permissions import PermissionManager
from minicode.prompt import build_system_prompt
from minicode.session import (
    AutosaveManager,
    SessionData,
    create_new_session,
    format_session_list,
    format_session_resume,
    get_latest_session,
    list_sessions,
    load_session,
    save_session,
)
from minicode.state import AppState, Store, create_app_store, format_app_state_summary
from minicode.tooling import ToolContext, ToolRegistry
from minicode.tui.chrome import (
    get_permission_prompt_max_scroll_offset,
    render_banner,
    render_footer_bar,
    render_panel,
    render_permission_prompt,
    render_slash_menu,
    render_status_line,
    render_tool_panel,
)
from minicode.tui.input import render_input_prompt
from minicode.tui.input_parser import (
    KeyEvent,
    ParsedInputEvent,
    TextEvent,
    WheelEvent,
    parse_input_chunk,
)
from minicode.tui.screen import (
    clear_screen,
    enter_alternate_screen,
    exit_alternate_screen,
    hide_cursor,
    show_cursor,
)
from minicode.tui.transcript import (
    get_transcript_max_scroll_offset,
    get_transcript_window_size,
    render_transcript,
)
from minicode.tui.types import TranscriptEntry
from minicode.types import ChatMessage, ModelAdapter
from minicode.workspace import resolve_tool_path

# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _get_session_stats(args: TtyAppArgs, state: ScreenState) -> dict[str, int]:
    return {
        "transcriptCount": len(state.transcript),
        "messageCount": len(args.messages),
        "skillCount": len(args.tools.get_skills()),
        "mcpCount": len(args.tools.get_mcp_servers()),
    }


def _push_transcript_entry(state: ScreenState, **kwargs: Any) -> int:
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
    for entry in state.transcript:
        if entry.id == entry_id and entry.kind == "tool":
            entry.status = status
            entry.body = body
            entry.collapsed = False
            entry.collapsedSummary = None
            entry.collapsePhase = None
            return


def _set_tool_entry_collapse_phase(state: ScreenState, entry_id: int, phase: int) -> None:
    for entry in state.transcript:
        if entry.id == entry_id and entry.kind == "tool" and entry.status != "running":
            entry.collapsePhase = phase
            return


def _collapse_tool_entry(state: ScreenState, entry_id: int, summary: str) -> None:
    for entry in state.transcript:
        if entry.id == entry_id and entry.kind == "tool" and entry.status != "running":
            entry.collapsePhase = None
            entry.collapsed = True
            entry.collapsedSummary = summary
            return


def _get_running_tool_entries(state: ScreenState) -> list[TranscriptEntry]:
    return [e for e in state.transcript if e.kind == "tool" and e.status == "running"]


def _finalize_dangling_running_tools(state: ScreenState) -> None:
    running = _get_running_tool_entries(state)
    for entry in running:
        entry.status = "error"
        entry.body = (
            f"{entry.body}\n\n"
            "ERROR: Tool did not report a final result before the turn ended. "
            "This usually means the command kept running in the background "
            "or the tool lifecycle got out of sync."
        )
        entry.collapsed = False
        entry.collapsedSummary = None
        entry.collapsePhase = None
        state.recent_tools.append({"name": entry.toolName or "unknown", "status": "error"})
    if running:
        state.active_tool = None
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
    summary = _summarize_collapsed_tool_body(output)

    def _do_phases() -> None:
        time.sleep(0.11)
        _set_tool_entry_collapse_phase(state, entry_id, 1)
        rerender()
        time.sleep(0.11)
        _set_tool_entry_collapse_phase(state, entry_id, 2)
        rerender()
        time.sleep(0.10)
        _collapse_tool_entry(state, entry_id, summary)
        rerender()

    t = threading.Thread(target=_do_phases, daemon=True)
    t.start()


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


def _get_transcript_body_lines(args: TtyAppArgs, state: ScreenState) -> int:
    try:
        rows = max(24, os.get_terminal_size().lines)
    except (AttributeError, ValueError, OSError):
        rows = 40
    header_lines = _render_header_panel(args, state).count("\n") + 1
    prompt_lines = _render_prompt_panel(state).count("\n") + 1
    footer_lines = 1
    gaps_between_sections = 3
    transcript_frame_lines = 4
    remaining = rows - header_lines - prompt_lines - footer_lines - gaps_between_sections - transcript_frame_lines
    return max(6, remaining)


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
# Rendering
# ---------------------------------------------------------------------------


def _render_header_panel(args: TtyAppArgs, state: ScreenState) -> str:
    return render_banner(
        args.runtime,
        args.cwd,
        args.permissions.get_summary(),
        _get_session_stats(args, state),
    )


def _render_prompt_panel(state: ScreenState) -> str:
    commands = _get_visible_commands(state.input)
    prompt_body = render_input_prompt(state.input, state.cursor_offset)
    if commands:
        prompt_body += "\n" + render_slash_menu(
            commands,
            min(state.selected_slash_index, len(commands) - 1),
        )
    return render_panel("prompt", prompt_body)


def _render_screen(args: TtyAppArgs, state: ScreenState) -> None:
    background_tasks = list_background_tasks()
    clear_screen()

    # Header
    sys.stdout.write(_render_header_panel(args, state) + "\n\n")

    if state.pending_approval:
        # Permission approval overlay
        sys.stdout.write(
            render_permission_prompt(
                state.pending_approval.request,
                expanded=state.pending_approval.details_expanded,
                scroll_offset=state.pending_approval.details_scroll_offset,
                selected_choice_index=state.pending_approval.selected_choice_index,
                feedback_mode=state.pending_approval.feedback_mode,
                feedback_input=state.pending_approval.feedback_input,
            )
            + "\n\n"
        )
        sys.stdout.write(
            render_panel(
                "activity",
                render_tool_panel(state.active_tool, state.recent_tools, background_tasks),
            )
            + "\n\n"
        )
        sys.stdout.write(
            render_footer_bar(
                state.status,
                True,
                len(args.tools.get_skills()) > 0,
                background_tasks,
            )
        )
        sys.stdout.flush()
        return

    # Transcript
    body_lines = _get_transcript_body_lines(args, state)
    if state.transcript:
        transcript_body = render_transcript(
            state.transcript, state.transcript_scroll_offset, body_lines
        )
    else:
        transcript_body = f"{render_status_line(None)}\n\nType /help for commands."
    sys.stdout.write(
        render_panel(
            "session feed",
            transcript_body,
            right_title=f"{len(state.transcript)} events",
            min_body_lines=body_lines,
        )
        + "\n\n"
    )

    # Prompt
    sys.stdout.write(_render_prompt_panel(state) + "\n\n")

    # Footer
    sys.stdout.write(
        render_footer_bar(
            state.status,
            True,
            len(args.tools.get_skills()) > 0,
            background_tasks,
        )
    )
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Cross-platform raw mode stdin
# ---------------------------------------------------------------------------


def _read_raw_char() -> str:
    """Read a single character from stdin in raw mode, cross-platform."""
    if sys.platform == "win32":
        import msvcrt

        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            return ch
        return ""
    else:
        import select

        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if ready:
            return sys.stdin.read(1)
        return ""


def _read_raw_chunk() -> str:
    """Read all available raw chars as a single chunk."""
    if sys.platform == "win32":
        import msvcrt

        result = ""
        while msvcrt.kbhit():
            result += msvcrt.getwch()
        return result
    else:
        import select

        result = ""
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if not ready:
                break
            ch = sys.stdin.read(1)
            if not ch:
                break
            result += ch
        return result


class _RawModeContext:
    """Context manager for raw terminal mode (Unix only; Windows uses msvcrt natively)."""

    def __init__(self) -> None:
        self._old_settings: Any = None

    def __enter__(self) -> _RawModeContext:
        if sys.platform != "win32":
            import termios
            import tty

            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())
        return self

    def __exit__(self, *_: Any) -> None:
        if sys.platform != "win32" and self._old_settings is not None:
            import termios

            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)


# ---------------------------------------------------------------------------
# Tool shortcut execution
# ---------------------------------------------------------------------------


def _execute_tool_shortcut(
    args: TtyAppArgs,
    state: ScreenState,
    tool_name: str,
    tool_input: Any,
    rerender: Callable[[], None],
) -> None:
    state.is_busy = True
    state.status = f"Running {tool_name}..."
    state.active_tool = tool_name
    entry_id = _push_transcript_entry(
        state,
        kind="tool",
        toolName=tool_name,
        status="running",
        body=_summarize_tool_input(tool_name, tool_input),
    )
    rerender()

    try:
        result = args.tools.execute(
            tool_name,
            tool_input,
            context=ToolContext(cwd=args.cwd, permissions=args.permissions),
        )
        state.recent_tools.append({
            "name": tool_name,
            "status": "success" if result.ok else "error",
        })
        output = result.output if result.ok else f"ERROR: {result.output}"
        _update_tool_entry(state, entry_id, "success" if result.ok else "error", output)
        _collapse_tool_entry(state, entry_id, _summarize_collapsed_tool_body(output))
        state.transcript_scroll_offset = 0
    finally:
        state.is_busy = False
        state.active_tool = None
        _finalize_dangling_running_tools(state)
        if not _get_running_tool_entries(state):
            state.status = None


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


def _handle_input(
    args: TtyAppArgs,
    state: ScreenState,
    rerender: Callable[[], None],
    submitted_raw_input: str | None = None,
) -> bool:
    """Returns True if /exit was typed."""
    if state.is_busy:
        state.status = (
            f"Running {state.active_tool}..."
            if state.active_tool
            else "Current turn is still running..."
        )
        return False

    input_text = (submitted_raw_input if submitted_raw_input is not None else state.input).strip()
    if not input_text:
        return False
    if input_text == "/exit":
        return True

    # History
    if not state.history or state.history[-1] != input_text:
        state.history.append(input_text)
        save_history_entries(state.history)
    state.history_index = len(state.history)
    state.history_draft = ""

    # Autosave trigger
    if state.autosave:
        state.autosave.mark_dirty()

    # /tools
    if input_text == "/tools":
        _push_transcript_entry(
            state,
            kind="assistant",
            body="\n".join(
                f"{t.name}: {t.description}" for t in args.tools.list()
            ),
        )
        return False

    # Local commands
    local_result = try_handle_local_command(input_text, tools=args.tools)
    if local_result is not None:
        _push_transcript_entry(state, kind="assistant", body=local_result)
        return False

    # Tool shortcuts
    shortcut = parse_local_tool_shortcut(input_text)
    if shortcut:
        _execute_tool_shortcut(
            args, state, shortcut["toolName"], shortcut["input"], rerender
        )
        return False

    # Unknown slash commands
    if input_text.startswith("/"):
        matches = find_matching_slash_commands(input_text)
        _push_transcript_entry(
            state,
            kind="assistant",
            body=(
                f"Unknown command. Did you mean:\n{chr(10).join(matches)}"
                if matches
                else "Unknown command. Type /help to see available commands."
            ),
        )
        return False

    # Agent turn
    _push_transcript_entry(state, kind="user", body=input_text)
    state.transcript_scroll_offset = 0
    state.status = "Thinking..."
    state.is_busy = True
    
    # Update app state
    if state.app_state:
        from minicode.state import set_busy
        state.app_state.set_state(set_busy())
    
    rerender()

    pending_tool_entries: dict[str, list[int]] = defaultdict(list)
    aggregated_edit_by_key: dict[str, AggregatedEditProgress] = {}
    aggregated_edit_by_entry_id: dict[int, AggregatedEditProgress] = {}

    # Refresh system prompt
    args.messages[0] = {
        "role": "system",
        "content": build_system_prompt(
            args.cwd,
            args.permissions.get_summary(),
            {
                "skills": args.tools.get_skills(),
                "mcpServers": args.tools.get_mcp_servers(),
            },
        ),
    }
    args.messages.append({"role": "user", "content": input_text})

    def on_assistant_message(content: str) -> None:
        _push_transcript_entry(state, kind="assistant", body=content)
        state.transcript_scroll_offset = 0
        rerender()

    def on_progress_message(content: str) -> None:
        _push_transcript_entry(state, kind="progress", body=content)
        state.transcript_scroll_offset = 0
        rerender()

    def on_tool_start(tool_name: str, tool_input: Any) -> None:
        state.status = f"Running {tool_name}..."
        state.active_tool = tool_name

        target_path = _extract_path_from_tool_input(tool_input)
        can_aggregate = _is_file_edit_tool(tool_name) and target_path is not None

        if can_aggregate:
            key = f"{tool_name}:{target_path}"
            existing = aggregated_edit_by_key.get(key)
            if existing:
                existing.total += 1
                existing.last_output = _summarize_tool_input(tool_name, tool_input)
                entry_id = existing.entry_id
                _update_tool_entry(
                    state,
                    entry_id,
                    "error" if existing.errors > 0 else "running",
                    f"Aggregated {tool_name} for {target_path}\nCompleted: {existing.completed}/{existing.total}",
                )
            else:
                entry_id = _push_transcript_entry(
                    state,
                    kind="tool",
                    toolName=tool_name,
                    status="running",
                    body=_summarize_tool_input(tool_name, tool_input),
                )
                progress = AggregatedEditProgress(
                    entry_id=entry_id,
                    tool_name=tool_name,
                    path=target_path,
                    total=1,
                    completed=0,
                    errors=0,
                    last_output=_summarize_tool_input(tool_name, tool_input),
                )
                aggregated_edit_by_key[key] = progress
                aggregated_edit_by_entry_id[entry_id] = progress
        else:
            entry_id = _push_transcript_entry(
                state,
                kind="tool",
                toolName=tool_name,
                status="running",
                body=_summarize_tool_input(tool_name, tool_input),
            )

        pending_tool_entries[tool_name].append(entry_id)
        state.transcript_scroll_offset = 0
        rerender()

    def on_tool_result(tool_name: str, output: str, is_error: bool) -> None:
        pending = pending_tool_entries.get(tool_name, [])
        entry_id = pending.pop(0) if pending else None
        if entry_id is not None:
            aggregated = aggregated_edit_by_entry_id.get(entry_id)
            if aggregated and aggregated.tool_name == tool_name:
                aggregated.completed += 1
                if is_error:
                    aggregated.errors += 1
                aggregated.last_output = output
                done = aggregated.completed >= aggregated.total
                if done:
                    state.recent_tools.append({
                        "name": f"{tool_name} x{aggregated.total}",
                        "status": "error" if aggregated.errors > 0 else "success",
                    })
                body = (
                    "\n".join([
                        f"Aggregated {tool_name} for {aggregated.path}",
                        f"Operations: {aggregated.total}, errors: {aggregated.errors}",
                        f"Last result: {aggregated.last_output}",
                    ])
                    if done
                    else f"Aggregated {tool_name} for {aggregated.path}\nCompleted: {aggregated.completed}/{aggregated.total}"
                )
                _update_tool_entry(
                    state,
                    entry_id,
                    "error" if aggregated.errors > 0 else ("success" if done else "running"),
                    body,
                )
                if done:
                    _collapse_tool_entry(state, entry_id, _summarize_collapsed_tool_body(body))
                    aggregated_edit_by_entry_id.pop(entry_id, None)
                    aggregated_edit_by_key.pop(f"{tool_name}:{aggregated.path}", None)
            else:
                state.recent_tools.append({
                    "name": tool_name,
                    "status": "error" if is_error else "success",
                })
                _update_tool_entry(
                    state,
                    entry_id,
                    "error" if is_error else "success",
                    f"ERROR: {output}" if is_error else output,
                )
                _schedule_tool_auto_collapse(
                    state,
                    entry_id,
                    f"ERROR: {output}" if is_error else output,
                    rerender,
                )

        state.active_tool = None
        remaining = sum(len(v) for v in pending_tool_entries.values())
        if remaining > 0:
            state.status = f"{remaining} tool(s) still running..."
        else:
            state.status = None
        state.transcript_scroll_offset = 0
        rerender()

    args.permissions.begin_turn()
    try:
        next_messages = run_agent_turn(
            model=args.model,
            tools=args.tools,
            messages=args.messages,
            cwd=args.cwd,
            permissions=args.permissions,
            on_tool_start=on_tool_start,
            on_tool_result=on_tool_result,
            on_assistant_message=on_assistant_message,
            on_progress_message=on_progress_message,
        )
        args.messages = next_messages
    finally:
        args.permissions.end_turn()
        state.is_busy = False
        state.active_tool = None
        _finalize_dangling_running_tools(state)
        if not _get_running_tool_entries(state):
            state.status = None

    return False


# ---------------------------------------------------------------------------
# Main event-driven TTY app
# ---------------------------------------------------------------------------


def run_tty_app(
    *,
    runtime: dict | None,
    tools: ToolRegistry,
    model: ModelAdapter,
    messages: list[ChatMessage],
    cwd: str,
    permissions: PermissionManager,
    resume_session: str | None = None,
    list_sessions_only: bool = False,
) -> list[ChatMessage]:
    """Event-driven full-screen TTY application, ported from the TypeScript version.
    
    Args:
        resume_session: Session ID to resume, or "latest" for most recent
        list_sessions_only: If True, print session list and exit
    """

    args = TtyAppArgs(
        runtime=runtime,
        tools=tools,
        model=model,
        messages=messages,
        cwd=cwd,
        permissions=permissions,
    )

    # Session initialization
    session: SessionData | None = None
    
    if list_sessions_only:
        sessions = list_sessions()
        print(format_session_list(sessions))
        return messages
    
    if resume_session:
        if resume_session == "latest":
            session = get_latest_session(workspace=str(Path(cwd).resolve()))
            if session:
                print(format_session_resume(session))
            else:
                print("No previous session found for this workspace.")
                session = create_new_session(workspace=str(Path(cwd).resolve()))
        else:
            session = load_session(resume_session)
            if not session:
                print(f"Session '{resume_session}' not found.")
                return messages
            print(format_session_resume(session))
    else:
        # Check for existing session in current workspace
        session = get_latest_session(workspace=str(Path(cwd).resolve()))
        if session:
            print(f"Previous session found: {session.session_id[:8]}")
            print("Use --resume to continue, or starting fresh session.")
            session = None
    
    if not session:
        session = create_new_session(workspace=str(Path(cwd).resolve()))
    
    # Initialize AppState store (Zustand-style)
    app_state_store = create_app_store({
        "session_id": session.session_id,
        "workspace": cwd,
        "model": runtime.get("model", "unknown") if runtime else "unknown",
    })
    
    # Initialize CostTracker
    cost_tracker = CostTracker()

    state = ScreenState(
        history=load_history_entries(),
        session=session,
        autosave=AutosaveManager(session),
        app_state=app_state_store,
        cost_tracker=cost_tracker,
    )
    state.history_index = len(state.history)

    # Restore session state if resuming
    if session.messages:
        # Restore messages
        args.messages.clear()
        args.messages.extend(session.messages)
        
        # Restore transcript entries
        for entry_data in session.transcript_entries:
            entry = TranscriptEntry(**entry_data)
            state.transcript.append(entry)
        
        print(f"Restored {len(session.messages)} messages, {len(state.transcript)} transcript entries.")

    # Wire up permission prompt handler
    approval_event = threading.Event()
    approval_result: dict[str, Any] = {}

    def _permission_prompt_handler(request: dict[str, Any]) -> dict[str, Any]:
        nonlocal approval_result
        state.pending_approval = PendingApproval(
            request=request,
            resolve=lambda r: None,
        )
        _render_screen(args, state)
        approval_event.clear()
        approval_event.wait()
        result = approval_result.copy()
        state.pending_approval = None
        return result

    permissions.prompt = _permission_prompt_handler

    def rerender() -> None:
        _render_screen(args, state)

    input_remainder = ""
    should_exit = False

    enter_alternate_screen()
    hide_cursor()
    try:
        _render_screen(args, state)

        with _RawModeContext():
            while not should_exit:
                # Autosave check
                if state.autosave:
                    state.autosave.save_if_needed()
                
                # Read raw input
                if sys.platform == "win32":
                    import msvcrt

                    if not msvcrt.kbhit():
                        time.sleep(0.02)
                        continue
                    chunk = ""
                    while msvcrt.kbhit():
                        chunk += msvcrt.getwch()
                else:
                    import select

                    ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if not ready:
                        continue
                    chunk = ""
                    while True:
                        ready2, _, _ = select.select([sys.stdin], [], [], 0)
                        if not ready2:
                            break
                        ch = sys.stdin.read(1)
                        if not ch:
                            should_exit = True
                            break
                        chunk += ch

                if not chunk:
                    continue

                parsed = parse_input_chunk(input_remainder + chunk)
                input_remainder = parsed.rest

                for event in parsed.events:
                    try:
                        _handle_event(args, state, event, rerender, approval_event, approval_result)
                        if state.input == "/exit" or (
                            isinstance(event, KeyEvent)
                            and event.name == "c"
                            and event.ctrl
                        ):
                            # Check for Ctrl+C
                            pass
                    except SystemExit:
                        should_exit = True
                        break
                    except Exception as exc:
                        _push_transcript_entry(
                            state,
                            kind="assistant",
                            body=str(exc),
                        )
                        state.input = ""
                        state.cursor_offset = 0
                        state.selected_slash_index = 0
                        state.status = None
                        _render_screen(args, state)

    finally:
        show_cursor()
        exit_alternate_screen()
        
        # Final session save
        if state.session:
            # Update session with current state
            state.session.messages = list(args.messages)
            state.session.transcript_entries = [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "toolName": e.toolName,
                    "status": e.status,
                    "body": e.body,
                    "collapsed": e.collapsed,
                    "collapsedSummary": e.collapsedSummary,
                    "collapsePhase": e.collapsePhase,
                }
                for e in state.transcript
            ]
            state.session.history = state.history
            state.session.permissions_summary = args.permissions.get_summary()
            state.session.skills = args.tools.get_skills()
            state.session.mcp_servers = args.tools.get_mcp_servers()
            
            # Force save
            if state.autosave:
                state.autosave.force_save()
            else:
                save_session(state.session)
            
            print(f"\nSession saved: {state.session.session_id[:8]}")

    return args.messages


def _handle_event(
    args: TtyAppArgs,
    state: ScreenState,
    event: ParsedInputEvent,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
) -> None:
    """Process a single parsed input event."""

    # ---------- Ctrl+C → exit ----------
    if isinstance(event, TextEvent) and event.ctrl and event.text == "c":
        raise SystemExit(0)

    # ---------- Pending approval mode ----------
    if state.pending_approval:
        pending = state.pending_approval

        if pending.feedback_mode:
            _handle_feedback_mode_event(state, event, rerender, approval_event, approval_result)
            return

        # Permission approval key handling
        if isinstance(event, KeyEvent):
            if event.name == "escape":
                approval_result.clear()
                approval_result["decision"] = "deny_once"
                approval_event.set()
                rerender()
                return
            if event.name == "return":
                choices = pending.request.get("choices", [])
                if choices and 0 <= pending.selected_choice_index < len(choices):
                    choice = choices[pending.selected_choice_index]
                    decision = choice.get("decision", "allow_once")
                    if decision == "deny_with_feedback":
                        pending.feedback_mode = True
                        pending.feedback_input = ""
                        rerender()
                        return
                    approval_result.clear()
                    approval_result["decision"] = decision
                    approval_event.set()
                else:
                    approval_result.clear()
                    approval_result["decision"] = "allow_once"
                    approval_event.set()
                rerender()
                return
            if event.name == "up":
                if _move_pending_approval_selection(state, -1):
                    rerender()
                return
            if event.name == "down":
                if _move_pending_approval_selection(state, 1):
                    rerender()
                return
            if event.name == "pageup":
                if _scroll_pending_approval_by(state, -5):
                    rerender()
                return
            if event.name == "pagedown":
                if _scroll_pending_approval_by(state, 5):
                    rerender()
                return

        if isinstance(event, TextEvent) and not event.ctrl:
            ch = event.text
            # 'v' to toggle expand
            if ch == "v":
                if _toggle_pending_approval_expand(state):
                    rerender()
                return
            # Digit keys to select choices
            choices = pending.request.get("choices", [])
            for i, choice in enumerate(choices):
                if ch == choice.get("key"):
                    decision = choice.get("decision", "allow_once")
                    if decision == "deny_with_feedback":
                        pending.feedback_mode = True
                        pending.feedback_input = ""
                        rerender()
                        return
                    approval_result.clear()
                    approval_result["decision"] = decision
                    approval_event.set()
                    rerender()
                    return

        if isinstance(event, WheelEvent):
            delta = 3 if event.direction == "up" else -3
            if _scroll_pending_approval_by(state, delta):
                rerender()
        return

    # ---------- Normal mode ----------

    visible_commands = _get_visible_commands(state.input)

    # Return → submit input or select slash command
    if isinstance(event, KeyEvent) and event.name == "return":
        if visible_commands and 0 <= state.selected_slash_index < len(visible_commands):
            selected = visible_commands[state.selected_slash_index]
            usage = getattr(selected, "usage", str(selected))
            state.input = usage
            state.cursor_offset = len(state.input)
            state.selected_slash_index = 0
            rerender()
            return

        submitted = state.input
        state.input = ""
        state.cursor_offset = 0
        state.selected_slash_index = 0
        rerender()
        if _handle_input(args, state, rerender, submitted):
            raise SystemExit(0)
        rerender()
        return

    # Tab → autocomplete slash command
    if isinstance(event, KeyEvent) and event.name == "tab":
        if visible_commands:
            selected = visible_commands[min(state.selected_slash_index, len(visible_commands) - 1)]
            usage = getattr(selected, "usage", str(selected))
            state.input = usage + " "
            state.cursor_offset = len(state.input)
            state.selected_slash_index = 0
            rerender()
        return

    # Backspace
    if isinstance(event, KeyEvent) and event.name == "backspace":
        if state.cursor_offset > 0:
            state.input = state.input[: state.cursor_offset - 1] + state.input[state.cursor_offset :]
            state.cursor_offset -= 1
            state.selected_slash_index = 0
            rerender()
        return

    # Delete
    if isinstance(event, KeyEvent) and event.name == "delete":
        if state.cursor_offset < len(state.input):
            state.input = state.input[: state.cursor_offset] + state.input[state.cursor_offset + 1 :]
            state.selected_slash_index = 0
            rerender()
        return

    # Home
    if isinstance(event, KeyEvent) and event.name == "home":
        state.cursor_offset = 0
        rerender()
        return

    # End
    if isinstance(event, KeyEvent) and event.name == "end":
        state.cursor_offset = len(state.input)
        rerender()
        return

    # Mouse wheel → scroll transcript
    if isinstance(event, WheelEvent):
        delta = 3 if event.direction == "up" else -3
        if _scroll_transcript_by(args, state, delta):
            rerender()
        return

    # Ctrl-P → history up
    if isinstance(event, TextEvent) and event.ctrl and event.text == "p":
        if _history_up(state):
            rerender()
        return

    # Ctrl-N → history down
    if isinstance(event, TextEvent) and event.ctrl and event.text == "n":
        if _history_down(state):
            rerender()
        return

    # Up arrow
    if isinstance(event, KeyEvent) and event.name == "up":
        if visible_commands:
            state.selected_slash_index = (state.selected_slash_index - 1 + len(visible_commands)) % len(visible_commands)
            rerender()
        elif event.meta:
            if _scroll_transcript_by(args, state, 1):
                rerender()
        elif _history_up(state):
            rerender()
        return

    # Down arrow
    if isinstance(event, KeyEvent) and event.name == "down":
        if visible_commands:
            state.selected_slash_index = (state.selected_slash_index + 1) % len(visible_commands)
            rerender()
        elif event.meta:
            if _scroll_transcript_by(args, state, -1):
                rerender()
        elif _history_down(state):
            rerender()
        return

    # PageUp → scroll transcript
    if isinstance(event, KeyEvent) and event.name == "pageup":
        if _scroll_transcript_by(args, state, 8):
            rerender()
        return

    # PageDown → scroll transcript
    if isinstance(event, KeyEvent) and event.name == "pagedown":
        if _scroll_transcript_by(args, state, -8):
            rerender()
        return

    # Left arrow
    if isinstance(event, KeyEvent) and event.name == "left":
        state.cursor_offset = max(0, state.cursor_offset - 1)
        rerender()
        return

    # Right arrow
    if isinstance(event, KeyEvent) and event.name == "right":
        state.cursor_offset = min(len(state.input), state.cursor_offset + 1)
        rerender()
        return

    # Ctrl-U → clear line
    if isinstance(event, TextEvent) and event.ctrl and event.text == "u":
        state.input = ""
        state.cursor_offset = 0
        state.selected_slash_index = 0
        rerender()
        return

    # Ctrl-A → home / jump to top
    if isinstance(event, TextEvent) and event.ctrl and event.text == "a":
        if not state.input:
            if _jump_transcript_to_edge(args, state, "top"):
                rerender()
            return
        state.cursor_offset = 0
        rerender()
        return

    # Ctrl-E → end / jump to bottom
    if isinstance(event, TextEvent) and event.ctrl and event.text == "e":
        if not state.input:
            if _jump_transcript_to_edge(args, state, "bottom"):
                rerender()
            return
        state.cursor_offset = len(state.input)
        rerender()
        return

    # Escape → clear input
    if isinstance(event, KeyEvent) and event.name == "escape":
        state.input = ""
        state.cursor_offset = 0
        state.selected_slash_index = 0
        rerender()
        return

    # Regular text input
    if isinstance(event, TextEvent) and not event.ctrl:
        state.input = state.input[: state.cursor_offset] + event.text + state.input[state.cursor_offset :]
        state.cursor_offset += len(event.text)
        state.selected_slash_index = 0
        state.history_index = len(state.history)
        rerender()
        return


# ---------------------------------------------------------------------------
# Public API / backward-compatible exports for tests
# ---------------------------------------------------------------------------


def summarize_tool_input(tool_name: str, tool_input: Any) -> str:
    """Public wrapper around _summarize_tool_input for external callers."""
    return _summarize_tool_input(tool_name, tool_input)


def summarize_tool_output(tool_name: str, output: str) -> str:
    """Summarize tool output: pick first meaningful line, truncate."""
    return _summarize_collapsed_tool_body(output)


def _format_history(entries: list[str], limit: int = 20) -> str:
    """Format recent history entries with 1-based numbers."""
    start = max(0, len(entries) - limit)
    return "\n".join(
        f"{start + i + 1}. {entry}" for i, entry in enumerate(entries[start:])
    )


def _save_transcript(state_obj: Any, cwd: str, permissions: PermissionManager, output_path: str) -> str:
    """Save transcript entries to file. Returns the resolved path string."""
    from minicode.tui.transcript import format_transcript_text

    target = resolve_tool_path(ToolContext(cwd=cwd, permissions=permissions), output_path, "write")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(format_transcript_text(state_obj.transcript), encoding="utf-8")
    return str(target)


def _apply_tool_result_visual_state(
    entry: TranscriptEntry,
    tool_name: str,
    output: str,
    is_error: bool,
) -> None:
    """Apply tool result visual state to a transcript entry."""
    entry.status = "error" if is_error else "success"
    entry.body = f"ERROR: {output}" if is_error else output
    if is_error:
        entry.collapsed = False
        entry.collapsedSummary = None
        entry.collapsePhase = None
    else:
        entry.collapsed = True
        entry.collapsedSummary = _summarize_collapsed_tool_body(output)
        entry.collapsePhase = 3


def _mark_unfinished_tools(state_obj: Any) -> int:
    """Mark running tool entries as errors and clean up state. Returns count of affected entries."""
    count = 0
    for entry in state_obj.transcript:
        if entry.kind == "tool" and entry.status == "running":
            entry.status = "error"
            entry.body = (
                f"{entry.body}\n\n"
                "ERROR: Tool did not report a final result before the turn ended. "
                "This usually means the command kept running in the background "
                "or the tool lifecycle got out of sync."
            )
            entry.collapsed = False
            entry.collapsedSummary = None
            entry.collapsePhase = None
            state_obj.recent_tools.append({"name": entry.toolName or "unknown", "status": "error"})
            count += 1
    if hasattr(state_obj, "pending_tool_runs"):
        state_obj.pending_tool_runs = {}
    state_obj.active_tool = None
    return count


def _handle_feedback_mode_event(
    state: ScreenState,
    event: ParsedInputEvent,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
) -> None:
    """Handle events when in feedback mode (rejection guidance input)."""
    pending = state.pending_approval
    if not pending:
        return

    if isinstance(event, KeyEvent):
        if event.name == "escape":
            pending.feedback_mode = False
            pending.feedback_input = ""
            rerender()
            return
        if event.name == "return":
            approval_result.clear()
            approval_result["decision"] = "deny_with_feedback"
            approval_result["feedback"] = pending.feedback_input
            approval_event.set()
            rerender()
            return
        if event.name == "backspace":
            if pending.feedback_input:
                pending.feedback_input = pending.feedback_input[:-1]
                rerender()
            return

    if isinstance(event, TextEvent) and not event.ctrl:
        pending.feedback_input += event.text
        rerender()
