from __future__ import annotations

import os
import shutil
from pathlib import Path

from minicode.tooling import ToolDefinition, ToolContext, ToolResult


def _validate_batch_copy(input_data: dict) -> dict:
    """Validate input for batch_copy tool."""
    source = input_data.get("source", "")
    destination = input_data.get("destination", "")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is required")
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError("destination is required")
    return {"source": source.strip(), "destination": destination.strip()}


def _run_batch_copy(input_data: dict, context: ToolContext) -> ToolResult:
    """Copy files or directories."""
    source = Path(context.cwd) / input_data["source"]
    destination = Path(context.cwd) / input_data["destination"]
    
    if not source.exists():
        return ToolResult(ok=False, output=f"Source not found: {input_data['source']}")
    
    try:
        if source.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
            return ToolResult(ok=True, output=f"Copied directory to {input_data['destination']}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return ToolResult(ok=True, output=f"Copied file to {input_data['destination']}")
    except Exception as e:
        return ToolResult(ok=False, output=f"Copy failed: {e}")


batch_copy_tool = ToolDefinition(
    name="batch_copy",
    description="Copy files or directories. Supports both files and directories.",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path (relative to workspace)"},
            "destination": {"type": "string", "description": "Destination path (relative to workspace)"}
        },
        "required": ["source", "destination"]
    },
    validator=_validate_batch_copy,
    run=_run_batch_copy,
)


# ---------------------------------------------------------------------------
# Batch Move Tool
# ---------------------------------------------------------------------------

def _validate_batch_move(input_data: dict) -> dict:
    """Validate input for batch_move tool."""
    source = input_data.get("source", "")
    destination = input_data.get("destination", "")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is required")
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError("destination is required")
    return {"source": source.strip(), "destination": destination.strip()}


def _run_batch_move(input_data: dict, context: ToolContext) -> ToolResult:
    """Move files or directories."""
    source = Path(context.cwd) / input_data["source"]
    destination = Path(context.cwd) / input_data["destination"]
    
    if not source.exists():
        return ToolResult(ok=False, output=f"Source not found: {input_data['source']}")
    
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return ToolResult(ok=True, output=f"Moved to {input_data['destination']}")
    except Exception as e:
        return ToolResult(ok=False, output=f"Move failed: {e}")


batch_move_tool = ToolDefinition(
    name="batch_move",
    description="Move files or directories to a new location.",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path (relative to workspace)"},
            "destination": {"type": "string", "description": "Destination path (relative to workspace)"}
        },
        "required": ["source", "destination"]
    },
    validator=_validate_batch_move,
    run=_run_batch_move,
)


# ---------------------------------------------------------------------------
# Batch Delete Tool
# ---------------------------------------------------------------------------

def _validate_batch_delete(input_data: dict) -> dict:
    """Validate input for batch_delete tool."""
    path = input_data.get("path", "")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path is required")
    return {"path": path.strip(), "recursive": input_data.get("recursive", False)}


def _run_batch_delete(input_data: dict, context: ToolContext) -> ToolResult:
    """Delete files or directories."""
    target = Path(context.cwd) / input_data["path"]
    recursive = input_data.get("recursive", False)
    
    if not target.exists():
        return ToolResult(ok=False, output=f"Path not found: {input_data['path']}")
    
    # Safety check: don't allow deleting outside workspace
    try:
        target.relative_to(Path(context.cwd).resolve())
    except ValueError:
        return ToolResult(ok=False, output="Cannot delete paths outside workspace")
    
    try:
        if target.is_dir():
            if recursive:
                shutil.rmtree(target)
                return ToolResult(ok=True, output=f"Deleted directory: {input_data['path']}")
            else:
                return ToolResult(ok=False, output="Use recursive=true to delete directories")
        else:
            target.unlink()
            return ToolResult(ok=True, output=f"Deleted file: {input_data['path']}")
    except Exception as e:
        return ToolResult(ok=False, output=f"Delete failed: {e}")


batch_delete_tool = ToolDefinition(
    name="batch_delete",
    description="Delete files or directories. Directories require recursive=true.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to delete (relative to workspace)"},
            "recursive": {"type": "boolean", "description": "Required to delete directories"}
        },
        "required": ["path"]
    },
    validator=_validate_batch_delete,
    run=_run_batch_delete,
)
