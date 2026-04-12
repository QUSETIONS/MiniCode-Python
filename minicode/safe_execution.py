"""Safe execution isolator for risky operations.

Inspired by Learn Claude Code best practices:
- Worktree execution isolation for exploratory/risky operations
- Risk assessment before execution
- Automatic cleanup after isolation

Provides:
- RiskAssessor: Evaluates operation risk level
- IsolationExecutor: Executes commands in isolated worktrees
- CleanupManager: Manages automatic cleanup of isolated environments
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from minicode.tooling import ToolResult


# ---------------------------------------------------------------------------
# Risk Assessment
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Operation risk levels."""
    SAFE = "safe"           # Read-only operations
    LOW = "low"             # Minor writes (config files)
    MEDIUM = "medium"       # Source code modifications
    HIGH = "high"           # Database operations, deployments
    CRITICAL = "critical"   # Destructive operations (rm -rf, drop table)


# Command risk classification
_CRITICAL_COMMANDS = frozenset({
    "rm", "shred", "dd", "mkfs", "fdisk", "format",
    "dropdb", "drop", "truncate",
})

_HIGH_COMMANDS = frozenset({
    "sudo", "su", "chmod", "chown", "mount", "umount",
    "systemctl", "service", "brew", "apt", "yum", "dnf",
})

_MEDIUM_COMMANDS = frozenset({
    "git", "npm", "pip", "cargo", "go", "make", "cmake",
    "docker", "docker-compose", "kubectl",
})


def assess_command_risk(command: str, args: list[str]) -> RiskLevel:
    """Assess the risk level of a command execution.

    Args:
        command: The command to execute
        args: Command arguments

    Returns:
        RiskLevel indicating required isolation
    """
    cmd_base = command.lower().split("/")[-1]

    # Critical: Destructive operations
    if cmd_base in _CRITICAL_COMMANDS:
        return RiskLevel.CRITICAL

    # Check for destructive flags
    destructive_flags = {"-rf", "-fr", "--force", "--recursive", "--no-preserve-root"}
    if any(flag in args for flag in destructive_flags):
        return RiskLevel.CRITICAL

    # High: System operations
    if cmd_base in _HIGH_COMMANDS:
        return RiskLevel.HIGH

    # Medium: Development tools
    if cmd_base in _MEDIUM_COMMANDS:
        return RiskLevel.MEDIUM

    # Low: File writes
    if cmd_base in {"echo", "cat", "tee", "cp", "mv", "mkdir", "touch"}:
        return RiskLevel.LOW

    # Safe: Read-only operations
    safe_commands = {
        "ls", "pwd", "cat", "head", "tail", "wc", "grep", "find",
        "which", "whoami", "date", "echo", "df", "du", "uname",
    }
    if cmd_base in safe_commands:
        return RiskLevel.SAFE

    # Default to medium for unknown commands
    return RiskLevel.MEDIUM


# ---------------------------------------------------------------------------
# Worktree Isolation
# ---------------------------------------------------------------------------

@dataclass
class IsolationContext:
    """Context for isolated operation execution."""

    worktree_path: Path
    original_path: Path
    branch_name: str
    created_at: float = field(default_factory=time.time)
    cleanup_on_exit: bool = True
    max_age_seconds: float = 3600  # 1 hour default

    def is_expired(self) -> bool:
        """Check if this isolation context has expired."""
        return (time.time() - self.created_at) > self.max_age_seconds


