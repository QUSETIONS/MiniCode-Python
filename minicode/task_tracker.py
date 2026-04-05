"""Lightweight task tracking for multi-step agent execution.

Provides simple todo/task tracking that integrates with the agent loop
to show progress during long multi-step operations.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from minicode.config import MINI_CODE_DIR


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    """Task status enum."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class Task:
    """A single task item."""
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    error: str | None = None
    
    def complete(self) -> None:
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = time.time()
        self.updated_at = time.time()
    
    def fail(self, error: str) -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED
        self.error = error
        self.updated_at = time.time()
    
    def cancel(self) -> None:
        """Mark task as cancelled."""
        self.status = TaskStatus.CANCELLED
        self.updated_at = time.time()
    
    def start(self) -> None:
        """Mark task as in progress."""
        self.status = TaskStatus.IN_PROGRESS
        self.updated_at = time.time()


@dataclass
class TaskList:
    """A list of tasks for tracking multi-step progress."""
    title: str = ""
    tasks: list[Task] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    @property
    def total(self) -> int:
        """Total number of tasks."""
        return len(self.tasks)
    
    @property
    def completed_count(self) -> int:
        """Number of completed tasks."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
    
    @property
    def pending_count(self) -> int:
        """Number of pending tasks."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.PENDING)
    
    @property
    def in_progress_count(self) -> int:
        """Number of in-progress tasks."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.IN_PROGRESS)
    
    @property
    def failed_count(self) -> int:
        """Number of failed tasks."""
        return sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)
    
    @property
    def progress_percentage(self) -> float:
        """Completion percentage."""
        if self.total == 0:
            return 0.0
        return (self.completed_count / self.total) * 100
    
    @property
    def is_complete(self) -> bool:
        """Check if all tasks are completed, cancelled, or failed."""
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED)
            for t in self.tasks
        )
    
    def add_task(self, description: str) -> Task:
        """Add a new task."""
        task = Task(
            id=str(len(self.tasks) + 1),
            description=description,
        )
        self.tasks.append(task)
        self.updated_at = time.time()
        return task
    
    def get_task(self, task_id: str) -> Task | None:
        """Get task by ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
    
    def mark_completed(self, task_id: str) -> bool:
        """Mark a task as completed."""
        task = self.get_task(task_id)
        if task:
            task.complete()
            self.updated_at = time.time()
            return True
        return False
    
    def mark_failed(self, task_id: str, error: str) -> bool:
        """Mark a task as failed."""
        task = self.get_task(task_id)
        if task:
            task.fail(error)
            self.updated_at = time.time()
            return True
        return False
    
    def get_current_task(self) -> Task | None:
        """Get the first pending or in-progress task."""
        for task in self.tasks:
            if task.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
                return task
        return None
    
    def get_next_pending(self) -> Task | None:
        """Get the next pending task."""
        for task in self.tasks:
            if task.status == TaskStatus.PENDING:
                return task
        return None


# ---------------------------------------------------------------------------
# Task Manager
# ---------------------------------------------------------------------------

