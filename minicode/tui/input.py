from __future__ import annotations

RESET = "\u001b[0m"
DIM = "\u001b[2m"
CYAN = "\u001b[36m"
GREEN = "\u001b[32m"
YELLOW = "\u001b[33m"
BOLD = "\u001b[1m"
REVERSE = "\u001b[7m"


def render_input_prompt(current_input: str, cursor_offset: int) -> str:
    offset = max(0, min(cursor_offset, len(current_input)))
    before = current_input[:offset]
    current = current_input[offset] if offset < len(current_input) else " "
    after = current_input[offset + 1 :]

    placeholder = (
        "" if current_input else " Ask for code, files, tasks, or MCP tools"
    )

    line1 = f"{YELLOW}{BOLD}prompt{RESET} {DIM}Enter send | /help commands | Esc clear | Ctrl+C exit{RESET}"
    line2 = ""
    line3 = f"{GREEN}{BOLD}mini-code>{RESET} {before}{REVERSE}{current}{RESET}{after}{DIM}{placeholder}{RESET}"

    return "\n".join([line1, line2, line3])
