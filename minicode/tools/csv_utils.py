from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from minicode.tooling import ToolDefinition, ToolContext, ToolResult


# ---------------------------------------------------------------------------
# CSV Parse
# ---------------------------------------------------------------------------

def _validate_csv_parse(input_data: dict) -> dict:
    content = input_data.get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content is required and must be a non-empty string")
    return {
        "content": content.strip(),
        "delimiter": input_data.get("delimiter", ","),
        "has_header": input_data.get("has_header", True),
    }


def _run_csv_parse(input_data: dict, context: ToolContext) -> ToolResult:
    content = input_data["content"]
    delimiter = input_data.get("delimiter", ",")
    has_header = input_data.get("has_header", True)
    
    try:
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        rows = list(reader)
        
        if not rows:
            return ToolResult(ok=True, output="Empty CSV")
        
        if has_header:
            headers = rows[0]
            data = rows[1:]
            # Convert to list of dicts
            result = [dict(zip(headers, row)) for row in data]
            output = json.dumps(result, indent=2, ensure_ascii=False)
        else:
            output = json.dumps(rows, indent=2, ensure_ascii=False)
        
        return ToolResult(ok=True, output=output)
    except Exception as e:
        return ToolResult(ok=False, output=f"CSV parse error: {e}")


csv_parse_tool = ToolDefinition(
    name="csv_parse",
    description="Parse CSV data to JSON. Supports custom delimiter.",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "CSV content"},
            "delimiter": {"type": "string", "description": "Delimiter (default: ,)"},
            "has_header": {"type": "boolean", "description": "First row is header (default: true)"}
        },
        "required": ["content"]
    },
    validator=_validate_csv_parse,
    run=_run_csv_parse,
)


# ---------------------------------------------------------------------------
# CSV Create
# ---------------------------------------------------------------------------

def _validate_csv_create(input_data: dict) -> dict:
    data = input_data.get("data", "")
    if not isinstance(data, str) or not data.strip():
        raise ValueError("data is required (JSON array)")
    return {
        "data": data.strip(),
        "delimiter": input_data.get("delimiter", ","),
        "include_header": input_data.get("include_header", True),
    }


def _run_csv_create(input_data: dict, context: ToolContext) -> ToolResult:
    data_str = input_data["data"]
    delimiter = input_data.get("delimiter", ",")
    include_header = input_data.get("include_header", True)
    
    try:
        data = json.loads(data_str)
        
        if not data:
            return ToolResult(ok=True, output="")
        
        output = io.StringIO()
        
        if isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], dict):
                # List of dicts
                if include_header:
                    writer = csv.DictWriter(output, fieldnames=data[0].keys(), delimiter=delimiter)
                    writer.writeheader()
                    writer.writerows(data)
                else:
                    writer = csv.writer(output, delimiter=delimiter)
                    writer.writerow(list(data[0].keys()))
                    for row in data:
                        writer.writerow(row.values())
            else:
                # List of lists
                writer = csv.writer(output, delimiter=delimiter)
                writer.writerows(data)
        else:
            return ToolResult(ok=False, output="Data must be a non-empty array")
        
        return ToolResult(ok=True, output=output.getvalue())
    except Exception as e:
        return ToolResult(ok=False, output=f"CSV create error: {e}")


csv_create_tool = ToolDefinition(
    name="csv_create",
    description="Create CSV from JSON data.",
    input_schema={
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "JSON array data"},
            "delimiter": {"type": "string", "description": "Delimiter (default: ,)"},
            "include_header": {"type": "boolean", "description": "Include header row (default: true)"}
        },
        "required": ["data"]
    },
    validator=_validate_csv_create,
    run=_run_csv_create,
)