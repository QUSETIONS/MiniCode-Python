from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from minicode.tooling import ToolDefinition, ToolContext, ToolResult


# ---------------------------------------------------------------------------
# UUID Generate
# ---------------------------------------------------------------------------

def _run_uuid_generate(input_data: dict, context: ToolContext) -> ToolResult:
    count = input_data.get("count", 1)
    version = input_data.get("version", 4)
    
    if not 1 <= count <= 100:
        return ToolResult(ok=False, output="count must be between 1 and 100")
    
    if version == 1:
        uuids = [str(uuid.uuid1()) for _ in range(count)]
    elif version == 4:
        uuids = [str(uuid.uuid4()) for _ in range(count)]
    elif version == 7:
        # UUID v7 is not in stdlib, use uuid4 as fallback
        uuids = [str(uuid.uuid4()) for _ in range(count)]
    else:
        return ToolResult(ok=False, output="version must be 1 or 4")
    
    output = "\n".join(uuids) if count > 1 else uuids[0]
    return ToolResult(ok=True, output=output)


uuid_generate_tool = ToolDefinition(
    name="uuid_generate",
    description="Generate UUIDs (version 1 or 4).",
    input_schema={
        "type": "object",
        "properties": {
            "count": {"type": "number", "description": "Number of UUIDs to generate (1-100)"},
            "version": {"type": "number", "description": "UUID version: 1 (timestamp) or 4 (random)"}
        }
    },
    validator=lambda x: x,
    run=_run_uuid_generate,
)


# ---------------------------------------------------------------------------
# Text Sort
# ---------------------------------------------------------------------------

def _validate_text_sort(input_data: dict) -> dict:
    content = input_data.get("content", "")
    if not isinstance(content, str):
        raise ValueError("content is required")
    return {
        "content": content,
        "reverse": input_data.get("reverse", False),
        "numeric": input_data.get("numeric", False),
        "ignore_case": input_data.get("ignore_case", False),
    }


def _run_text_sort(input_data: dict, context: ToolContext) -> ToolResult:
    content = input_data["content"]
    reverse = input_data.get("reverse", False)
    numeric = input_data.get("numeric", False)
    ignore_case = input_data.get("ignore_case", False)
    
    lines = content.strip().split("\n")
    
    # Filter empty lines for sorting, keep them at end
    non_empty = [line for line in lines if line.strip()]
    empty = [line for line in lines if not line.strip()]
    
    # Sort
    if numeric:
        try:
            non_empty.sort(key=lambda x: float(x.strip()), reverse=reverse)
        except ValueError:
            return ToolResult(ok=False, output="Cannot sort numerically - invalid numbers")
    elif ignore_case:
        non_empty.sort(key=lambda x: x.lower(), reverse=reverse)
    else:
        non_empty.sort(reverse=reverse)
    
    result = non_empty + empty
    return ToolResult(ok=True, output="\n".join(result))


text_sort_tool = ToolDefinition(
    name="text_sort",
    description="Sort text lines (alphabetically or numerically).",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Text to sort (one line per item)"},
            "reverse": {"type": "boolean", "description": "Sort in descending order"},
            "numeric": {"type": "boolean", "description": "Sort numerically"},
            "ignore_case": {"type": "boolean", "description": "Case-insensitive sorting"}
        },
        "required": ["content"]
    },
    validator=_validate_text_sort,
    run=_run_text_sort,
)


# ---------------------------------------------------------------------------
# Text Dedupe
# ---------------------------------------------------------------------------

def _validate_text_dedupe(input_data: dict) -> dict:
    content = input_data.get("content", "")
    if not isinstance(content, str):
        raise ValueError("content is required")
    return {"content": content, "preserve_order": input_data.get("preserve_order", True)}


def _run_text_dedupe(input_data: dict, context: ToolContext) -> ToolResult:
    content = input_data["content"]
    preserve_order = input_data.get("preserve_order", True)
    
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    
    if preserve_order:
        seen = set()
        result = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                result.append(line)
    else:
        result = list(set(lines))
    
    return ToolResult(ok=True, output="\n".join(result))


text_dedupe_tool = ToolDefinition(
    name="text_dedupe",
    description="Remove duplicate lines from text.",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Text with potential duplicates"},
            "preserve_order": {"type": "boolean", "description": "Keep first occurrence order (default: true)"}
        },
        "required": ["content"]
    },
    validator=_validate_text_dedupe,
    run=_run_text_dedupe,
)


# ---------------------------------------------------------------------------
# Text Join
# ---------------------------------------------------------------------------

def _validate_text_join(input_data: dict) -> dict:
    items = input_data.get("items", "")
    separator = input_data.get("separator", "\n")
    if not isinstance(items, str):
        raise ValueError("items is required")
    return {"items": items, "separator": separator}


def _run_text_join(input_data: dict, context: ToolContext) -> ToolResult:
    items = input_data["items"]
    separator = input_data.get("separator", "\n")
    
    lines = [line.strip() for line in items.strip().split("\n") if line.strip()]
    result = separator.join(lines)
    
    return ToolResult(ok=True, output=result)


text_join_tool = ToolDefinition(
    name="text_join",
    description="Join lines with a custom separator.",
    input_schema={
        "type": "object",
        "properties": {
            "items": {"type": "string", "description": "Lines to join (one per line)"},
            "separator": {"type": "string", "description": "Separator (default: newline)"}
        },
        "required": ["items"]
    },
    validator=_validate_text_join,
    run=_run_text_join,
)


# ---------------------------------------------------------------------------
# Line Count
# ---------------------------------------------------------------------------

def _run_line_count(input_data: dict, context: ToolContext) -> ToolResult:
    content = input_data.get("content", "")
    
    lines = content.split("\n")
    total = len(lines)
    non_empty = len([l for l in lines if l.strip()])
    empty = total - non_empty
    
    output = f"""Lines:
  Total: {total}
  Non-empty: {non_empty}
  Empty: {empty}
  Characters: {len(content)}"""
    
    return ToolResult(ok=True, output=output)


line_count_tool = ToolDefinition(
    name="line_count",
    description="Count lines, characters in text.",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Text to analyze"}
        },
        "required": ["content"]
    },
    validator=lambda x: x,
    run=_run_line_count,
)


# ---------------------------------------------------------------------------
# Random String
# ---------------------------------------------------------------------------

def _run_random_string(input_data: dict, context: ToolContext) -> ToolResult:
    length = input_data.get("length", 16)
    chars = input_data.get("chars", "alphanumeric")
    
    if not 1 <= length <= 1000:
        return ToolResult(ok=False, output="length must be between 1 and 1000")
    
    import random
    import string
    
    if chars == "alphanumeric":
        alphabet = string.ascii_letters + string.digits
    elif chars == "alpha":
        alphabet = string.ascii_letters
    elif chars == "numeric":
        alphabet = string.digits
    elif chars == "hex":
        alphabet = string.hexdigits.lower()
    elif chars == "ascii":
        alphabet = string.printable
    else:
        alphabet = chars
    
    result = "".join(random.choice(alphabet) for _ in range(length))
    return ToolResult(ok=True, output=result)


random_string_tool = ToolDefinition(
    name="random_string",
    description="Generate random string.",
    input_schema={
        "type": "object",
        "properties": {
            "length": {"type": "number", "description": "String length (1-1000)"},
            "chars": {"type": "string", "description": "Character set: alphanumeric, alpha, numeric, hex, ascii, or custom string"}
        }
    },
    validator=lambda x: x,
    run=_run_random_string,
)