from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any
from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path


# ---------------------------------------------------------------------------
# Code Review Checks
# ---------------------------------------------------------------------------

def _check_unused_imports(tree: ast.AST, content: str) -> list[dict[str, Any]]:
    """Check for unused imports."""
    issues = []

    # Get all imports
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                imports[name] = {"node": node, "type": "import"}
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                imports[name] = {"node": node, "type": "from"}

    # Check if each import is used
    for name, info in imports.items():
        # Simple check: search for name in code (excluding import lines)
        lines = content.split("\n")
        used = False
        for i, line in enumerate(lines):
            # Skip import lines
            if line.strip().startswith(("import ", "from ")):
                continue
            if name in line:
                used = True
                break

        if not used:
            issues.append({
                "type": "unused_import",
                "severity": "warning",
                "message": f"Import '{name}' is imported but never used",
                "line": getattr(info["node"], "lineno", 0),
            })

    return issues


def _check_hardcoded_values(tree: ast.AST) -> list[dict[str, Any]]:
    """Check for hardcoded values that should be constants."""
    issues = []

    for node in ast.walk(tree):
        # Check for string literals that look like hardcoded config
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Skip docstrings and short strings
            if len(node.value) < 10:
                continue
            # Skip if it's in a docstring position
            if hasattr(node, "parent") and isinstance(node.parent, ast.Expr):
                continue

        # Check for magic numbers
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            # Skip 0, 1, -1 which are commonly used
            if node.value in (0, 1, -1, 0.0, 1.0, -1.0):
                continue
            # Check if it's used multiple times (likely a constant)
            issues.append({
                "type": "magic_number",
                "severity": "info",
                "message": f"Consider extracting magic number '{node.value}' to a named constant",
                "line": getattr(node, "lineno", 0),
            })

    return issues[:10]  # Limit to 10 issues


def _check_empty_docstrings(tree: ast.AST) -> list[dict[str, Any]]:
    """Check for functions/classes without docstrings."""
    issues = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            docstring = ast.get_docstring(node)
            if not docstring:
                name = getattr(node, "name", "unknown")
                type_label = "Function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "Class"
                issues.append({
                    "type": "missing_docstring",
                    "severity": "info",
                    "message": f"{type_label} '{name}' has no docstring",
                    "line": getattr(node, "lineno", 0),
                })

    return issues[:10]  # Limit to 10 issues


def _check_long_functions(tree: ast.AST) -> list[dict[str, Any]]:
    """Check for functions that are too long."""
    issues = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Calculate function length
            if hasattr(node, "end_lineno") and hasattr(node, "lineno"):
                length = node.end_lineno - node.lineno
                if length > 50:
                    issues.append({
                        "type": "long_function",
                        "severity": "warning",
                        "message": f"Function '{node.name}' is {length} lines long (consider splitting)",
                        "line": node.lineno,
                    })

    return issues


# ---------------------------------------------------------------------------
# Tool Implementation
# ---------------------------------------------------------------------------

def _validate(input_data: dict) -> dict:
    path = input_data.get("path", ".")
    checks = input_data.get("checks", "all")
    if checks not in ("all", "imports", "style", "complexity"):
        raise ValueError(f"checks must be one of: all, imports, style, complexity")
    return {"path": path, "checks": checks}


def _run(input_data: dict, context) -> ToolResult:
    """Review Python code quality."""
    try:
        target = resolve_tool_path(context, input_data["path"], "review")
    except (PermissionError, RuntimeError) as error:
        return ToolResult(ok=False, output=str(error))
    checks_type = input_data["checks"]

    if not target.exists():
        return ToolResult(ok=False, output=f"Path not found: {target}")

    # Find Python files
    py_files = []
    if target.is_file():
        py_files = [target]
    else:
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "venv", "env", ".tox", "node_modules")]
            for f in files:
                if f.endswith(".py"):
                    py_files.append(Path(root) / f)

    all_issues = []
    files_reviewed = 0

    for py_file in py_files:
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        files_reviewed += 1

        # Run checks based on type
        if checks_type in ("all", "imports"):
            all_issues.extend([
                {**issue, "file": str(py_file.relative_to(context.cwd))}
                for issue in _check_unused_imports(tree, content)
            ])

        if checks_type in ("all", "style"):
            all_issues.extend([
                {**issue, "file": str(py_file.relative_to(context.cwd))}
                for issue in _check_hardcoded_values(tree)
            ])
            all_issues.extend([
                {**issue, "file": str(py_file.relative_to(context.cwd))}
                for issue in _check_empty_docstrings(tree)
            ])

        if checks_type in ("all", "complexity"):
            all_issues.extend([
                {**issue, "file": str(py_file.relative_to(context.cwd))}
                for issue in _check_long_functions(tree)
            ])

    # Sort by severity
    severity_order = {"error": 0, "warning": 1, "info": 2}
    all_issues.sort(key=lambda x: severity_order.get(x["severity"], 3))

    # Format output
    lines = ["Code Review Result", "=" * 60, ""]

    lines.append(f"Files reviewed: {files_reviewed}")
    lines.append(f"Issues found: {len(all_issues)}")
    lines.append("")

    # Group by severity
    errors = [i for i in all_issues if i["severity"] == "error"]
    warnings = [i for i in all_issues if i["severity"] == "warning"]
    infos = [i for i in all_issues if i["severity"] == "info"]

    if errors:
        lines.append(f"❌ Errors ({len(errors)}):")
        for issue in errors[:10]:
            lines.append(f"  L{issue.get('line', '?')} {issue['file']}")
            lines.append(f"     {issue['message']}")
        lines.append("")

    if warnings:
        lines.append(f"⚠️  Warnings ({len(warnings)}):")
        for issue in warnings[:10]:
            lines.append(f"  L{issue.get('line', '?')} {issue['file']}")
            lines.append(f"     {issue['message']}")
        lines.append("")

    if infos:
        lines.append(f"ℹ️  Info ({len(infos)}):")
        for issue in infos[:10]:
            lines.append(f"  L{issue.get('line', '?')} {issue['file']}")
            lines.append(f"     {issue['message']}")
        lines.append("")

    if not all_issues:
        lines.append("✓ No issues found! Code looks clean.")

    return ToolResult(
        ok=len(errors) == 0,
        output="\n".join(lines),
    )


code_review_tool = ToolDefinition(
    name="code_review",
    description="Review Python code quality by checking for unused imports, hardcoded values, missing docstrings, and long functions. Use this after making changes to ensure code quality.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File or directory path to review (default: current directory)"},
            "checks": {"type": "string", "enum": ["all", "imports", "style", "complexity"], "description": "Types of checks to run (default: all)"},
        },
    },
    validator=_validate,
    run=_run,
)
