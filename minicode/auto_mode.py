"""Auto Mode for MiniCode Python.

Inspired by Claude Code's auto mode which sits between standard approval
and --dangerously-skip-permissions. It includes:
- Input-layer prompt injection detection
- Output-layer transcription classifier
- Safe operations auto-approve
- High-risk operations blocked or guided to safe alternatives

Permission modes:
- default: Ask for every action (current behavior)
- auto: Auto-approve safe operations, prompt for risky ones
- bypass: Skip all permissions (dangerous!)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Permission modes
# ---------------------------------------------------------------------------

class PermissionMode(str, Enum):
    """Permission modes (inspired by Claude Code)."""
    DEFAULT = "default"           # Ask for everything
    AUTO = "auto"                 # Auto-approve safe ops
    BYPASS = "bypass"             # Skip all permissions (dangerous!)
    PLAN = "plan"                 # Read-only, no execution


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Operation risk levels."""
    SAFE = "safe"                 # Auto-approve
    LOW = "low"                   # Auto-approve with logging
    MEDIUM = "medium"             # Prompt with explanation
    HIGH = "high"                 # Block or require strong justification
    DANGEROUS = "dangerous"       # Always block


# ---------------------------------------------------------------------------
# Risk rules
# ---------------------------------------------------------------------------

# Safe tools (auto-approve in auto mode)
SAFE_TOOLS = {
    "read_file",
    "list_files",
    "grep_files",
    "load_skill",
}

# Low-risk tools (auto-approve with logging)
LOW_RISK_TOOLS = {
    "run_command",  # Only for read-only commands
}

# Medium-risk tools (require approval)
MEDIUM_RISK_TOOLS = {
    "write_file",
    "edit_file",
    "patch_file",
    "modify_file",
}

# High-risk commands (block or require strong justification)
HIGH_RISK_COMMANDS = {
    # Unix
    "rm -rf",
    "rm -r",
    "git reset --hard",
    "git clean",
    "git push --force",
    "sudo",
    "chmod -R",
    "chown -R",
    # Windows
    "del /s",
    "del /q",
    "rmdir /s",
    "rd /s",
    "icacls",
    "takeown",
    "net user",
    "net localgroup",
    "reg delete",
    "format",
}

# Dangerous patterns (always block)
DANGEROUS_PATTERNS = [
    # Unix
    r"rm\s+-rf\s+/",           # Delete root
    r"chmod\s+777",            # World-writable
    r"curl.*\|\s*sh",          # Pipe curl to shell
    r"wget.*\|\s*sh",
    r"mkfs",                   # Format filesystem
    r"dd\s+if=",               # Disk dump
    # Windows
    r"del\s+/[sfq].*[\\]",     # Recursive/force delete with path
    r"rmdir\s+/s\s+/q",        # Silent recursive dir removal
    r"rd\s+/s\s+/q",
    r"format\s+[a-zA-Z]:",     # Format drive
    r"powershell.*\biex\b",    # PowerShell invoke-expression from remote
    r"powershell.*Invoke-Expression", 
    r"iwr.*\|\s*iex",          # Download and execute (PowerShell)
    r"reg\s+delete\s+HKLM",   # Delete machine-wide registry keys
]


@dataclass
class RiskAssessment:
    """Risk assessment result."""
    level: RiskLevel
    tool_name: str
    action: str  # "approve", "prompt", "block"
    reason: str
    safe_alternative: str | None = None


# ---------------------------------------------------------------------------
# Auto mode checker
# ---------------------------------------------------------------------------

