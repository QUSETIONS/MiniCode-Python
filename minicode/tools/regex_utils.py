from __future__ import annotations

import re

from minicode.tooling import ToolDefinition, ToolContext, ToolResult


def _validate_regex_test(input_data: dict) -> dict:
    """Validate input for regex_test tool."""
    pattern = input_data.get("pattern", "")
    text = input_data.get("text", "")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern is required and must be a non-empty string")
    if not isinstance(text, str):
        raise ValueError("text is required and must be a string")
    flags = input_data.get("flags", "")
    return {"pattern": pattern.strip(), "text": text, "flags": flags.strip()}


def _run_regex_test(input_data: dict, context: ToolContext) -> ToolResult:
    """Test a regex pattern against text."""
    pattern = input_data["pattern"]
    text = input_data["text"]
    flags = input_data.get("flags", "")
    
    # Parse flags
    flag_bits = 0
    if "i" in flags:
        flag_bits |= re.IGNORECASE
    if "m" in flags:
        flag_bits |= re.MULTILINE
    if "s" in flags:
        flag_bits |= re.DOTALL
    
    try:
        regex = re.compile(pattern, flag_bits)
        matches = list(regex.finditer(text))
        
        if not matches:
            return ToolResult(ok=True, output="No matches found")
        
        # Build result
        lines = [f"Found {len(matches)} match(es):"]
        for i, match in enumerate(matches, 1):
            lines.append(f"\n--- Match {i} ---")
            lines.append(f"Full match: '{match.group(0)}'")
            lines.append(f"Span: {match.span()}")
            if match.groups():
                lines.append(f"Groups: {match.groups()}")
            if match.groupdict():
                lines.append(f"Named groups: {match.groupdict()}")
        
        return ToolResult(ok=True, output="\n".join(lines))
    except re.error as e:
        return ToolResult(ok=False, output=f"Invalid regex: {e}")


regex_test_tool = ToolDefinition(
    name="regex_test",
    description="Test a regex pattern against text. Shows all matches with groups and spans.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression pattern"},
            "text": {"type": "string", "description": "Text to search"},
            "flags": {"type": "string", "description": "Flags: i=ignore case, m=multiline, s=dotall"}
        },
        "required": ["pattern", "text"]
    },
    validator=_validate_regex_test,
    run=_run_regex_test,
)


# ---------------------------------------------------------------------------
# Regex Replace Tool
# ---------------------------------------------------------------------------

def _validate_regex_replace(input_data: dict) -> dict:
    """Validate input for regex_replace tool."""
    pattern = input_data.get("pattern", "")
    text = input_data.get("text", "")
    replacement = input_data.get("replacement", "")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern is required and must be a non-empty string")
    if not isinstance(text, str):
        raise ValueError("text is required and must be a string")
    if not isinstance(replacement, str):
        raise ValueError("replacement is required and must be a string")
    flags = input_data.get("flags", "")
    return {"pattern": pattern.strip(), "text": text, "replacement": replacement, "flags": flags.strip()}


def _run_regex_replace(input_data: dict, context: ToolContext) -> ToolResult:
    """Replace regex matches in text."""
    pattern = input_data["pattern"]
    text = input_data["text"]
    replacement = input_data["replacement"]
    flags = input_data.get("flags", "")
    
    # Parse flags
    flag_bits = 0
    if "i" in flags:
        flag_bits |= re.IGNORECASE
    if "m" in flags:
        flag_bits |= re.MULTILINE
    if "s" in flags:
        flag_bits |= re.DOTALL
    
    try:
        regex = re.compile(pattern, flag_bits)
        result, count = regex.subn(replacement, text)
        
        output = f"Replaced {count} match(es):\n\n--- Result ---\n{result}"
        return ToolResult(ok=True, output=output)
    except re.error as e:
        return ToolResult(ok=False, output=f"Invalid regex: {e}")


regex_replace_tool = ToolDefinition(
    name="regex_replace",
    description="Replace regex matches in text. Returns the modified text and match count.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression pattern"},
            "text": {"type": "string", "description": "Text to search and replace"},
            "replacement": {"type": "string", "description": "Replacement text (supports \\1, \\2, etc.)"},
            "flags": {"type": "string", "description": "Flags: i=ignore case, m=multiline, s=dotall"}
        },
        "required": ["pattern", "text", "replacement"]
    },
    validator=_validate_regex_replace,
    run=_run_regex_replace,
)
