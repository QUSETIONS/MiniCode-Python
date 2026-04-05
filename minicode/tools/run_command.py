from __future__ import annotations

import os
import shlex
import subprocess
import sys
from typing import Sequence

from minicode.background_tasks import register_background_shell_task
from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path

# 命令执行超时（秒）- 5 分钟
COMMAND_TIMEOUT = 300

# Read-only commands that never need permission prompts.
# Includes both Unix and Windows equivalents.
READONLY_COMMANDS = {
    # Unix
    "pwd",
    "ls",
    "find",
    "rg",
    "grep",
    "cat",
    "head",
    "tail",
    "wc",
    "sed",
    "echo",
    "df",
    "du",
    "whoami",
    # Windows equivalents
    "dir",
    "type",
    "where",
    "findstr",
    "more",
    "hostname",
}

# Development commands (write access but commonly allowed).
DEVELOPMENT_COMMANDS = {
    "git",
    "npm",
    "node",
    "python",
    "python3",
    "pytest",
    "bash",
    "sh",
    # Windows-common development tools
    "pip",
    "pip3",
    "cargo",
    "go",
    "make",
    "cmake",
    "dotnet",
    "powershell",
    "pwsh",
    "cmd",
}


def split_command_line(command_line: str) -> list[str]:
    """Split a command string into tokens.

    On Windows, ``shlex.split(posix=True)`` can choke on backslash paths
    (e.g. ``C:\\Users\\foo``).  We fall back to ``posix=False`` which
    preserves backslashes, then try the native ``shlex.split`` as a
    last resort.
    """
    if os.name == "nt":
        try:
            return shlex.split(command_line, posix=False)
        except ValueError:
            # If even non-posix fails, fall back to simple whitespace split
            return command_line.split()
    return shlex.split(command_line, posix=True)


def _is_allowed_command(command: str) -> bool:
    cmd = command.lower() if os.name == "nt" else command
    return cmd in READONLY_COMMANDS or cmd in DEVELOPMENT_COMMANDS


def _is_read_only_command(command: str) -> bool:
    cmd = command.lower() if os.name == "nt" else command
    return cmd in READONLY_COMMANDS


def _looks_like_shell_snippet(command: str, args: list[str]) -> bool:
    return not args and any(char in command for char in "|&;<>()$`")


def _is_background_shell_snippet(command: str, args: list[str]) -> bool:
    trimmed = command.strip()
    return not args and trimmed.endswith("&") and not trimmed.endswith("&&")


def _strip_trailing_background_operator(command: str) -> str:
    return command.strip().removesuffix("&").strip()


def _normalize_command_input(input_data: dict) -> tuple[str, list[str]]:
    command = str(input_data.get("command", "")).strip()
    raw_args = input_data.get("args") or []
    if raw_args:
        return command, [str(arg) for arg in raw_args]
    parsed = split_command_line(command) if command else []
    return (parsed[0], parsed[1:]) if parsed else ("", [])


def _is_windows_shell_builtin(command: str) -> bool:
    return os.name == "nt" and command.lower() in {
        "cd",
        "chdir",
        "cls",
        "copy",
        "date",
        "del",
        "dir",
        "echo",
        "erase",
        "md",
        "mkdir",
        "mklink",
        "move",
        "rd",
        "ren",
        "rename",
        "rmdir",
        "time",
        "type",
        "ver",
        "vol",
    }


def _build_execution_command(
    raw_command: str,
    normalized_command: str,
    normalized_args: Sequence[str],
    *,
    use_shell: bool,
    background_shell: bool,
) -> tuple[str, list[str]]:
    if use_shell:
        shell_command = _strip_trailing_background_operator(raw_command) if background_shell else raw_command
        if os.name == "nt":
            return "cmd", ["/d", "/s", "/c", shell_command]
        return "bash", ["-lc", shell_command]
    if _is_windows_shell_builtin(normalized_command):
        quoted_args = subprocess.list2cmdline(list(normalized_args))
        shell_command = normalized_command if not quoted_args else f"{normalized_command} {quoted_args}"
        return "cmd", ["/d", "/s", "/c", shell_command]
    return normalized_command, list(normalized_args)


def _validate(input_data: dict) -> dict:
    command = input_data.get("command")
    if not isinstance(command, str):
        raise ValueError("command is required")
    args = input_data.get("args") or []
    if not isinstance(args, list):
        raise ValueError("args must be a list")
    cwd = input_data.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("cwd must be a string")
    return {"command": command, "args": [str(arg) for arg in args], "cwd": cwd}


def _run(input_data: dict, context) -> ToolResult:
    effective_cwd = str(resolve_tool_path(context, input_data["cwd"], "list")) if input_data.get("cwd") else context.cwd
    normalized_command, normalized_args = _normalize_command_input(input_data)
    if not normalized_command:
        return ToolResult(ok=False, output="Command not allowed: empty command")

    raw_args = input_data.get("args") or []
    use_shell = _looks_like_shell_snippet(input_data["command"], raw_args)
    background_shell = _is_background_shell_snippet(input_data["command"], raw_args)
    known_command = _is_allowed_command(normalized_command)

    command, args = _build_execution_command(
        input_data["command"],
        normalized_command,
        normalized_args,
        use_shell=use_shell,
        background_shell=background_shell,
    )
    force_prompt_reason = None if use_shell or known_command else f"Unknown command '{normalized_command}' is not in the built-in read-only/development set"

    if context.permissions is not None:
        if force_prompt_reason:
            context.permissions.ensure_command(command, args, effective_cwd, force_prompt_reason=force_prompt_reason)
        elif use_shell or not _is_read_only_command(normalized_command):
            context.permissions.ensure_command(command, args, effective_cwd)

    if use_shell and background_shell:
        # Platform-specific process isolation flags
        popen_kwargs: dict = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            # On Unix, start the background process in its own session so
            # it is not killed when the parent terminal closes.
            popen_kwargs["start_new_session"] = True

        child = subprocess.Popen(  # noqa: S603
            [command, *args],
            cwd=effective_cwd,
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **popen_kwargs,
        )
        
        if child.pid is None:
            return ToolResult(
                ok=False,
                output="Failed to get PID for background command. Process may have exited immediately.",
            )
        
        background_task = register_background_shell_task(
            command=_strip_trailing_background_operator(input_data["command"]),
            pid=child.pid,
            cwd=effective_cwd,
        )
        return ToolResult(
            ok=True,
            output=f"Background command started.\nTASK: {background_task.taskId}\nPID: {background_task.pid}",
            backgroundTask=background_task,
        )

    try:
        completed = subprocess.run(  # noqa: S603
            [command, *args],
            cwd=effective_cwd,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            encoding="utf-8",  # 显式指定 UTF-8
            errors="replace",   # 无法解码时替换字符而非报错
            check=False,
            timeout=COMMAND_TIMEOUT,
        )
        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part).strip()
        return ToolResult(ok=completed.returncode == 0, output=output)
    except subprocess.TimeoutExpired as e:
        return ToolResult(
            ok=False,
            output=f"Command timed out after {COMMAND_TIMEOUT} seconds. Command: {normalized_command} {' '.join(normalized_args)}",
        )


run_command_tool = ToolDefinition(
    name="run_command",
    description="Run a common development command from an allowlist.",
    input_schema={"type": "object", "properties": {"command": {"type": "string"}, "args": {"type": "array"}, "cwd": {"type": "string"}}, "required": ["command"]},
    validator=_validate,
    run=_run,
)
