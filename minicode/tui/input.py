from __future__ import annotations

from .chrome import (
    RESET, DIM, BOLD, ITALIC, HIGHLIGHT_BG,
    BRIGHT_GREEN, SUBTLE,
    ICON_PROMPT, ICON_DOT,
)
from .theme import theme


def render_input_prompt(current_input: str, cursor_offset: int, compact: bool = False) -> str:
    """Render the input prompt line.

    Format matches the Rust version:
      mini-code> <input with cursor>

    When compact=True (small terminal), the hint bar is hidden to save lines.
    """
    t = theme()
    offset = max(0, min(cursor_offset, len(current_input)))
    before = current_input[:offset]
    current = current_input[offset] if offset < len(current_input) else " "
    after = current_input[offset + 1:]

    placeholder = (
        "" if current_input
        else f"{ITALIC} Type a message or /help for commands{RESET}"
    )

    # Prompt: "mini-code> " prefix (matches Rust render_screen)
    prefix = f"{t.input}{BOLD}mini-code>{RESET} "
    input_line = f" {prefix}{before}{HIGHLIGHT_BG}{BRIGHT_GREEN}{current}{RESET}{after}{DIM}{placeholder}{RESET}"

    if compact:
        return input_line

    # Hint bar
    key_enter = f"{t.subtle}[{RESET}{DIM}Enter{RESET}{t.subtle}]{RESET} {t.subtle}send{RESET}"
    key_help = f"{t.subtle}[{RESET}{DIM}/help{RESET}{t.subtle}]{RESET} {t.subtle}cmds{RESET}"
    key_esc = f"{t.subtle}[{RESET}{DIM}Esc{RESET}{t.subtle}]{RESET} {t.subtle}clear{RESET}"
    key_exit = f"{t.subtle}[{RESET}{DIM}^C{RESET}{t.subtle}]{RESET} {t.subtle}exit{RESET}"

    line1 = f"  {key_enter}  {key_help}  {key_esc}  {key_exit}"
    line2 = ""

    return "\n".join([line1, line2, input_line])
