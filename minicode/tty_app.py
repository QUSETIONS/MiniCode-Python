"""MiniCode Python TTY Application.

This module implements the full-screen terminal user interface for MiniCode,
including:
- Real-time transcript rendering with tool output collapsing
- Interactive permission approval prompts
- Background agent thread management
- Keyboard event handling and command routing
- Session persistence and autosave
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
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
    _cached_terminal_size,
    get_permission_prompt_max_scroll_offset,
    render_banner,
    render_footer_bar,
    render_panel,
    render_permission_prompt,
    render_slash_menu,
    render_status_line,
    render_tool_panel,
    SUBTLE,
    RESET,
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
    _render_transcript_lines,
    get_transcript_max_scroll_offset,
    get_transcript_window_size,
    render_transcript,
)
from minicode.tui.types import TranscriptEntry
from minicode.types import ChatMessage, ModelAdapter
from minicode.workspace import resolve_tool_path

# ---------------------------------------------------------------------------
# Terminal size — use unified cache from chrome module
# ---------------------------------------------------------------------------

# Alias to the single canonical implementation in chrome.py
_get_terminal_size = _cached_terminal_size


# ---------------------------------------------------------------------------
# Throttled renderer
# ---------------------------------------------------------------------------

class _ThrottledRenderer:
    """Coalesces rapid rerender() calls into at most one actual render per interval.

    THREAD SAFETY: The actual render function (_render_fn) is ONLY executed on
    the thread that calls ``flush()`` or ``force()``.  ``request()`` never
    invokes the render function directly — it only marks a pending flag.  This
    ensures that background threads (agent, collapse timer) can safely call
    ``request()`` without writing to stdout concurrently with the main UI
    thread.
    """

    __slots__ = ("_render_fn", "_min_interval", "_pending", "_last_render_time", "_lock")

    def __init__(self, render_fn: Callable[[], None], min_interval: float = 0.033) -> None:
        self._render_fn = render_fn
        self._min_interval = min_interval  # ~30 fps cap (sufficient for terminal UI)
        self._pending = False
        self._last_render_time: float = 0.0
        self._lock = threading.Lock()

    def request(self) -> None:
        """Mark that a rerender is needed.

        This method is safe to call from any thread.  It never invokes the
        render function — the actual render happens on the next ``flush()``
        call from the main event loop.
        """
        with self._lock:
            self._pending = True

    def flush(self) -> None:
        """Execute a pending render if the throttle interval has elapsed.

        Must be called from the main UI thread only.
        """
        now = time.monotonic()
        with self._lock:
            if not self._pending:
                return
            elapsed = now - self._last_render_time
            if elapsed < self._min_interval:
                return  # Still within throttle window — defer
            self._pending = False
            self._last_render_time = now
        self._render_fn()

    def force(self) -> None:
        """Unconditionally render now, ignoring throttle.

        Must be called from the main UI thread only.
        """
        with self._lock:
            self._pending = False
            self._last_render_time = time.monotonic()
        self._render_fn()


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
    """根据当前状态提供上下文相关的帮助提示（纯文本，不含 emoji）。"""
    if not state.is_busy and not state.pending_approval:
        return None  # 保持状态栏简洁

    if state.is_busy and state.active_tool:
        return f"Running {state.active_tool}... (Ctrl+C to cancel)"

    if state.pending_approval:
        return "Approval required. Use arrow keys and Enter to choose."

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


_FOOTER_LINES = 1

# Cache for chrome overhead so we only re-measure when state changes
_chrome_overhead_cache: dict[str, tuple[tuple, int]] = {}


def _count_rendered_lines(s: str) -> int:
    """Count screen lines in a rendered string (split on \\n)."""
    return s.count("\n") + 1


def _get_chrome_overhead(args: TtyAppArgs, state: ScreenState) -> int:
    """Measure the actual line count of header + prompt panels (cached).

    Accounts for compact mode (small terminal): uses single-\\n separators
    instead of double-\\n, saving 2 lines.
    """
    compact = _is_compact_terminal()
    # sep "\n\n" adds 2 blank lines between panels; "\n" adds 1.
    # There are 2 separators (header→transcript, transcript→prompt).
    gaps = 2 if compact else 4
    cache_key = (
        args.cwd,
        getattr(args, "model", None),
        state.input,
        bool(state.pending_approval),
        compact,
    )
    cached = _chrome_overhead_cache.get("key")
    if cached is not None and cached[0] == cache_key:
        return cached[1]

    header_lines = _count_rendered_lines(_render_header_panel(args, state))
    prompt_lines = _count_rendered_lines(_render_prompt_panel(state))
    overhead = header_lines + prompt_lines + _FOOTER_LINES + gaps
    _chrome_overhead_cache["key"] = (cache_key, overhead)
    return overhead


def _get_transcript_body_lines(args: TtyAppArgs, state: ScreenState) -> int:
    _, rows = _get_terminal_size()
    rows = max(24, rows)
    # Subtract the actual rendered chrome (header + prompt + footer + gaps)
    # plus 4 lines for the transcript panel frame (top border, title, divider, bottom border)
    transcript_frame = 4
    chrome_overhead = _get_chrome_overhead(args, state) + transcript_frame
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
# Rendering — cached header & footer
# ---------------------------------------------------------------------------

# Banner cache: the banner rarely changes (only when cwd, model, or stats change).
_banner_cache: dict[str, tuple[tuple, str]] = {"key": ((), "")}


_COMPACT_ROWS_THRESHOLD = 35  # Use compact UI when terminal rows < this value


def _is_compact_terminal() -> bool:
    """Return True when the terminal is too short for the full UI chrome."""
    _, rows = _get_terminal_size()
    return rows < _COMPACT_ROWS_THRESHOLD


def _render_header_panel(args: TtyAppArgs, state: ScreenState) -> str:
    """Render the top banner panel with model info, cwd, and session stats.
    
    The result is cached to avoid re-rendering when stats haven't changed.
    Uses compact single-line mode when the terminal has fewer than
    _COMPACT_ROWS_THRESHOLD rows so that the transcript area has more space.
    """
    stats = _get_session_stats(args, state)
    compact = _is_compact_terminal()
    cache_key = (
        args.cwd,
        id(args.runtime),
        stats.get("transcriptCount"),
        stats.get("messageCount"),
        stats.get("skillCount"),
        stats.get("mcpCount"),
        _cached_terminal_size(),
        compact,
    )
    cached = _banner_cache.get("key")
    if cached and cached[0] == cache_key:
        return cached[1]
    result = render_banner(
        args.runtime,
        args.cwd,
        args.permissions.get_summary(),
        stats,
        compact=compact,
    )
    _banner_cache["key"] = (cache_key, result)
    return result


# Footer cache: only changes with status, tool/skill state, background tasks
_footer_cache: dict[str, tuple[tuple, str]] = {"key": ((), "")}


def _render_footer_cached(
    status: str | None,
    tools_enabled: bool,
    skills_enabled: bool,
    background_tasks: list[dict[str, Any]],
) -> str:
    """Render the bottom status bar with caching to reduce flicker.
    
    Shows current operation status, tool/skill availability, and background tasks.
    """
    cache_key = (
        status,
        tools_enabled,
        skills_enabled,
        len(background_tasks),
        _cached_terminal_size(),
    )
    cached = _footer_cache.get("key")
    if cached and cached[0] == cache_key:
        return cached[1]
    result = render_footer_bar(status, tools_enabled, skills_enabled, background_tasks)
    _footer_cache["key"] = (cache_key, result)
    return result


def _render_prompt_panel(state: ScreenState) -> str:
    compact = _is_compact_terminal()
    commands = _get_visible_commands(state.input)
    prompt_body = render_input_prompt(state.input, state.cursor_offset, compact=compact)
    if commands:
        prompt_body += "\n" + render_slash_menu(
            commands,
            min(state.selected_slash_index, len(commands) - 1),
        )
    return render_panel("prompt", prompt_body)


def _render_screen(args: TtyAppArgs, state: ScreenState) -> None:
    background_tasks = list_background_tasks()
    compact = _is_compact_terminal()
    sep = "\n" if compact else "\n\n"

    # Build the entire frame into a buffer, then write once
    buf: list[str] = []
    # CSI H + CSI J  (cursor home + erase to end) – avoids full clear flicker
    buf.append("\x1b[H\x1b[J")

    # Header
    buf.append(_render_header_panel(args, state))
    buf.append(sep)

    has_skills = len(args.tools.get_skills()) > 0

    if state.pending_approval:
        # Permission approval overlay
        buf.append(
            render_permission_prompt(
                state.pending_approval.request,
                expanded=state.pending_approval.details_expanded,
                scroll_offset=state.pending_approval.details_scroll_offset,
                selected_choice_index=state.pending_approval.selected_choice_index,
                feedback_mode=state.pending_approval.feedback_mode,
                feedback_input=state.pending_approval.feedback_input,
            )
        )
        buf.append(sep)
        buf.append(
            render_panel(
                "activity",
                render_tool_panel(state.active_tool, state.recent_tools, background_tasks),
            )
        )
        buf.append(sep)
        buf.append(_render_footer_cached(state.status, True, has_skills, background_tasks))
        sys.stdout.write("".join(buf))
        sys.stdout.flush()
        return

    # Transcript — snapshot the list to avoid IndexError from concurrent
    # agent-thread appends (CPython GIL makes list.append atomic but
    # iteration + append can still race on length vs slot access).
    transcript_snapshot = list(state.transcript)
    body_lines = _get_transcript_body_lines(args, state)
    if transcript_snapshot:
        transcript_body = render_transcript(
            transcript_snapshot, state.transcript_scroll_offset, body_lines
        )
    else:
        transcript_body = f"{render_status_line(None)}\n\nType /help for commands."
    buf.append(
        render_panel(
            "session feed",
            transcript_body,
            right_title=f"{len(transcript_snapshot)} events",
            min_body_lines=body_lines,
        )
    )
    buf.append(sep)

    # Prompt
    buf.append(_render_prompt_panel(state))
    buf.append(sep)

    # Footer (cached)
    buf.append(_render_footer_cached(state.status, True, has_skills, background_tasks))

    # Contextual hint (only when busy or awaiting approval — no idle spam)
    contextual_help = _get_contextual_help(state, args)
    if contextual_help:
        buf.append(f"\n{SUBTLE}{contextual_help}{RESET}")

    sys.stdout.write("".join(buf))
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Cross-platform raw mode stdin
# ---------------------------------------------------------------------------

# Windows msvcrt scan-code → ANSI escape sequence mapping.
# msvcrt.getwch() returns a two-char sequence for special keys:
#   prefix ('\x00' or '\xe0') + scan-code byte.
# We translate these to the ANSI sequences that input_parser.py already
# understands.
_WIN_SCANCODE_TO_ANSI: dict[int, str] = {
    72: "\x1b[A",    # Up
    80: "\x1b[B",    # Down
    77: "\x1b[C",    # Right
    75: "\x1b[D",    # Left
    71: "\x1b[H",    # Home
    79: "\x1b[F",    # End
    73: "\x1b[5~",   # Page Up
    81: "\x1b[6~",   # Page Down
    83: "\x1b[3~",   # Delete
    82: "\x1b[2~",   # Insert
    # Alt+Arrow (returned with \x00 prefix on some terminals)
    152: "\x1b[1;3A",  # Alt+Up
    160: "\x1b[1;3B",  # Alt+Down
    157: "\x1b[1;3C",  # Alt+Right
    155: "\x1b[1;3D",  # Alt+Left
    # Ctrl+Arrow
    141: "\x1b[1;5A",  # Ctrl+Up
    145: "\x1b[1;5B",  # Ctrl+Down
    116: "\x1b[1;5C",  # Ctrl+Right
    115: "\x1b[1;5D",  # Ctrl+Left
}


def _win_read_one_key() -> str:
    """Read one logical key from Windows msvcrt, translating special keys
    into ANSI escape sequences.

    Returns an empty string if no key is available.
    """
    import msvcrt

    if not msvcrt.kbhit():
        return ""

    ch = msvcrt.getwch()

    # Special-key prefix: next char is a scan code
    if ch in ("\x00", "\xe0"):
        if msvcrt.kbhit():
            scan = ord(msvcrt.getwch())
        else:
            # Prefix arrived alone (rare) — treat as Escape
            return "\x1b"
        return _WIN_SCANCODE_TO_ANSI.get(scan, "")

    # Ctrl+C → keep as '\x03' so parse_input_chunk handles it
    return ch


def _read_raw_char() -> str:
    """Read a single character from stdin in raw mode, cross-platform."""
    if sys.platform == "win32":
        return _win_read_one_key()
    else:
        import select

        fd = sys.stdin.fileno()
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            # Use os.read() to bypass Python's TextIOWrapper buffering.
            # In raw/cbreak mode the kernel returns whatever bytes are
            # available, so os.read() won't block.
            data = os.read(fd, 4096)
            return data.decode("utf-8", errors="replace") if data else ""
        return ""


def _read_raw_chunk() -> str:
    """Read all available raw chars as a single chunk."""
    if sys.platform == "win32":
        result = ""
        while True:
            ch = _win_read_one_key()
            if not ch:
                break
            result += ch
        return result
    else:
        import select

        fd = sys.stdin.fileno()
        # First wait with a timeout for initial data
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            return ""
        # Read all available bytes in one go.  In raw mode the kernel
        # delivers whatever has arrived so far; os.read() returns
        # immediately with 1..N bytes.
        data = os.read(fd, 4096)
        if not data:
            return ""
        # Drain any remaining bytes without blocking
        while True:
            ready2, _, _ = select.select([fd], [], [], 0)
            if not ready2:
                break
            more = os.read(fd, 4096)
            if not more:
                break
            data += more
        return data.decode("utf-8", errors="replace")


class _RawModeContext:
    """Context manager for raw terminal mode.

    On Unix: switches stdin to raw mode via termios/tty and restores on exit.
    On Windows: msvcrt provides character-at-a-time input natively, but we
    need to ensure the console code page is set for UTF-8 and VT processing
    is enabled.
    """

    def __init__(self) -> None:
        self._old_settings: Any = None
        self._old_cp: int | None = None

    def __enter__(self) -> _RawModeContext:
        if sys.platform == "win32":
            # Ensure VT processing is active (idempotent)
            from minicode.tui.screen import _enable_windows_vt_processing
            _enable_windows_vt_processing()
            # Switch console to UTF-8 code page for proper Unicode handling
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                self._old_cp = kernel32.GetConsoleOutputCP()
                kernel32.SetConsoleOutputCP(65001)  # UTF-8
            except Exception:
                pass
        else:
            import termios

            fd = sys.stdin.fileno()
            self._old_settings = termios.tcgetattr(fd)
            new = termios.tcgetattr(fd)
            # Input flags: disable CR→NL translation and XON/XOFF flow control,
            # strip high bit, and break signal generation.
            new[0] &= ~(
                termios.BRKINT | termios.ICRNL | termios.INPCK
                | termios.ISTRIP | termios.IXON
            )
            # Output flags: KEEP OPOST so that \n → \r\n translation still
            # works.  tty.setraw() clears OPOST which causes "staircase"
            # output on Linux/macOS — every newline only moves down without
            # returning the cursor to column 0.
            # new[1] is intentionally left untouched.
            # Control flags: set 8-bit chars
            new[2] &= ~(termios.CSIZE | termios.PARENB)
            new[2] |= termios.CS8
            # Local flags: disable echo, canonical mode, extended processing,
            # and signal generation from keys (Ctrl-C, Ctrl-Z).
            new[3] &= ~(
                termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG
            )
            # Special characters: read returns after 1 byte, no timeout.
            new[6][termios.VMIN] = 1
            new[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSAFLUSH, new)
        return self

    def __exit__(self, *_: Any) -> None:
        if sys.platform == "win32":
            if self._old_cp is not None:
                try:
                    import ctypes
                    ctypes.windll.kernel32.SetConsoleOutputCP(self._old_cp)  # type: ignore[attr-defined]
                except Exception:
                    pass
        elif self._old_settings is not None:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_settings)


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
        # Don't reset scroll offset — respect user's manual scroll position
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

    # /debug — show scroll diagnostics
    if input_text == "/debug":
        from minicode.tui.transcript import _compute_total_lines, get_transcript_max_scroll_offset
        cols, rows = _get_terminal_size()
        compact = _is_compact_terminal()
        body_lines = _get_transcript_body_lines(args, state)
        total_lines = _compute_total_lines(state.transcript)
        max_scroll = get_transcript_max_scroll_offset(state.transcript, body_lines)
        chrome = _get_chrome_overhead(args, state)
        lines = [
            "=== Scroll Debug ===",
            f"Terminal: {cols}x{rows}  compact={compact}",
            f"Chrome overhead: {chrome} lines",
            f"Transcript frame: 4 lines",
            f"Body window: {body_lines} lines",
            f"Transcript total: {total_lines} lines",
            f"Scroll offset: {state.transcript_scroll_offset}/{max_scroll}",
            f"Mouse tracking: ESC[?1000h ESC[?1003h ESC[?1006h",
            "",
            "Try scrolling now. If scroll_offset changes, mouse events work.",
            "Use PageUp/PageDown or Ctrl+A/E as keyboard alternatives.",
        ]
        _push_transcript_entry(state, kind="assistant", body="\n".join(lines))
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
        # Don't reset scroll offset — respect user's manual scroll position
        rerender()

    def on_progress_message(content: str) -> None:
        _push_transcript_entry(state, kind="progress", body=content)
        # Don't reset scroll offset — respect user's manual scroll position
        rerender()

    def on_tool_start(tool_name: str, tool_input: Any) -> None:
        state.status = f"Running {tool_name}..."
        state.active_tool = tool_name
        state.tool_start_time = time.monotonic()  # 记录工具启动时间

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
        # Don't reset scroll offset — respect user's manual scroll position
        rerender()

    def on_tool_result(tool_name: str, output: str, is_error: bool) -> None:
        # 计算并显示工具执行时间
        elapsed = ""
        if state.tool_start_time is not None:
            elapsed_secs = time.monotonic() - state.tool_start_time
            if elapsed_secs > 1:
                elapsed = f" ({elapsed_secs:.1f}s)"
        
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
                
                # Error recovery hints (plain text, no emoji)
                display_output = output
                if is_error:
                    suggestions = []
                    output_lower = output.lower()
                    if "not found" in output_lower or "no such file" in output_lower:
                        suggestions.append("Hint: file not found — use /ls to list files")
                    elif "permission" in output_lower or "denied" in output_lower:
                        suggestions.append("Hint: permission denied — check file access rights")
                    elif "syntax" in output_lower or "error" in output_lower:
                        suggestions.append("Hint: error occurred — review output and fix issues")

                    if suggestions:
                        display_output = f"ERROR: {output}\n\n" + "\n".join(suggestions)
                    else:
                        display_output = f"ERROR: {output}"
                
                _update_tool_entry(
                    state,
                    entry_id,
                    "error" if is_error else "success",
                    display_output,
                )
                _schedule_tool_auto_collapse(
                    state,
                    entry_id,
                    display_output,
                    rerender,
                )

        state.active_tool = None
        remaining = sum(len(v) for v in pending_tool_entries.values())
        if remaining > 0:
            state.status = f"{remaining} tool(s) still running..."
        else:
            state.status = None
        # Don't reset scroll offset — respect user's manual scroll position
        rerender()

    args.permissions.begin_turn()
    
    # Run agent turn in background thread to keep UI responsive
    agent_error = None
    agent_result: dict = {"messages": None}
    agent_thread_lock = threading.Lock()
    
    def _run_agent_background():
        nonlocal agent_error, agent_result
        try:
            next_messages = run_agent_turn(
                model=args.model,
                tools=args.tools,
                messages=list(args.messages),  # Copy to avoid race condition
                cwd=args.cwd,
                permissions=args.permissions,
                on_tool_start=on_tool_start,
                on_tool_result=on_tool_result,
                on_assistant_message=on_assistant_message,
                on_progress_message=on_progress_message,
            )
            with agent_thread_lock:
                agent_result["messages"] = next_messages
        except Exception as e:
            agent_error = e
        finally:
            args.permissions.end_turn()
            with agent_thread_lock:
                agent_result["done"] = True
            state.is_busy = False
            state.active_tool = None
            state.status = None
            rerender()
    
    agent_thread = threading.Thread(target=_run_agent_background, daemon=True)
    agent_thread.start()
    state.agent_thread = agent_thread
    # Assign lock BEFORE result — the main loop checks agent_result first,
    # so the lock must already be available to avoid AttributeError.
    state.agent_lock = agent_thread_lock
    state.agent_result = agent_result
    
    # Return immediately - agent runs in background
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
        # Signal the main thread's throttled renderer to show the approval UI.
        # Do NOT call _render_screen() here — we're on the agent thread and
        # writing to stdout concurrently with the main thread would corrupt
        # the terminal display.  request() only sets a pending flag; the main
        # event loop's next flush() will do the actual render safely.
        rerender()
        approval_event.clear()
        approval_event.wait()
        result = approval_result.copy()
        state.pending_approval = None
        return result

    permissions.prompt = _permission_prompt_handler

    # Throttled renderer: coalesces rapid rerender() calls to reduce flickering
    throttled = _ThrottledRenderer(lambda: _render_screen(args, state), min_interval=0.016)

    def rerender() -> None:
        throttled.request()

    input_remainder = ""
    should_exit = False
    # Autosave throttle: check at most every ~2 seconds, not every 20ms
    _autosave_counter = 0
    _AUTOSAVE_CHECK_INTERVAL = 100  # iterations (~2s at 20ms polling)

    enter_alternate_screen()
    hide_cursor()

    # On Unix, listen for SIGWINCH so terminal resizes are picked up
    # immediately rather than waiting for the 0.5s cache TTL.
    # signal.signal() can only be called from the main thread.
    _prev_sigwinch = None
    if (
        sys.platform != "win32"
        and threading.current_thread() is threading.main_thread()
    ):
        import signal as _signal

        from minicode.tui.chrome import invalidate_terminal_size_cache

        def _on_sigwinch(_signum: int, _frame: Any) -> None:
            invalidate_terminal_size_cache()
            throttled.request()

        try:
            _prev_sigwinch = _signal.signal(_signal.SIGWINCH, _on_sigwinch)
        except (OSError, ValueError):
            # Couldn't set signal handler (e.g. not main thread despite check)
            _prev_sigwinch = None

    try:
        _render_screen(args, state)

        with _RawModeContext():
            while not should_exit:
                # Autosave check (throttled)
                _autosave_counter += 1
                if state.autosave and _autosave_counter >= _AUTOSAVE_CHECK_INTERVAL:
                    _autosave_counter = 0
                    state.autosave.save_if_needed()
                
                # Check if background agent thread completed
                agent_result_data = state.agent_result
                lock = getattr(state, "agent_lock", None)
                if agent_result_data is not None and lock is not None and agent_result_data.get("done"):
                    with lock:
                        if agent_result_data.get("messages"):
                            args.messages = agent_result_data["messages"]
                        agent_result_data["done"] = False  # Reset flag

                # Read raw input
                if sys.platform == "win32":
                    import msvcrt

                    if not msvcrt.kbhit():
                        # Flush any deferred renders during idle
                        throttled.flush()
                        time.sleep(0.05)  # 从 0.02 增加到 0.05 降低 CPU 使用率
                        continue
                    # Use _win_read_one_key to translate special keys
                    chunk = ""
                    while True:
                        ch = _win_read_one_key()
                        if not ch:
                            break
                        chunk += ch
                else:
                    import select

                    _fd = sys.stdin.fileno()
                    ready, _, _ = select.select([_fd], [], [], 0.05)
                    if not ready:
                        # Flush any deferred renders during idle
                        throttled.flush()
                        continue
                    # Use os.read() to bypass Python's TextIOWrapper/
                    # BufferedReader which can block on partial UTF-8
                    # sequences in raw mode.
                    _raw = os.read(_fd, 4096)
                    if not _raw:
                        should_exit = True
                        continue
                    # Drain any remaining bytes without blocking
                    while True:
                        ready2, _, _ = select.select([_fd], [], [], 0)
                        if not ready2:
                            break
                        _more = os.read(_fd, 4096)
                        if not _more:
                            break
                        _raw += _more
                    chunk = _raw.decode("utf-8", errors="replace")

                if not chunk:
                    continue

                parsed = parse_input_chunk(input_remainder + chunk)
                input_remainder = parsed.rest

                for event in parsed.events:
                    try:
                        _handle_event(args, state, event, rerender, approval_event, approval_result)
                        if state.input == "/exit":
                            raise SystemExit(0)
                    except SystemExit:
                        should_exit = True
                        break
                    except Exception as e:
                        # 记录事件处理错误，但不中断主循环
                        logging.debug("Event handling error: %s", e, exc_info=True)

                # Ensure the final state after processing all events is visible
                throttled.flush()

    finally:
        # Restore previous SIGWINCH handler on Unix
        if _prev_sigwinch is not None and sys.platform != "win32":
            import signal as _signal

            _signal.signal(_signal.SIGWINCH, _prev_sigwinch)

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
    """Process a single parsed input event.
    
    Routes the event to the appropriate handler based on current state:
    - Ctrl+C: Exit immediately
    - Pending approval: Handle permission dialog input
    - Normal mode: Handle input, navigation, and commands
    
    Args:
        args: Application arguments (tools, model, permissions)
        state: Current screen state
        event: Parsed input event from terminal
        rerender: Function to trigger screen redraw
        approval_event: Threading event for approval synchronization
        approval_result: Dict to store approval decision
    """
    # ---------- Ctrl+C → exit ----------
    # \x03 is parsed as KeyEvent(name='c', ctrl=True) by parse_input_chunk
    # (CTRL_CHAR_TO_NAME maps \x03 → 'c', produces KeyEvent not TextEvent)
    if isinstance(event, KeyEvent) and event.ctrl and event.name == "c":
        raise SystemExit(0)
    if isinstance(event, TextEvent) and event.ctrl and event.text == "c":
        raise SystemExit(0)

    # ---------- Pending approval mode ----------
    # Capture locally to avoid TOCTOU — the agent thread may clear
    # state.pending_approval between our check and the handler's use.
    pending = state.pending_approval
    if pending is not None:
        _handle_pending_approval_event(state, pending, event, rerender, approval_event, approval_result)
        return

    # ---------- Normal mode ----------
    _handle_normal_mode_event(args, state, event, rerender)


# ---------------------------------------------------------------------------
# Pending approval event handlers
# ---------------------------------------------------------------------------


def _handle_pending_approval_event(
    state: ScreenState,
    pending: Any,
    event: ParsedInputEvent,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
) -> None:
    """Handle input events while a permission approval is pending.
    
    ``pending`` is captured by the caller to avoid TOCTOU races with the
    agent thread (which may set ``state.pending_approval = None`` after an
    approval event is signalled).
    """
    if pending.feedback_mode:
        _handle_feedback_mode_event(state, event, rerender, approval_event, approval_result)
        return
    
    if isinstance(event, KeyEvent):
        if _handle_pending_approval_key(state, event, rerender, approval_event, approval_result):
            return
    
    if isinstance(event, TextEvent) and not event.ctrl:
        if _handle_pending_approval_text(state, event, rerender, approval_event, approval_result):
            return
    
    if isinstance(event, WheelEvent):
        if _handle_pending_approval_wheel(state, event, rerender):
            return


def _handle_pending_approval_key(
    state: ScreenState,
    event: KeyEvent,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
) -> bool:
    """Handle key events during pending approval. Returns True if handled."""
    pending = state.pending_approval
    
    if event.name == "escape":
        approval_result.clear()
        approval_result["decision"] = "deny_once"
        approval_event.set()
        rerender()
        return True
    
    if event.name == "return":
        _confirm_pending_choice(state, rerender, approval_event, approval_result)
        return True
    
    if event.name == "up" and _move_pending_approval_selection(state, -1):
        rerender()
        return True
    
    if event.name == "down" and _move_pending_approval_selection(state, 1):
        rerender()
        return True
    
    if event.name == "pageup" and _scroll_pending_approval_by(state, -5):
        rerender()
        return True
    
    if event.name == "pagedown" and _scroll_pending_approval_by(state, 5):
        rerender()
        return True
    
    # Digit keys for choices
    choices = pending.request.get("choices", [])
    for choice in choices:
        if event.text == choice.get("key"):
            _select_pending_choice(state, choice, rerender, approval_event, approval_result)
            return True
    
    return False


def _handle_pending_approval_text(
    state: ScreenState,
    event: TextEvent,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
) -> bool:
    """Handle text events during pending approval. Returns True if handled."""
    pending = state.pending_approval
    
    if event.text == "v" and _toggle_pending_approval_expand(state):
        rerender()
        return True
    
    # Check digit keys for choices
    choices = pending.request.get("choices", [])
    for choice in choices:
        if event.text == choice.get("key"):
            _select_pending_choice(state, choice, rerender, approval_event, approval_result)
            return True
    
    return False


def _handle_pending_approval_wheel(
    state: ScreenState,
    event: WheelEvent,
    rerender: Callable[[], None],
) -> bool:
    """Handle wheel events during pending approval for scrolling. Returns True if handled."""
    delta = 3 if event.direction == "up" else -3
    if _scroll_pending_approval_by(state, delta):
        rerender()
        return True
    return False



def _confirm_pending_choice(
    state: ScreenState,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
) -> None:
    """Confirm the selected permission choice."""
    pending = state.pending_approval
    choices = pending.request.get("choices", [])
    
    if choices and 0 <= pending.selected_choice_index < len(choices):
        choice = choices[pending.selected_choice_index]
        _select_pending_choice(state, choice, rerender, approval_event, approval_result)
    else:
        approval_result.clear()
        approval_result["decision"] = "allow_once"
        approval_event.set()
        rerender()


def _select_pending_choice(
    state: ScreenState,
    choice: dict,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
) -> None:
    """Select a permission choice and resolve."""
    pending = state.pending_approval
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


# ---------------------------------------------------------------------------
# Normal mode event handlers
# ---------------------------------------------------------------------------


def _handle_normal_mode_event(
    args: TtyAppArgs,
    state: ScreenState,
    event: ParsedInputEvent,
    rerender: Callable[[], None],
) -> None:
    """Handle input events in normal mode (no pending approval)."""
    visible_commands = _get_visible_commands(state.input)
    
    if isinstance(event, KeyEvent):
        if _handle_normal_mode_key(args, state, event, visible_commands, rerender):
            return
    elif isinstance(event, TextEvent):
        if _handle_normal_mode_text(args, state, event, visible_commands, rerender):
            return
    elif isinstance(event, WheelEvent):
        if _handle_normal_mode_wheel(args, state, event, rerender):
            return


def _handle_normal_mode_key(
    args: TtyAppArgs,
    state: ScreenState,
    event: KeyEvent,
    visible_commands: list,
    rerender: Callable[[], None],
) -> bool:
    """Handle key events in normal mode. Returns True if handled."""
    # Return → submit input or select slash command
    if event.name == "return":
        _handle_normal_mode_return(args, state, visible_commands, rerender)
        return True
    
    # Tab → autocomplete slash command
    if event.name == "tab" and visible_commands:
        _handle_normal_mode_tab(state, visible_commands, rerender)
        return True
    
    # Navigation and editing keys
    if _handle_normal_mode_navigation(state, event, rerender):
        return True
    
    # Ctrl shortcuts (P, N handled in text handler)
    # PageUp/PageDown → scroll transcript
    if event.name == "pageup" and _scroll_transcript_by(args, state, 8):
        rerender()
        return True
    
    if event.name == "pagedown" and _scroll_transcript_by(args, state, -8):
        rerender()
        return True
    
    # Alt+Up / Alt+Down → scroll transcript (keyboard alternative to mouse wheel)
    if event.name == "up" and event.meta:
        if _scroll_transcript_by(args, state, 3):
            rerender()
        return True
    
    if event.name == "down" and event.meta:
        if _scroll_transcript_by(args, state, -3):
            rerender()
        return True
    
    # Up/Down arrows (history or command selection)
    if event.name == "up":
        _handle_up_arrow(args, state, visible_commands, rerender)
        return True
    
    if event.name == "down":
        _handle_down_arrow(args, state, visible_commands, rerender)
        return True
    
    return False


def _handle_normal_mode_return(
    args: TtyAppArgs,
    state: ScreenState,
    visible_commands: list,
    rerender: Callable[[], None],
) -> None:
    """Handle Return key in normal mode."""
    if visible_commands and 0 <= state.selected_slash_index < len(visible_commands):
        selected = visible_commands[state.selected_slash_index]
        usage = getattr(selected, "usage", str(selected))
        # Only auto-fill if the current input doesn't already exactly match the
        # selected command. If it already matches, fall through and submit.
        if state.input.strip() != usage:
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


def _handle_normal_mode_tab(
    state: ScreenState,
    visible_commands: list,
    rerender: Callable[[], None],
) -> None:
    """Handle Tab key for slash command autocompletion."""
    selected = visible_commands[min(state.selected_slash_index, len(visible_commands) - 1)]
    usage = getattr(selected, "usage", str(selected))
    state.input = usage + " "
    state.cursor_offset = len(state.input)
    state.selected_slash_index = 0
    rerender()


def _handle_normal_mode_navigation(
    state: ScreenState,
    event: KeyEvent,
    rerender: Callable[[], None],
) -> bool:
    """Handle navigation and editing keys. Returns True if handled."""
    if event.name == "backspace" and state.cursor_offset > 0:
        state.input = state.input[:state.cursor_offset - 1] + state.input[state.cursor_offset:]
        state.cursor_offset -= 1
        state.selected_slash_index = 0
        rerender()
        return True
    
    if event.name == "delete" and state.cursor_offset < len(state.input):
        state.input = state.input[:state.cursor_offset] + state.input[state.cursor_offset + 1:]
        state.selected_slash_index = 0
        rerender()
        return True
    
    if event.name == "home":
        state.cursor_offset = 0
        rerender()
        return True
    
    if event.name == "end":
        state.cursor_offset = len(state.input)
        rerender()
        return True
    
    if event.name == "left":
        state.cursor_offset = max(0, state.cursor_offset - 1)
        rerender()
        return True
    
    if event.name == "right":
        state.cursor_offset = min(len(state.input), state.cursor_offset + 1)
        rerender()
        return True
    
    if event.name == "escape":
        state.input = ""
        state.cursor_offset = 0
        state.selected_slash_index = 0
        rerender()
        return True
    
    return False


def _handle_up_arrow(
    args: TtyAppArgs,
    state: ScreenState,
    visible_commands: list,
    rerender: Callable[[], None],
) -> None:
    """Handle Up arrow key."""
    if visible_commands:
        state.selected_slash_index = (state.selected_slash_index - 1 + len(visible_commands)) % len(visible_commands)
        rerender()
    elif _history_up(state):
        rerender()


def _handle_down_arrow(
    args: TtyAppArgs,
    state: ScreenState,
    visible_commands: list,
    rerender: Callable[[], None],
) -> None:
    """Handle Down arrow key."""
    if visible_commands:
        state.selected_slash_index = (state.selected_slash_index + 1) % len(visible_commands)
        rerender()
    elif _history_down(state):
        rerender()


def _handle_normal_mode_text(
    args: TtyAppArgs,
    state: ScreenState,
    event: TextEvent,
    visible_commands: list,
    rerender: Callable[[], None],
) -> bool:
    """Handle text events in normal mode. Returns True if handled."""
    # Ctrl shortcuts
    if event.ctrl:
        if event.text == "u":  # Ctrl-U → clear line
            state.input = ""
            state.cursor_offset = 0
            state.selected_slash_index = 0
            rerender()
            return True
        
        if event.text == "a":  # Ctrl-A → home / jump to top
            if not state.input:
                if _jump_transcript_to_edge(args, state, "top"):
                    rerender()
                return True
            state.cursor_offset = 0
            rerender()
            return True
        
        if event.text == "e":  # Ctrl-E → end / jump to bottom
            if not state.input:
                if _jump_transcript_to_edge(args, state, "bottom"):
                    rerender()
                return True
            state.cursor_offset = len(state.input)
            rerender()
            return True
        
        if event.text == "p":  # Ctrl-P → history up
            if _history_up(state):
                rerender()
            return True
        
        if event.text == "n":  # Ctrl-N → history down
            if _history_down(state):
                rerender()
            return True
        
        return False
    
    # Regular text input (accept any non-empty text, including multi-byte CJK/emoji)
    if not event.ctrl and event.text:
        state.input = state.input[:state.cursor_offset] + event.text + state.input[state.cursor_offset:]
        state.cursor_offset += len(event.text)
        state.selected_slash_index = 0
        state.history_index = len(state.history)
        rerender()
        return True
    
    return False


def _handle_normal_mode_wheel(
    args: TtyAppArgs,
    state: ScreenState,
    event: WheelEvent,
    rerender: Callable[[], None],
) -> bool:
    """Handle wheel events in normal mode for scrolling. Returns True if handled."""
    delta = 3 if event.direction == "up" else -3
    if _scroll_transcript_by(args, state, delta):
        rerender()
        return True
    return False


# ---------------------------------------------------------------------------
# Public API / backward-compatible exports for tests
# ---------------------------------------------------------------------------


def summarize_tool_input(tool_name: str, tool_input: Any) -> str:
    """Generate a human-readable summary of tool input.
    
    Public wrapper around _summarize_tool_input for external callers.
    
    Args:
        tool_name: Name of the tool being called
        tool_input: Input dictionary passed to the tool
        
    Returns:
        Human-readable summary string for display in transcript
    """
    return _summarize_tool_input(tool_name, tool_input)


def summarize_tool_output(tool_name: str, output: str) -> str:
    """Summarize tool output for collapsed display.
    
    Picks the first meaningful line and truncates to 140 characters.
    
    Args:
        tool_name: Name of the tool (unused but kept for API consistency)
        output: Full tool output string
        
    Returns:
        Truncated summary suitable for collapsed tool display
    """
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
