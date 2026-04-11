"""Grep tool — search file contents with regex, glob filtering, and context lines.

Inspired by Claude Code's Grep tool which uses ripgrep-level search
with AST-aware filtering, glob patterns, and context lines.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKIP_DIRS = frozenset({
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox',
    'dist', 'build', '.hg', '.svn', '.next', '.nuxt', 'target',
    'vendor', 'Pods', '.dart_tool', '.gradle', '.idea', '.vscode',
    'coverage', '.coverage', 'htmlcov', '.mypy_cache', '.pytest_cache',
    '.ruff_cache', '.pytype',
})

# Binary file extensions to skip
BINARY_EXTENSIONS = frozenset({
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svg',
    '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv', '.flv',
    '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.so', '.dll', '.dylib', '.exe', '.bin', '.dat',
    '.pyc', '.pyo', '.class', '.o', '.obj',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.sqlite', '.db', '.lock',
})

MAX_FILES = 5000
MAX_RESULTS = 200
MAX_RESULT_SIZE = 50_000  # chars


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------

def _matches_glob(path: Path, include_globs: list[str] | None, exclude_globs: list[str] | None) -> bool:
    """Check if a path matches include/exclude glob patterns.
    
    Args:
        path: File path relative to search root
        include_globs: If provided, file must match at least one
        exclude_globs: If provided, file must NOT match any
    """
    posix_path = path.as_posix()
    name = path.name
    
    if exclude_globs:
        for pattern in exclude_globs:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(posix_path, pattern):
                return False
    
    if include_globs:
        for pattern in include_globs:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(posix_path, pattern):
                return True
        return False  # Didn't match any include pattern
    
    return True


# ---------------------------------------------------------------------------
# Search logic
# ---------------------------------------------------------------------------

def _search_file(
    file_path: Path,
    regex: re.Pattern,
    context_lines: int,
    root: Path,
) -> list[dict[str, Any]] | None:
    """Search a single file for regex matches with context.
    
    Returns list of match dicts, or None if file can't be read.
    """
    # Skip binary files
    if file_path.suffix.lower() in BINARY_EXTENSIONS:
        return None
    
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None
    
    lines = content.splitlines()
    matches = []
    
    for line_num, line in enumerate(lines, start=1):
        if regex.search(line):
            # Build context
            context_before = []
            context_after = []
            
            if context_lines > 0:
                for i in range(max(0, line_num - 1 - context_lines), line_num - 1):
                    context_before.append({
                        "line": i + 1,
                        "text": lines[i],
                        "is_match": False,
                    })
                for i in range(line_num, min(len(lines), line_num + context_lines)):
                    context_after.append({
                        "line": i + 1,
                        "text": lines[i],
                        "is_match": False,
                    })
            
            matches.append({
                "line": line_num,
                "text": line,
                "is_match": True,
                "context_before": context_before,
                "context_after": context_after,
            })
    
    return matches if matches else None


def _format_results(
    results: list[tuple[Path, list[dict[str, Any]]]],
    root: Path,
    max_results: int = MAX_RESULTS,
) -> str:
    """Format search results for output.
    
    Format: path:line:content (with optional context lines)
    """
    output_parts = []
    total_matches = 0
    
    for file_path, matches in results:
        if total_matches >= max_results:
            break
        
        rel_path = file_path.relative_to(root).as_posix()
        
        for match in matches:
            if total_matches >= max_results:
                break
            total_matches += 1
            
            # Context before
            for ctx in match.get("context_before", []):
                output_parts.append(
                    f"{rel_path}:{ctx['line']}:  {ctx['text']}"
                )
            
            # Match line
            output_parts.append(
                f"{rel_path}:{match['line']}: {match['text']}"
            )
            
            # Context after
            for ctx in match.get("context_after", []):
                output_parts.append(
                    f"{rel_path}:{ctx['line']}:  {ctx['text']}"
                )
            
            # Separator between matches
            if len(matches) > 1 or match.get("context_before") or match.get("context_after"):
                output_parts.append("")
    
    return "\n".join(output_parts)


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

def _validate(input_data: dict) -> dict:
    pattern = input_data.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern is required")
    
    # Validate regex
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}")
    
    # Parse include/exclude globs
    include = input_data.get("include")
    if isinstance(include, str):
        include = [include]
    elif include is None:
        include = None
    elif not isinstance(include, list):
        include = None
    
    exclude = input_data.get("exclude")
    if isinstance(exclude, str):
        exclude = [exclude]
    elif exclude is None:
        # Default excludes
        exclude = []
    elif not isinstance(exclude, list):
        exclude = []
    
    return {
        "pattern": pattern,
        "path": input_data.get("path", "."),
        "include": include,
        "exclude": exclude,
        "context_lines": min(int(input_data.get("context_lines", 0)), 5),
        "case_sensitive": bool(input_data.get("case_sensitive", False)),
    }


def _run(input_data: dict, context) -> ToolResult:
    root = resolve_tool_path(context, input_data["path"], "search")
    
    # Compile regex
    flags = 0 if input_data.get("case_sensitive", False) else re.IGNORECASE
    try:
        regex = re.compile(input_data["pattern"], flags)
    except re.error as e:
        return ToolResult(ok=False, output=f"Invalid regex: {e}")
    
    context_lines = input_data.get("context_lines", 0)
    include_globs = input_data.get("include", [])
    exclude_globs = input_data.get("exclude", [])
    
    # Collect files
    try:
        all_files = sorted(root.rglob("*"))
    except PermissionError:
        return ToolResult(ok=False, output=f"Permission denied: {root}")
    except OSError as e:
        return ToolResult(ok=False, output=f"Cannot read directory: {e}")
    
    # Search
    results: list[tuple[Path, list[dict[str, Any]]]] = []
    file_count = 0
    skipped = 0
    total_matches = 0
    
    for file_path in all_files:
        # Skip directories
        if not file_path.is_file():
            continue
        
        # Skip hidden and common large directories
        if any(part in SKIP_DIRS or part.startswith('.') for part in file_path.relative_to(root).parts):
            skipped += 1
            continue
        
        # File limit
        if file_count >= MAX_FILES:
            break
        
        # Glob filtering
        rel_path = file_path.relative_to(root)
        if not _matches_glob(rel_path, include_globs, exclude_globs if exclude_globs else None):
            skipped += 1
            continue
        
        file_count += 1
        
        # Search file
        matches = _search_file(file_path, regex, context_lines, root)
        if matches:
            results.append((file_path, matches))
            total_matches += len(matches)
            if total_matches >= MAX_RESULTS:
                break
    
    # Format output
    if not results:
        return ToolResult(ok=True, output="No matches found.")
    
    output = _format_results(results, root)
    
    # Truncate if too large
    if len(output) > MAX_RESULT_SIZE:
        output = output[:MAX_RESULT_SIZE] + f"\n\n... (truncated, showing first {MAX_RESULT_SIZE} chars)"
    
    # Add summary
    output += f"\n\n{total_matches} match(es) in {len(results)} file(s)"
    if file_count >= MAX_FILES:
        output += f" (search stopped at {MAX_FILES} files)"
    if skipped > 0:
        output += f" ({skipped} file(s) skipped)"
    
    return ToolResult(ok=True, output=output)


grep_files_tool = ToolDefinition(
    name="grep_files",
    description=(
        "Search UTF-8 text files under a directory using a regex pattern. "
        "Supports glob-based include/exclude filtering and context lines. "
        "Results are formatted as path:line:content with optional surrounding context."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: current directory)",
            },
            "include": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
                "description": "Glob pattern(s) to include (e.g. '*.py', ['*.ts', '*.tsx']). Only matching files are searched.",
            },
            "exclude": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
                "description": "Glob pattern(s) to exclude (e.g. '*.test.ts', ['*.min.js', '*.generated.*'])",
            },
            "context_lines": {
                "type": "integer",
                "description": "Number of context lines before and after each match (0-5, default: 0)",
                "minimum": 0,
                "maximum": 5,
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case-sensitive search (default: false)",
            },
        },
        "required": ["pattern"],
    },
    validator=_validate,
    run=_run,
)