class WorktreeIsolator:
    """Manages git worktree isolation for risky operations.

    Creates temporary git worktrees so that exploratory or destructive
    operations don't affect the main working directory.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        prefix: str = "isolated",
    ) -> None:
        self.base_dir = base_dir or Path(tempfile.gettempdir()) / "minicode-isolation"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self.active_contexts: dict[str, IsolationContext] = {}

    def create_isolation(
        self,
        source_path: Path,
        task_id: str | None = None,
        max_age_seconds: float = 3600,
    ) -> IsolationContext:
        """Create a new isolated worktree from the source repository.

        Args:
            source_path: Path to the source git repository
            task_id: Unique task identifier (auto-generated if None)
            max_age_seconds: Maximum age before auto-cleanup

        Returns:
            IsolationContext with worktree path and metadata
        """
        task_id = task_id or str(uuid.uuid4())[:8]
        branch_name = f"{self.prefix}_{task_id}"
        worktree_path = self.base_dir / f"{self.prefix}_{task_id}"

        # Verify source is a git repository
        git_dir = source_path / ".git"
        if not git_dir.exists():
            raise ValueError(f"Source path is not a git repository: {source_path}")

        try:
            # Create worktree
            subprocess.run(
                [
                    "git", "-C", str(source_path),
                    "worktree", "add",
                    "-b", branch_name,
                    str(worktree_path),
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            context = IsolationContext(
                worktree_path=worktree_path,
                original_path=source_path,
                branch_name=branch_name,
                max_age_seconds=max_age_seconds,
            )
            self.active_contexts[task_id] = context
            return context

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create worktree: {e.stderr}") from e

    def execute_in_isolation(
        self,
        task_id: str,
        command: str,
        args: list[str],
        cwd: Path | None = None,
        timeout: int = 300,
    ) -> ToolResult:
        """Execute a command inside an isolated worktree.

        Args:
            task_id: Task ID from create_isolation()
            command: Command to execute
            args: Command arguments
            cwd: Working directory relative to worktree (default: worktree root)
            timeout: Execution timeout in seconds

        Returns:
            ToolResult with command output
        """
        context = self.active_contexts.get(task_id)
        if not context:
            return ToolResult(
                ok=False,
                output=f"Isolation context not found: {task_id}",
            )

        if context.is_expired():
            self.cleanup_isolation(task_id)
            return ToolResult(
                ok=False,
                output="Isolation context expired. Create a new one.",
            )

        exec_cwd = cwd if cwd else context.worktree_path
        if not exec_cwd.exists():
            return ToolResult(
                ok=False,
                output=f"Working directory not found: {exec_cwd}",
            )

        try:
            result = subprocess.run(
                [command, *args],
                cwd=str(exec_cwd),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )

            output = "\n".join(
                part for part in [result.stdout.strip(), result.stderr.strip()] if part
            )
            return ToolResult(ok=result.returncode == 0, output=output[:10000])

        except subprocess.TimeoutExpired:
            return ToolResult(
                ok=False,
                output=f"Command timed out after {timeout} seconds in isolation.",
            )
        except Exception as e:
            return ToolResult(
                ok=False,
                output=f"Execution failed in isolation: {e}",
            )

    def cleanup_isolation(self, task_id: str) -> bool:
        """Clean up an isolated worktree.

        Args:
            task_id: Task ID to clean up

        Returns:
            True if cleanup succeeded
        """
        context = self.active_contexts.pop(task_id, None)
        if not context:
            return False

        try:
            # Remove worktree
            subprocess.run(
                [
                    "git", "-C", str(context.original_path),
                    "worktree", "remove", "-f",
                    str(context.worktree_path),
                ],
                capture_output=True,
                text=True,
            )
        except Exception:
            pass  # Best effort cleanup

        # Remove directory if it still exists
        if context.worktree_path.exists():
            try:
                shutil.rmtree(context.worktree_path)
            except Exception:
                pass

        return True

    def cleanup_expired(self) -> list[str]:
        """Clean up all expired isolation contexts.

        Returns:
            List of cleaned up task IDs
        """
        expired = [
            tid for tid, ctx in self.active_contexts.items()
            if ctx.is_expired()
        ]
        for tid in expired:
            self.cleanup_isolation(tid)
        return expired

    def cleanup_all(self) -> list[str]:
        """Clean up all active isolation contexts.

        Returns:
            List of cleaned up task IDs
        """
        all_ids = list(self.active_contexts.keys())
        for tid in all_ids:
            self.cleanup_isolation(tid)
        return all_ids

    def get_active_count(self) -> int:
        """Get count of active isolation contexts."""
        return len(self.active_contexts)

    def get_status(self) -> dict[str, Any]:
        """Get isolation status information."""
        return {
            "active_isolations": len(self.active_contexts),
            "base_dir": str(self.base_dir),
            "isolations": [
                {
                    "task_id": tid,
                    "branch": ctx.branch_name,
                    "age_seconds": time.time() - ctx.created_at,
                    "expired": ctx.is_expired(),
                }
                for tid, ctx in self.active_contexts.items()
            ],
        }


# ---------------------------------------------------------------------------
# Safe Execution Tool
# ---------------------------------------------------------------------------

_default_isolator = WorktreeIsolator()


def get_isolator() -> WorktreeIsolator:
    """Get the global worktree isolator."""
    return _default_isolator


def execute_safely(
    command: str,
    args: list[str],
    source_path: Path,
    task_id: str | None = None,
    timeout: int = 300,
) -> ToolResult:
    """Execute a command with automatic risk assessment and isolation.

    This is the main entry point for safe command execution. It:
    1. Assesses command risk level
    2. Creates isolation for MEDIUM+ risk commands
    3. Executes command in isolation (if needed)
    4. Cleans up isolation after execution

    Args:
        command: Command to execute
        args: Command arguments
        source_path: Source repository path for worktree creation
        task_id: Optional task ID for tracking
        timeout: Execution timeout in seconds

    Returns:
        ToolResult with execution output and risk metadata
    """
    risk = assess_command_risk(command, args)

    # Safe and low risk commands execute directly
    if risk in (RiskLevel.SAFE, RiskLevel.LOW):
        try:
            result = subprocess.run(
                [command, *args],
                cwd=str(source_path),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            output = "\n".join(
                part for part in [result.stdout.strip(), result.stderr.strip()] if part
            )
            return ToolResult(
                ok=result.returncode == 0,
                output=f"[Risk: {risk.value}] {output[:10000]}",
            )
        except Exception as e:
            return ToolResult(
                ok=False,
                output=f"[Risk: {risk.value}] Execution failed: {e}",
            )

    # Medium+ risk commands get isolated
    isolator = get_isolator()
    try:
        context = isolator.create_isolation(
            source_path=source_path,
            task_id=task_id,
            max_age_seconds=600,  # 10 minutes for isolated execution
        )

        result = isolator.execute_in_isolation(
            task_id=context.branch_name.split("_")[-1],
            command=command,
            args=args,
            timeout=timeout,
        )

        # Cleanup after execution
        isolator.cleanup_isolation(context.branch_name.split("_")[-1])

        # Prepend risk level to output
        if result.ok:
            result.output = f"[Risk: {risk.value}, Isolated] {result.output}"
        else:
            result.output = f"[Risk: {risk.value}, Isolated] {result.output}"

        return result

    except Exception as e:
        return ToolResult(
            ok=False,
            output=f"[Risk: {risk.value}] Isolation failed: {e}",
        )


def format_risk_info(command: str, args: list[str]) -> str:
    """Format risk assessment information for display.

    Args:
        command: Command to assess
        args: Command arguments

    Returns:
        Human-readable risk assessment string
    """
    risk = assess_command_risk(command, args)

    risk_descriptions = {
        RiskLevel.SAFE: "Read-only operation, no side effects",
        RiskLevel.LOW: "Minor writes, low risk of data loss",
        RiskLevel.MEDIUM: "Development operation, isolated execution recommended",
        RiskLevel.HIGH: "System operation, requires isolation",
        RiskLevel.CRITICAL: "Destructive operation, requires strict isolation",
    }

    return (
        f"Risk Assessment\n"
        f"{'=' * 50}\n"
        f"Command: {command} {' '.join(args)}\n"
        f"Level: {risk.value.upper()}\n"
        f"Description: {risk_descriptions[risk]}\n"
    )
