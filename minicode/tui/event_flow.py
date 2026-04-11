from __future__ import annotations

import threading
from typing import Any, Callable

from minicode.tui.input_parser import KeyEvent, ParsedInputEvent, TextEvent, WheelEvent
from minicode.tui.navigation import (
    _get_visible_commands,
    _history_down,
    _history_up,
    _jump_transcript_to_edge,
    _move_pending_approval_selection,
    _scroll_pending_approval_by,
    _scroll_transcript_by,
    _toggle_pending_approval_expand,
)
from minicode.tui.state import ScreenState, TtyAppArgs


def _handle_event(
    args: TtyAppArgs,
    state: ScreenState,
    event: ParsedInputEvent,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
    handle_input_fn: Callable[[TtyAppArgs, ScreenState, Callable[[], None], str | None], bool],
) -> None:
    if isinstance(event, TextEvent) and event.ctrl and event.text == "c":
        raise SystemExit(0)

    pending = state.pending_approval
    if pending is not None:
        _handle_pending_approval_event(state, pending, event, rerender, approval_event, approval_result)
        return

    _handle_normal_mode_event(args, state, event, rerender, handle_input_fn)


def _handle_pending_approval_event(
    state: ScreenState,
    pending: Any,
    event: ParsedInputEvent,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
) -> None:
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
    pending = state.pending_approval

    if event.text == "v" and _toggle_pending_approval_expand(state):
        rerender()
        return True

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


def _handle_normal_mode_event(
    args: TtyAppArgs,
    state: ScreenState,
    event: ParsedInputEvent,
    rerender: Callable[[], None],
    handle_input_fn: Callable[[TtyAppArgs, ScreenState, Callable[[], None], str | None], bool],
) -> None:
    visible_commands = _get_visible_commands(state.input)

    if isinstance(event, KeyEvent):
        if _handle_normal_mode_key(args, state, event, visible_commands, rerender, handle_input_fn):
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
    handle_input_fn: Callable[[TtyAppArgs, ScreenState, Callable[[], None], str | None], bool],
) -> bool:
    if event.name == "return":
        _handle_normal_mode_return(args, state, visible_commands, rerender, handle_input_fn)
        return True

    if event.name == "tab" and visible_commands:
        _handle_normal_mode_tab(state, visible_commands, rerender)
        return True

    if _handle_normal_mode_navigation(state, event, rerender):
        return True

    if event.name == "pageup" and _scroll_transcript_by(args, state, 8):
        rerender()
        return True

    if event.name == "pagedown" and _scroll_transcript_by(args, state, -8):
        rerender()
        return True

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
    handle_input_fn: Callable[[TtyAppArgs, ScreenState, Callable[[], None], str | None], bool],
) -> None:
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
    if handle_input_fn(args, state, rerender, submitted):
        raise SystemExit(0)
    rerender()


def _handle_normal_mode_tab(
    state: ScreenState,
    visible_commands: list,
    rerender: Callable[[], None],
) -> None:
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
    if event.name == "backspace" and state.cursor_offset > 0:
        state.input = state.input[: state.cursor_offset - 1] + state.input[state.cursor_offset :]
        state.cursor_offset -= 1
        state.selected_slash_index = 0
        rerender()
        return True

    if event.name == "delete" and state.cursor_offset < len(state.input):
        state.input = state.input[: state.cursor_offset] + state.input[state.cursor_offset + 1 :]
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
    if event.ctrl:
        if event.text == "u":
            state.input = ""
            state.cursor_offset = 0
            state.selected_slash_index = 0
            rerender()
            return True

        if event.text == "a":
            if not state.input:
                if _jump_transcript_to_edge(args, state, "top"):
                    rerender()
                return True
            state.cursor_offset = 0
            rerender()
            return True

        if event.text == "e":
            if not state.input:
                if _jump_transcript_to_edge(args, state, "bottom"):
                    rerender()
                return True
            state.cursor_offset = len(state.input)
            rerender()
            return True

        if event.text == "p":
            if _history_up(state):
                rerender()
            return True

        if event.text == "n":
            if _history_down(state):
                rerender()
            return True

        return False

    if not event.ctrl and event.text:
        state.input = state.input[: state.cursor_offset] + event.text + state.input[state.cursor_offset :]
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
    delta = 3 if event.direction == "up" else -3
    if _scroll_transcript_by(args, state, delta):
        rerender()
        return True
    return False


def _handle_feedback_mode_event(
    state: ScreenState,
    event: ParsedInputEvent,
    rerender: Callable[[], None],
    approval_event: threading.Event,
    approval_result: dict[str, Any],
) -> None:
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
