from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# ANSI color constants
RESET = "\u001b[0m"
DIM = "\u001b[2m"
CYAN = "\u001b[36m"
GREEN = "\u001b[32m"
YELLOW = "\u001b[33m"
RED = "\u001b[31m"
BLUE = "\u001b[34m"
MAGENTA = "\u001b[35m"
BOLD = "\u001b[1m"
REVERSE = "\u001b[7m"
BRIGHT_GREEN = "\u001b[92m"
BRIGHT_RED = "\u001b[91m"
BRIGHT_CYAN = "\u001b[96m"
BRIGHT_YELLOW = "\u001b[93m"
BORDER = "\u001b[38;5;31m"


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return re.sub(r"\u001b\[[0-9;]*m", "", text)


def char_display_width(char: str) -> int:
    """CJK/Emoji width detection (return 2 for wide chars, 1 otherwise)."""
    if not char:
        return 0
    code = ord(char)
    if (
        0x1100 <= code <= 0x115F
        or code == 0x2329
        or code == 0x232A
        or (0x2E80 <= code <= 0xA4CF and code != 0x303F)
        or 0xAC00 <= code <= 0xD7A3
        or 0xF900 <= code <= 0xFAFF
        or 0xFE10 <= code <= 0xFE19
        or 0xFE30 <= code <= 0xFE6F
        or 0xFF00 <= code <= 0xFF60
        or 0xFFE0 <= code <= 0xFFE6
        or 0x1F300 <= code <= 0x1FAF6
        or 0x20000 <= code <= 0x3FFFD
    ):
        return 2
    return 1


def string_display_width(text: str) -> int:
    """Sum of char_display_width for stripped text."""
    return sum(char_display_width(c) for c in strip_ansi(text))


def truncate_plain(text: str, width: int) -> str:
    """Truncate with '...' suffix, CJK aware. Preserves ANSI codes."""
    if string_display_width(text) <= width:
        return text

    limit = max(0, width - 3)
    res = ""
    w = 0
    i = 0
    ansi_regex = re.compile(r"\u001b\[[0-9;]*m")
    while i < len(text):
        match = ansi_regex.match(text, i)
        if match:
            res += match.group()
            i = match.end()
            continue

        char = text[i]
        cw = char_display_width(char)
        if w + cw > limit:
            res += "..."
            # Keep any trailing ANSI codes to avoid leaking style
            i += 1
            while i < len(text):
                m = ansi_regex.match(text, i)
                if m:
                    res += m.group()
                    i = m.end()
                else:
                    i += 1
            return res

        res += char
        w += cw
        i += 1
    return res


def pad_plain(text: str, width: int) -> str:
    """Right-pad to width, CJK aware."""
    display_w = string_display_width(text)
    return text + (" " * max(0, width - display_w))


def truncate_path_middle(path: str, width: int) -> str:
    """Truncate middle with '...' keeping both ends."""
    if string_display_width(path) <= width:
        return path
    if width <= 5:
        return truncate_plain(path, width)

    half = (width - 3) // 2
    start_chars = ""
    start_w = 0
    for c in path:
        cw = char_display_width(c)
        if start_w + cw > half:
            break
        start_chars += c
        start_w += cw

    end_chars = ""
    end_w = 0
    for c in reversed(path):
        cw = char_display_width(c)
        if end_w + cw > (width - 3 - start_w):
            break
        end_chars = c + end_chars
        end_w += cw

    return start_chars + "..." + end_chars


def color_badge(label: str, value: str, color: str) -> str:
    """E.g. [provider] custom with color."""
    return f"{color}[{label}]{RESET} {BOLD}{value}{RESET}"


def border_line(kind: str, width: int) -> str:
    """Unicode box drawing: ╭─╮ or ╰─╯."""
    if kind == "top":
        return f"{BORDER}╭{'─' * (width - 2)}╮{RESET}"
    elif kind == "bottom":
        return f"{BORDER}╰{'─' * (width - 2)}╯{RESET}"
    else:
        return f"{BORDER}├{'─' * (width - 2)}┤{RESET}"


