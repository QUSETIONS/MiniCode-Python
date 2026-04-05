from __future__ import annotations

from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path

DEFAULT_READ_LIMIT = 8000
MAX_READ_LIMIT = 20000


def _validate(input_data: dict) -> dict:
    path = input_data.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("path is required")
    offset = int(input_data.get("offset", 0))
    limit = int(input_data.get("limit", DEFAULT_READ_LIMIT))
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit < 1 or limit > MAX_READ_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_READ_LIMIT}")
    return {"path": path, "offset": offset, "limit": limit}


def _run(input_data: dict, context) -> ToolResult:
    target = resolve_tool_path(context, input_data["path"], "read")
    
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult(
            ok=False,
            output=f"File {input_data['path']} appears to be binary. Cannot read as text.",
        )
    
    offset = input_data["offset"]
    limit = input_data["limit"]
    end = min(len(content), offset + limit)
    chunk = content[offset:end]
    truncated = end < len(content)
    header = "\n".join(
        [
            f"FILE: {input_data['path']}",
            f"OFFSET: {offset}",
            f"END: {end}",
            f"TOTAL_CHARS: {len(content)}",
            f"TRUNCATED: {'yes - call read_file again with offset ' + str(end) if truncated else 'no'}",
            "",
        ]
    )
    return ToolResult(ok=True, output=header + chunk)


read_file_tool = ToolDefinition(
    name="read_file",
    description="Read a UTF-8 text file relative to the workspace root.",
    input_schema={"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "number"}, "limit": {"type": "number"}}, "required": ["path"]},
    validator=_validate,
    run=_run,
)

