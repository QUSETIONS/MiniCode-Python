from __future__ import annotations

from functools import lru_cache

from .chrome import (
    _cached_terminal_size,
    RESET, DIM, CYAN, GREEN, YELLOW, RED, MAGENTA, BOLD, BLUE,
    BRIGHT_CYAN, BRIGHT_GREEN, BRIGHT_YELLOW, BRIGHT_MAGENTA, BRIGHT_RED,
    ACCENT, ACCENT2, SUBTLE, ITALIC,
    ICON_USER, ICON_ASSISTANT, ICON_TOOL, ICON_PROGRESS,
    ICON_SUCCESS, ICON_ERROR, ICON_RUNNING, ICON_DIVIDER, ICON_DOT,
)
from .markdown import render_markdownish
from .types import TranscriptEntry

# Pre-build the separator string once (immutable)
_SEPARATOR = f"  {SUBTLE}{ICON_DOT} {ICON_DIVIDER * 3} {ICON_DOT}{RESET}"
_SEPARATOR_LINES = ["", _SEPARATOR, ""]
_SEPARATOR_LINE_COUNT = 3  # empty, separator, empty


def _indent_block(text: str, prefix: str = "  ") -> str:
    """Indent all lines in a block of text."""
    return "\n".join(prefix + line for line in text.split("\n"))


def preview_tool_body(tool_name: str, body: str) -> str:
    """Truncate tool output based on tool name and content size."""
    max_chars = 1000 if tool_name == "read_file" else 1800
    max_lines = 20 if tool_name == "read_file" else 36

    lines = body.split("\n")
    limited_lines = lines[:max_lines] if len(lines) > max_lines else lines
    limited = "\n".join(limited_lines)

    if len(limited) > max_chars:
        limited = limited[:max_chars] + "..."

    if limited != body:
        return f"{limited}\n{DIM}... output truncated in transcript{RESET}"

    return limited


def _render_transcript_entry(entry: TranscriptEntry) -> str:
    """Render a single TranscriptEntry with icons and rich styling."""
    if entry.kind == "user":
        label = f"{BRIGHT_CYAN}{ICON_USER}{RESET} {CYAN}{BOLD}you{RESET}"
        return f"{label}\n{_indent_block(entry.body)}"

    if entry.kind == "assistant":
        label = f"{BRIGHT_GREEN}{ICON_ASSISTANT}{RESET} {GREEN}{BOLD}assistant{RESET}"
        return f"{label}\n{_indent_block(render_markdownish(entry.body))}"

    if entry.kind == "progress":
        label = f"{ACCENT}{ICON_PROGRESS}{RESET} {YELLOW}{BOLD}progress{RESET}"
        return f"{label}\n{_indent_block(render_markdownish(entry.body))}"

    if entry.kind == "tool":
        if entry.status == "running":
            status_label = f"{BRIGHT_YELLOW}{ICON_RUNNING} running{RESET}"
        elif entry.status == "success":
            status_label = f"{GREEN}{ICON_SUCCESS} ok{RESET}"
        else:
            status_label = f"{BRIGHT_RED}{ICON_ERROR} err{RESET}"

        tool_name_display = f"{BRIGHT_MAGENTA}{entry.toolName}{RESET}"
        label = f"{ACCENT2}{ICON_TOOL}{RESET} {MAGENTA}{BOLD}tool{RESET} {tool_name_display} {status_label}"

        if entry.status == "running":
            body = entry.body
        elif entry.collapsed:
            body = f"{SUBTLE}{ITALIC}{entry.collapsedSummary or 'output collapsed'}{RESET}"
        elif entry.collapsePhase:
            dots = f"{ACCENT}{ICON_DOT}{RESET}" * (entry.collapsePhase or 0)
            body = f"{SUBTLE}collapsing{dots}{RESET}"
        else:
            body = preview_tool_body(
                entry.toolName or "", render_markdownish(entry.body)
            )

        return f"{label}\n{_indent_block(body)}"

    return ""


def get_transcript_window_size(window_size: int | None = None) -> int:
    """Calculate the number of lines to display in the transcript window."""
    if window_size is not None:
        return max(4, window_size)
    _, rows = _cached_terminal_size()
    return max(8, rows - 15)


# ---------------------------------------------------------------------------
# Per-entry rendering cache
# ---------------------------------------------------------------------------
# Uses object id + content fingerprint for fast cache lookup.
# Cache is periodically pruned to avoid unbounded growth.

_entry_cache: dict[int, tuple[tuple, list[str]]] = {}
_CACHE_MAX_SIZE = 500  # prune when exceeding this