def panel_row(left: str, width: int, right: str | None = None) -> str:
    """│ left ... right │"""
    inner_width = width - 4
    if right:
        l_w = string_display_width(left)
        r_w = string_display_width(right)
        gap = inner_width - l_w - r_w
        if gap < 1:
            left = truncate_plain(left, inner_width - r_w - 1)
            gap = 1
        return f"{BORDER}│{RESET} {left}{' ' * gap}{right} {BORDER}│{RESET}"
    else:
        return f"{BORDER}│{RESET} {pad_plain(left, inner_width)} {BORDER}│{RESET}"


def empty_panel_row(width: int) -> str:
    """│          │"""
    return panel_row("", width)


def wrap_panel_body_line(line: str, width: int) -> list[str]:
    """Wrap long lines for panel, CJK aware."""
    inner_width = width - 6  # Increased margin to prevent wrapping/shift
    if string_display_width(line) <= inner_width:
        return [line]

    lines = []
    current_line = ""
    current_w = 0
    i = 0
    ansi_regex = re.compile(r"\u001b\[[0-9;]*m")
    while i < len(line):
        match = ansi_regex.match(line, i)
        if match:
            current_line += match.group()
            i = match.end()
            continue
        char = line[i]
        cw = char_display_width(char)
        if current_w + cw > inner_width:
            lines.append(current_line)
            current_line = ""
            current_w = 0
            if char == " ":
                i += 1
                continue
        current_line += char
        current_w += cw
        i += 1
    if current_line:
        lines.append(current_line)
    return lines


def render_panel(title: str, body: str, right_title: str | None = None, min_body_lines: int = 0) -> str:
    """Full panel with Unicode borders."""
    try:
        width = os.get_terminal_size().columns
    except (AttributeError, ValueError, OSError):
        width = 100
    if width < 40:
        width = 40

    res = [border_line("top", width)]
    res.append(panel_row(f"{CYAN}{BOLD}{title}{RESET}", width, f"{DIM}{right_title}{RESET}" if right_title else None))
    res.append(empty_panel_row(width))

    body_lines = body.splitlines() if body else []
    wrapped_lines = []
    for bl in body_lines:
        wrapped_lines.extend(wrap_panel_body_line(bl, width))

    while len(wrapped_lines) < min_body_lines:
        wrapped_lines.append("")

    for wl in wrapped_lines:
        res.append(panel_row(wl, width))
    res.append(border_line("bottom", width))
    return "\n".join(res)


def render_banner(runtime: dict | None, cwd: str, permission_summary: list[str], session: dict[str, int]) -> str:
    """Render banner with color_badge and truncate_path_middle."""
    model = runtime.get("model", "not-configured") if runtime else "not-configured"
    provider = "offline"
    if runtime and runtime.get("baseUrl"):
        provider = runtime["baseUrl"].replace("https://", "").replace("http://", "").split("/")[0]

    cwd_path = Path(cwd)
    folder_name = cwd_path.name or str(cwd_path)

    try:
        width = os.get_terminal_size().columns
    except (AttributeError, ValueError, OSError):
        width = 100

    body = "\n".join(
        [
            f"{DIM}Terminal coding assistant for MiniCode.{RESET}",
            "",
            f"{BLUE}{BOLD}{folder_name}{RESET} {DIM}{truncate_path_middle(str(cwd), max(20, width - 10 - string_display_width(folder_name)))}{RESET}",
            f"{color_badge('provider', provider, CYAN)}  {color_badge('model', model, GREEN)}  [msgs] {session.get('messageCount', 0)}  [events] {session.get('transcriptCount', 0)}  [skills] {session.get('skillCount', 0)}  [mcp] {session.get('mcpCount', 0)}",
            f"{DIM}{' | '.join(permission_summary)}{RESET}",
        ]
    )
    return render_panel("MiniCode", body, right_title=provider)


def render_status_line(status: str | None) -> str:
    """Render the status line with formatting."""
    return f"{YELLOW}{BOLD}{status}{RESET}" if status else f"{DIM}Ready{RESET}"


