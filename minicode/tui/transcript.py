from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from .chrome import (
    _cached_terminal_size,
    RESET,
    DIM,
    BOLD,
    ICON_DIVIDER,
    ICON_DOT,
)
from .markdown import render_markdownish
from .theme import theme
from .types import TranscriptEntry

# Pre-build the separator string once (immutable)
_SEPARATOR = f"  {DIM}{ICON_DOT} {ICON_DIVIDER * 3} {ICON_DOT}{RESET}"
_SEPARATOR_LINES = ["", _SEPARATOR, ""]
_SEPARATOR_LINE_COUNT = 3

# Tool output preview limits (match Rust TOOL_PREVIEW_LINES / TOOL_PREVIEW_CHARS)
_TOOL_PREVIEW_LINES = 6
_TOOL_PREVIEW_CHARS = 180


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
    """Render a single TranscriptEntry with Morandi theme colors."""
    t = theme()

    if entry.kind == "user":
        label = f"{t.user}{t.bold}▶ you{t.reset}"
        return f"{label}\n{_indent_block(entry.body)}"

    if entry.kind == "assistant":
        label = f"{t.assistant}{t.bold}▶ assistant{t.reset}"
        return f"{label}\n{_indent_block(render_markdownish(entry.body))}"

    if entry.kind == "progress":
        label = f"{t.progress}{t.bold}▶ progress{t.reset}"
        return f"{label}\n{_indent_block(render_markdownish(entry.body))}"

    if entry.kind == "tool":
        if entry.status == "running":
            status_label = f"{t.tool}{ICON_DOT} running{t.reset}"
        elif entry.status == "success":
            status_label = f"{t.assistant}ok{t.reset}"
        else:
            status_label = f"{t.tool_error}err{t.reset}"

        tool_name_display = f"{t.tool}{t.bold}{entry.toolName}{t.reset}"

        body_lines = entry.body.split("\n") if entry.body else []
        total_lines = len(body_lines)
        collapsible_by_lines = total_lines > _TOOL_PREVIEW_LINES
        collapsible_by_chars = any(
            len(ln) > _TOOL_PREVIEW_CHARS for ln in body_lines[:_TOOL_PREVIEW_LINES]
        )
        is_collapsed = entry.collapsed or entry.collapsePhase == 3
        is_collapsing = entry.collapsePhase in (1, 2)
        can_toggle = collapsible_by_lines or collapsible_by_chars or is_collapsing

        if can_toggle:
            if is_collapsing:
                toggle_text = f"  {t.expandable}{t.bold}[collapsing]{t.reset}"
            else:
                toggle_text = (
                    f"  {t.expandable}{t.bold}[收起]{t.reset}"
                    if not is_collapsed
                    else f"  {t.expandable}{t.bold}[展开]{t.reset}"
                )
        else:
            toggle_text = ""

        label = (
            f"{t.tool}{t.bold}▶ tool{t.reset} {tool_name_display}"
            f" {status_label}{toggle_text}"
        )

        if entry.status == "running":
            body = entry.body
        elif is_collapsing:
            if collapsible_by_lines:
                preview = "\n".join(body_lines[:_TOOL_PREVIEW_LINES])
                hidden = max(0, total_lines - _TOOL_PREVIEW_LINES)
                body = (
                    preview_tool_body(entry.toolName or "", render_markdownish(preview))
                    + (f"\n{t.subtle}  ... {hidden} more lines{t.reset}" if hidden > 0 else "")
                )
            else:
                body = preview_tool_body(entry.toolName or "", render_markdownish(entry.body))
        elif is_collapsed:
            summary = entry.collapsedSummary or "output collapsed"
            body = f"{t.subtle}{t.italic}{summary}{t.reset}"
        else:
            if collapsible_by_lines:
                preview = "\n".join(body_lines[:_TOOL_PREVIEW_LINES])
                hidden = total_lines - _TOOL_PREVIEW_LINES
                body = (
                    preview_tool_body(entry.toolName or "", render_markdownish(preview))
                    + f"\n{t.subtle}  ... {hidden} more lines{t.reset}"
                )
            else:
                body = preview_tool_body(entry.toolName or "", render_markdownish(entry.body))

        return f"{label}\n{_indent_block(body)}"

    return ""


