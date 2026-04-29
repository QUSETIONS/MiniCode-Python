from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from typing import Sequence

from minicode.background_tasks import register_background_shell_task
from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path

# 命令执行超时（秒）- 5 分钟
COMMAND_TIMEOUT = 300

# 最大输出大小（字符）- 防止超大输出撑爆上下文
MAX_OUTPUT_CHARS = 200_000


def _truncate_large_output(output: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate very large command output to prevent context bloat."""
    if len(output) <= max_chars:
        return output
    
    lines = output.split("\n")
    total_lines = len(lines)
    # Keep head (first 60%) and tail (last 40%)
    head_lines = int(total_lines * 0.6)
    tail_lines = total_lines - head_lines
    if tail_lines > int(total_lines * 0.4):
        tail_lines = int(total_lines * 0.4)
        head_lines = total_lines - tail_lines
    
    head = "\n".join(lines[:head_lines])
    tail = "\n".join(lines[-tail_lines:])
    omitted = total_lines - head_lines - tail_lines
    return f"{head}\n\n... [{omitted} lines omitted, output was {len(output):,} chars] ...\n\n{tail}"

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


def _classify_shell_snippet_risk(command: str) -> str | None:
    lowered = command.lower()
    collapsed = re.sub(r"\s+", " ", lowered).strip()
    if re.search(r"\brm\s+-[a-z]*r[a-z]*f\b|\brm\s+-[a-z]*f[a-z]*r\b", collapsed):
        return f"shell snippet contains rm -rf payload: {command}"
    if re.search(r"\b(del|erase)\b.*\s/(s|q)\b", collapsed):
        return f"shell snippet contains recursive Windows delete payload: {command}"
    if re.search(r"\b(rmdir|rd)\b.*\s/s\b", collapsed):
        return f"shell snippet contains recursive Windows directory removal: {command}"
    if re.search(r"\b(curl|wget)\b.*\|\s*(sh|bash|zsh|fish)\b", collapsed):
        return f"shell snippet downloads and executes a shell script: {command}"
    if re.search(r"\b(iwr|irm|invoke-webrequest|invoke-restmethod|curl|wget)\b.*\|\s*(iex|invoke-expression)\b", collapsed):
        return f"shell snippet downloads and executes PowerShell code: {command}"
    if re.search(r"\b(powershell|pwsh)\b.*\b(iex|invoke-expression)\b", collapsed):
        return f"shell snippet invokes PowerShell expression execution: {command}"
    if re.search(r"\b(sh|bash|zsh|fish|cmd|powershell|pwsh)\b\s+(-c|/c|/command)\b", collapsed):
        return f"shell snippet invokes an explicit command interpreter: {command}"
    return None


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
        # Use the user's preferred shell (macOS defaults to zsh since
        # Catalina).  Fall back to /bin/sh for maximum POSIX compatibility.
        shell = os.environ.get("SHELL", "/bin/sh")
        return shell, ["-lc", shell_command]
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
    # Optional timeout (seconds), clamped to [1, 600]
    timeout = input_data.get("timeout")
    if timeout is not None:
        try:
            timeout = max(1, min(600, int(timeout)))
        except (ValueError, TypeError):
            timeout = None
    return {"command": command, "args": [str(arg) for arg in args], "cwd": cwd, "timeout": timeout}


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
    shell_prompt_reason = _classify_shell_snippet_risk(input_data["command"]) if use_shell else None
    force_prompt_reason = (
        shell_prompt_reason
        if shell_prompt_reason
        else None if use_shell or known_command else f"Unknown command '{normalized_command}' is not in the built-in read-only/development set"
    )

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

    if sys.platform != "win32":
        try:
            import pty
            import select
            
            master_fd, slave_fd = pty.openpty()
            effective_timeout = input_data.get("timeout") or COMMAND_TIMEOUT
            
            process = subprocess.Popen(
                [command, *args],
                cwd=effective_cwd,
                env=os.environ.copy(),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )
            
            os.close(slave_fd)
            output_bytes = bytearray()
            timed_out = False
            
            try:
                while True:
                    r, _, _ = select.select([master_fd], [], [], effective_timeout)
                    if not r:
                        timed_out = True
                        process.kill()
                        process.wait()
                        break
                    
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            break
                        output_bytes.extend(data)
                    except OSError:
                        # EIO happens when child closes the PTY or exits
                        break
            finally:
                os.close(master_fd)
                if not timed_out:
                    process.wait()
                
            output_str = output_bytes.decode("utf-8", errors="replace").strip()
            output_str = output_str.replace("\r\n", "\n")
            output_str = _truncate_large_output(output_str)
            
            if timed_out:
                return ToolResult(
                    ok=False,
                    output=f"Command timed out after {effective_timeout} seconds (process killed).\nPartial output:\n{output_str}",
                )
            return ToolResult(ok=process.returncode == 0, output=output_str)
            
        except ImportError:
            pass  # Fallback to subprocess on systems without pty

    try:
        effective_timeout = input_data.get("timeout") or COMMAND_TIMEOUT
        completed = subprocess.run(  # noqa: S603
            [command, *args],
            cwd=effective_cwd,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            encoding="utf-8",  # 显式指定 UTF-8
            errors="replace",   # 无法解码时替换字符而非报错
            check=False,
            timeout=effective_timeout,
        )
        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part).strip()
        output = _truncate_large_output(output)
        return ToolResult(ok=completed.returncode == 0, output=output)
    except subprocess.TimeoutExpired as e:
        # Capture partial output from timeout
        partial_stdout = (e.stdout or "").strip() if e.stdout else ""
        partial_stderr = (e.stderr or "").strip() if e.stderr else ""
        partial = "\n".join(part for part in [partial_stdout, partial_stderr] if part)
        if partial:
            partial = f"\nPartial output:\n{_truncate_large_output(partial)}"
        return ToolResult(
            ok=False,
            output=f"Command timed out after {effective_timeout} seconds (process killed).{partial}",
        )


run_command_tool = ToolDefinition(
    name="run_command",
    description="Run a common development command from an allowlist. Supports optional timeout parameter (1-600 seconds).",
    input_schema={"type": "object", "properties": {"command": {"type": "string", "description": "Command to run"}, "args": {"type": "array", "items": {"type": "string"}, "description": "Arguments"}, "cwd": {"type": "string", "description": "Working directory"}, "timeout": {"type": "integer", "description": "Timeout in seconds (1-600, default 300)"}}, "required": ["command"]},
    validator=_validate,
    run=_run,
)
