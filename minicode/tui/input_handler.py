from __future__ import annotations
from collections import defaultdict
import logging
import os
import sys
import threading
import time
from typing import Any, Callable
from minicode.tui.input_parser import KeyEvent, ParsedInputEvent, TextEvent, WheelEvent, parse_input_chunk
from minicode.tui.state import ScreenState, TtyAppArgs
from minicode.cli_commands import try_handle_local_command, find_matching_slash_commands
from minicode.agent_loop import run_agent_turn
from minicode.context_manager import save_context_state
from minicode.history import save_history_entries
from minicode.local_tool_shortcuts import parse_local_tool_shortcut
from minicode.prompt import build_system_prompt
from minicode.tooling import ToolContext
from minicode.tui.navigation import _scroll_pending_approval_by, _toggle_pending_approval_expand, _move_pending_approval_selection, _scroll_transcript_by, _jump_transcript_to_edge, _history_up, _history_down, _get_visible_commands
from minicode.tui.chrome import _cached_terminal_size
from minicode.tui.tool_helpers import _summarize_tool_input, _is_file_edit_tool, _extract_path_from_tool_input, _summarize_collapsed_tool_body
from minicode.tui.tool_lifecycle import _push_transcript_entry, _update_tool_entry, _update_transcript_entry, _append_to_transcript_entry, _collapse_tool_entry, _finalize_dangling_running_tools, _get_running_tool_entries, _schedule_tool_auto_collapse

logger = logging.getLogger("minicode.input_handler")

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

    memory_mgr = getattr(args, "memory_manager", None)
    if memory_mgr is not None:
        memory_result = memory_mgr.handle_user_memory_input(input_text)
        if memory_result is not None:
            _push_transcript_entry(state, kind="user", body=input_text)
            _push_transcript_entry(state, kind="assistant", body=memory_result)
            return False

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
    local_result = try_handle_local_command(input_text, tools=args.tools, cwd=args.cwd)
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
    
    # Hook: user input
    from minicode.hooks import HookEvent, fire_hook_sync
    fire_hook_sync(HookEvent.USER_INPUT, user_input=input_text)
    
    # Prompt injection detection (input layer)
    from minicode.auto_mode import AutoModeChecker
    is_injection, injection_reason = AutoModeChecker.detect_prompt_injection(input_text)
    if is_injection:
        logger.warning("Potential prompt injection detected: %s", injection_reason)
        # Don't block, but add a system message warning
        args.messages.append({
            "role": "system",
            "content": f"[SECURITY WARNING] Potential prompt injection pattern detected: {injection_reason}. Proceed with caution and verify all outputs."
        })
    
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
                "memory_context": memory_mgr.get_relevant_context(query=input_text) if memory_mgr is not None else "",
            },
        ),
    }
    args.messages.append({"role": "user", "content": input_text})

    active_stream_entry_id = None

    def on_assistant_stream_chunk(content: str) -> None:
        nonlocal active_stream_entry_id
        if active_stream_entry_id is None:
            active_stream_entry_id = _push_transcript_entry(state, kind="assistant", body=content)
        else:
            _append_to_transcript_entry(state, active_stream_entry_id, content)
        state.transcript_scroll_offset = 0
        rerender()

    def on_assistant_message(content: str) -> None:
        nonlocal active_stream_entry_id
        # Hook: assistant output
        fire_hook_sync(HookEvent.ASSISTANT_OUTPUT, assistant_output=content[:500])
        # Output safety check (output layer)
        from minicode.auto_mode import AutoModeChecker
        is_unsafe, unsafe_reason = AutoModeChecker.classify_output_safety(content)
        if is_unsafe:
            logger.warning("Potentially unsafe output detected: %s", unsafe_reason)
        if active_stream_entry_id is not None:
            _update_transcript_entry(state, active_stream_entry_id, body=content)
            active_stream_entry_id = None
        else:
            _push_transcript_entry(state, kind="assistant", body=content)
        state.transcript_scroll_offset = 0
        rerender()

    def on_progress_message(content: str) -> None:
        nonlocal active_stream_entry_id
        if active_stream_entry_id is not None:
            _update_transcript_entry(state, active_stream_entry_id, kind="progress", body=content)
            active_stream_entry_id = None
        else:
            _push_transcript_entry(state, kind="progress", body=content)
        state.transcript_scroll_offset = 0
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
        state.transcript_scroll_offset = 0
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
                
                # 错误恢复引导
                display_output = output
                if is_error:
                    suggestions = []
                    output_lower = output.lower()
                    if "not found" in output_lower or "no such file" in output_lower:
                        suggestions.append("💡 File not found. Try /ls to see available files")
                    elif "permission" in output_lower or "denied" in output_lower:
                        suggestions.append("💡 Permission denied. Check file access rights")
                    elif "syntax" in output_lower or "error" in output_lower:
                        suggestions.append("💡 Error occurred. Review the output and fix issues")
                    
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
        state.transcript_scroll_offset = 0
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
                on_assistant_stream_chunk=on_assistant_stream_chunk,
                store=state.app_state,
                context_manager=args.context_manager,
                runtime=args.runtime,
            )
            if args.context_manager is not None:
                args.context_manager.messages = next_messages
                save_context_state(args.context_manager)
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
