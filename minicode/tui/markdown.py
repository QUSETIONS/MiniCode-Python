from __future__ import annotations
import re

RESET = "\u001b[0m"
DIM = "\u001b[2m"
CYAN = "\u001b[36m"
YELLOW = "\u001b[33m"
MAGENTA = "\u001b[35m"
BOLD = "\u001b[1m"
ITALIC = "\u001b[3m"
UNDERLINE = "\u001b[4m"
# Extended colors for markdown rendering
BRIGHT_CYAN = "\u001b[96m"
BRIGHT_YELLOW = "\u001b[93m"
SUBTLE = "\u001b[38;5;243m"
CODE_BG = "\u001b[48;5;236m"    # dark bg for code
CODE_FG = "\u001b[38;5;215m"    # warm amber for inline code
QUOTE_BAR = "\u001b[38;5;243m"  # subtle gray for blockquote
HEADING_ACCENT = "\u001b[38;5;39m"  # bright blue for headings

# Pre-compiled regexes for markdown parsing
_RE_TABLE_SEP = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")
_RE_TABLE_ROW = re.compile(r"^\|.*\|$")
_RE_LIST_ITEM = re.compile(r"^(\s*)[-*]\s+")
_RE_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_RE_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_RE_NUMBERED_LIST = re.compile(r"^(\s*)\d+\.\s+")

def render_markdownish(input_text: str) -> str:
    lines = input_text.split("\n")
    in_code_block = False
    result_lines: list[str] = []

    for line in lines:
        formatted = line

        if line.startswith("```"):
            in_code_block = not in_code_block
            lang = line[3:].strip()
            if in_code_block and lang:
                result_lines.append(f"{CODE_BG}{SUBTLE} {lang} {RESET}")
            else:
                result_lines.append(f"{SUBTLE}{'─' * 4}{RESET}")
            continue

        if in_code_block:
            result_lines.append(f"{CODE_BG}{DIM} {line} {RESET}")
            continue

        trimmed_line = line.strip()

        # Horizontal rule
        if trimmed_line in ("---", "***", "___"):
            result_lines.append(f"{SUBTLE}{'─' * 20}{RESET}")
            continue

        # Table separator logic
        if _RE_TABLE_SEP.match(trimmed_line):
            result_lines.append(f"{SUBTLE}{trimmed_line.replace('|', ' ').strip()}{RESET}")
            continue

        # Table data row logic
        if _RE_TABLE_ROW.match(trimmed_line):
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            result_lines.append(f" {SUBTLE}│{RESET} ".join(cells))
            continue

        # Headings with visual accent
        if line.startswith("### "):
            result_lines.append(f"{HEADING_ACCENT}{BOLD}  {line[4:]}{RESET}")
            continue
        if line.startswith("## "):
            result_lines.append(f"{HEADING_ACCENT}{BOLD}{UNDERLINE} {line[3:]}{RESET}")
            continue
        if line.startswith("# "):
            result_lines.append(f"{BRIGHT_CYAN}{BOLD}{UNDERLINE} {line[2:]}{RESET}")
            continue

        # Blockquote with visual bar
        if line.startswith("> "):
            result_lines.append(f"{QUOTE_BAR}▎{RESET} {ITALIC}{DIM}{line[2:]}{RESET}")
            continue

        # Unordered list items with colored bullet
        m = _RE_LIST_ITEM.match(line)
        if m:
            indent = m.group(1)
            rest = line[m.end():]
            formatted = f"{indent}{BRIGHT_YELLOW}•{RESET} {rest}"
        else:
            # Numbered list items with colored number
            m2 = _RE_NUMBERED_LIST.match(line)
            if m2:
                indent = m2.group(1)
                rest = line[m2.end():]
                num = line[len(indent):m2.end()].strip()
                formatted = f"{indent}{BRIGHT_CYAN}{num}{RESET} {rest}"

        # Inline formatting
        formatted = _RE_INLINE_CODE.sub(
            rf"{CODE_BG}{CODE_FG}\1{RESET}", formatted
        )
        formatted = _RE_BOLD.sub(rf"{BOLD}\1{RESET}", formatted)
        formatted = _RE_ITALIC.sub(rf"{ITALIC}\1{RESET}", formatted)

        result_lines.append(formatted)

    return "\n".join(result_lines)