class TaskManager:
    """Manages task lists for the current session."""
    
    def __init__(self):
        self.active_list: TaskList | None = None
        self.history: list[TaskList] = []
    
    def create_list(self, title: str) -> TaskList:
        """Create a new task list."""
        # Archive current list if exists
        if self.active_list:
            self.history.append(self.active_list)
        
        self.active_list = TaskList(title=title)
        return self.active_list
    
    def add_task(self, description: str) -> Task | None:
        """Add task to active list."""
        if not self.active_list:
            self.active_list = TaskList(title="Tasks")
        return self.active_list.add_task(description)
    
    def complete_task(self, task_id: str) -> bool:
        """Mark task as completed."""
        if not self.active_list:
            return False
        return self.active_list.mark_completed(task_id)
    
    def fail_task(self, task_id: str, error: str) -> bool:
        """Mark task as failed."""
        if not self.active_list:
            return False
        return self.active_list.mark_failed(task_id, error)
    
    def get_status(self) -> str:
        """Get formatted status string."""
        if not self.active_list:
            return "No active tasks"
        
        tl = self.active_list
        status_parts = []
        
        if tl.title:
            status_parts.append(f"📋 {tl.title}")
        
        status_parts.append(
            f"{tl.completed_count}/{tl.total} done "
            f"({tl.progress_percentage:.0f}%)"
        )
        
        if tl.in_progress_count > 0:
            current = tl.get_current_task()
            if current:
                status_parts.append(f"→ {current.description[:50]}")
        
        if tl.failed_count > 0:
            status_parts.append(f"⚠ {tl.failed_count} failed")
        
        return " | ".join(status_parts)
    
    def format_details(self) -> str:
        """Format full task list details."""
        if not self.active_list:
            return "No active task list."
        
        tl = self.active_list
        lines = [
            f"Task List: {tl.title or 'Untitled'}",
            f"Progress: {tl.completed_count}/{tl.total} completed ({tl.progress_percentage:.0f}%)",
            "",
        ]
        
        for task in tl.tasks:
            status_icon = {
                TaskStatus.PENDING: "○",
                TaskStatus.IN_PROGRESS: "◐",
                TaskStatus.COMPLETED: "●",
                TaskStatus.FAILED: "✗",
                TaskStatus.CANCELLED: "⊘",
            }.get(task.status, "?")
            
            lines.append(f"  {status_icon} [{task.id}] {task.description}")
            
            if task.status == TaskStatus.FAILED and task.error:
                lines.append(f"      Error: {task.error}")
        
        lines.append("")
        lines.append(f"Total: {tl.total} | Done: {tl.completed_count} | Pending: {tl.pending_count}")
        
        if tl.failed_count > 0:
            lines.append(f"Failed: {tl.failed_count}")
        
        return "\n".join(lines)
    
    def auto_detect_tasks(self, user_input: str) -> list[str] | None:
        """Auto-detect task list from user input.
        
        Looks for patterns like:
        - "Do X, then Y, then Z"
        - "First X, second Y, finally Z"
        - Numbered/bulleted lists
        """
        import re
        
        lines = user_input.strip().split("\n")
        
        # Check for numbered list
        numbered = []
        for line in lines:
            match = re.match(r"^\d+[\.\)]\s+(.+)", line.strip())
            if match:
                numbered.append(match.group(1))
        
        if len(numbered) >= 2:
            return numbered
        
        # Check for bullet points
        bullets = []
        for line in lines:
            match = re.match(r"^[-*•]\s+(.+)", line.strip())
            if match:
                bullets.append(match.group(1))
        
        if len(bullets) >= 2:
            return bullets
        
        # Check for comma-separated steps
        if "," in user_input and len(lines) == 1:
            steps = [s.strip() for s in user_input.split(",") if s.strip()]
            if len(steps) >= 3:
                # Check for sequential indicators
                sequential_words = ["then", "next", "after", "finally", "last"]
                has_sequence = any(word in user_input.lower() for word in sequential_words)
                if has_sequence:
                    return steps
        
        return None
    
    def create_from_input(self, user_input: str, title: str = "") -> TaskList | None:
        """Create task list from user input if it contains multiple steps."""
        tasks = self.auto_detect_tasks(user_input)
        if not tasks:
            return None
        
        task_list = self.create_list(title or "Auto-detected tasks")
        for task_desc in tasks:
            task_list.add_task(task_desc)
        
        return task_list
    
    def clear(self) -> None:
        """Clear active task list."""
        if self.active_list:
            self.history.append(self.active_list)
            self.active_list = None


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------

def format_task_update(task: Task, status: TaskStatus) -> str:
    """Format a task status update for display."""
    icons = {
        TaskStatus.PENDING: "○",
        TaskStatus.IN_PROGRESS: "◐",
        TaskStatus.COMPLETED: "✓",
        TaskStatus.FAILED: "✗",
        TaskStatus.CANCELLED: "⊘",
    }
    
    icon = icons.get(status, "?")
    return f"{icon} Task {task.id}: {task.description}"


def should_show_task_progress(task_list: TaskList | None) -> bool:
    """Check if task progress should be shown in UI."""
    if not task_list:
        return False
    return not task_list.is_complete and task_list.total > 1


def format_task_progress_bar(task_list: TaskList, width: int = 30) -> str:
    """Format a visual progress bar."""
    if task_list.total == 0:
        return " " * width
    
    filled = int(width * task_list.progress_percentage / 100)
    empty = width - filled
    
    bar = "█" * filled + "░" * empty
    return f"[{bar}] {task_list.progress_percentage:.0f}%"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_task_list(task_list: TaskList, session_id: str) -> None:
    """Save task list to disk."""
    tasks_dir = MINI_CODE_DIR / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    
    task_file = tasks_dir / f"{session_id}.json"
    
    data = {
        "title": task_list.title,
        "created_at": task_list.created_at,
        "updated_at": task_list.updated_at,
        "tasks": [
            {
                "id": t.id,
                "description": t.description,
                "status": t.status.value,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
                "completed_at": t.completed_at,
                "error": t.error,
            }
            for t in task_list.tasks
        ],
    }
    
    task_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_task_list(session_id: str) -> TaskList | None:
    """Load task list from disk."""
    task_file = MINI_CODE_DIR / "tasks" / f"{session_id}.json"
    if not task_file.exists():
        return None
    
    try:
        data = json.loads(task_file.read_text(encoding="utf-8"))
        task_list = TaskList(
            title=data.get("title", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )
        
        for task_data in data.get("tasks", []):
            task = Task(
                id=task_data["id"],
                description=task_data["description"],
                status=TaskStatus(task_data.get("status", "pending")),
                created_at=task_data.get("created_at", time.time()),
                updated_at=task_data.get("updated_at", time.time()),
                completed_at=task_data.get("completed_at"),
                error=task_data.get("error"),
            )
            task_list.tasks.append(task)
        
        return task_list
    except (json.JSONDecodeError, KeyError):
        return None
