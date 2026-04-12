"""Persistent task graph for cross-step workflow management.

Inspired by Learn Claude Code best practices:
- Distinguish between session-local planning and persistent task coordination
- Separate task definition (what) from execution slot (who is running / progress)
- Background task slot management with timed scheduling
- Worktree execution isolation for risky operations

Provides:
- TaskGraph: DAG of tasks with dependencies
- TaskSlot: Named execution slot with state tracking
- WorktreeIsolator: Temporary worktree for risky operations
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from minicode.config import MINI_CODE_DIR


# ---------------------------------------------------------------------------
# Task Graph
# ---------------------------------------------------------------------------

class TaskState(str, Enum):
    """Task execution state."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskPriority(str, Enum):
    """Task priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TaskDefinition:
    """What needs to be done (persistent, cross-session)."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.NORMAL
    timeout_seconds: int = 300
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskSlot:
    """Who is running and current progress (session-local)."""

    task_id: str
    slot_name: str = "default"
    state: TaskState = TaskState.PENDING
    progress: float = 0.0  # 0.0 - 1.0
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    result: str | None = None


@dataclass
class TaskGraph:
    """Persistent task graph with execution slots."""

    name: str = ""
    definitions: dict[str, TaskDefinition] = field(default_factory=dict)
    slots: dict[str, TaskSlot] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # --- Definition API ---
    def add_task(
        self,
        name: str,
        description: str = "",
        dependencies: list[str] | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout_seconds: int = 300,
    ) -> TaskDefinition:
        """Add a task definition to the graph."""
        task_def = TaskDefinition(
            name=name,
            description=description,
            dependencies=dependencies or [],
            priority=priority,
            timeout_seconds=timeout_seconds,
        )
        self.definitions[task_def.id] = task_def
        self.updated_at = time.time()
        return task_def

    # --- Slot API ---
    def assign_slot(self, task_id: str, slot_name: str = "default") -> TaskSlot:
        """Assign a task to an execution slot."""
        if task_id not in self.definitions:
            raise ValueError(f"Task {task_id} not found")

        slot = TaskSlot(task_id=task_id, slot_name=slot_name)
        slot_key = f"{slot_name}:{task_id}"
        self.slots[slot_key] = slot
        self.updated_at = time.time()
        return slot

    def start_task(self, slot_key: str) -> TaskSlot:
        """Mark a slot as running."""
        slot = self.slots.get(slot_key)
        if not slot:
            raise ValueError(f"Slot {slot_key} not found")
        slot.state = TaskState.RUNNING
        slot.started_at = time.time()
        slot.progress = 0.0
        self.updated_at = time.time()
        return slot

    def complete_task(self, slot_key: str, result: str = "") -> TaskSlot:
        """Mark a slot as completed."""
        slot = self.slots.get(slot_key)
        if not slot:
            raise ValueError(f"Slot {slot_key} not found")
        slot.state = TaskState.COMPLETED
        slot.completed_at = time.time()
        slot.progress = 1.0
        slot.result = result
        self.updated_at = time.time()
        return slot

    def fail_task(self, slot_key: str, error: str) -> TaskSlot:
        """Mark a slot as failed."""
        slot = self.slots.get(slot_key)
        if not slot:
            raise ValueError(f"Slot {slot_key} not found")
        slot.state = TaskState.FAILED
        slot.completed_at = time.time()
        slot.error = error
        self.updated_at = time.time()
        return slot

    # --- Graph Logic ---
    def get_ready_tasks(self) -> list[TaskDefinition]:
        """Get tasks whose dependencies are all completed."""
        completed_task_ids = {
            slot.task_id for slot in self.slots.values()
            if slot.state == TaskState.COMPLETED
        }

        ready = []
        for task_def in self.definitions.values():
            if task_def.id in completed_task_ids:
                continue
            # Check if already running
            if any(
                s.task_id == task_def.id and s.state == TaskState.RUNNING
                for s in self.slots.values()
            ):
                continue
            # Check dependencies
            if all(dep in completed_task_ids for dep in task_def.dependencies):
                ready.append(task_def)

        # Sort by priority
        priority_order = {
            TaskPriority.CRITICAL: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.LOW: 3,
        }
        ready.sort(key=lambda t: priority_order.get(t.priority, 2))
        return ready

    def is_graph_complete(self) -> bool:
        """Check if all tasks in the graph are completed."""
        if not self.definitions:
            return True
        completed_ids = {
            slot.task_id for slot in self.slots.values()
            if slot.state == TaskState.COMPLETED
        }
        return all(tid in completed_ids for tid in self.definitions)

    def get_progress_percentage(self) -> float:
        """Overall graph progress."""
        if not self.definitions:
            return 0.0
        completed = sum(
            1 for slot in self.slots.values()
            if slot.state == TaskState.COMPLETED
        )
        return (completed / len(self.definitions)) * 100

    # --- Persistence ---
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "definitions": {
                tid: {
                    "id": td.id,
                    "name": td.name,
                    "description": td.description,
                    "dependencies": td.dependencies,
                    "priority": td.priority.value,
                    "timeout_seconds": td.timeout_seconds,
                    "created_at": td.created_at,
                    "metadata": td.metadata,
                }
                for tid, td in self.definitions.items()
            },
            "slots": {
                sk: {
                    "task_id": s.task_id,
                    "slot_name": s.slot_name,
                    "state": s.state.value,
                    "progress": s.progress,
                    "started_at": s.started_at,
                    "completed_at": s.completed_at,
                    "error": s.error,
                    "result": s.result,
                }
                for sk, s in self.slots.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskGraph:
        """Deserialize from dictionary."""
        graph = cls(
            name=data.get("name", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )
        for tid, td_data in data.get("definitions", {}).items():
            graph.definitions[tid] = TaskDefinition(
                id=td_data["id"],
                name=td_data["name"],
                description=td_data.get("description", ""),
                dependencies=td_data.get("dependencies", []),
                priority=TaskPriority(td_data.get("priority", "normal")),
                timeout_seconds=td_data.get("timeout_seconds", 300),
                created_at=td_data.get("created_at", time.time()),
                metadata=td_data.get("metadata", {}),
            )
        for sk, s_data in data.get("slots", {}).items():
            graph.slots[sk] = TaskSlot(
                task_id=s_data["task_id"],
                slot_name=s_data.get("slot_name", "default"),
                state=TaskState(s_data.get("state", "pending")),
                progress=s_data.get("progress", 0.0),
                started_at=s_data.get("started_at"),
                completed_at=s_data.get("completed_at"),
                error=s_data.get("error"),
                result=s_data.get("result"),
            )
        return graph


# ---------------------------------------------------------------------------
# Worktree Isolator (for risky operations)
# ---------------------------------------------------------------------------

class WorktreeIsolator:
    """Creates temporary git worktrees for risky task execution.

    Provides isolation so that exploratory or destructive operations
    don't affect the main working directory.
    """

    def __init__(self, base_path: Path, prefix: str = "isolated_task") -> None:
        self.base_path = base_path
        self.prefix = prefix
        self.active_worktrees: list[Path] = []

    def create_worktree(self, task_id: str) -> Path:
        """Create a new worktree for the given task."""
        import subprocess

        worktree_path = self.base_path / f"{self.prefix}_{task_id}"
        worktree_path.mkdir(parents=True, exist_ok=True)

        # Create a new orphan branch for isolation
        branch_name = f"{self.prefix}_{task_id}"
        subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, str(worktree_path), "--detach"],
            capture_output=True,
            text=True,
        )

        self.active_worktrees.append(worktree_path)
        return worktree_path

    def cleanup_worktree(self, worktree_path: Path) -> None:
        """Remove a worktree and its directory."""
        import subprocess

        try:
            subprocess.run(
                ["git", "worktree", "remove", "-f", str(worktree_path)],
                capture_output=True,
                text=True,
            )
        except Exception:
            pass  # Best effort cleanup

        # Remove directory if it still exists
        if worktree_path.exists():
            import shutil
            try:
                shutil.rmtree(worktree_path)
            except Exception:
                pass

        if worktree_path in self.active_worktrees:
            self.active_worktrees.remove(worktree_path)

    def cleanup_all(self) -> None:
        """Remove all active worktrees."""
        for wt in list(self.active_worktrees):
            self.cleanup_worktree(wt)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_TASK_GRAPH_DIR = MINI_CODE_DIR / "task_graphs"


def save_task_graph(graph: TaskGraph, graph_id: str) -> Path:
    """Save task graph to disk."""
    _TASK_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    graph_file = _TASK_GRAPH_DIR / f"{graph_id}.json"
    graph_file.write_text(
        json.dumps(graph.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return graph_file


def load_task_graph(graph_id: str) -> TaskGraph | None:
    """Load task graph from disk."""
    graph_file = _TASK_GRAPH_DIR / f"{graph_id}.json"
    if not graph_file.exists():
        return None
    try:
        data = json.loads(graph_file.read_text(encoding="utf-8"))
        return TaskGraph.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None


def list_task_graphs() -> list[str]:
    """List all saved task graph IDs."""
    if not _TASK_GRAPH_DIR.exists():
        return []
    return [f.stem for f in _TASK_GRAPH_DIR.glob("*.json")]


def delete_task_graph(graph_id: str) -> bool:
    """Delete a saved task graph."""
    graph_file = _TASK_GRAPH_DIR / f"{graph_id}.json"
    if graph_file.exists():
        graph_file.unlink()
        return True
    return False
