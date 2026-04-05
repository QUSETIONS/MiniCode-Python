from __future__ import annotations

import subprocess
import sys
import re
from pathlib import Path
from typing import Any
from minicode.tooling import ToolDefinition, ToolResult


# ---------------------------------------------------------------------------
# Debug Output Parsers
# ---------------------------------------------------------------------------

def _parse_python_error(output: str, cwd: str) -> list[dict[str, Any]]:
    """Parse Python traceback and extract error locations."""
    errors = []
    
    # Pattern for Python tracebacks
    traceback_pattern = re.compile(
        r'File "([^"]+)", line (\d+), in (.+)',
        re.MULTILINE,
    )
    
    # Pattern for the actual error
    error_pattern = re.compile(
        r'(\w+Error|\w+Exception): (.+)',
        re.MULTILINE,
    )
    
    # Find all traceback frames
    frames = traceback_pattern.findall(output)
    error_match = error_pattern.search(output)
    
    if error_match:
        error_type = error_match.group(1)
        error_message = error_match.group(2)
    else:
        error_type = "UnknownError"
        error_message = output[:200]
    
    # Extract context around each frame
    for file_path, line_num, func_name in frames:
        abs_path = Path(file_path) if Path(file_path).is_absolute() else Path(cwd) / file_path
        
        context_lines = []
        if abs_path.exists():
            try:
                content = abs_path.read_text(encoding="utf-8")
                lines = content.split("\n")
                line_idx = int(line_num) - 1
                
                # Get surrounding context (±2 lines)
                start = max(0, line_idx - 2)
                end = min(len(lines), line_idx + 3)
                
                for i in range(start, end):
                    marker = "→ " if i == line_idx else "  "
                    context_lines.append(f"{marker}{i+1:4d} | {lines[i]}")
            except Exception:
                context_lines = ["Unable to read file"]
        
        errors.append({
            "file": str(abs_path.relative_to(cwd)) if str(abs_path).startswith(cwd) else file_path,
            "line": int(line_num),
            "function": func_name,
            "context": "\n".join(context_lines),
        })
    
    # If no frames found, try to extract line from error message
    if not errors:
        line_match = re.search(r'line (\d+)', error_message)
        if line_match:
            errors.append({
                "file": "unknown",
                "line": int(line_match.group(1)),
                "function": "unknown",
                "context": "",
            })
    
    return {
        "type": error_type,
        "message": error_message,
        "frames": errors,
    }


def _parse_node_error(output: str, cwd: str) -> dict[str, Any]:
    """Parse Node.js error output."""
    # Pattern for Node.js stack traces
    stack_pattern = re.compile(r'at .+ \((.+):(\d+):(\d+)\)', re.MULTILINE)
    error_pattern = re.compile(r'(\w+Error|\w+Exception): (.+)', re.MULTILINE)
    
    error_match = error_pattern.search(output)
    if error_match:
        error_type = error_match.group(1)
        error_message = error_match.group(2)
    else:
        error_type = "UnknownError"
        error_message = output[:200]
    
    frames = []
    for match in stack_pattern.finditer(output):
        file_path, line_num, col_num = match.groups()
        frames.append({
            "file": file_path,
            "line": int(line_num),
            "column": int(col_num),
        })
    
    return {
        "type": error_type,
        "message": error_message,
        "frames": frames[:5],  # Limit to 5 frames
    }


def _parse_generic_error(output: str) -> dict[str, Any]:
    """Parse generic error output."""
    # Try to find any error-like patterns
    error_patterns = [
        r'(?:error|ERROR|Error|fatal|FATAL|warning|WARNING)[:\s]+(.+)',
        r'failed to (.+)',
        r'cannot (.+)',
        r'invalid (.+)',
    ]
    
    for pattern in error_patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return {
                "type": "Error",
                "message": match.group(1) if match.lastindex else output[:200],
                "frames": [],
            }
    
    return {
        "type": "Error",
        "message": output[:200],
        "frames": [],
    }


# ---------------------------------------------------------------------------
# Tool Implementation
# ---------------------------------------------------------------------------

