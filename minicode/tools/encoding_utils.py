from __future__ import annotations

import base64
import urllib.parse

from minicode.tooling import ToolDefinition, ToolContext, ToolResult


# ---------------------------------------------------------------------------
# Base64 Encode
# ---------------------------------------------------------------------------

def _validate_base64_encode(input_data: dict) -> dict:
    text = input_data.get("text", "")
    if not isinstance(text, str):
        raise ValueError("text is required and must be a string")
    return {"text": text, "encoding": input_data.get("encoding", "utf-8")}


def _run_base64_encode(input_data: dict, context: ToolContext) -> ToolResult:
    text = input_data["text"]
    encoding = input_data.get("encoding", "utf-8")
    
    try:
        encoded = base64.b64encode(text.encode(encoding)).decode("ascii")
        return ToolResult(ok=True, output=encoded)
    except Exception as e:
        return ToolResult(ok=False, output=f"Encoding error: {e}")


base64_encode_tool = ToolDefinition(
    name="base64_encode",
    description="Encode text to Base64.",
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to encode"},
            "encoding": {"type": "string", "description": "Character encoding (default: utf-8)"}
        },
        "required": ["text"]
    },
    validator=_validate_base64_encode,
    run=_run_base64_encode,
)


# ---------------------------------------------------------------------------
# Base64 Decode
# ---------------------------------------------------------------------------

def _validate_base64_decode(input_data: dict) -> dict:
    text = input_data.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required and must be a non-empty string")
    return {"text": text.strip(), "encoding": input_data.get("encoding", "utf-8")}


def _run_base64_decode(input_data: dict, context: ToolContext) -> ToolResult:
    text = input_data["text"]
    encoding = input_data.get("encoding", "utf-8")
    
    try:
        decoded = base64.b64decode(text.encode("ascii")).decode(encoding)
        return ToolResult(ok=True, output=decoded)
    except Exception as e:
        return ToolResult(ok=False, output=f"Decoding error: {e}")


base64_decode_tool = ToolDefinition(
    name="base64_decode",
    description="Decode Base64 to text.",
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Base64 string to decode"},
            "encoding": {"type": "string", "description": "Output character encoding (default: utf-8)"}
        },
        "required": ["text"]
    },
    validator=_validate_base64_decode,
    run=_run_base64_decode,
)


# ---------------------------------------------------------------------------
# URL Encode
# ---------------------------------------------------------------------------

def _validate_url_encode(input_data: dict) -> dict:
    text = input_data.get("text", "")
    if not isinstance(text, str):
        raise ValueError("text is required and must be a string")
    return {"text": text, "safe": input_data.get("safe", "/")}


def _run_url_encode(input_data: dict, context: ToolContext) -> ToolResult:
    text = input_data["text"]
    safe = input_data.get("safe", "/")
    
    encoded = urllib.parse.quote(text, safe=safe)
    return ToolResult(ok=True, output=encoded)


url_encode_tool = ToolDefinition(
    name="url_encode",
    description="URL-encode text (percent-encoding).",
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to encode"},
            "safe": {"type": "string", "description": "Characters to keep unencoded (default: /)"}
        },
        "required": ["text"]
    },
    validator=_validate_url_encode,
    run=_run_url_encode,
)


# ---------------------------------------------------------------------------
# URL Decode
# ---------------------------------------------------------------------------

def _validate_url_decode(input_data: dict) -> dict:
    text = input_data.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required and must be a non-empty string")
    return {"text": text.strip()}


def _run_url_decode(input_data: dict, context: ToolContext) -> ToolResult:
    text = input_data["text"]
    
    try:
        decoded = urllib.parse.unquote(text)
        return ToolResult(ok=True, output=decoded)
    except Exception as e:
        return ToolResult(ok=False, output=f"Decoding error: {e}")


url_decode_tool = ToolDefinition(
    name="url_decode",
    description="URL-decode text (percent-decoding).",
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "URL-encoded text to decode"}
        },
        "required": ["text"]
    },
    validator=_validate_url_decode,
    run=_run_url_decode,
)