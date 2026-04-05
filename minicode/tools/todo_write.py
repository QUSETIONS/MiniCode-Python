from __future__ import annotations

import json
import time
from minicode.tooling import ToolDefinition, ToolResult

# In-memory task storage (resets per session)
_tasks = []
_task_id_counter = 0


def _validate(input_data: dict) -> dict:
    todos = input_data.get("todos")
    if not isinstance(todos, list):
        raise ValueError("todos must be a list")
    for i, todo in enumerate(todos):
        if not isinstance(todo, dict):
            raise ValueError(f"todo[{i}] must be an object")
        if "content" not in todo:
            raise ValueError(f"todo[{i}] must have a 'content' field")
        status = todo.get("status", "pending")
        if status not in ("pending", "in_progress", "completed"):
            raise ValueError(f"todo[{i}] status must be 'pending', 'in_progress', or 'completed'")
    return {"todos": todos}


def _run(input_data: dict, context) -> ToolResult:
    global _tasks, _task_id_counter

    todos = input_data["todos"]

    # Clear existing tasks and replace
    _tasks.clear()

    for todo in todos:
        # Try to find existing task by content
        existing = None
        for task in _tasks:
            if task["content"] == todo["content"]:
                existing = task
                break

        if existing:
            # Update existing task
            existing["status"] = todo.get("status", existing["status"])
            if todo.get("status") == "completed" and not existing.get("completed_at"):
                existing["completed_at"] = time.time()
        else:
            # Create new task
            _task_id_counter += 1
            new_task = {
                "id": _task_id_counter,
                "content": todo["content"],
                "status": todo.get("status", "pending"),
                "created_at": time.time(),
                "completed_at": time.time() if todo.get("status") == "completed" else None,
            }
            _tasks.append(new_task)

    # Format output
    lines = ["Task list updated:", ""]

    for task in _tasks:
        status_icon = {
            "pending": "○",
            "in_progress": "◐",
            "completed": "●",
        }.get(task["status"], "?")

        lines.append(f"{status_icon} [{task['id']}] {task['content']}")

    lines.append("")

    # Summary
    pending = sum(1 for t in _tasks if t["status"] == "pending")
    in_progress = sum(1 for t in _tasks if t["status"] == "in_progress")
    completed = sum(1 for t in _tasks if t["status"] == "completed")
    total = len(_tasks)

    lines.extend([
        f"Total: {total} | Pending: {pending} | In Progress: {in_progress} | Completed: {completed}",
    ])

    return ToolResult(ok=True, output="\n".join(lines))


todo_write_tool = ToolDefinition(
    name="todo_write",
    description="Create or update a list of tasks. Use this to track progress on multi-step tasks. Each task has content (required) and status (pending/in_progress/completed). Pass the complete list each time to update.",
    input_schema={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Complete list of tasks to track. Each task must have 'content' (string) and optionally 'status' (pending/in_progress/completed).",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Task description"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "Task status"},
                    },
                    "required": ["content"],
                },
            },
        },
        "required": ["todos"],
    },
    validator=_validate,
    run=_run,
)