def render_tool_panel(
    active_tool: str | None, recent_tools: list[dict[str, str]], background_tasks: list[dict[str, Any]] = []
) -> str:
    """Include background task support."""
    parts = []
    if active_tool:
        parts.append(f"{YELLOW}running:{RESET} {active_tool}")
    for task in background_tasks:
        if task.get("status") == "running":
            parts.append(f"{BRIGHT_CYAN}bg:{RESET} {task.get('label', 'task')}")
    if not parts and not recent_tools:
        parts.append(f"{DIM}none{RESET}")
    else:
        for tool in recent_tools[-3:]:
            style = GREEN if tool.get("status") == "success" else RED
            parts.append(f"{style}{tool.get('name', 'tool')}{RESET}")
    return f"{DIM}tools{RESET}  " + "  ".join(parts)


def render_footer_bar(
    status: str | None, tools_enabled: bool, skills_enabled: bool, background_tasks: list[dict[str, Any]] = []
) -> str:
    """Single line with gap."""
    try:
        width = os.get_terminal_size().columns
    except (AttributeError, ValueError, OSError):
        width = 100
    left = render_status_line(status)
    bg_info = f" {BRIGHT_CYAN}({len(background_tasks)} bg){RESET} |" if background_tasks else ""
    right = (
        f"{bg_info} {DIM}tools{RESET} {'on' if tools_enabled else 'off'} | {DIM}skills{RESET} {'on' if skills_enabled else 'off'}"
    )
    gap = max(1, width - string_display_width(left) - string_display_width(right))
    return f"{left}{' ' * gap}{right}"


def render_slash_menu(commands: list[Any], selected_index: int) -> str:
    """With REVERSE highlight and padded usage."""
    if not commands:
        return f"{DIM}no commands{RESET}"
    try:
        width = os.get_terminal_size().columns
    except (AttributeError, ValueError, OSError):
        width = 100
    rows = [f"{DIM}commands{RESET}"]
    for i, cmd in enumerate(commands):
        usage = pad_plain(getattr(cmd, "usage", str(cmd)), 12)
        desc = getattr(cmd, "description", "")
        line = f"{REVERSE} {usage} {RESET} {desc}" if i == selected_index else f" {usage} {DIM}{desc}{RESET}"
        rows.append(truncate_plain(line, width))
    return "\n".join(rows)


def classify_diff_line(line: str) -> str:
    """Returns 'meta'|'add'|'remove'|'context'."""
    if line.startswith(("+++", "---", "@@")):
        return "meta"
    if line.startswith("+"):
        return "add"
    if line.startswith("-"):
        return "remove"
    return "context"


def compute_changed_range(removed: str, added: str) -> tuple[int, int] | None:
    """Word-level emphasis ranges."""
    if not removed or not added:
        return None
    p = 0
    while p < len(removed) and p < len(added) and removed[p] == added[p]:
        p += 1
    s = 0
    while s < (len(removed) - p) and s < (len(added) - p) and removed[-(s + 1)] == added[-(s + 1)]:
        s += 1
    return (p, len(added) - s) if p < (len(added) - s) else None


def apply_word_emphasis(content: str, color: str, emphasis_range: tuple[int, int] | None = None) -> str:
    """Apply color and word-level emphasis."""
    if not emphasis_range:
        return f"{color}{content}{RESET}"
    s, e = emphasis_range
    return f"{color}{content[:s]}{BOLD}{REVERSE}{content[s:e]}{RESET}{color}{content[e:]}{RESET}"


