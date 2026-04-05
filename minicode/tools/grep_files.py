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
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for index, line in enumerate(lines, start=1):
            if regex.search(line):
                results.append(f"{file_path.relative_to(Path(context.cwd)).as_posix()}:{index}:{line}")
    return ToolResult(ok=True, output="\n".join(results) if results else "No matches found.")


grep_files_tool = ToolDefinition(
    name="grep_files",
    description="Search UTF-8 text files under the workspace using a regex pattern.",
    input_schema={"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]},
    validator=_validate,
    run=_run,
)

