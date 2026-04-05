from __future__ import annotations

from pathlib import Path

from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path


def _validate(input_data: dict) -> dict:
    if "path" in input_data and not isinstance(input_data["path"], str):
        raise ValueError("path must be a string")
    return {"path": input_data.get("path", ".")}


def _run(input_data: dict, context) -> ToolResult:
    target = resolve_tool_path(context, input_data["path"], "list")
    if not target.exists():
        return ToolResult(ok=False, output=f"Path does not exist: {input_data['path']}")
    if target.is_file():
        return ToolResult(ok=True, output=f"file {Path(input_data['path']).name}")

    entries = sorted(Path(target).iterdir(), key=lambda item: item.name.lower())
    lines = []
    for entry in entries:
        lines.append(f"{'dir ' if entry.is_dir() else 'file'} {entry.name}")
    return ToolResult(ok=True, output="\n".join(lines[:200]) if lines else "(empty)")


list_files_tool = ToolDefinition(
    name="list_files",
    description="List files and directories relative to the workspace root.",
    input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
    validator=_validate,
    run=_run,
)