class AutoModeChecker:
    """Checks if operations can be auto-approved.
    
    Inspired by Claude Code's auto mode with input/output layer checks.
    """
    
    def __init__(self, mode: PermissionMode = PermissionMode.DEFAULT):
        self.mode = mode
    
    def set_mode(self, mode: PermissionMode) -> None:
        """Change permission mode."""
        self.mode = mode
    
    def assess_risk(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> RiskAssessment:
        """Assess risk of a tool operation.
        
        Args:
            tool_name: Name of tool being called
            tool_input: Tool input dictionary
        
        Returns:
            RiskAssessment with action recommendation
        """
        # Bypass mode - approve everything
        if self.mode == PermissionMode.BYPASS:
            return RiskAssessment(
                level=RiskLevel.DANGEROUS,
                tool_name=tool_name,
                action="approve",
                reason="Bypass mode: all permissions skipped",
            )
        
        # Plan mode - read-only only
        if self.mode == PermissionMode.PLAN:
            if tool_name in SAFE_TOOLS:
                return RiskAssessment(
                    level=RiskLevel.SAFE,
                    tool_name=tool_name,
                    action="approve",
                    reason="Plan mode: read-only tool",
                )
            else:
                return RiskAssessment(
                    level=RiskLevel.HIGH,
                    tool_name=tool_name,
                    action="block",
                    reason="Plan mode: execution not allowed",
                )
        
        # Default mode - ask for everything
        if self.mode == PermissionMode.DEFAULT:
            return RiskAssessment(
                level=RiskLevel.MEDIUM,
                tool_name=tool_name,
                action="prompt",
                reason="Default mode: approval required",
            )
        
        # Auto mode - intelligent assessment
        return self._assess_auto_mode(tool_name, tool_input)
    
    def _assess_auto_mode(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> RiskAssessment:
        """Assess risk in auto mode."""
        # Safe tools - auto-approve
        if tool_name in SAFE_TOOLS:
            return RiskAssessment(
                level=RiskLevel.SAFE,
                tool_name=tool_name,
                action="approve",
                reason=f"Auto mode: {tool_name} is read-only",
            )
        
        # Check run_command for read-only commands
        if tool_name == "run_command":
            return self._assess_command(tool_input)
        
        # File modification tools
        if tool_name in MEDIUM_RISK_TOOLS:
            return self._assess_file_edit(tool_name, tool_input)
        
        # Unknown tool - prompt
        return RiskAssessment(
            level=RiskLevel.MEDIUM,
            tool_name=tool_name,
            action="prompt",
            reason=f"Auto mode: unknown tool '{tool_name}'",
        )
    
    def _assess_command(self, tool_input: dict[str, Any]) -> RiskAssessment:
        """Assess risk of run_command."""
        command = tool_input.get("command", "")
        if isinstance(command, list):
            command = " ".join(command)
        
        # Check dangerous patterns
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return RiskAssessment(
                    level=RiskLevel.DANGEROUS,
                    tool_name="run_command",
                    action="block",
                    reason=f"Dangerous pattern detected: {pattern}",
                )
        
        # Check high-risk commands
        for risky_cmd in HIGH_RISK_COMMANDS:
            if risky_cmd in command:
                return RiskAssessment(
                    level=RiskLevel.HIGH,
                    tool_name="run_command",
                    action="prompt",
                    reason=f"High-risk command: '{risky_cmd}'",
                    safe_alternative=f"Consider safer alternative to '{risky_cmd}'",
                )
        
        # Low-risk - auto-approve with logging
        return RiskAssessment(
            level=RiskLevel.LOW,
            tool_name="run_command",
            action="approve",
            reason=f"Auto mode: command appears safe",
        )
    
    def _assess_file_edit(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> RiskAssessment:
        """Assess risk of file editing tools."""
        path = tool_input.get("path", "")
        
        # Check if editing sensitive files
        # Use [/\\] to match both Unix / and Windows \ separators
        sensitive_patterns = [
            r"\.env",
            r"\.git[/\\]",
            r"node_modules[/\\]",
            r"__pycache__[/\\]",
            r"\.pyc$",
        ]
        
        for pattern in sensitive_patterns:
            if re.search(pattern, path):
                return RiskAssessment(
                    level=RiskLevel.HIGH,
                    tool_name=tool_name,
                    action="prompt",
                    reason=f"Modifying sensitive file: {path}",
                )
        
        # Normal file edit - prompt
        return RiskAssessment(
            level=RiskLevel.MEDIUM,
            tool_name=tool_name,
            action="prompt",
            reason=f"Auto mode: file modification requires approval",
        )
    
    # -----------------------------------------------------------------------
    # Input/Output layer checks (inspired by Claude Code)
    # -----------------------------------------------------------------------
    
    @staticmethod
    def detect_prompt_injection(user_input: str) -> tuple[bool, str]:
        """Detect potential prompt injection in user input.
        
        Returns:
            (is_injection, reason)
        """
        injection_patterns = [
            r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|rules|prompts)",
            r"(system|developer)\s*:\s*",
            r"\[?ignore\s+security\]?",
            r"(bypass|skip|override)\s+(permissions|safety|restrictions)",
            r"(execute|run)\s+(this|following)\s+code\s*:",
            r"ignore\s+(all|your)\s+instructions",
        ]
        
        for pattern in injection_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                return True, f"Potential prompt injection: {pattern}"
        
        return False, ""
    
    @staticmethod
    def classify_output_safety(output: str) -> tuple[bool, str]:
        """Classify if AI output contains unsafe operations.
        
        Returns:
            (is_unsafe, reason)
        """
        unsafe_patterns = [
            # Unix
            r"rm\s+-rf",
            r"sudo\s+",
            r"chmod\s+777",
            # Windows
            r"del\s+/[sfq]",
            r"rmdir\s+/s",
            r"rd\s+/s",
            r"format\s+[a-zA-Z]:",
            # SQL
            r"DROP\s+TABLE",
            r"DELETE\s+FROM.*WHERE\s+1\s*=\s*1",
        ]
        
        for pattern in unsafe_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                return True, f"Unsafe operation detected: {pattern}"
        
        return False, ""


# ---------------------------------------------------------------------------
# Mode management
# ---------------------------------------------------------------------------

@dataclass
class ModeState:
    """Current permission mode state."""
    mode: PermissionMode = PermissionMode.DEFAULT
    mode_changed_at: float = 0.0
    mode_changed_by: str = "user"
    auto_approve_count: int = 0
    prompt_count: int = 0
    block_count: int = 0
    
    def record_decision(self, action: str) -> None:
        """Record a permission decision."""
        import time
        if action == "approve":
            self.auto_approve_count += 1
        elif action == "prompt":
            self.prompt_count += 1
        elif action == "block":
            self.block_count += 1
    
    def format_status(self) -> str:
        """Format mode status."""
        mode_descriptions = {
            PermissionMode.DEFAULT: "Ask for every action",
            PermissionMode.AUTO: "Auto-approve safe operations",
            PermissionMode.BYPASS: "⚠️ Skip all permissions (dangerous!)",
            PermissionMode.PLAN: "Read-only mode",
        }
        
        lines = [
            "Permission Mode",
            "=" * 50,
            f"Current mode: {self.mode.value}",
            f"Description: {mode_descriptions.get(self.mode, 'Unknown')}",
            "",
            "Statistics:",
            f"  Auto-approved: {self.auto_approve_count}",
            f"  Prompted: {self.prompt_count}",
            f"  Blocked: {self.block_count}",
        ]
        
        total = self.auto_approve_count + self.prompt_count + self.block_count
        if total > 0:
            auto_pct = self.auto_approve_count / total * 100
            lines.append(f"  Auto-approval rate: {auto_pct:.0f}%")
        
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_checker = AutoModeChecker()
_mode_state = ModeState()


def get_checker() -> AutoModeChecker:
    """Get global auto mode checker."""
    return _checker


def get_mode_state() -> ModeState:
    """Get global mode state."""
    return _mode_state


def set_permission_mode(mode: PermissionMode) -> str:
    """Set global permission mode."""
    import time
    _checker.set_mode(mode)
    _mode_state.mode = mode
    _mode_state.mode_changed_at = time.time()
    
    mode_messages = {
        PermissionMode.DEFAULT: "✓ Default mode: All actions require approval",
        PermissionMode.AUTO: "⚡ Auto mode: Safe operations auto-approved",
        PermissionMode.BYPASS: "⚠️ BYPASS MODE: All permissions skipped!",
        PermissionMode.PLAN: "📖 Plan mode: Read-only operations allowed",
    }
    
    return mode_messages.get(mode, f"Mode changed to {mode.value}")