def get_transcript_window_size(window_size: int | None = None) -> int:
    if window_size is not None:
        return max(4, window_size)
    _, rows = _cached_terminal_size()
    return max(8, rows - 15)


@dataclass(slots=True)
class TranscriptLayout:
    revision: int
    total_lines: int
    entry_line_starts: list[int]
    entry_line_counts: list[int]


_EntryCacheKey = tuple[
    str,
    str,
    str | None,
    bool,
    int | None,
    str | None,
    str | None,
]
_entry_cache: dict[_EntryCacheKey, list[str]] = {}
_line_count_cache: dict[_EntryCacheKey, int] = {}
_LayoutCacheKey = tuple[int, int, int]
_layout_cache: dict[_LayoutCacheKey, TranscriptLayout] = {}
_CACHE_MAX_SIZE = 500
_LAYOUT_CACHE_MAX_SIZE = 64


def _entry_cache_key(entry: TranscriptEntry) -> _EntryCacheKey:
    """Build a collision-free key from entry render-affecting state."""
    return (
        entry.kind,
        entry.body,
        entry.status,
        entry.collapsed,
        entry.collapsePhase,
        entry.collapsedSummary,
        entry.toolName,
    )


def _get_entry_lines(entry: TranscriptEntry) -> list[str]:
    cache_key = _entry_cache_key(entry)

    cached = _entry_cache.get(cache_key)
    if cached is not None:
        return cached

    lines = _render_transcript_entry(entry).split("\n")

    if len(_entry_cache) > _CACHE_MAX_SIZE:
        keys = list(_entry_cache.keys())
        for k in keys[: len(keys) // 2]:
            del _entry_cache[k]
            _line_count_cache.pop(k, None)

    _entry_cache[cache_key] = lines
    return lines


def _get_entry_line_count(entry: TranscriptEntry) -> int:
    cache_key = _entry_cache_key(entry)

    cached_lc = _line_count_cache.get(cache_key)
    if cached_lc is not None:
        return cached_lc

    cached_full = _entry_cache.get(cache_key)
    if cached_full is not None:
        count = len(cached_full)
        _line_count_cache[cache_key] = count
        return count

    lines = _get_entry_lines(entry)
    count = len(lines)
    _line_count_cache[cache_key] = count
    return count


def _layout_cache_key(
    entries: list[TranscriptEntry],
    revision: int | None,
) -> _LayoutCacheKey | None:
    if revision is None:
        return None
    return (id(entries), revision, len(entries))


def _build_transcript_layout(
    entries: list[TranscriptEntry],
    revision: int | None,
) -> TranscriptLayout:
    cache_key = _layout_cache_key(entries, revision)
    if cache_key is not None:
        cached = _layout_cache.get(cache_key)
        if cached is not None:
            return cached

    entry_line_starts: list[int] = []
    entry_line_counts: list[int] = []
    current_line = 0

    for i, entry in enumerate(entries):
        if i > 0:
            current_line += _SEPARATOR_LINE_COUNT
        entry_line_starts.append(current_line)
        line_count = _get_entry_line_count(entry)
        entry_line_counts.append(line_count)
        current_line += line_count

    layout = TranscriptLayout(
        revision=revision or 0,
        total_lines=current_line,
        entry_line_starts=entry_line_starts,
        entry_line_counts=entry_line_counts,
    )

    if cache_key is not None:
        if len(_layout_cache) >= _LAYOUT_CACHE_MAX_SIZE:
            for key in list(_layout_cache.keys())[: len(_layout_cache) // 2]:
                del _layout_cache[key]
        _layout_cache[cache_key] = layout
    return layout


def _compute_total_lines(entries: list[TranscriptEntry], revision: int | None = None) -> int:
    if not entries:
        return 0
    return _build_transcript_layout(entries, revision).total_lines


def _render_visible_window(
    entries: list[TranscriptEntry],
    start_line: int,
    end_line: int,
    revision: int | None = None,
) -> list[str]:
    if not entries:
        return []

    layout = _build_transcript_layout(entries, revision)
    result: list[str] = []
    if not layout.entry_line_starts:
        return result

    start_index = bisect_left(layout.entry_line_starts, start_line)
    if start_index > 0:
        start_index -= 1

    for i in range(start_index, len(entries)):
        entry_start = layout.entry_line_starts[i]
        entry_line_count = layout.entry_line_counts[i]
        entry_end = entry_start + entry_line_count

        if i > 0:
            sep_start = entry_start - _SEPARATOR_LINE_COUNT
            sep_end = entry_start
            if sep_start < end_line and sep_end > start_line:
                vis_start = max(0, start_line - sep_start)
                vis_end = min(_SEPARATOR_LINE_COUNT, end_line - sep_start)
                result.extend(_SEPARATOR_LINES[vis_start:vis_end])

        if entry_start >= end_line:
            break

        if entry_start < end_line and entry_end > start_line:
            lines = _get_entry_lines(entries[i])
            vis_start = max(0, start_line - entry_start)
            vis_end = min(entry_line_count, end_line - entry_start)
            result.extend(lines[vis_start:vis_end])

    return result


def get_transcript_max_scroll_offset(
    entries: list[TranscriptEntry],
    window_size: int | None = None,
    revision: int | None = None,
) -> int:
    if not entries:
        return 0
    total = _compute_total_lines(entries, revision)
    ws = get_transcript_window_size(window_size)
    return max(0, total - ws)


def render_transcript(
    entries: list[TranscriptEntry],
    scroll_offset: int,
    window_size: int | None = None,
    revision: int | None = None,
) -> str:
    """Render a windowed view of the transcript. O(visible)."""
    t = theme()
    if not entries:
        return ""

    layout = _build_transcript_layout(entries, revision)
    total_lines = layout.total_lines
    ws = get_transcript_window_size(window_size)
    max_offset = max(0, total_lines - ws)
    offset = max(0, min(scroll_offset, max_offset))

    if offset == 0:
        end = total_lines
        start = max(0, end - ws)
        visible_lines = _render_visible_window(entries, start, end, revision)
        return "\n".join(visible_lines)

    content_ws = max(1, ws - 1)
    end = total_lines - offset
    start = max(0, end - content_ws)
    visible_lines = _render_visible_window(entries, start, end, revision)
    body = "\n".join(visible_lines)

    return (
        f"{body}\n"
        f"{t.subtle}  {ICON_DIVIDER * 2} scroll {offset}/{max_offset} "
        f"(PgUp/PgDn or scroll){ICON_DIVIDER * 2}{t.reset}"
    )


# ---------------------------------------------------------------------------
# Legacy full-render API (backward compat)
# ---------------------------------------------------------------------------

def _render_transcript_lines(entries: list[TranscriptEntry]) -> list[str]:
    """Render all entries into lines with separators. Kept for backward compat."""
    all_lines: list[str] = []
    for i, entry in enumerate(entries):
        if i > 0:
            all_lines.extend(_SEPARATOR_LINES)
        all_lines.extend(_get_entry_lines(entry))
    return all_lines


def format_transcript_text(entries: list[TranscriptEntry]) -> str:
    """Format transcript entries as plain text (no ANSI) for file saving."""
    parts = []
    for entry in entries:
        label = "you" if entry.kind == "user" else entry.kind
        if entry.kind == "tool":
            status_text = f" ({entry.status})" if entry.status else ""
            label = f"{entry.toolName or 'tool'}{status_text}"
        indented = "\n".join("  " + line for line in entry.body.splitlines())
        parts.append(f"{label}\n{indented}")
    return "\n\n---\n\n".join(parts)
