from __future__ import annotations

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


def _render_transcript_lines(entries: list[TranscriptEntry]) -> list[str]:
    """Render all entries into a list of lines with decorative separators."""
    all_lines: list[str] = []
    # Visually distinct separator with dots pattern
    separator = f"  {SUBTLE}{ICON_DOT} {ICON_DIVIDER * 3} {ICON_DOT}{RESET}"

    for i, entry in enumerate(entries):
        if i > 0:
            all_lines.append("")
            all_lines.append(separator)
            all_lines.append("")

        entry_text = _render_transcript_entry(entry)
        all_lines.extend(entry_text.split("\n"))

    return all_lines


def get_transcript_max_scroll_offset(
    entries: list[TranscriptEntry], window_size: int | None = None
) -> int:
    """Calculate the maximum possible scroll offset."""
    if not entries:
        return 0
    lines = _render_transcript_lines(entries)
    ws = get_transcript_window_size(window_size)
    return max(0, len(lines) - ws)


def render_transcript(
    entries: list[TranscriptEntry], scroll_offset: int, window_size: int | None = None
) -> str:
    """Render a windowed view of the transcript with an optional scroll indicator."""
    if not entries:
        return ""

    lines = _render_transcript_lines(entries)
    ws = get_transcript_window_size(window_size)
    max_offset = max(0, len(lines) - ws)
    offset = max(0, min(scroll_offset, max_offset))

    end = len(lines) - offset
    start = max(0, end - ws)
    body = "\n".join(lines[start:end])

    if offset == 0:
        return body

    return f"{body}\n\n{SUBTLE}  {ICON_DIVIDER * 2} scroll {offset}/{max_offset} {ICON_DIVIDER * 2}{RESET}"


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
