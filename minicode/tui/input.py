from __future__ import annotations

import sys
from minicode.tui.chrome import string_display_width

RESET = "\u001b[0m"
DIM = "\u001b[2m"
CYAN = "\u001b[36m"
GREEN = "\u001b[32m"
YELLOW = "\u001b[33m"
BOLD = "\u001b[1m"
REVERSE = "\u001b[7m"

# Use a colored background for the cursor to ensure visibility over CJK characters
# Light Blue Background
CURSOR_BG = "\u001b[48;5;39m"
# Use full-width space for CJK cursor alignment at end of line
FULL_WIDTH_SPACE = "\u3000"


def render_input_prompt(current_input: str, cursor_offset: int) -> str:
    offset = max(0, min(cursor_offset, len(current_input)))
    before = current_input[:offset]

    if offset < len(current_input):
        current = current_input[offset]
        after = current_input[offset + 1:]
    else:
        # Use full-width space for CJK cursor at end
        current = FULL_WIDTH_SPACE
        after = ""

    # Use display width for placeholder logic
    input_display_width = string_display_width(current_input)
    placeholder = (
        "" if current_input else " Ask for code, files, tasks, or MCP tools"
    )

    line1 = f"{YELLOW}{BOLD}prompt{RESET} {DIM}Enter send | /help commands | Esc clear | Ctrl+C exit{RESET}"
    line2 = ""
    # Use CURSOR_BG for better visibility on CJK
    line3 = f"{GREEN}{BOLD}mini-code>{RESET} {before}{CURSOR_BG}{current}{RESET}{after}{DIM}{placeholder}{RESET}"

    return "\n".join([line1, line2, line3])
