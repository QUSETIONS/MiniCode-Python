"""Edit file tool with precise string matching, inspired by Claude Code's Edit tool.

Key features:
- Exact string match with line/whitespace-aware comparison
- Multiple match detection and disambiguation
- Fuzzy whitespace matching (tabs vs spaces, trailing whitespace)
- Line number diagnostics on mismatch
- Replace-all mode
"""
from __future__ import annotations

import difflib
from pathlib import Path

from minicode.file_review import apply_reviewed_file_change, load_existing_file
from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path


# ---------------------------------------------------------------------------
# String matching helpers
# ---------------------------------------------------------------------------

def _normalize_line(line: str) -> str:
    """Normalize a line for fuzzy matching: strip trailing whitespace, normalize tabs."""
    return line.rstrip().replace("\t", "    ")


def _find_exact_match(content: str, search: str, fuzzy: bool = False) -> list[tuple[int, int]]:
    """Find all occurrences of search in content.
    
    Returns list of (start_char_offset, end_char_offset) tuples.
    
    Args:
        content: The file content to search in
        search: The search string
        fuzzy: If True, use whitespace-fuzzy matching (normalize tabs/trailing whitespace)
    """
    if not search:
        return []
    
    if not fuzzy:
        # Exact matching
        results = []
        start = 0
        while True:
            idx = content.find(search, start)
            if idx == -1:
                break
            results.append((idx, idx + len(search)))
            start = idx + 1
        return results
    
    # Fuzzy matching: compare line-by-line with normalized whitespace
    search_lines = search.split("\n")
    content_lines = content.split("\n")
    results = []
    
    for i in range(len(content_lines) - len(search_lines) + 1):
        match = True
        for j, search_line in enumerate(search_lines):
            if _normalize_line(content_lines[i + j]) != _normalize_line(search_line):
                match = False
                break
        if match:
            # Calculate character offsets from line positions
            char_start = sum(len(line) + 1 for line in content_lines[:i])
            char_end = char_start + len("\n".join(content_lines[i:i + len(search_lines)]))
            results.append((char_start, char_end))
    
    return results


def _format_mismatch_diagnostic(content: str, search: str) -> str:
    """Produce a helpful diagnostic when search string is not found.
    
    Shows the closest match with line numbers and diff hints.
    """
    search_lines = search.split("\n")
    content_lines = content.split("\n")
    
    # Find the best matching region using difflib
    best_ratio = 0.0
    best_start = -1
    
    # Search in a sliding window
    window_size = len(search_lines)
    for i in range(max(1, len(content_lines) - window_size + 1)):
        window = content_lines[i:i + window_size]
        if len(window) != window_size:
            continue
        ratio = difflib.SequenceMatcher(None, window, search_lines).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i
    
    lines = ["Search string not found in file."]
    
    if best_start >= 0 and best_ratio > 0.3:
        lines.append(f"")
        lines.append(f"Closest match at line {best_start + 1} (similarity: {best_ratio:.0%}):")
        lines.append("")
        
        # Show the closest match with line numbers
        for j, line in enumerate(content_lines[best_start:best_start + window_size]):
            line_num = best_start + 1 + j
            prefix = "  "
            # Check if this line matches the search line
            if j < len(search_lines):
                norm_content = _normalize_line(line)
                norm_search = _normalize_line(search_lines[j])
                if norm_content != norm_search:
                    prefix = ">>"
            lines.append(f"{prefix} {line_num:4d} | {line}")
        
        # Show diff hint
        if best_ratio < 1.0:
            lines.append("")
            lines.append("Hints:")
            search_norm = [_normalize_line(l) for l in search_lines]
            content_norm = [_normalize_line(l) for l in content_lines[best_start:best_start + window_size]]
            for j in range(min(len(search_norm), len(content_norm))):
                if search_norm[j] != content_norm[j]:
                    lines.append(f"  Line {best_start + 1 + j}: expected {search_norm[j]!r}, found {content_norm[j]!r}")
    else:
        # No close match found, show first few lines of file for context
        lines.append("")
        lines.append(f"File has {len(content_lines)} lines. First 10 lines:")
        for i, line in enumerate(content_lines[:10]):
            lines.append(f"  {i + 1:4d} | {line}")
    
    return "\n".join(lines)


