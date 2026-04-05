from __future__ import annotations

from .chrome import (
    RESET, DIM, CYAN, GREEN, YELLOW, BOLD, REVERSE, ITALIC,
    BRIGHT_CYAN, BRIGHT_GREEN, ACCENT, ACCENT2, SUBTLE,
    HIGHLIGHT_BG, ICON_PROMPT, ICON_DOT, ICON_ARROW,
)


def render_input_prompt(current_input: str, cursor_offset: int) -> str:
    offset = max(0, min(cursor_offset, len(current_input)))
    before = current_input[:offset]
    current = current_input[offset] if offset < len(current_input) else " "
    after = current_input[offset + 1 :]

    placeholder = (
        "" if current_input else f"{ITALIC} Type a message or /help for commands{RESET}"
    )

    # Hint bar with subtle key badges
    key_enter = f"{SUBTLE}[{RESET}{DIM}Enter{RESET}{SUBTLE}]{RESET} {SUBTLE}send{RESET}"
    key_help = f"{SUBTLE}[{RESET}{DIM}/help{RESET}{SUBTLE}]{RESET} {SUBTLE}cmds{RESET}"
    key_esc = f"{SUBTLE}[{RESET}{DIM}Esc{RESET}{SUBTLE}]{RESET} {SUBTLE}clear{RESET}"
    key_exit = f"{SUBTLE}[{RESET}{DIM}^C{RESET}{SUBTLE}]{RESET} {SUBTLE}exit{RESET}"

    line1 = f"  {key_enter}  {key_help}  {key_esc}  {key_exit}"
    line2 = ""
    # Prompt line with colored chevron
    prompt_icon = f"{ACCENT}{ICON_PROMPT}{ICON_PROMPT}{RESET}"
    line3 = f" {prompt_icon} {before}{HIGHLIGHT_BG}{BRIGHT_GREEN}{current}{RESET}{after}{DIM}{placeholder}{RESET}"

    return "\n".join([line1, line2, line3])