def colorize_unified_diff_block(block: str) -> str:
    """Full diff with word-level highlighting and look-ahead pairing."""
    lines = block.splitlines()
    res: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(("--- ", "+++ ", "@@ ")):
            res.append(f"{CYAN}{line}{RESET}")
            i += 1
            continue
        # Collect consecutive removal/addition blocks for pairing
        if line.startswith("-"):
            removals: list[str] = []
            while i < len(lines) and lines[i].startswith("-"):
                removals.append(lines[i][1:])
                i += 1
            additions: list[str] = []
            while i < len(lines) and lines[i].startswith("+"):
                additions.append(lines[i][1:])
                i += 1
            # Pair removals with additions for word-level emphasis
            paired = min(len(removals), len(additions))
            for j in range(paired):
                emphasis = compute_changed_range(removals[j], additions[j])
                res.append("-" + apply_word_emphasis(removals[j], RED, emphasis))
                res.append("+" + apply_word_emphasis(additions[j], GREEN, emphasis))
            # Remaining unpaired removals
            for j in range(paired, len(removals)):
                res.append(f"{RED}-{removals[j]}{RESET}")
            # Remaining unpaired additions
            for j in range(paired, len(additions)):
                res.append(f"{GREEN}+{additions[j]}{RESET}")
            continue
        if line.startswith("+"):
            res.append(f"{GREEN}{line}{RESET}")
            i += 1
        else:
            res.append(f"{DIM}{line}{RESET}")
            i += 1
    return "\n".join(res)


def _looks_like_diff_block(detail: str) -> bool:
    """Check if a detail string looks like a unified diff block."""
    return (
        "\n" in detail
        and ("--- a/" in detail or "+++ b/" in detail or "@@ " in detail)
    )


def colorize_edit_permission_details(details: list[str]) -> list[str]:
    """Colorize diff blocks in permission details."""
    return [
        colorize_unified_diff_block(d) if _looks_like_diff_block(d) else d
        for d in details
    ]


def get_permission_prompt_max_scroll_offset(request: dict[str, Any], expanded: bool = False) -> int:
    """Calculate max scroll offset for permission details."""
    if not expanded:
        return 0
    flat = flatten_detail_lines(request.get("details", []))
    try:
        rows = os.get_terminal_size().lines
    except (AttributeError, ValueError, OSError):
        rows = 40
    max_visible = max(4, rows - 20)
    return max(0, len(flat) - max_visible)


def flatten_detail_lines(details: list[str]) -> list[str]:
    """Flatten a list of detail strings (which may contain newlines) into individual lines."""
    result: list[str] = []
    for detail in details:
        result.extend(detail.split("\n"))
    return result


def slice_visible_details(flat_lines: list[str], scroll_offset: int, max_visible: int | None = None) -> tuple[list[str], int]:
    """Return the visible slice of detail lines and total count.
    
    If max_visible is None, uses terminal height minus chrome to calculate.
    """
    if max_visible is None:
        try:
            rows = os.get_terminal_size().lines
        except (AttributeError, ValueError, OSError):
            rows = 40
        max_visible = max(4, rows - 20)
    total = len(flat_lines)
    offset = max(0, min(scroll_offset, max(0, total - max_visible)))
    return flat_lines[offset:offset + max_visible], total


def render_permission_prompt(
    request: dict[str, Any],
    expanded: bool = False,
    scroll_offset: int = 0,
    selected_choice_index: int = 0,
    feedback_mode: bool = False,
    feedback_input: str = "",
) -> str:
    """FULL interactive permission prompt."""
    lines = []
    if feedback_mode:
        lines.extend(
            [
                f"{BRIGHT_YELLOW}Provide reason for rejection:{RESET}",
                f"> {feedback_input}_",
                "",
                f"{DIM}Press Enter to send, Esc to cancel.{RESET}",
            ]
        )
    else:
        lines.extend([request.get("summary", "Permission Request"), ""])
        details = request.get("details", [])
        if details:
            flat = flatten_detail_lines(details)
            if not expanded:
                lines.append(f"{DIM}[ {len(flat)} lines of details hidden - press 'v' to expand | Ctrl+O toggle ]{RESET}")
            else:
                colorized = colorize_edit_permission_details(flat)
                visible, total = slice_visible_details(colorized, scroll_offset)
                lines.extend(visible)
                if total > len(visible):
                    lines.append(f"{DIM}--- scroll {scroll_offset+1}/{total} (Wheel/PgUp/PgDn) ---{RESET}")
            lines.append("")
        for i, choice in enumerate(request.get("choices", [])):
            txt = f" {choice.get('label', '')} ({choice.get('key', '')}) "
            lines.append(f"{REVERSE} > {txt}{RESET}" if i == selected_choice_index else f"   {txt}")
    return render_panel("Action Required", "\n".join(lines), right_title="Permission")
