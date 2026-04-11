from __future__ import annotations

import json
from pathlib import Path

from minicode.tooling import ToolDefinition, ToolContext, ToolResult


def _validate(input_data: dict) -> dict:
    """Validate input for json_format tool."""
    content = input_data.get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content is required and must be a non-empty string")
    return {"content": content.strip()}


def _run(input_data: dict, context: ToolContext) -> ToolResult:
    """Format and validate JSON content."""
    content = input_data["content"]
    try:
        parsed = json.loads(content)
        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
        return ToolResult(ok=True, output=formatted)
    except json.JSONDecodeError as e:
        return ToolResult(ok=False, output=f"Invalid JSON: {e}")


json_format_tool = ToolDefinition(
    name="json_format",
    description="Format and validate JSON content. Pretty-prints JSON with proper indentation.",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "JSON string to format"}
        },
        "required": ["content"]
    },
    validator=_validate,
    run=_run,
)


# ---------------------------------------------------------------------------
# JSON Parse Tool
# ---------------------------------------------------------------------------

def _validate_parse(input_data: dict) -> dict:
    """Validate input for json_parse tool."""
    content = input_data.get("content", "")
    path = input_data.get("path", "")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content is required and must be a non-empty string")
    return {"content": content.strip(), "path": path.strip() if path else ""}


def _run_parse(input_data: dict, context: ToolContext) -> ToolResult:
    """Parse JSON and optionally extract a specific path."""
    content = input_data["content"]
    path = input_data.get("path", "")
    
    try:
        parsed = json.loads(content)
        
        # Extract path if specified
        if path:
            keys = path.split(".")
            current = parsed
            for key in keys:
                if isinstance(current, dict):
                    current = current.get(key)
                elif isinstance(current, list):
                    try:
                        idx = int(key)
                        current = current[idx]
                    except (ValueError, IndexError):
                        return ToolResult(ok=False, output=f"Invalid path: {path}")
                else:
                    return ToolResult(ok=False, output=f"Cannot index into {type(current)}")
            
            if current is None:
                return ToolResult(ok=False, output=f"Path not found: {path}")
            return ToolResult(ok=True, output=json.dumps(current, indent=2, ensure_ascii=False))
        
        return ToolResult(ok=True, output=json.dumps(parsed, indent=2, ensure_ascii=False))
    except json.JSONDecodeError as e:
        return ToolResult(ok=False, output=f"Invalid JSON: {e}")


json_parse_tool = ToolDefinition(
    name="json_parse",
    description="Parse JSON and extract values by dot-notation path (e.g., 'data.items.0.name').",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "JSON string to parse"},
            "path": {"type": "string", "description": "Optional dot-notation path to extract (e.g., 'data.0.name')"}
        },
        "required": ["content"]
    },
    validator=_validate_parse,
    run=_run_parse,
)
