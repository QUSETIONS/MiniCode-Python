from __future__ import annotations

from pathlib import Path
from minicode.tooling import ToolDefinition, ToolResult
from minicode.tools.governance_audit import (
    run_full_audit,
    audit_dependency_directions,
    audit_sink_rules,
)


def _validate(input_data: dict) -> dict:
    action = input_data.get("action", "full")
    if action not in ("full", "deps", "sinks"):
        raise ValueError(f"action must be one of: full, deps, sinks")
    path = input_data.get("path", ".")
    return {"action": action, "path": path}


def _run(input_data: dict, context) -> ToolResult:
    pkg_root = Path(context.cwd) / input_data["path"]
    if not pkg_root.exists():
        return ToolResult(ok=False, output=f"Path not found: {pkg_root}")
    
    action = input_data["action"]
    
    if action == "full":
        result = run_full_audit(pkg_root)
    elif action == "deps":
        result = audit_dependency_directions(pkg_root)
    elif action == "sinks":
        result = audit_sink_rules(pkg_root)
    else:
        return ToolResult(ok=False, output=f"Unknown action: {action}")
    
    return ToolResult(
        ok=result.passed,
        output=result.summary(),
    )


governance_audit_tool = ToolDefinition(
    name="governance_audit",
    description="Run engineering governance audit on a package. Checks dependency directions, sink rules, and compliance with governance rules. Actions: 'full' (complete audit), 'deps' (dependency directions only), 'sinks' (sink rules only).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to package root (default: current directory)"},
            "action": {"type": "string", "enum": ["full", "deps", "sinks"], "description": "Audit type (default: full)"},
        },
    },
    validator=_validate,
    run=_run,
)