def _validate(input_data: dict) -> dict:
    path = input_data.get("path")
    search = input_data.get("search", input_data.get("old"))
    replace = input_data.get("replace", input_data.get("new"))
    replace_all = bool(input_data.get("replaceAll", input_data.get("replace_all", False)))
    fuzzy = bool(input_data.get("fuzzy", False))
    
    if not isinstance(path, str) or not path:
        raise ValueError("path is required")
    if not isinstance(search, str) or not isinstance(replace, str):
        raise ValueError("search and replace must be strings")
    if not search:
        raise ValueError("search must be non-empty")
    
    # Normalize \r\n → \n so that search/replace strings provided by the
    # model always match the file content (read_text uses universal newlines).
    search = search.replace("\r\n", "\n")
    replace = replace.replace("\r\n", "\n")
    
    return {
        "path": path,
        "search": search,
        "replace": replace,
        "replace_all": replace_all,
        "fuzzy": fuzzy,
    }


def _run(input_data: dict, context) -> ToolResult:
    target = resolve_tool_path(context, input_data["path"], "write")
    content = load_existing_file(target)
    
    # Try exact matching first
    matches = _find_exact_match(content, input_data["search"], fuzzy=False)
    
    # If no exact match, try fuzzy matching (whitespace-tolerant)
    if not matches and input_data.get("fuzzy", False):
        matches = _find_exact_match(content, input_data["search"], fuzzy=True)
    
    if not matches:
        # No match found — provide helpful diagnostic
        diagnostic = _format_mismatch_diagnostic(content, input_data["search"])
        return ToolResult(ok=False, output=diagnostic)
    
    if len(matches) > 1 and not input_data["replace_all"]:
        # Multiple matches — report them with line numbers
        content_lines = content.split("\n")
        match_lines = []
        for start_offset, _ in matches:
            # Find line number from char offset
            char_count = 0
            for line_num, line in enumerate(content_lines, start=1):
                if char_count + len(line) + 1 > start_offset:
                    match_lines.append(line_num)
                    break
                char_count += len(line) + 1
        
        return ToolResult(
            ok=False,
            output=(
                f"Found {len(matches)} matches for the search string. "
                f"Use replace_all=true to replace all occurrences, or provide more context to make the match unique.\n"
                f"Matches at lines: {', '.join(str(l) for l in match_lines)}"
            ),
        )
    
    # Apply replacement
    if input_data["replace_all"]:
        # Replace from end to start to preserve offsets
        next_content = content
        for start_offset, end_offset in reversed(matches):
            next_content = next_content[:start_offset] + input_data["replace"] + next_content[end_offset:]
    else:
        start_offset, end_offset = matches[0]
        next_content = content[:start_offset] + input_data["replace"] + content[end_offset:]
    
    return apply_reviewed_file_change(context, input_data["path"], target, next_content)


edit_file_tool = ToolDefinition(
    name="edit_file",
    description=(
        "Replace a substring in a file. The search string must match exactly (including whitespace and indentation). "
        "If the search string appears multiple times, you must provide more surrounding context to make it unique, "
        "or set replace_all=true. On mismatch, a diagnostic is shown with the closest match and line numbers."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to edit"},
            "old": {"type": "string", "description": "Text to find (exact match required)"},
            "new": {"type": "string", "description": "Replacement text"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences (default: false)"},
            "fuzzy": {"type": "boolean", "description": "Enable whitespace-fuzzy matching (default: false)"},
        },
        "required": ["path", "old", "new"],
    },
    validator=_validate,
    run=_run,
)
