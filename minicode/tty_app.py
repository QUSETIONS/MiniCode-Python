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
import random
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from minicode.cli_commands import (
    SLASH_COMMANDS,
    try_handle_local_command,
)
from minicode.cost_tracker import CostTracker
from minicode.local_tool_shortcuts import parse_local_tool_shortcut
from minicode.permissions import PermissionManager
from minicode.session import SessionData
from minicode.state import Store
from minicode.tooling import ToolRegistry
from minicode.tui.chrome import (
    _cached_terminal_size,
    get_permission_prompt_max_scroll_offset,
    render_permission_prompt,
    SUBTLE,
    RESET,
)
from minicode.tui.input_parser import (
    KeyEvent,
    ParsedInputEvent,
    TextEvent,
    WheelEvent,
    parse_input_chunk,
)
from minicode.tui.transcript import (
    _render_transcript_lines,
)
from minicode.tui.types import TranscriptEntry
from minicode.types import ChatMessage, ModelAdapter

# ---------------------------------------------------------------------------
from minicode.tui.state import TtyAppArgs, ScreenState, PendingApproval
from minicode.tui.navigation import _scroll_transcript_by, _jump_transcript_to_edge, _scroll_pending_approval_by, _toggle_pending_approval_expand, _move_pending_approval_selection, _history_up, _history_down, _get_visible_commands
from minicode.tui.tool_helpers import _is_file_edit_tool, _extract_path_from_tool_input, _summarize_collapsed_tool_body, _summarize_tool_input, _apply_tool_result_visual_state as _shared_apply_tool_result_visual_state, _mark_unfinished_tools as _shared_mark_unfinished_tools, _save_transcript as _shared_save_transcript
from minicode.tui.tool_lifecycle import _push_transcript_entry, _update_tool_entry, _collapse_tool_entry, _finalize_dangling_running_tools, _schedule_tool_auto_collapse, _get_running_tool_entries
from minicode.tui.event_flow import _handle_event as _handle_tty_event
from minicode.tui.runtime_control import enter_tty_runtime, exit_tty_runtime, install_sigwinch_rerender
from minicode.tui.session_flow import handle_session_listing, load_or_create_session, build_tty_runtime_state, install_permission_prompt, finalize_tty_session
from minicode.tui.renderer import _render_screen
from minicode.tui.input_handler import _RawModeContext, _handle_input

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

    if handle_session_listing(cwd, list_sessions_only):
        return messages

    session = load_or_create_session(cwd, resume_session)
    args, state = build_tty_runtime_state(runtime, tools, model, messages, cwd, permissions, session)

    # Throttled renderer: coalesces rapid rerender() calls to reduce flickering
    throttled = _ThrottledRenderer(lambda: _render_screen(args, state), min_interval=0.016)

    def rerender() -> None:
        throttled.request()

    approval_event, approval_result, _ = install_permission_prompt(args, state, rerender)

    input_remainder = ""
    should_exit = False
    # Autosave throttle: check at most every ~2 seconds, not every 20ms
    _autosave_counter = 0
    _AUTOSAVE_CHECK_INTERVAL = 100  # iterations (~2s at 20ms polling)

    enter_tty_runtime()

    # On Unix, listen for SIGWINCH so terminal resizes are picked up
    # immediately rather than waiting for the 0.5s cache TTL.
    # signal.signal() can only be called from the main thread.
    _prev_sigwinch = install_sigwinch_rerender(throttled)

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
                        _handle_tty_event(args, state, event, rerender, approval_event, approval_result, _handle_input)
                        if state.input == "/exit" or (
                            isinstance(event, KeyEvent)
                            and event.name == "c"
                            and event.ctrl
                        ):
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
        exit_tty_runtime(_prev_sigwinch)
        
        finalize_tty_session(args, state)

    return args.messages


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
    return _shared_save_transcript(state_obj, cwd, permissions, output_path)


def _apply_tool_result_visual_state(
    entry: TranscriptEntry,
    tool_name: str,
    output: str,
    is_error: bool,
) -> None:
    """Apply tool result visual state to a transcript entry."""
    _shared_apply_tool_result_visual_state(entry, tool_name, output, is_error)


def _mark_unfinished_tools(state_obj: Any) -> int:
    """Mark running tool entries as errors and clean up state. Returns count of affected entries."""
    return _shared_mark_unfinished_tools(state_obj)


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
