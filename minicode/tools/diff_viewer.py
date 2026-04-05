from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any
from minicode.tooling import ToolDefinition, ToolResult


# ---------------------------------------------------------------------------
# Diff Viewer Helpers
# ---------------------------------------------------------------------------

def _colorize_line(line: str) -> str:
    """Add ANSI color codes to diff lines."""
    if line.startswith('+'):
        return f"\033[32m{line}\033[0m"  # Green
    elif line.startswith('-'):
        return f"\033[31m{line}\033[0m"  # Red
    elif line.startswith('@@'):
        return f"\033[36m{line}\033[0m"  # Cyan
    elif line.startswith('---') or line.startswith('+++'):
        return f"\033[1m{line}\033[0m"  # Bold
    else:
        return line


def _generate_diff(old_content: str, new_content: str, old_name: str, new_name: str, context_lines: int = 3) -> str:
    """Generate unified diff between two content strings."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=old_name,
        tofile=new_name,
        n=context_lines,
    )
    
    return ''.join(diff)


def _generate_inline_diff(old_content: str, new_content: str, context_lines: int = 3) -> list[dict[str, Any]]:
    """Generate inline diff showing what changed."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        
        changes.append({
            "type": tag,  # 'replace', 'delete', 'insert'
            "old_start": i1,
            "old_end": i2,
            "new_start": j1,
            "new_end": j2,
            "old_lines": old_lines[i1:i2],
            "new_lines": new_lines[j1:j2],
        })
    
    return changes


def _format_diff_output(diff_text: str, max_lines: int = 100) -> str:
    """Format diff for display."""
    lines = diff_text.split('\n')
    
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"\n... (diff truncated, showing first {max_lines} lines)")
    
    # Add colors (for terminals that support it)
    colored_lines = [_colorize_line(line) for line in lines]
    
    return '\n'.join(colored_lines)


# ---------------------------------------------------------------------------
# Tool Implementation
# ---------------------------------------------------------------------------

def _validate(input_data: dict) -> dict:
    files = input_data.get("files")
    if not isinstance(files, list):
        raise ValueError("files must be a list")
    if not files:
        raise ValueError("files cannot be empty")
    
    for i, file_entry in enumerate(files):
        if not isinstance(file_entry, dict):
            raise ValueError(f"files[{i}] must be an object")
        if "path" not in file_entry:
            raise ValueError(f"files[{i}] must have a 'path' field")
        if "before" not in file_entry and "after" not in file_entry:
            raise ValueError(f"files[{i}] must have 'before' or 'after' field")
    
    context_lines = int(input_data.get("context_lines", 3))
    if context_lines < 1 or context_lines > 10:
        raise ValueError("context_lines must be between 1 and 10")
    format_type = input_data.get("format", "unified")
    if format_type not in ("unified", "inline", "stat"):
        raise ValueError("format must be one of: unified, inline, stat")
    
    return {
        "files": files,
        "context_lines": context_lines,
        "format": format_type,
    }


