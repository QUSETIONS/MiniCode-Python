from __future__ import annotations
import re

RESET = "\u001b[0m"
DIM = "\u001b[2m"
CYAN = "\u001b[36m"
YELLOW = "\u001b[33m"
MAGENTA = "\u001b[35m"
BOLD = "\u001b[1m"

def render_markdownish(input_text: str) -> str:
    lines = input_text.split("\n")
    in_code_block = False
    result_lines = []

    for line in lines:
        formatted = line

        if line.startswith("```"):
            in_code_block = not in_code_block
            result_lines.append(f"{DIM}{line}{RESET}")
            continue

        if in_code_block:
            result_lines.append(f"{DIM}{line}{RESET}")
            continue

        trimmed_line = line.strip()

        # Table separator logic
        if re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", trimmed_line):
            result_lines.append(f"{DIM}{trimmed_line.replace('|', ' ').strip()}{RESET}")
            continue

        # Table data row logic
        if re.match(r"^\|.*\|$", trimmed_line):
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            result_lines.append(f" {DIM}|{RESET} ".join(cells))
            continue

        # Headings
        if line.startswith("### "):
            result_lines.append(f"{CYAN}{BOLD}{line[4:]}{RESET}")
            continue
        if line.startswith("## "):
            result_lines.append(f"{CYAN}{BOLD}{line[3:]}{RESET}")
            continue
        if line.startswith("# "):
            result_lines.append(f"{CYAN}{BOLD}{line[2:]}{RESET}")
            continue

        # Blockquote
        if line.startswith("> "):
            result_lines.append(f"{DIM}{line}{RESET}")
            continue

        # List items
        if re.match(r"^\s*[-*]\s+", line):
            formatted = re.sub(r"^\s*[-*]\s+", f"{YELLOW}•{RESET} ", line)

        # Inline formatting
        formatted = re.sub(r"`([^`]+)`", rf"{MAGENTA}\1{RESET}", formatted)
        formatted = re.sub(r"\*\*([^*]+)\*\*", rf"{BOLD}\1{RESET}", formatted)

        result_lines.append(formatted)

    return "\n".join(result_lines)
