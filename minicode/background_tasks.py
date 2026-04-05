from __future__ import annotations

import os
import signal
import time
import uuid
from typing import Any

from minicode.tooling import BackgroundTaskResult

# In-memory registry of background tasks
_background_tasks: dict[str, dict[str, Any]] = {}


def _refresh_record(record: dict[str, Any]) -> dict[str, Any]:
    """Check if a running process is still alive and update status."""
    if record.get("status") != "running":
        return record
    pid = record.get("pid")
    if pid is None:
        return record
    try:
        os.kill(pid, 0)  # signal 0 = existence check, no actual signal sent
        return record
    except ProcessLookupError:
        # ESRCH — process no longer exists
        record["status"] = "completed"
        return record
    except PermissionError:
        # EPERM — process exists but we can't signal it; still alive
        return record
    except OSError:
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