def _validate(input_data: dict) -> dict:
    command = input_data.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command is required and must be non-empty")
    
    cwd = input_data.get("cwd", ".")
    timeout = int(input_data.get("timeout", 30))
    if timeout < 1 or timeout > 300:
        raise ValueError("timeout must be between 1 and 300 seconds")
    
    language = input_data.get("language", "auto")
    if language not in ("auto", "python", "node", "generic"):
        raise ValueError("language must be one of: auto, python, node, generic")
    
    return {
        "command": command.strip(),
        "cwd": cwd,
        "timeout": timeout,
        "language": language,
    }


def _run(input_data: dict, context) -> ToolResult:
    """Run command with debug output parsing."""
    command = input_data["command"]
    work_dir = Path(context.cwd) / input_data["cwd"]
    timeout = input_data["timeout"]
    language = input_data["language"]
    
    if not work_dir.exists():
        return ToolResult(ok=False, output=f"Working directory not found: {work_dir}")
    
    # Determine shell
    if sys.platform == "win32":
        shell_cmd = ["cmd", "/c", command]
    else:
        shell_cmd = ["/bin/sh", "-c", command]
    
    try:
        result = subprocess.run(
            shell_cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        success = result.returncode == 0
        stdout = result.stdout
        stderr = result.stderr
        
    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False,
            output=f"❌ Command timed out after {timeout} seconds\n\nCommand: {command}",
        )
    except FileNotFoundError:
        return ToolResult(
            ok=False,
            output=f"❌ Command not found\n\nCommand: {command}",
        )
    except Exception as e:
        return ToolResult(
            ok=False,
            output=f"❌ Execution error: {e}\n\nCommand: {command}",
        )
    
    # Parse errors if any
    error_output = stderr if stderr else stdout
    parsed_error = None
    
    if not success and error_output:
        if language == "python" or (language == "auto" and "python" in command.lower()):
            parsed_error = _parse_python_error(error_output, str(work_dir))
        elif language == "node" or (language == "auto" and "node" in command.lower()):
            parsed_error = _parse_node_error(error_output, str(work_dir))
        else:
            parsed_error = _parse_generic_error(error_output)
    
    # Format output
    lines = []
    
    if success:
        lines.append("✓ Command succeeded")
        lines.append("")
        if stdout:
            lines.append("Output:")
            lines.append(stdout[:5000])  # Limit output
            if len(stdout) > 5000:
                lines.append(f"\n... (output truncated, showing first 5000 chars)")
    else:
        lines.append("❌ Command failed")
        lines.append(f"Exit code: {result.returncode}")
        lines.append("")
        
        if parsed_error:
            lines.append(f"🔍 Error Analysis:")
            lines.append(f"  Type: {parsed_error['type']}")
            lines.append(f"  Message: {parsed_error['message']}")
            lines.append("")
            
            if parsed_error.get("frames"):
                lines.append("📍 Stack Trace:")
                for i, frame in enumerate(parsed_error["frames"][:3], 1):
                    lines.append(f"  {i}. {frame.get('file', 'unknown')}")
                    if "line" in frame:
                        lines.append(f"     Line: {frame['line']}")
                    if "function" in frame:
                        lines.append(f"     Function: {frame['function']}")
                    if "context" in frame and frame["context"]:
                        lines.append(f"     Context:")
                        for ctx_line in frame["context"].split("\n"):
                            lines.append(f"       {ctx_line}")
                    lines.append("")
            
            lines.append("")
            lines.append("-" * 60)
            lines.append("")
            lines.append("Full Error Output:")
            lines.append(error_output[:3000])
            if len(error_output) > 3000:
                lines.append(f"\n... (error output truncated)")
        else:
            if stderr:
                lines.append("Error Output:")
                lines.append(stderr[:3000])
            if stdout:
                lines.append("Standard Output:")
                lines.append(stdout[:3000])
    
    return ToolResult(
        ok=success,
        output="\n".join(lines),
    )


run_with_debug_tool = ToolDefinition(
    name="run_with_debug",
    description="Run a command and automatically parse error output. Supports Python tracebacks, Node.js stack traces, and generic errors. Returns structured error analysis with file locations and context.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute"},
            "cwd": {"type": "string", "description": "Working directory (default: current directory)"},
            "timeout": {"type": "number", "description": "Timeout in seconds (default: 30, max: 300)"},
            "language": {"type": "string", "enum": ["auto", "python", "node", "generic"], "description": "Language for error parsing (default: auto)"},
        },
        "required": ["command"],
    },
    validator=_validate,
    run=_run,
)
