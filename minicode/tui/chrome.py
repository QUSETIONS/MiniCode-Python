from __future__ import annotations

import os
import re
import time
from functools import lru_cache
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
ITALIC = "\u001b[3m"
UNDERLINE = "\u001b[4m"
BRIGHT_GREEN = "\u001b[92m"
BRIGHT_RED = "\u001b[91m"
BRIGHT_CYAN = "\u001b[96m"
BRIGHT_YELLOW = "\u001b[93m"
BRIGHT_BLUE = "\u001b[94m"
BRIGHT_MAGENTA = "\u001b[95m"
BRIGHT_WHITE = "\u001b[97m"
# Extended 256-color palette for richer visuals
BORDER = "\u001b[38;5;39m"       # brighter blue border
BORDER_DIM = "\u001b[38;5;24m"   # subtle dark blue for secondary borders
ACCENT = "\u001b[38;5;214m"      # warm orange accent
ACCENT2 = "\u001b[38;5;141m"     # soft purple accent
SUBTLE = "\u001b[38;5;243m"      # gray for subtle text
HIGHLIGHT_BG = "\u001b[48;5;236m"  # dark bg highlight for selections

# ---------------------------------------------------------------------------
# Unicode decorative characters
# ---------------------------------------------------------------------------
ICON_MINICODE = "\u2726"   # ✦
ICON_USER = "\u25B6"       # ▶
ICON_ASSISTANT = "\u2734"  # ✴
ICON_TOOL = "\u2699"       # ⚙
ICON_PROGRESS = "\u25CF"   # ●
ICON_SUCCESS = "\u2714"    # ✔
ICON_ERROR = "\u2718"      # ✘
ICON_RUNNING = "\u25CB"    # ○
ICON_FOLDER = "\u25A0"     # ■
ICON_MODEL = "\u25C6"      # ◆
ICON_PROVIDER = "\u25C8"   # ◈
ICON_PROMPT = "\u276F"     # ❯
ICON_SKILL = "\u2605"      # ★
ICON_MSG = "\u25AC"        # ▬
ICON_EVENT = "\u25AA"      # ▪
ICON_MCP = "\u25C9"        # ◉
ICON_BG = "\u25D0"         # ◐
ICON_LOCK = "\u25A3"       # ▣
ICON_DIVIDER = "\u2500"    # ─
ICON_DOT = "\u00B7"        # ·
ICON_ARROW = "\u25B8"      # ▸

