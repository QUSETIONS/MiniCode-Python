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
from minicode.history import load_history_entries
from minicode.local_tool_shortcuts import parse_local_tool_shortcut
from minicode.permissions import PermissionManager
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
from minicode.state import Store, create_app_store
from minicode.tooling import ToolContext, ToolRegistry
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
from minicode.tui.screen import (
    enter_alternate_screen,
    exit_alternate_screen,
    hide_cursor,
    show_cursor,
)
from minicode.tui.transcript import (
    _render_transcript_lines,
)
from minicode.tui.types import TranscriptEntry
from minicode.types import ChatMessage, ModelAdapter
from minicode.workspace import resolve_tool_path

# ---------------------------------------------------------------------------
from minicode.tui.state import TtyAppArgs, ScreenState, PendingApproval, _push_transcript_entry, _update_tool_entry, _collapse_tool_entry, _finalize_dangling_running_tools, _scroll_transcript_by, _jump_transcript_to_edge, _scroll_pending_approval_by, _toggle_pending_approval_expand, _move_pending_approval_selection, _history_up, _history_down, _get_visible_commands, _is_file_edit_tool, _extract_path_from_tool_input, _summarize_collapsed_tool_body, _summarize_tool_input
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
