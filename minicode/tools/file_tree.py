from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path


# ---------------------------------------------------------------------------
# File Tree Helpers
# ---------------------------------------------------------------------------

def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


def _format_time(timestamp: float) -> str:
    """Format timestamp in human-readable format."""
    dt = datetime.fromtimestamp(timestamp)
    now = time.time()
    diff = now - timestamp
    
    if diff < 3600:
        mins = int(diff / 60)
        return f"{mins}m ago"
    elif diff < 86400:
        hours = int(diff / 3600)
        return f"{hours}h ago"
    elif diff < 604800:
        days = int(diff / 86400)
        return f"{days}d ago"
    else:
        return dt.strftime("%Y-%m-%d")


def _get_file_icon(file_path: Path) -> str:
    """Get icon based on file extension."""
    ext = file_path.suffix.lower()
    icons = {
        '.py': '🐍',
        '.js': '📜',
        '.ts': '🔷',
        '.jsx': '⚛️',
        '.tsx': '⚛️',
        '.html': '🌐',
        '.css': '🎨',
        '.md': '📝',
        '.json': '📋',
        '.yaml': '⚙️',
        '.yml': '⚙️',
        '.toml': '⚙️',
        '.txt': '📄',
        '.log': '📃',
        '.sh': '🖥️',
        '.bat': '🖥️',
        '.gitignore': '🚫',
        '.env': '🔒',
        '.lock': '🔒',
        '.png': '🖼️',
        '.jpg': '🖼️',
        '.jpeg': '🖼️',
        '.svg': '🎭',
        '.ipynb': '📓',
    }
    if file_path.name == 'README':
        return '📖'
    return icons.get(ext, '📄')


def _get_file_status_color(file_path: Path) -> str:
    """Get status indicator based on file modification time."""
    now = time.time()
    age = now - file_path.stat().st_mtime
    
    if age < 3600:  # Modified within 1 hour
        return "🟢"
    elif age < 86400:  # Modified within 24 hours
        return "🟡"
    else:
        return "⚪"


def _build_tree(
    path: Path,
    prefix: str = "",
    is_last: bool = True,
    max_depth: int = 3,
    current_depth: int = 0,
    show_hidden: bool = False,
    ignore_dirs: set[str] | None = None,
) -> list[str]:
    """Build file tree with proper formatting."""
    if ignore_dirs is None:
        ignore_dirs = {'.git', '__pycache__', 'venv', 'env', '.tox', 'node_modules', '.mypy_cache', '.pytest_cache'}
    
    lines = []
    
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return [f"{prefix}{'└── ' if is_last else '├── '}🔒 Permission denied"]
    
    # Filter hidden files
    if not show_hidden:
        entries = [e for e in entries if not e.name.startswith('.')]
    
    # Filter ignored directories
    if path.is_dir():
        entries = [e for e in entries if not (e.is_dir() and e.name in ignore_dirs)]
    
    for i, entry in enumerate(entries):
        is_last_entry = (i == len(entries) - 1)
        
        # Choose connector
        connector = "└── " if is_last_entry else "├── "
        extension = "    " if is_last_entry else "│   "
        
        if entry.is_dir():
            icon = "📁"
            lines.append(f"{prefix}{connector}{icon} {entry.name}")
            
            if current_depth < max_depth:
                lines.extend(_build_tree(
                    entry,
                    prefix + extension,
                    is_last_entry,
                    max_depth,
                    current_depth + 1,
                    show_hidden,
                    ignore_dirs,
                ))
            else:
                lines.append(f"{prefix}{extension}    ...")
        else:
            icon = _get_file_icon(entry)
            status = _get_file_status_color(entry)
            size = _format_size(entry.stat().st_size)
            mod_time = _format_time(entry.stat().st_mtime)
            
            lines.append(f"{prefix}{connector}{status} {icon} {entry.name} ({size}, {mod_time})")
    
    return lines


# ---------------------------------------------------------------------------
# Tool Implementation
# ---------------------------------------------------------------------------

def _validate(input_data: dict) -> dict:
    path = input_data.get("path", ".")
    max_depth = int(input_data.get("max_depth", 3))
    if max_depth < 1 or max_depth > 10:
        raise ValueError("max_depth must be between 1 and 10")
    show_hidden = input_data.get("show_hidden", False)
    if not isinstance(show_hidden, bool):
        raise ValueError("show_hidden must be a boolean")
    
    pattern = input_data.get("pattern")
    
    return {
        "path": path,
        "max_depth": max_depth,
        "show_hidden": show_hidden,
        "pattern": pattern,
    }


def _run(input_data: dict, context) -> ToolResult:
    """Display file tree."""
    try:
        target = resolve_tool_path(context, input_data["path"], "list")
    except (PermissionError, RuntimeError) as error:
        return ToolResult(ok=False, output=str(error))
    max_depth = input_data["max_depth"]
    show_hidden = input_data["show_hidden"]
    pattern = input_data.get("pattern")
    
    if not target.exists():
        return ToolResult(ok=False, output=f"Path not found: {target}")
    
    # Build tree
    tree_lines = _build_tree(
        target,
        max_depth=max_depth,
        show_hidden=show_hidden,
    )
    
    # Apply pattern filter if provided
    if pattern:
        import fnmatch
        tree_lines = [
            line for line in tree_lines
            if fnmatch.fnmatch(line, f"*{pattern}*")
        ]
        if not tree_lines:
            return ToolResult(
                ok=True,
                output=f"No files match pattern '{pattern}'",
            )
    
    # Count stats
    try:
        total_files = sum(1 for _ in target.rglob("*") if _.is_file() and not _.name.startswith('.'))
        total_dirs = sum(1 for _ in target.rglob("*") if _.is_dir() and not _.name.startswith('.'))
    except Exception:
        total_files = 0
        total_dirs = 0
    
    # Format output
    lines = [
        f"📂 File Tree: {input_data['path']}",
        "=" * 60,
        "",
    ]
    
    # Add target name at root
    if target.is_dir():
        lines.append(f"📁 {target.name}")
        for line in tree_lines:
            lines.append(f"  {line}")
    else:
        for line in tree_lines:
            lines.append(line)
    
    lines.extend([
        "",
        "-" * 60,
        f"📊 Stats:",
        f"  Files: {total_files}",
        f"  Directories: {total_dirs}",
        f"  Max depth shown: {max_depth}",
    ])
    
    # Legend
    lines.extend([
        "",
        "🎨 Legend:",
        "  🟢 Modified < 1h ago",
        "  🟡 Modified < 24h ago",
        "  ⚪ Modified > 24h ago",
    ])
    
    return ToolResult(ok=True, output="\n".join(lines))


file_tree_tool = ToolDefinition(
    name="file_tree",
    description="Display a visual file tree with file sizes, modification times, and type icons. Supports filtering by pattern and controlling depth.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory or file path to display (default: current directory)"},
            "max_depth": {"type": "number", "description": "Maximum depth to display (default: 3, max: 10)"},
            "show_hidden": {"type": "boolean", "description": "Show hidden files (starting with .) (default: false)"},
            "pattern": {"type": "string", "description": "Filter files by glob pattern (e.g., '*.py', 'test_*')"},
        },
    },
    validator=_validate,
    run=_run,
)
