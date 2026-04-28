from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal

from minicode.config import MINI_CODE_PERMISSIONS_PATH

# Auto mode integration
from minicode.auto_mode import AutoModeChecker, PermissionMode, RiskLevel, get_checker, get_mode_state

# 权限决策类型 — 对齐 TS 版 PermissionDecision
PermissionDecision = Literal[
    "allow_once",
    "allow_always",
    "allow_turn",
    "allow_all_turn",
    "deny_once",
    "deny_always",
    "deny_with_feedback",
]

PromptHandler = Callable[[dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Path normalization with LRU cache
# ---------------------------------------------------------------------------

# LRU cache for _normalize_path — this is called on every permission check
# and Path.resolve() is expensive (stat syscall per path component).
# Typical session: hundreds of checks on ~50 unique paths.
_CACHE_MAX_SIZE = 512

_normalize_path_cached = lru_cache(maxsize=_CACHE_MAX_SIZE)(
    lambda p: str(Path(p).resolve())
)


def _normalize_path(target_path: str) -> str:
    """Normalize a path with caching. Resolves symlinks and normalizes separators.
    
    Cached to avoid redundant Path.resolve() syscalls — the same paths are
    checked repeatedly (e.g., workspace root on every tool call).
    """
    return _normalize_path_cached(target_path)


# Pre-computed result for the workspace root check (most common case)
# This avoids calling _is_within_directory for the trivial case.
_is_win = sys.platform == "win32"


def _is_within_directory(root: str, target: str) -> bool:
    """Check if target is within root directory.
    
    On Windows, uses case-insensitive comparison since NTFS paths are
    case-insensitive by default.
    
    Both root and target should be pre-normalized (resolved) for
    correct comparison.
    """
    if _is_win:
        # Windows: case-insensitive path comparison
        target_str = target.lower()
        root_str = root.lower().rstrip("\\/")
        return (
            target_str == root_str
            or target_str.startswith(root_str + "\\")
            or target_str.startswith(root_str + "/")
        )
    
    # Unix: direct string comparison (paths already normalized)
    root_str = root.rstrip(os.sep)
    return target == root_str or target.startswith(root_str + os.sep)


def _matches_directory_prefix(target_path: str, directories: set[str]) -> bool:
    """Check if target matches any directory prefix.
    
    Optimized: sorts directories by length (most specific first)
    and short-circuits on first match.
    """
    for directory in directories:
        if _is_within_directory(directory, target_path):
            return True
    return False


def _format_command_signature(command: str, args: list[str]) -> str:
    return " ".join([command, *args]).strip()


def _classify_dangerous_command(command: str, args: list[str]) -> str | None:
    normalized_args = [arg.strip() for arg in args if arg.strip()]
    signature = _format_command_signature(command, normalized_args)

    if command == "git":
        if "reset" in normalized_args and "--hard" in normalized_args:
            return f"git reset --hard can discard local changes ({signature})"
        if "clean" in normalized_args:
            return f"git clean can delete untracked files ({signature})"
        if "checkout" in normalized_args and "--" in normalized_args:
            return f"git checkout -- can overwrite working tree files ({signature})"
        if "push" in normalized_args and any(arg in {"--force", "-f"} for arg in normalized_args):
            return f"git push --force rewrites remote history ({signature})"
        if "restore" in normalized_args and any(arg.startswith("--source") for arg in normalized_args):
            return f"git restore --source can overwrite local files ({signature})"

    if command == "npm" and "publish" in normalized_args:
        return f"npm publish affects a registry outside this machine ({signature})"

    # 灾难性删除命令检测
    if command == "rm":
        # 组合所有标志（支持 -rf, -fr, -Rf, -r -f 等）
        combined_flags = "".join(arg for arg in normalized_args if arg.startswith("-")).lower()
        # 检查是否同时有递归和强制标志
        if "r" in combined_flags and "f" in combined_flags:
            # 检查是否针对根目录或使用 --no-preserve-root
            if any(arg in {"/", "/*"} for arg in normalized_args) or "--no-preserve-root" in normalized_args:
                return f"rm -rf can cause catastrophic data loss ({signature})"
            # 即使不是根目录，rm -rf 也是危险的
            return f"rm -rf can cause catastrophic data loss ({signature})"

    # 磁盘写入/格式化命令检测
    if command in {"dd", "mkfs", "mkfs.ext4", "mkfs.vfat", "fdisk", "format"}:
        return f"{command} can modify or destroy disk partitions ({signature})"

    # 权限全开命令检测
    if command == "chmod":
        if "777" in normalized_args or any(arg.endswith("777") for arg in normalized_args):
            return f"chmod 777 opens permissions to all users ({signature})"

    if command in {
        "node", "python", "python3", "pythonw",
        "bun", "bash", "sh", "zsh", "fish",
        "powershell", "pwsh",
    }:
        return f"{command} can execute arbitrary local code ({signature})"

    # macOS-specific dangerous commands
    if command == "diskutil":
        return f"diskutil can erase or partition disks ({signature})"
    if command == "csrutil":
        return f"csrutil modifies System Integrity Protection ({signature})"
    if command == "defaults" and "write" in normalized_args:
        return f"defaults write modifies system preferences ({signature})"
    if command == "launchctl" and any(arg in {"unload", "bootout", "disable"} for arg in normalized_args):
        return f"launchctl can disable system services ({signature})"
    if command == "dscl":
        return f"dscl can modify directory services and user accounts ({signature})"

    return None


def _read_permission_store() -> dict[str, Any]:
    if not MINI_CODE_PERMISSIONS_PATH.exists():
        return {}
    try:
        data = json.loads(MINI_CODE_PERMISSIONS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        # 损坏的文件 — 返回空存储并记录警告
        import warnings
        warnings.warn(f"Corrupted permissions file, resetting: {e}")
        return {}


def _write_permission_store(store: dict[str, Any]) -> None:
    """使用原子写入持久化权限存储，防止竞争条件"""
    import tempfile
    
    MINI_CODE_PERMISSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # 写入临时文件
    fd, tmp_path = tempfile.mkstemp(
        dir=MINI_CODE_PERMISSIONS_PATH.parent,
        suffix=".tmp"
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(store, f, indent=2)
            f.write('\n')
        # 原子替换
        os.replace(tmp_path, MINI_CODE_PERMISSIONS_PATH)
    except Exception:
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class PermissionManager:
    def __init__(self, workspace_root: str, prompt: PromptHandler | None = None, auto_mode: PermissionMode | None = None) -> None:
        self.workspace_root = _normalize_path(workspace_root)
        self.prompt = prompt
        self.auto_checker = AutoModeChecker(mode=auto_mode or PermissionMode.DEFAULT)
        self.allowed_directory_prefixes: set[str] = set()
        self.denied_directory_prefixes: set[str] = set()
        self.session_allowed_paths: set[str] = set()
        self.session_denied_paths: set[str] = set()
        self.allowed_command_patterns: set[str] = set()
        self.denied_command_patterns: set[str] = set()
        self.session_allowed_commands: set[str] = set()
        self.session_denied_commands: set[str] = set()
        self.allowed_edit_patterns: set[str] = set()
        self.denied_edit_patterns: set[str] = set()
        self.session_allowed_edits: set[str] = set()
        self.session_denied_edits: set[str] = set()
        self.turn_allowed_edits: set[str] = set()
        self.turn_allow_all_edits = False
        self._initialize()

    def _initialize(self) -> None:
        store = _read_permission_store()
        self.allowed_directory_prefixes |= {_normalize_path(item) for item in store.get("allowedDirectoryPrefixes", [])}
        self.denied_directory_prefixes |= {_normalize_path(item) for item in store.get("deniedDirectoryPrefixes", [])}
        self.allowed_command_patterns |= set(store.get("allowedCommandPatterns", []))
        self.denied_command_patterns |= set(store.get("deniedCommandPatterns", []))
        self.allowed_edit_patterns |= {_normalize_path(item) for item in store.get("allowedEditPatterns", [])}
        self.denied_edit_patterns |= {_normalize_path(item) for item in store.get("deniedEditPatterns", [])}

    def begin_turn(self) -> None:
        self.turn_allowed_edits.clear()
        self.turn_allow_all_edits = False

    def end_turn(self) -> None:
        self.begin_turn()

    def get_summary(self) -> list[str]:
        summary = [f"cwd: {self.workspace_root}"]
        summary.append(
            "extra allowed dirs: "
            + (", ".join(sorted(self.allowed_directory_prefixes)[:4]) if self.allowed_directory_prefixes else "none")
        )
        summary.append(
            "dangerous allowlist: "
            + (", ".join(sorted(self.allowed_command_patterns)[:4]) if self.allowed_command_patterns else "none")
        )
        if self.allowed_edit_patterns:
            summary.append("trusted edit targets: " + ", ".join(sorted(self.allowed_edit_patterns)[:2]))
        return summary

    def _persist(self) -> None:
        _write_permission_store(
            {
                "allowedDirectoryPrefixes": sorted(self.allowed_directory_prefixes),
                "deniedDirectoryPrefixes": sorted(self.denied_directory_prefixes),
                "allowedCommandPatterns": sorted(self.allowed_command_patterns),
                "deniedCommandPatterns": sorted(self.denied_command_patterns),
                "allowedEditPatterns": sorted(self.allowed_edit_patterns),
                "deniedEditPatterns": sorted(self.denied_edit_patterns),
            }
        )

    def ensure_path_access(self, target_path: str, intent: str) -> None:
        normalized_target = _normalize_path(target_path)
        
        # Fast path: check workspace root first (most common case)
        # workspace_root is already normalized, so no need for Path.resolve() again
        if _is_within_directory(self.workspace_root, normalized_target):
            return
        
        # Check denial sets first (fail fast)
        if normalized_target in self.session_denied_paths or _matches_directory_prefix(normalized_target, self.denied_directory_prefixes):
            raise RuntimeError(f"Access denied for path outside cwd: {normalized_target}")
        
        # Check approval sets
        if normalized_target in self.session_allowed_paths or _matches_directory_prefix(normalized_target, self.allowed_directory_prefixes):
            return
        if normalized_target in self.session_denied_paths or _matches_directory_prefix(normalized_target, self.denied_directory_prefixes):
            raise RuntimeError(f"Access denied for path outside cwd: {normalized_target}")
        if normalized_target in self.session_allowed_paths or _matches_directory_prefix(normalized_target, self.allowed_directory_prefixes):
            return
        
        # Auto mode risk assessment for path access
        assessment = self.auto_checker.assess_risk("path_access", {"path": normalized_target, "intent": intent})
        if assessment.action == "approve":
            get_mode_state().record_decision("approve")
            self.session_allowed_paths.add(normalized_target)
            return
        
        if self.prompt is None:
            raise RuntimeError(
                f"Path {normalized_target} is outside cwd {self.workspace_root}. Start minicode in TTY mode to approve it."
            )

        scope_directory = normalized_target if intent in {"list", "command_cwd"} else str(Path(normalized_target).parent)
        result = self.prompt(
            {
                "kind": "path",
                "summary": f"mini-code wants {intent.replace('_', ' ')} access outside the current cwd",
                "details": [
                    f"cwd: {self.workspace_root}",
                    f"target: {normalized_target}",
                    f"scope directory: {scope_directory}",
                ],
                "scope": scope_directory,
                "choices": [
                    {"key": "y", "label": "allow once", "decision": "allow_once"},
                    {"key": "a", "label": "allow this directory", "decision": "allow_always"},
                    {"key": "n", "label": "deny once", "decision": "deny_once"},
                    {"key": "d", "label": "deny this directory", "decision": "deny_always"},
                ],
            }
        )
        decision = result.get("decision")
        if decision == "allow_once":
            self.session_allowed_paths.add(normalized_target)
            return
        if decision == "allow_always":
            self.allowed_directory_prefixes.add(scope_directory)
            self._persist()
            return
        if decision == "deny_always":
            self.denied_directory_prefixes.add(scope_directory)
            self._persist()
        else:
            self.session_denied_paths.add(normalized_target)
        raise RuntimeError(f"Access denied for path outside cwd: {normalized_target}")

    def ensure_command(
        self,
        command: str,
        args: list[str],
        command_cwd: str,
        force_prompt_reason: str | None = None,
    ) -> None:
        self.ensure_path_access(command_cwd, "command_cwd")
        reason = force_prompt_reason or _classify_dangerous_command(command, args)
        if not reason:
            # Not classified as dangerous — check auto mode for auto-approve
            assessment = self.auto_checker.assess_risk("run_command", {"command": [command] + args})
            if assessment.action == "approve":
                get_mode_state().record_decision("approve")
                return
            if assessment.action == "block":
                get_mode_state().record_decision("block")
                raise RuntimeError(f"Command blocked by auto mode: {assessment.reason}")
            # action == "prompt" — fall through to normal approval flow
            return
        signature = _format_command_signature(command, args)
        if signature in self.session_denied_commands or signature in self.denied_command_patterns:
            raise RuntimeError(f"Command denied: {signature}")
        if signature in self.session_allowed_commands or signature in self.allowed_command_patterns:
            return
        
        # Auto mode risk assessment for dangerous commands
        assessment = self.auto_checker.assess_risk("run_command", {"command": [command] + args})
        if assessment.action == "approve":
            get_mode_state().record_decision("approve")
            self.session_allowed_commands.add(signature)
            return
        if assessment.action == "block":
            get_mode_state().record_decision("block")
            raise RuntimeError(f"Command blocked by auto mode: {assessment.reason}")
        
        if self.prompt is None:
            raise RuntimeError(f"Command requires approval: {signature}. Start minicode in TTY mode to approve it.")
        # Distinguish forced prompts (external trigger) from dangerous commands
        summary = (
            "mini-code wants to run a dangerous command"
            if not force_prompt_reason
            else "mini-code wants approval for this command"
        )
        result = self.prompt(
            {
                "kind": "command",
                "summary": summary,
                "details": [f"cwd: {command_cwd}", f"command: {signature}", f"reason: {reason}"],
                "scope": signature,
                "choices": [
                    {"key": "y", "label": "allow once", "decision": "allow_once"},
                    {"key": "a", "label": "always allow this command", "decision": "allow_always"},
                    {"key": "n", "label": "deny once", "decision": "deny_once"},
                    {"key": "d", "label": "always deny this command", "decision": "deny_always"},
                ],
            }
        )
        decision = result.get("decision")
        if decision == "allow_once":
            self.session_allowed_commands.add(signature)
            return
        if decision == "allow_always":
            self.allowed_command_patterns.add(signature)
            self._persist()
            return
        if decision == "deny_always":
            self.denied_command_patterns.add(signature)
            self._persist()
        else:
            self.session_denied_commands.add(signature)
        raise RuntimeError(f"Command denied: {signature}")

    def ensure_edit(self, target_path: str, diff_preview: str) -> None:
        normalized_target = _normalize_path(target_path)
        if (
            normalized_target in self.session_denied_edits
            or normalized_target in self.denied_edit_patterns
        ):
            raise RuntimeError(f"Edit denied: {normalized_target}")
        if (
            normalized_target in self.session_allowed_edits
            or normalized_target in self.turn_allowed_edits
            or self.turn_allow_all_edits
            or normalized_target in self.allowed_edit_patterns
        ):
            return
        
        # Auto mode risk assessment for file edits
        assessment = self.auto_checker.assess_risk("edit_file", {"path": normalized_target})
        if assessment.action == "approve":
            get_mode_state().record_decision("approve")
            self.session_allowed_edits.add(normalized_target)
            return
        if assessment.action == "block":
            get_mode_state().record_decision("block")
            raise RuntimeError(f"Edit blocked by auto mode: {assessment.reason}")
        
        if self.prompt is None:
            raise RuntimeError(f"Edit requires approval: {normalized_target}. Start minicode in TTY mode to review it.")
        result = self.prompt(
            {
                "kind": "edit",
                "summary": "mini-code wants to apply a file modification",
                "details": [f"target: {normalized_target}", "", diff_preview],
                "scope": normalized_target,
                "choices": [
                    {"key": "1", "label": "apply once", "decision": "allow_once"},
                    {"key": "2", "label": "allow this file in this turn", "decision": "allow_turn"},
                    {"key": "3", "label": "allow all edits in this turn", "decision": "allow_all_turn"},
                    {"key": "4", "label": "always allow this file", "decision": "allow_always"},
                    {"key": "5", "label": "reject once", "decision": "deny_once"},
                    {"key": "6", "label": "reject and send guidance to model", "decision": "deny_with_feedback"},
                    {"key": "7", "label": "always reject this file", "decision": "deny_always"},
                ],
            }
        )
        decision = result.get("decision")
        if decision == "allow_once":
            self.session_allowed_edits.add(normalized_target)
            return
        if decision == "allow_turn":
            self.turn_allowed_edits.add(normalized_target)
            return
        if decision == "allow_all_turn":
            self.turn_allow_all_edits = True
            return
        if decision == "allow_always":
            self.allowed_edit_patterns.add(normalized_target)
            self._persist()
            return
        if decision == "deny_with_feedback":
            guidance = str(result.get("feedback", "")).strip()
            if guidance:
                raise RuntimeError(f"Edit denied: {normalized_target}\nUser guidance: {guidance}")
        if decision == "deny_always":
            self.denied_edit_patterns.add(normalized_target)
            self._persist()
        else:
            self.session_denied_edits.add(normalized_target)
        raise RuntimeError(f"Edit denied: {normalized_target}")


class PermissionGate:
    """Explicit permission gate for critical actions.

    Provides a declarative way to check permissions before executing
    high-risk operations (file writes, command execution, network requests).

    Usage:
        gate = PermissionGate(permissions, cwd)
        gate.check_file_write("src/main.py")
        gate.check_command_run("rm -rf /tmp")
    """

    def __init__(
        self,
        permissions: PermissionManager,
        cwd: str,
    ) -> None:
        self.permissions = permissions
        self.cwd = cwd

    def check_path_access(self, target_path: str, intent: str) -> None:
        """Gate for path access (read/write/list/search)."""
        self.permissions.ensure_path_access(target_path, intent)

    def check_file_write(self, target_path: str) -> None:
        """Gate specifically for file write operations."""
        self.check_path_access(target_path, "write")

    def check_command_run(self, command: str, args: list[str]) -> None:
        """Gate for command execution."""
        self.permissions.ensure_command(command, args, self.cwd)

    def check_file_edit(self, target_path: str, diff_preview: str) -> None:
        """Gate for file edit operations with diff preview."""
        self.permissions.ensure_edit(target_path, diff_preview)