def _run(input_data: dict, context) -> ToolResult:
    """View diffs between file versions."""
    files = input_data["files"]
    context_lines = input_data["context_lines"]
    format_type = input_data["format"]
    cwd = Path(context.cwd)
    
    all_diffs = []
    total_additions = 0
    total_deletions = 0
    files_with_changes = 0
    
    for file_entry in files:
        file_path = cwd / file_entry["path"]
        old_content = file_entry.get("before", "")
        new_content = file_entry.get("after", "")
        
        # Load from file if not provided
        if old_content == "__file__":
            if file_path.exists():
                old_content = file_path.read_text(encoding="utf-8")
            else:
                old_content = ""
        if new_content == "__file__":
            if file_path.exists():
                new_content = file_path.read_text(encoding="utf-8")
            else:
                new_content = ""
        
        # Skip if no changes
        if old_content == new_content:
            all_diffs.append({
                "file": file_entry["path"],
                "status": "unchanged",
                "diff": "",
            })
            continue
        
        files_with_changes += 1
        
        # Generate diff based on format
        if format_type == "stat":
            # Simple stats
            old_lines = old_content.count('\n') + 1 if old_content else 0
            new_lines = new_content.count('\n') + 1 if new_content else 0
            additions = max(0, new_lines - old_lines)
            deletions = max(0, old_lines - new_lines)
            
            total_additions += additions
            total_deletions += deletions
            
            all_diffs.append({
                "file": file_entry["path"],
                "status": "changed",
                "diff": f"{file_entry['path']}: +{additions} -{deletions} lines",
            })
        elif format_type == "inline":
            # Inline diff
            changes = _generate_inline_diff(old_content, new_content, context_lines)
            
            diff_lines = [f"📄 {file_entry['path']}", ""]
            for change in changes[:10]:  # Limit to 10 changes per file
                if change["type"] == "replace":
                    diff_lines.append(f"  L{change['old_start']+1} → L{change['new_start']+1}:")
                    for line in change["old_lines"]:
                        diff_lines.append(f"    - {line}")
                    for line in change["new_lines"]:
                        diff_lines.append(f"    + {line}")
                elif change["type"] == "delete":
                    diff_lines.append(f"  L{change['old_start']+1}: DELETED")
                    for line in change["old_lines"]:
                        diff_lines.append(f"    - {line}")
                elif change["type"] == "insert":
                    diff_lines.append(f"  L{change['new_start']+1}: INSERTED")
                    for line in change["new_lines"]:
                        diff_lines.append(f"    + {line}")
                
                diff_lines.append("")
            
            all_diffs.append({
                "file": file_entry["path"],
                "status": "changed",
                "diff": "\n".join(diff_lines),
            })
        else:
            # Unified diff (default)
            old_name = f"a/{file_entry['path']}"
            new_name = f"b/{file_entry['path']}"
            diff_text = _generate_diff(old_content, new_content, old_name, new_name, context_lines)
            
            # Count additions and deletions
            for line in diff_text.split('\n'):
                if line.startswith('+') and not line.startswith('+++'):
                    total_additions += 1
                elif line.startswith('-') and not line.startswith('---'):
                    total_deletions += 1
            
            all_diffs.append({
                "file": file_entry["path"],
                "status": "changed",
                "diff": diff_text,
            })
    
    # Format output
    lines = ["🔍 Diff Viewer", "=" * 70, ""]
    
    lines.append(f"Files compared: {len(files)}")
    lines.append(f"Files with changes: {files_with_changes}")
    
    if format_type == "stat":
        lines.append(f"Total additions: +{total_additions} lines")
        lines.append(f"Total deletions: -{total_deletions} lines")
    
    lines.append("")
    lines.append("-" * 70)
    lines.append("")
    
    for diff_entry in all_diffs:
        if diff_entry["status"] == "unchanged":
            lines.append(f"✓ {diff_entry['file']} (no changes)")
        else:
            lines.append(f"📝 {diff_entry['file']}")
            lines.append(diff_entry["diff"])
        
        lines.append("")
        lines.append("-" * 70)
        lines.append("")
    
    if files_with_changes == 0:
        lines.append("✓ All files are identical. No differences found.")
    
    return ToolResult(ok=True, output="\n".join(lines))


diff_viewer_tool = ToolDefinition(
    name="diff_viewer",
    description="View differences between file versions with unified diff, inline diff, or stats. Supports comparing files, showing before/after, or comparing against current file on disk.",
    input_schema={
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "description": "List of files to compare. Each entry: {path, before?, after?}. Use '__file__' to load from disk.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path (for display)"},
                        "before": {"type": "string", "description": "Original content (or '__file__' to load from disk)"},
                        "after": {"type": "string", "description": "New content (or '__file__' to load from disk)"},
                    },
                    "required": ["path"],
                },
            },
            "context_lines": {"type": "number", "description": "Number of context lines around changes (default: 3)"},
            "format": {"type": "string", "enum": ["unified", "inline", "stat"], "description": "Diff format (default: unified)"},
        },
        "required": ["files"],
    },
    validator=_validate,
    run=_run,
)
