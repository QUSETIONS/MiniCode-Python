from __future__ import annotations

import subprocess
from pathlib import Path
from minicode.tooling import ToolDefinition, ToolResult


def _validate(input_data: dict) -> dict:
    action = input_data.get("action")
    if not isinstance(action, str) or not action:
        raise ValueError("action is required")
    if action not in ("status", "diff", "log", "commit", "review"):
        raise ValueError(f"action must be one of: status, diff, log, commit, review")
    if action == "commit":
        message = input_data.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message is required for commit action")
    return {
        "action": action,
        "message": input_data.get("message", ""),
        "max_lines": int(input_data.get("max_lines", 50)),
    }


def _run(input_data: dict, context) -> ToolResult:
    action = input_data["action"]
    max_lines = input_data["max_lines"]
    cwd = context.cwd

    try:
        if action == "status":
            return _run_status(cwd)
        elif action == "diff":
            return _run_diff(cwd, max_lines)
        elif action == "log":
            return _run_log(cwd, max_lines)
        elif action == "commit":
            return _run_commit(cwd, input_data["message"])
        elif action == "review":
            return _run_review(cwd, max_lines)
    except FileNotFoundError:
        return ToolResult(ok=False, output="Git is not installed or not in PATH.")
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, output="Git command timed out.")
    except Exception as e:
        return ToolResult(ok=False, output=f"Git error: {e}")

    return ToolResult(ok=False, output=f"Unknown action: {action}")


def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _run_status(cwd: str) -> ToolResult:
    rc, stdout, stderr = _run_git(["status", "--short"], cwd)
    if rc != 0:
        return ToolResult(ok=False, output=f"Git status failed: {stderr}")

    if not stdout:
        return ToolResult(ok=True, output="Working tree clean. Nothing to commit.")

    # Count changes
    staged = sum(1 for line in stdout.split("\n") if line and line[0] != " ")
    unstaged = sum(1 for line in stdout.split("\n") if line and line[0] == " ")

    lines = [
        "Git Status:",
        f"  Staged changes: {staged}",
        f"  Unstaged changes: {unstaged}",
        "",
        "Files:",
    ]

    for line in stdout.split("\n")[:30]:
        if line:
            status = line[:2].strip()
            file = line[3:]
            lines.append(f"  [{status}] {file}")

    if stdout.count("\n") >= 30:
        lines.append(f"\n... and {stdout.count(chr(10)) - 29} more files")

    return ToolResult(ok=True, output="\n".join(lines))


def _run_diff(cwd: str, max_lines: int) -> ToolResult:
    rc, stdout, stderr = _run_git(["diff", "--stat"], cwd)
    if rc != 0:
        return ToolResult(ok=False, output=f"Git diff failed: {stderr}")

    if not stdout:
        return ToolResult(ok=True, output="No unstaged changes.")

    lines = [
        "Unstaged Changes:",
        "",
    ]
    lines.extend(stdout.split("\n")[:max_lines])

    if stdout.count("\n") >= max_lines:
        lines.append(f"\n... and more ({stdout.count(chr(10)) - max_lines + 1} lines total)")

    return ToolResult(ok=True, output="\n".join(lines))


def _run_log(cwd: str, max_lines: int) -> ToolResult:
    rc, stdout, stderr = _run_git(["log", "--oneline", f"-{max_lines}"], cwd)
    if rc != 0:
        return ToolResult(ok=False, output=f"Git log failed: {stderr}")

    if not stdout:
        return ToolResult(ok=True, output="No commits found.")

    lines = ["Recent Commits:", ""]
    lines.extend(stdout.split("\n"))

    return ToolResult(ok=True, output="\n".join(lines))


def _run_commit(cwd: str, message: str) -> ToolResult:
    # First check what will be committed
    rc, staged, _ = _run_git(["diff", "--cached", "--stat"], cwd)

    if not staged:
        return ToolResult(
            ok=False,
            output="No staged changes. Use 'git add' to stage files first.",
        )

    # Perform commit
    rc, stdout, stderr = _run_git(["commit", "-m", message], cwd)
    if rc != 0:
        return ToolResult(ok=False, output=f"Commit failed: {stderr}")

    lines = [
        f"✓ Committed: {message}",
        "",
        "Changes:",
    ]
    lines.extend(staged.split("\n")[:20])

    return ToolResult(ok=True, output="\n".join(lines))


def _run_review(cwd: str, max_lines: int) -> ToolResult:
    """Review recent changes (last 5 commits + diff stat)."""
    # Get recent commits
    rc, log, _ = _run_git(["log", "--oneline", "-5"], cwd)
    if rc != 0:
        return ToolResult(ok=False, output=f"Git review failed: {log or _}")

    # Get diff stat for last commit
    rc, diff_stat, _ = _run_git(["diff", "--stat", "HEAD~1"], cwd)

    lines = [
        "Git Review (Last 5 Commits):",
        "=" * 60,
        "",
        log or "(no commits found)",
    ]

    if diff_stat:
        lines.extend([
            "",
            "Latest Commit Changes:",
            "",
            diff_stat,
        ])

    # Check for uncommitted changes
    rc, status, _ = _run_git(["status", "--short"], cwd)
    if status:
        lines.extend([
            "",
            "⚠️  Uncommitted Changes:",
            status,
        ])
    else:
        lines.append("")
        lines.append("✓ Working tree clean")

    return ToolResult(ok=True, output="\n".join(lines))


git_tool = ToolDefinition(
    name="git",
    description="Git workflow tool. Actions: status (show working tree status), diff (show unstaged changes), log (show recent commits), commit (create a git commit with message), review (review recent changes and working tree).",
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "diff", "log", "commit", "review"],
                "description": "Git action to perform",
            },
            "message": {"type": "string", "description": "Commit message (required for commit action)"},
            "max_lines": {"type": "number", "description": "Maximum output lines (default: 50)"},
        },
        "required": ["action"],
    },
    validator=_validate,
    run=_run,
)
