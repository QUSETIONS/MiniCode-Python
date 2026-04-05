"""Screen rendering for the MiniCode TTY application.

This module handles all visual rendering of the TTY interface including:
- Header panel (banner with model, cwd, stats)
- Footer panel (status, tools, skills indicators)
- Prompt panel (input line + slash command menu)
- Full screen composition with transcript
- Cross-platform raw terminal mode
"""

from __future__ import annotations

import sys
from typing import Any

from minicode.background_tasks import list_background_tasks
from minicode.tty_app.state_helpers import (
    _get_contextual_help,
    _get_transcript_body_lines,
    _get_max_transcript_scroll_offset,
)
from minicode.tty_app.types import ScreenState, TtyAppArgs
from minicode.tui.chrome import (
    _cached_terminal_size,
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
from minicode.tui.input_parser import KeyEvent, ParsedInputEvent, TextEvent, WheelEvent, parse_input_chunk
from minicode.tui.screen import (
    enter_alternate_screen,
    exit_alternate_screen,
    hide_cursor,
    show_cursor,
)
from minicode.tui.transcript import render_transcript


# ---------------------------------------------------------------------------
# Rendering cache
# ---------------------------------------------------------------------------

_banner_cache: dict[str, tuple[tuple, str]] = {"key": ((), "")}
_footer_cache: dict[str, tuple[tuple, str]] = {"key": ((), "")}


# ---------------------------------------------------------------------------
# Panel renderers
# ---------------------------------------------------------------------------


def _render_header_panel(args: TtyAppArgs, state: ScreenState) -> str:
    """Render the top banner panel with model info, cwd, and session stats.
    
    The result is cached to avoid re-rendering when stats haven't changed.
    """
    from minicode.tty_app.state_helpers import _get_session_stats
    stats = _get_session_stats(args, state)
    cache_key = (
        args.cwd,
        id(args.runtime),
        stats.get("transcriptCount"),
        stats.get("messageCount"),
        stats.get("skillCount"),
        stats.get("mcpCount"),
        _cached_terminal_size(),
    )
    cached = _banner_cache.get("key")
    if cached and cached[0] == cache_key:
        return cached[1]
    result = render_banner(
        args.runtime,
        args.cwd,
        args.permissions.get_summary(),
        stats,
    )
    _banner_cache["key"] = (cache_key, result)
    return result


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
    """Render the input prompt panel with slash command menu."""
    from minicode.tty_app.input_handling import _get_visible_commands
    commands = _get_visible_commands(state.input)
    prompt_body = render_input_prompt(state.input, state.cursor_offset)
    if commands:
        prompt_body += "\n" + render_slash_menu(
            commands,
            min(state.selected_slash_index, len(commands) - 1),
        )
    return render_panel("prompt", prompt_body)


def _render_screen(args: TtyAppArgs, state: ScreenState) -> None:
    """Render the complete TTY screen in a single atomic write.
    
    Builds the entire frame into a buffer then writes once to minimize flicker.
    """
    background_tasks = list_background_tasks()
    contextual_help = _get_contextual_help(state, args)

    # Build frame buffer
    buf: list[str] = []
    buf.append("\u001b[H\u001b[J")  # Cursor home + erase to end
    buf.append(_render_header_panel(args, state))
    buf.append("\n\n")

    has_skills = len(args.tools.get_skills()) > 0

    if state.pending_approval:
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
        buf.append("\n\n")
        buf.append(
            render_panel(
                "activity",
                render_tool_panel(state.active_tool, state.recent_tools, background_tasks),
            )
        )
        buf.append("\n\n")
        buf.append(_render_footer_cached(state.status, True, has_skills, background_tasks))
    else:
        body_lines = _get_transcript_body_lines(args, state)
        if state.transcript:
            transcript_body = render_transcript(
                state.transcript, state.transcript_scroll_offset, body_lines
            )
        else:
            transcript_body = f"{render_status_line(None)}\n\nType /help for commands."
        buf.append(
            render_panel(
                "session feed",
                transcript_body,
                right_title=f"{len(state.transcript)} events",
                min_body_lines=body_lines,
            )
        )
        buf.append("\n\n")
        buf.append(_render_prompt_panel(state))
        buf.append("\n\n")
        buf.append(_render_footer_cached(state.status, True, has_skills, background_tasks))
        if contextual_help:
            buf.append(f"\n{SUBTLE}{contextual_help}{RESET}")

    sys.stdout.write("".join(buf))
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Cross-platform raw mode stdin
# ---------------------------------------------------------------------------

_WIN_SCANCODE_TO_ANSI: dict[int, str] = {
    72: "\x1b[A", 80: "\x1b[B", 77: "\x1b[C", 75: "\x1b[D",
    71: "\x1b[H", 79: "\x1b[F", 73: "\x1b[5~", 81: "\x1b[6~",
    83: "\x1b[3~", 82: "\x1b[2~",
    152: "\x1b[1;3A", 160: "\x1b[1;3B", 157: "\x1b[1;3C", 155: "\x1b[1;3D",
    141: "\x1b[1;5A", 145: "\x1b[1;5B", 116: "\x1b[1;5C", 115: "\x1b[1;5D",
}


def _win_read_one_key() -> str:
    """Read one logical key from Windows msvcrt, translating to ANSI sequences."""
    import msvcrt
    if not msvcrt.kbhit():
        return ""
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        if msvcrt.kbhit():
            scan = ord(msvcrt.getwch())
        else:
            return "\x1b"
        return _WIN_SCANCODE_TO_ANSI.get(scan, "")
    return ch


def _read_raw_chunk() -> str:
    """Read all available raw chars as a single chunk, cross-platform."""
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
    """Context manager for raw terminal mode, cross-platform."""

    def __init__(self) -> None:
        self._old_settings: Any = None
        self._old_cp: int | None = None

    def __enter__(self) -> _RawModeContext:
        if sys.platform == "win32":
            from minicode.tui.screen import _enable_windows_vt_processing
            _enable_windows_vt_processing()
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                self._old_cp = kernel32.GetConsoleOutputCP()
                kernel32.SetConsoleOutputCP(65001)
            except Exception:
                pass
        else:
            import termios
            import tty
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())
        return self

    def __exit__(self, *_: Any) -> None:
        if sys.platform == "win32":
            if self._old_cp is not None:
                try:
                    import ctypes
                    ctypes.windll.kernel32.SetConsoleOutputCP(self._old_cp)
                except Exception:
                    pass
        elif self._old_settings is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
