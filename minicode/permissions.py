from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from minicode.config import MINI_CODE_PERMISSIONS_PATH


PromptHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _normalize_path(target_path: str) -> str:
    return str(Path(target_path).resolve())


def _is_within_directory(root: str, target: str) -> bool:
    try:
        Path(target).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _matches_directory_prefix(target_path: str, directories: set[str]) -> bool:
    return any(_is_within_directory(directory, target_path) for directory in directories)


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

    if command in {"node", "python", "python3", "bun", "bash", "sh"}:
        return f"{command} can execute arbitrary local code ({signature})"

    return None


def _read_permission_store() -> dict[str, Any]:
    if not MINI_CODE_PERMISSIONS_PATH.exists():
        return {}
    return json.loads(MINI_CODE_PERMISSIONS_PATH.read_text(encoding="utf-8"))


def _write_permission_store(store: dict[str, Any]) -> None:
    MINI_CODE_PERMISSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MINI_CODE_PERMISSIONS_PATH.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


class PermissionManager:
    def __init__(self, workspace_root: str, prompt: PromptHandler | None = None) -> None:
        self.workspace_root = _normalize_path(workspace_root)
        self.prompt = prompt
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
        if _is_within_directory(self.workspace_root, normalized_target):
            return
        if normalized_target in self.session_denied_paths or _matches_directory_prefix(normalized_target, self.denied_directory_prefixes):
            raise RuntimeError(f"Access denied for path outside cwd: {normalized_target}")
        if normalized_target in self.session_allowed_paths or _matches_directory_prefix(normalized_target, self.allowed_directory_prefixes):
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
            return
        signature = _format_command_signature(command, args)
        if signature in self.session_denied_commands or signature in self.denied_command_patterns:
            raise RuntimeError(f"Command denied: {signature}")
        if signature in self.session_allowed_commands or signature in self.allowed_command_patterns:
            return
        if self.prompt is None:
            raise RuntimeError(f"Command requires approval: {signature}. Start minicode in TTY mode to approve it.")
        result = self.prompt(
            {
                "kind": "command",
                "summary": "mini-code wants approval for this command",
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
