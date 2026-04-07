from __future__ import annotations

from .chrome import (
    _cached_terminal_size,
    RESET, DIM, BOLD,
    ICON_DIVIDER, ICON_DOT,
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
    """Render a single TranscriptEntry with Morandi theme colors.

    Tool entries follow the Rust [展开]/[收起] toggle pattern:
    - expanded=False → show preview lines + [展开] label
    - expanded=True  → show full output + [收起] label
    The ``collapsed`` / ``collapsePhase`` fields drive the display:
      collapsed=True  → entry was auto-collapsed after completion
      collapsePhase   → animation step (kept for compat, treated as collapsed)
    """
    t = theme()

    if entry.kind == "user":
        label = f"{t.user}{t.bold}▌ you{t.reset}"
        return f"{label}\n{_indent_block(entry.body)}"

    if entry.kind == "assistant":
        label = f"{t.assistant}{t.bold}▌ assistant{t.reset}"
        return f"{label}\n{_indent_block(render_markdownish(entry.body))}"

    if entry.kind == "progress":
        label = f"{t.progress}{t.bold}▌ progress{t.reset}"
        return f"{label}\n{_indent_block(render_markdownish(entry.body))}"

    if entry.kind == "tool":
        # Status indicator
        if entry.status == "running":
            status_label = f"{t.tool}{ICON_DOT} running{t.reset}"
        elif entry.status == "success":
            status_label = f"{t.assistant}ok{t.reset}"
        else:
            status_label = f"{t.tool_error}err{t.reset}"

        tool_name_display = f"{t.tool}{t.bold}{entry.toolName}{t.reset}"

        # Determine expand/collapse toggle text
        body_lines = entry.body.split("\n") if entry.body else []
        total_lines = len(body_lines)
        collapsible_by_lines = total_lines > _TOOL_PREVIEW_LINES
        collapsible_by_chars = any(
            len(ln) > _TOOL_PREVIEW_CHARS
            for ln in body_lines[:_TOOL_PREVIEW_LINES]
        )
        can_toggle = collapsible_by_lines or collapsible_by_chars

        is_collapsed = entry.collapsed or entry.collapsePhase is not None

        if can_toggle:
            toggle_text = (
                f"  {t.expandable}{t.bold}[收起]{t.reset}"
                if not is_collapsed
                else f"  {t.expandable}{t.bold}[展开]{t.reset}"
            )
        else:
            toggle_text = ""

        label = (
            f"{t.tool}{t.bold}▌ tool{t.reset} {tool_name_display}"
            f" {status_label}{toggle_text}"
        )

        if entry.status == "running":
            body = entry.body
        elif is_collapsed:
            summary = entry.collapsedSummary or "output collapsed"
            body = f"{t.subtle}{t.italic}{summary}{t.reset}"
        else:
            # Show preview (matches Rust's collapsed_preview_len = TOOL_PREVIEW_LINES)
            if collapsible_by_lines:
                preview = "\n".join(body_lines[:_TOOL_PREVIEW_LINES])
                hidden = total_lines - _TOOL_PREVIEW_LINES
                body = (
                    preview_tool_body(entry.toolName or "", render_markdownish(preview))
                    + f"\n{t.subtle}  ... {hidden} more lines{t.reset}"
                )
            else:
                body = preview_tool_body(
                    entry.toolName or "", render_markdownish(entry.body)
                )

        return f"{label}\n{_indent_block(body)}"

    return ""


def get_transcript_window_size(window_size: int | None = None) -> int:
    if window_size is not None:
        return max(4, window_size)
    _, rows = _cached_terminal_size()
    return max(8, rows - 15)


# ---------------------------------------------------------------------------
# Per-entry rendering cache
# ---------------------------------------------------------------------------

_entry_cache: dict[int, tuple[tuple, list[str]]] = {}
_CACHE_MAX_SIZE = 500


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

    if len(_entry_cache) > _CACHE_MAX_SIZE:
        keys = list(_entry_cache.keys())
        for k in keys[: len(keys) // 2]:
            del _entry_cache[k]

    _entry_cache[entry_id] = (state, lines)
    return lines


# ---------------------------------------------------------------------------
# Per-entry line count cache
# ---------------------------------------------------------------------------

_line_count_cache: dict[int, tuple[tuple, int]] = {}


def _get_entry_line_count(entry: TranscriptEntry) -> int:
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

    cached_lc = _line_count_cache.get(entry_id)
    if cached_lc is not None and cached_lc[0] == state:
        return cached_lc[1]

    cached_full = _entry_cache.get(entry_id)
    if cached_full is not None and cached_full[0] == state:
        count = len(cached_full[1])
        _line_count_cache[entry_id] = (state, count)
        return count

    lines = _get_entry_lines(entry)
    count = len(lines)
    _line_count_cache[entry_id] = (state, count)
    return count


# ---------------------------------------------------------------------------
# Windowed transcript rendering — O(visible)
# ---------------------------------------------------------------------------

def _compute_total_lines(entries: list[TranscriptEntry]) -> int:
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
    if not entries:
        return []

    result: list[str] = []
    current_line = 0

    for i, entry in enumerate(entries):
        if i > 0:
            sep_start = current_line
            sep_end = current_line + _SEPARATOR_LINE_COUNT
            if sep_start < end_line and sep_end > start_line:
                vis_start = max(0, start_line - sep_start)
                vis_end = min(_SEPARATOR_LINE_COUNT, end_line - sep_start)
                result.extend(_SEPARATOR_LINES[vis_start:vis_end])
            current_line = sep_end
            if current_line >= end_line:
                break

        entry_line_count = _get_entry_line_count(entry)
        entry_start = current_line
        entry_end = current_line + entry_line_count

        if entry_start < end_line and entry_end > start_line:
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
    if not entries:
        return 0
    total = _compute_total_lines(entries)
    ws = get_transcript_window_size(window_size)
    return max(0, total - ws)


def render_transcript(
    entries: list[TranscriptEntry], scroll_offset: int, window_size: int | None = None
) -> str:
    """Render a windowed view of the transcript. O(visible)."""
    t = theme()
    if not entries:
        return ""

    total_lines = _compute_total_lines(entries)
    ws = get_transcript_window_size(window_size)
    max_offset = max(0, total_lines - ws)
    offset = max(0, min(scroll_offset, max_offset))

    if offset == 0:
        # No scroll indicator needed — use full window
        end = total_lines
        start = max(0, end - ws)
        visible_lines = _render_visible_window(entries, start, end)
        return "\n".join(visible_lines)

    # Reserve 1 line for the scroll indicator so the panel stays within bounds
    content_ws = max(1, ws - 1)
    end = total_lines - offset
    start = max(0, end - content_ws)
    visible_lines = _render_visible_window(entries, start, end)
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