# Pre-compiled regex for ANSI stripping (avoid re-compiling every call)
_ANSI_RE = re.compile(r"\u001b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# Cached terminal size (avoids repeated os.get_terminal_size syscalls)
# ---------------------------------------------------------------------------
_ts_cache: tuple[int, int] | None = None
_ts_cache_time: float = 0.0
_TS_TTL: float = 0.5


def _cached_terminal_size() -> tuple[int, int]:
    """Return (columns, rows) with caching."""
    global _ts_cache, _ts_cache_time
    now = time.monotonic()
    if _ts_cache is None or (now - _ts_cache_time) > _TS_TTL:
        try:
            ts = os.get_terminal_size()
            _ts_cache = (ts.columns, ts.lines)
        except (AttributeError, ValueError, OSError):
            _ts_cache = (100, 40)
        _ts_cache_time = now
    return _ts_cache


def invalidate_terminal_size_cache() -> None:
    """Force the next ``_cached_terminal_size`` call to re-query the OS.

    Called from the SIGWINCH handler on Unix so that a terminal resize
    is picked up immediately instead of waiting for the TTL to expire.
    """
    global _ts_cache
    _ts_cache = None


# ---------------------------------------------------------------------------
# Width computation — optimized hot path
# ---------------------------------------------------------------------------

# Build a fast lookup set for wide character ranges
def _build_wide_char_set() -> frozenset[int]:
    """Pre-compute the set of codepoint ranges that are double-width."""
    # We use ranges for lookup instead of a set of all codepoints
    return frozenset()  # placeholder — we use range checks below

# Optimized: inline the range checks but skip the per-char function call overhead
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


@lru_cache(maxsize=2048)
def _stripped_display_width(stripped: str) -> int:
    """Width of a string that is already ANSI-stripped. Cached for hot paths."""
    width = 0
    for c in stripped:
        code = ord(c)
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
            width += 2
        else:
            width += 1
    return width


def string_display_width(text: str) -> int:
    """Sum of char_display_width for stripped text. Uses LRU cache on stripped content."""
    stripped = _ANSI_RE.sub("", text)
    return _stripped_display_width(stripped)


def truncate_plain(text: str, width: int) -> str:
    """Truncate with '...' suffix, CJK aware. Preserves ANSI codes."""
    if string_display_width(text) <= width:
        return text

    limit = max(0, width - 3)
    res = ""
    w = 0
    i = 0
    while i < len(text):
        match = _ANSI_RE.match(text, i)
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
                m = _ANSI_RE.match(text, i)
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


def color_badge(label: str, value: str, color: str, icon: str = "") -> str:
    """Render a styled badge: icon [label] value."""
    icon_part = f"{color}{icon} " if icon else ""
    return f"{icon_part}{color}{DIM}[{label}]{RESET} {BOLD}{value}{RESET}"


def border_line(kind: str, width: int, accent: bool = False) -> str:
    """Unicode box drawing: ╭─╮ or ╰─╯ with optional accent color."""
    color = ACCENT if accent else BORDER
    if kind == "top":
        return f"{color}╭{'─' * (width - 2)}╮{RESET}"
    elif kind == "bottom":
        return f"{color}╰{'─' * (width - 2)}╯{RESET}"
    elif kind == "divider":
        return f"{color}├{'─' * (width - 2)}┤{RESET}"
    else:
        return f"{color}├{'─' * (width - 2)}┤{RESET}"


def panel_row(left: str, width: int, right: str | None = None, border_color: str = "") -> str:
    """│ left ... right │"""
    bc = border_color or BORDER
    inner_width = width - 4
    if right:
        l_w = string_display_width(left)
        r_w = string_display_width(right)
        gap = inner_width - l_w - r_w
        if gap < 1:
            left = truncate_plain(left, inner_width - r_w - 1)
            gap = 1
        return f"{bc}│{RESET} {left}{' ' * gap}{right} {bc}│{RESET}"
    else:
        return f"{bc}│{RESET} {pad_plain(left, inner_width)} {bc}│{RESET}"


def empty_panel_row(width: int) -> str:
    """│          │"""
    return panel_row("", width)


def wrap_panel_body_line(line: str, width: int) -> list[str]:
    """Wrap long lines for panel, CJK aware. Uses finditer for ANSI positions."""
    inner_width = width - 4
    if string_display_width(line) <= inner_width:
        return [line]

    # Pre-compute ANSI escape positions so we don't regex-match per character
    ansi_spans: list[tuple[int, int]] = []
    for m in _ANSI_RE.finditer(line):
        ansi_spans.append((m.start(), m.end()))

    lines: list[str] = []
    current_line = ""
    current_w = 0
    i = 0
    span_idx = 0  # pointer into ansi_spans

    while i < len(line):
        # Check if current position is the start of a known ANSI escape
        if span_idx < len(ansi_spans) and i == ansi_spans[span_idx][0]:
            end = ansi_spans[span_idx][1]
            current_line += line[i:end]
            i = end
            span_idx += 1
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


# Panel-title icon mapping for automatic icon decoration
_PANEL_ICONS: dict[str, str] = {
    "minicode": ICON_MINICODE,
    "session feed": ICON_MSG,
    "prompt": ICON_PROMPT,
    "activity": ICON_TOOL,
    "action required": ICON_LOCK,
}


def render_panel(title: str, body: str, right_title: str | None = None, min_body_lines: int = 0) -> str:
    """Full panel with Unicode borders and decorative title icons."""
    width, _ = _cached_terminal_size()
    if width < 40:
        width = 40

    # Pick icon for this panel title
    icon = _PANEL_ICONS.get(title.lower(), "")
    icon_str = f"{ACCENT}{icon} {RESET}" if icon else ""

    # Top border
    res = [border_line("top", width)]
    # Title row with icon
    title_display = f"{icon_str}{BRIGHT_CYAN}{BOLD}{title}{RESET}"
    right_display = f"{SUBTLE}{right_title}{RESET}" if right_title else None
    res.append(panel_row(title_display, width, right_display))
    # Thin divider under title
    inner = width - 4
    divider_line = f"{BORDER_DIM}{'╌' * inner}{RESET}"
    res.append(panel_row(divider_line, width))

    body_lines = body.splitlines() if body else []
    wrapped_lines: list[str] = []
    for bl in body_lines:
        wrapped_lines.extend(wrap_panel_body_line(bl, width))

    while len(wrapped_lines) < min_body_lines:
        wrapped_lines.append("")

    for wl in wrapped_lines:
        res.append(panel_row(wl, width))
    res.append(border_line("bottom", width))
    return "\n".join(res)


def render_banner(runtime: dict | None, cwd: str, permission_summary: list[str], session: dict[str, int]) -> str:
    """Render banner with rich visual badges and icons."""
    model = runtime.get("model", "not-configured") if runtime else "not-configured"
    provider = "offline"
    if runtime and runtime.get("baseUrl"):
        provider = runtime["baseUrl"].replace("https://", "").replace("http://", "").split("/")[0]

    cwd_path = Path(cwd)
    folder_name = cwd_path.name or str(cwd_path)

    width, _ = _cached_terminal_size()

    # Tagline with subtle styling
    tagline = f"{SUBTLE}{ITALIC}Terminal coding assistant powered by AI{RESET}"

    # Working directory with folder icon
    path_display = truncate_path_middle(str(cwd), max(20, width - 10 - string_display_width(folder_name)))
    cwd_line = f"{ICON_FOLDER} {BRIGHT_BLUE}{BOLD}{folder_name}{RESET} {SUBTLE}{path_display}{RESET}"

    # Stats — split into two lines: provider/model and counters
    msg_count = session.get("messageCount", 0)
    evt_count = session.get("transcriptCount", 0)
    skill_count = session.get("skillCount", 0)
    mcp_count = session.get("mcpCount", 0)

    config_line = (
        f"{color_badge('provider', provider, CYAN, ICON_PROVIDER)}"
        f"  {color_badge('model', model, GREEN, ICON_MODEL)}"
    )
    stats_line = (
        f"{ACCENT}{ICON_MSG}{RESET} {BOLD}{msg_count}{RESET}{SUBTLE} msgs{RESET}"
        f"  {ACCENT2}{ICON_EVENT}{RESET} {BOLD}{evt_count}{RESET}{SUBTLE} events{RESET}"
        f"  {YELLOW}{ICON_SKILL}{RESET} {BOLD}{skill_count}{RESET}{SUBTLE} skills{RESET}"
        f"  {MAGENTA}{ICON_MCP}{RESET} {BOLD}{mcp_count}{RESET}{SUBTLE} mcp{RESET}"
    )

    # Permissions with lock icon
    perm_line = f"{ICON_LOCK} {SUBTLE}{' │ '.join(permission_summary)}{RESET}"

    body = "\n".join([tagline, "", cwd_line, config_line, stats_line, perm_line])
    return render_panel("MiniCode", body, right_title=f"{SUBTLE}v0.1{RESET}")


def render_status_line(status: str | None) -> str:
    """Render the status line with icon and formatting."""
    if status:
        return f"{ACCENT}{ICON_RUNNING}{RESET} {YELLOW}{BOLD}{status}{RESET}"
    return f"{GREEN}{ICON_SUCCESS}{RESET} {DIM}Ready{RESET}"


def render_tool_panel(
    active_tool: str | None, recent_tools: list[dict[str, str]], background_tasks: list[dict[str, Any]] = []
) -> str:
    """Include background task support with icons."""
    parts: list[str] = []
    if active_tool:
        parts.append(f"{ICON_RUNNING} {YELLOW}{BOLD}running{RESET} {BRIGHT_YELLOW}{active_tool}{RESET}")
    for task in background_tasks:
        if task.get("status") == "running":
            parts.append(f"{ICON_BG} {BRIGHT_CYAN}bg{RESET} {task.get('label', 'task')}")
    if not parts and not recent_tools:
        parts.append(f"{SUBTLE}{ICON_DOT} idle{RESET}")
    else:
        for tool in recent_tools[-3:]:
            if tool.get("status") == "success":
                parts.append(f"{GREEN}{ICON_SUCCESS} {tool.get('name', 'tool')}{RESET}")
            else:
                parts.append(f"{RED}{ICON_ERROR} {tool.get('name', 'tool')}{RESET}")
    return f"{ICON_TOOL} {DIM}tools{RESET}  " + f"  {SUBTLE}{ICON_DOT}{RESET}  ".join(parts)


def render_footer_bar(
    status: str | None, tools_enabled: bool, skills_enabled: bool, background_tasks: list[dict[str, Any]] = []
) -> str:
    """Stylish single-line footer with icons."""
    width, _ = _cached_terminal_size()
    left = render_status_line(status)

    bg_info = ""
    if background_tasks:
        bg_info = f" {ICON_BG} {BRIGHT_CYAN}{len(background_tasks)} bg{RESET} {SUBTLE}│{RESET}"

    tools_indicator = f"{GREEN}{ICON_SUCCESS}{RESET}" if tools_enabled else f"{RED}{ICON_ERROR}{RESET}"
    skills_indicator = f"{GREEN}{ICON_SUCCESS}{RESET}" if skills_enabled else f"{RED}{ICON_ERROR}{RESET}"

    right = (
        f"{bg_info} {ICON_TOOL} {SUBTLE}tools{RESET} {tools_indicator}"
        f" {SUBTLE}│{RESET} {ICON_SKILL} {SUBTLE}skills{RESET} {skills_indicator}"
    )
    gap = max(1, width - string_display_width(left) - string_display_width(right))
    return f"{left}{' ' * gap}{right}"


def render_slash_menu(commands: list[Any], selected_index: int) -> str:
    """With icons, highlight, and padded usage."""
    if not commands:
        return f"{SUBTLE}no commands{RESET}"
    width, _ = _cached_terminal_size()
    rows = [f"{ACCENT}{ICON_ARROW}{RESET} {DIM}commands{RESET}"]
    for i, cmd in enumerate(commands):
        usage = pad_plain(getattr(cmd, "usage", str(cmd)), 14)
        desc = getattr(cmd, "description", "")
        if i == selected_index:
            line = f"  {HIGHLIGHT_BG}{BRIGHT_CYAN}{ICON_ARROW}{RESET}{HIGHLIGHT_BG} {BRIGHT_WHITE}{BOLD}{usage}{RESET}{HIGHLIGHT_BG} {desc} {RESET}"
        else:
            line = f"   {SUBTLE}{ICON_DOT}{RESET} {usage} {SUBTLE}{desc}{RESET}"
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
    _, rows = _cached_terminal_size()
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
        _, rows = _cached_terminal_size()
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
    """FULL interactive permission prompt with enhanced visuals."""
    lines: list[str] = []
    if feedback_mode:
        lines.extend(
            [
                f"{BRIGHT_YELLOW}{ICON_PROMPT} Provide reason for rejection:{RESET}",
                f"  {GREEN}{ICON_PROMPT}{RESET} {feedback_input}_",
                "",
                f"{SUBTLE}  Press Enter to send, Esc to cancel.{RESET}",
            ]
        )
    else:
        lines.extend([request.get("summary", "Permission Request"), ""])
        details = request.get("details", [])
        if details:
            flat = flatten_detail_lines(details)
            if not expanded:
                lines.append(f"{SUBTLE}  {ICON_ARROW} {len(flat)} lines hidden {SUBTLE}│{RESET} {DIM}press 'v' to expand │ Ctrl+O toggle{RESET}")
            else:
                colorized = colorize_edit_permission_details(flat)
                visible, total = slice_visible_details(colorized, scroll_offset)
                lines.extend(visible)
                if total > len(visible):
                    lines.append(f"{SUBTLE}  {ICON_DIVIDER * 3} scroll {scroll_offset+1}/{total} (Wheel/PgUp/PgDn) {ICON_DIVIDER * 3}{RESET}")
            lines.append("")
        for i, choice in enumerate(request.get("choices", [])):
            label = choice.get("label", "")
            key = choice.get("key", "")
            if i == selected_choice_index:
                lines.append(f"  {HIGHLIGHT_BG}{BRIGHT_CYAN}{ICON_ARROW}{RESET}{HIGHLIGHT_BG} {BRIGHT_WHITE}{BOLD}{label}{RESET}{HIGHLIGHT_BG} {SUBTLE}({key}){RESET}")
            else:
                lines.append(f"    {SUBTLE}{ICON_DOT}{RESET} {label} {SUBTLE}({key}){RESET}")
    return render_panel("Action Required", "\n".join(lines), right_title="Permission")