def _get_entry_lines(entry: TranscriptEntry) -> list[str]:
    state = (
        entry.kind,
        entry.body,
        entry.status,
        entry.collapsed,
        entry.collapsePhase,
        entry.collapsedSummary,
        entry.toolName,
    )

    entry_id = id(entry)
    cached = _entry_cache.get(entry_id)
    if cached is not None and cached[0] == state:
        return cached[1]

    lines = _render_transcript_entry(entry).split("\n")

    # Prune cache if too large (remove oldest half)
    if len(_entry_cache) > _CACHE_MAX_SIZE:
        keys = list(_entry_cache.keys())
        for k in keys[: len(keys) // 2]:
            del _entry_cache[k]

    _entry_cache[entry_id] = (state, lines)
    return lines


# ---------------------------------------------------------------------------
# Per-entry line count cache (lightweight — avoids full render for counting)
# ---------------------------------------------------------------------------

_line_count_cache: dict[int, tuple[tuple, int]] = {}


def _get_entry_line_count(entry: TranscriptEntry) -> int:
    """Get the number of rendered lines for an entry (uses cache, avoids full render if possible)."""
    state = (
        entry.kind,
        entry.body,
        entry.status,
        entry.collapsed,
        entry.collapsePhase,
        entry.collapsedSummary,
        entry.toolName,
    )
    entry_id = id(entry)

    # Check line-count cache first
    cached_lc = _line_count_cache.get(entry_id)
    if cached_lc is not None and cached_lc[0] == state:
        return cached_lc[1]

    # Check full render cache — if we already have rendered lines, just count
    cached_full = _entry_cache.get(entry_id)
    if cached_full is not None and cached_full[0] == state:
        count = len(cached_full[1])
        _line_count_cache[entry_id] = (state, count)
        return count

    # Fall back to full render (will also populate _entry_cache)
    lines = _get_entry_lines(entry)
    count = len(lines)
    _line_count_cache[entry_id] = (state, count)
    return count


# ---------------------------------------------------------------------------
# Windowed transcript rendering — O(visible) instead of O(N)
# ---------------------------------------------------------------------------

def _compute_total_lines(entries: list[TranscriptEntry]) -> int:
    """Compute total line count across all entries including separators."""
    if not entries:
        return 0
    total = 0
    for i, entry in enumerate(entries):
        if i > 0:
            total += _SEPARATOR_LINE_COUNT
        total += _get_entry_line_count(entry)
    return total


def _render_visible_window(
    entries: list[TranscriptEntry],
    start_line: int,
    end_line: int,
) -> list[str]:
    """Only render entries that intersect with the visible [start_line, end_line) range."""
    if not entries:
        return []

    result: list[str] = []
    current_line = 0

    for i, entry in enumerate(entries):
        # Separator before entry (except the first)
        if i > 0:
            sep_start = current_line
            sep_end = current_line + _SEPARATOR_LINE_COUNT
            if sep_start < end_line and sep_end > start_line:
                # This separator is visible (at least partially)
                vis_start = max(0, start_line - sep_start)
                vis_end = min(_SEPARATOR_LINE_COUNT, end_line - sep_start)
                result.extend(_SEPARATOR_LINES[vis_start:vis_end])
            current_line = sep_end
            if current_line >= end_line:
                break

        # Entry lines
        entry_line_count = _get_entry_line_count(entry)
        entry_start = current_line
        entry_end = current_line + entry_line_count

        if entry_start < end_line and entry_end > start_line:
            # This entry is visible (at least partially) — now render it
            lines = _get_entry_lines(entry)
            vis_start = max(0, start_line - entry_start)
            vis_end = min(entry_line_count, end_line - entry_start)
            result.extend(lines[vis_start:vis_end])

        current_line = entry_end
        if current_line >= end_line:
            break

    return result


def get_transcript_max_scroll_offset(
    entries: list[TranscriptEntry], window_size: int | None = None
) -> int:
    """Calculate the maximum possible scroll offset. O(N) in entry count but NOT in line rendering."""
    if not entries:
        return 0
    total = _compute_total_lines(entries)
    ws = get_transcript_window_size(window_size)
    return max(0, total - ws)


def render_transcript(
    entries: list[TranscriptEntry], scroll_offset: int, window_size: int | None = None
) -> str:
    """Render a windowed view of the transcript. Only renders visible entries — O(visible)."""
    if not entries:
        return ""

    total_lines = _compute_total_lines(entries)
    ws = get_transcript_window_size(window_size)
    max_offset = max(0, total_lines - ws)
    offset = max(0, min(scroll_offset, max_offset))

    # Calculate the visible line range (scroll_offset=0 means bottom)
    end = total_lines - offset
    start = max(0, end - ws)

    visible_lines = _render_visible_window(entries, start, end)
    body = "\n".join(visible_lines)

    if offset == 0:
        return body

    return f"{body}\n\n{SUBTLE}  {ICON_DIVIDER * 2} scroll {offset}/{max_offset} {ICON_DIVIDER * 2}{RESET}"


# ---------------------------------------------------------------------------
# Legacy full-render API (kept for backward compat, e.g. tty_app imports)
# ---------------------------------------------------------------------------

def _render_transcript_lines(entries: list[TranscriptEntry]) -> list[str]:
    """Render all entries into a list of lines with decorative separators.
    
    NOTE: This is kept for backward compatibility. Prefer render_transcript()
    which uses windowed rendering.
    """
    all_lines: list[str] = []
    for i, entry in enumerate(entries):
        if i > 0:
            all_lines.extend(_SEPARATOR_LINES)
        all_lines.extend(_get_entry_lines(entry))
    return all_lines


def format_transcript_text(entries: list[TranscriptEntry]) -> str:
    """Format transcript entries as plain text (no ANSI) for saving to file."""
    parts = []
    for entry in entries:
        label = "you" if entry.kind == "user" else entry.kind
        if entry.kind == "tool":
            status_text = f" ({entry.status})" if entry.status else ""
            label = f"{entry.toolName or 'tool'}{status_text}"
        indented = "\n".join("  " + line for line in entry.body.splitlines())
        parts.append(f"{label}\n{indented}")
    return "\n\n---\n\n".join(parts)
