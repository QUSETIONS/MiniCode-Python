from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any

from minicode.tooling import BackgroundTaskResult

# In-memory registry of background tasks
_background_tasks: dict[str, dict[str, Any]] = {}


def _is_process_alive(pid: int) -> bool | None:
    """Check if a process is alive.  Cross-platform.

    Returns:
        True  — process is alive
        False — process is definitely gone
        None  — cannot determine (treat as "failed")
    """
    if sys.platform == "win32":
        # On Windows, os.kill(pid, 0) raises OSError for *every* case
        # (including when the process exists), so we use ctypes instead.
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259

            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False  # Cannot open → process gone

            try:
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == STILL_ACTIVE
                return None
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return None
    else:
        # Unix: signal 0 checks existence without actually sending a signal
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # EPERM — process exists but we can't signal it; still alive
            return True
        except OSError:
            return None


def _refresh_record(record: dict[str, Any]) -> dict[str, Any]:
    """Check if a running process is still alive and update status."""
    if record.get("status") != "running":
        return record
    pid = record.get("pid")
    if pid is None:
        return record

    alive = _is_process_alive(pid)
    if alive is True:
        return record
    elif alive is False:
        record["status"] = "completed"
    else:
        record["status"] = "failed"
    return record


def register_background_shell_task(command: str, pid: int, cwd: str) -> BackgroundTaskResult:
    del cwd
    result = BackgroundTaskResult(
        taskId=f"task_{uuid.uuid4().hex[:8]}",
        type="local_bash",
        command=command,
        pid=pid,
        status="running",
        startedAt=int(time.time() * 1000),
    )
    _background_tasks[result.taskId] = {
        "taskId": result.taskId,
        "type": result.type,
        "command": result.command,
        "pid": result.pid,
        "status": result.status,
        "startedAt": result.startedAt,
        "label": command[:60],
    }
    return result


def list_background_tasks() -> list[dict[str, Any]]:
    """Return the list of currently tracked background tasks with refreshed status."""
    return [_refresh_record(record) for record in _background_tasks.values()]


def get_background_task(task_id: str) -> dict[str, Any] | None:
    """Get a single background task by ID with refreshed status."""
    record = _background_tasks.get(task_id)
    if record is None:
        return None
    return _refresh_record(record)
