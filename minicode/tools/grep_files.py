from __future__ import annotations

import re
from pathlib import Path

from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path


def _validate(input_data: dict) -> dict:
    pattern = input_data.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern is required")
    return {
        "pattern": pattern,
        "path": input_data.get("path", "."),
    }


def _run(input_data: dict, context) -> ToolResult:
    root = resolve_tool_path(context, input_data["path"], "search")
    regex = re.compile(input_data["pattern"])
    results: list[str] = []
    skipped = 0
    file_count = 0
    
    # 跳过常见大目录
    SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', 'dist', 'build'}
    MAX_FILES = 5000

    try:
        all_files = sorted(root.rglob("*"))
    except PermissionError:
        return ToolResult(ok=False, output=f"Permission denied: {root}")
    except OSError as e:
        return ToolResult(ok=False, output=f"Cannot read directory: {e}")

    for file_path in all_files:
        # 跳过大目录
        if any(part in SKIP_DIRS for part in file_path.parts):
            skipped += 1
            continue
            
        # 限制文件数量
        if file_count >= MAX_FILES:
            output = "\n".join(results) if results else "No matches found."
            output += f"\n\n⚠️ Results truncated at {MAX_FILES} files. Try a more specific path."
            return ToolResult(ok=True, output=output)
        
        file_count += 1
        
        if not file_path.is_file():
            continue
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            skipped += 1
            continue
        except OSError:
            skipped += 1
            continue
        for index, line in enumerate(lines, start=1):
            if regex.search(line):
                results.append(f"{file_path.relative_to(Path(context.cwd)).as_posix()}:{index}:{line}")
    
    output = "\n".join(results) if results else "No matches found."
    if skipped > 0:
        output += f"\n({skipped} file(s) skipped)"
    return ToolResult(ok=True, output=output)


grep_files_tool = ToolDefinition(
    name="grep_files",
    description="Search UTF-8 text files under the workspace using a regex pattern.",
    input_schema={"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]},
    validator=_validate,
    run=_run,
)

