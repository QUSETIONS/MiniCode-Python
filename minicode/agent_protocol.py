"""Multi-agent collaboration protocol.

Inspired by Learn Claude Code best practices:
- Named persistent teammates with standardized communication
- Safe autonomous task claiming with validation
- Worktree execution isolation for parallel operations

Provides:
- AgentIdentity: Named agent with capabilities and status
- CollaborationMessage: Standardized message format for inter-agent communication
- TeamRegistry: Registry of available agents with task claiming
- MessageRouter: Routes messages between agents safely
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from minicode.context_isolation import AgentContext, ContextSandbox, get_sandbox


# ---------------------------------------------------------------------------
# Agent Identity
# ---------------------------------------------------------------------------

class AgentStatus(str, Enum):
    """Agent lifecycle status."""
    IDLE = "idle"
    BUSY = "busy"
    AWAY = "away"
    OFFLINE = "offline"


class AgentRole(str, Enum):
    """Agent role types."""
    EXPLORER = "explorer"      # Codebase exploration
    PLANNER = "planner"        # Task planning and decomposition
    IMPLEMENTER = "implementer"  # Code implementation
    REVIEWER = "reviewer"      # Code review and quality checks
    GENERAL = "general"        # General purpose


@dataclass
class AgentIdentity:
    """Named persistent agent identity.

    Each agent has a unique identity with capabilities, status,
    and current task information.
    """

    agent_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    role: AgentRole = AgentRole.GENERAL
    status: AgentStatus = AgentStatus.IDLE
    capabilities: list[str] = field(default_factory=list)
    current_task: str | None = None
    task_started_at: float | None = None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    def start_task(self, task_id: str) -> None:
        """Mark agent as busy with a task."""
        self.status = AgentStatus.BUSY
        self.current_task = task_id
        self.task_started_at = time.time()
        self.last_active = time.time()

    def complete_task(self) -> None:
        """Mark task as complete and return to idle."""
        self.status = AgentStatus.IDLE
        self.current_task = None
        self.task_started_at = None
        self.last_active = time.time()

    def go_away(self) -> None:
        """Mark agent as temporarily unavailable."""
        self.status = AgentStatus.AWAY
        self.last_active = time.time()

    def go_offline(self) -> None:
        """Mark agent as offline."""
        self.status = AgentStatus.OFFLINE
        self.last_active = time.time()

    def is_available(self) -> bool:
        """Check if agent is available for new tasks."""
        return self.status == AgentStatus.IDLE

    def get_active_duration(self) -> float:
        """Get duration of current task in seconds."""
        if self.task_started_at is None:
            return 0.0
        return time.time() - self.task_started_at


# ---------------------------------------------------------------------------
# Collaboration Messages
# ---------------------------------------------------------------------------

class MessageType(str, Enum):
    """Standardized message types for inter-agent communication."""
    TASK_ASSIGN = "task_assign"         # Assign task to agent
    TASK_CLAIM = "task_claim"           # Agent claims available task
    TASK_COMPLETE = "task_complete"     # Task completed notification
    TASK_FAILED = "task_failed"         # Task failed notification
    HELP_REQUEST = "help_request"       # Request assistance
    HELP_RESPONSE = "help_response"     # Response to help request
    STATUS_UPDATE = "status_update"     # Agent status update
    CONTEXT_SHARE = "context_share"     # Share context information
    REVIEW_REQUEST = "review_request"   # Request code review
    REVIEW_RESPONSE = "review_response" # Code review feedback


@dataclass
class CollaborationMessage:
    """Standardized message format for inter-agent communication."""

    msg_type: MessageType
    sender_id: str
    receiver_id: str | None = None  # None = broadcast
    task_id: str | None = None
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict[str, Any]:
        """Serialize message to dictionary."""
        return {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type.value,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "task_id": self.task_id,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollaborationMessage:
        """Deserialize message from dictionary."""
        return cls(
            msg_type=MessageType(data["msg_type"]),
            sender_id=data["sender_id"],
            receiver_id=data.get("receiver_id"),
            task_id=data.get("task_id"),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", time.time()),
            msg_id=data.get("msg_id", str(uuid.uuid4())[:8]),
        )


# ---------------------------------------------------------------------------
# Team Registry
# ---------------------------------------------------------------------------

@dataclass
class TaskPosting:
    """A task available for agents to claim."""

    task_id: str
    description: str
    required_role: AgentRole | None = None
    required_capabilities: list[str] = field(default_factory=list)
    priority: str = "normal"  # low, normal, high, critical
    posted_at: float = field(default_factory=time.time)
    claimed_by: str | None = None
    status: str = "open"  # open, claimed, completed, failed


class TeamRegistry:
    """Registry of available agents with standardized task claiming.

    Manages:
    - Agent registration and discovery
    - Task posting and claiming
    - Safe autonomous task assignment
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentIdentity] = {}
        self._tasks: dict[str, TaskPosting] = {}
        self._message_handlers: dict[MessageType, list[Callable]] = {}

    # --- Agent Management ---
    def register_agent(self, agent: AgentIdentity) -> None:
        """Register an agent with the team."""
        self._agents[agent.agent_id] = agent

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the team."""
        self._agents.pop(agent_id, None)

    def get_agent(self, agent_id: str) -> AgentIdentity | None:
        """Get agent identity by ID."""
        return self._agents.get(agent_id)

    def get_available_agents(
        self,
        role: AgentRole | None = None,
        capability: str | None = None,
    ) -> list[AgentIdentity]:
        """Get list of available agents matching criteria."""
        available = [a for a in self._agents.values() if a.is_available()]

        if role:
            available = [a for a in available if a.role == role]

        if capability:
            available = [
                a for a in available
                if capability in a.capabilities
            ]

        return available

    # --- Task Management ---
    def post_task(
        self,
        description: str,
        required_role: AgentRole | None = None,
        required_capabilities: list[str] | None = None,
        priority: str = "normal",
    ) -> TaskPosting:
        """Post a task for agents to claim."""
        task = TaskPosting(
            task_id=str(uuid.uuid4())[:8],
            description=description,
            required_role=required_role,
            required_capabilities=required_capabilities or [],
            priority=priority,
        )
        self._tasks[task.task_id] = task
        return task

    def claim_task(
        self,
        task_id: str,
        agent_id: str,
    ) -> bool:
        """Agent claims a task. Returns True if successful."""
        task = self._tasks.get(task_id)
        agent = self._agents.get(agent_id)

        if not task or not agent:
            return False

        if task.status != "open":
            return False

        if not agent.is_available():
            return False

        # Validate role/capability requirements
        if task.required_role and agent.role != task.required_role:
            return False

        for cap in task.required_capabilities:
            if cap not in agent.capabilities:
                return False

        # Claim the task
        task.claimed_by = agent_id
        task.status = "claimed"
        agent.start_task(task_id)

        return True

    def complete_task(self, task_id: str, agent_id: str) -> bool:
        """Mark task as completed."""
        task = self._tasks.get(task_id)
        agent = self._agents.get(agent_id)

        if not task or not agent:
            return False

        if task.claimed_by != agent_id:
            return False

        task.status = "completed"
        agent.complete_task()

        return True

    def fail_task(self, task_id: str, agent_id: str, reason: str = "") -> bool:
        """Mark task as failed."""
        task = self._tasks.get(task_id)
        agent = self._agents.get(agent_id)

        if not task or not agent:
            return False

        task.status = "failed"
        task.metadata["failure_reason"] = reason
        agent.complete_task()  # Return to idle

        return True

    def get_open_tasks(self) -> list[TaskPosting]:
        """Get all open tasks."""
        return [t for t in self._tasks.values() if t.status == "open"]

    # --- Message Routing ---
    def register_handler(
        self,
        msg_type: MessageType,
        handler: Callable[[CollaborationMessage], None],
    ) -> None:
        """Register a message handler for a message type."""
        if msg_type not in self._message_handlers:
            self._message_handlers[msg_type] = []
        self._message_handlers[msg_type].append(handler)

    def send_message(self, message: CollaborationMessage) -> list[Any]:
        """Send a message to registered handlers."""
        handlers = self._message_handlers.get(message.msg_type, [])
        results = []
        for handler in handlers:
            try:
                results.append(handler(message))
            except Exception:
                results.append(None)
        return results

    # --- Status ---
    def get_team_status(self) -> dict[str, Any]:
        """Get overall team status."""
        return {
            "agents": {
                aid: {
                    "name": a.name,
                    "role": a.role.value,
                    "status": a.status.value,
                    "current_task": a.current_task,
                }
                for aid, a in self._agents.items()
            },
            "tasks": {
                "open": sum(1 for t in self._tasks.values() if t.status == "open"),
                "claimed": sum(1 for t in self._tasks.values() if t.status == "claimed"),
                "completed": sum(1 for t in self._tasks.values() if t.status == "completed"),
                "failed": sum(1 for t in self._tasks.values() if t.status == "failed"),
            },
        }

    def format_team_status(self) -> str:
        """Format team status for display."""
        status = self.get_team_status()
        lines = [
            "Team Status",
            "=" * 50,
            f"Agents: {len(status['agents'])}",
            f"Tasks: {status['tasks']['open']} open, "
            f"{status['tasks']['claimed']} claimed, "
            f"{status['tasks']['completed']} done",
            "",
        ]

        if status["agents"]:
            lines.append("Agents:")
            for aid, info in status["agents"].items():
                task_info = ""
                if info["current_task"]:
                    task_info = f" (task: {info['current_task'][:8]})"
                lines.append(
                    f"  • [{info['status']}] {info['name']} "
                    f"({info['role']}){task_info}"
                )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_team_registry = TeamRegistry()


def get_team_registry() -> TeamRegistry:
    """Get the global team registry."""
    return _team_registry


def register_agent(agent: AgentIdentity) -> None:
    """Convenience function to register an agent."""
    _team_registry.register_agent(agent)


def post_task(
    description: str,
    required_role: AgentRole | None = None,
    required_capabilities: list[str] | None = None,
    priority: str = "normal",
) -> TaskPosting:
    """Convenience function to post a task."""
    return _team_registry.post_task(
        description, required_role, required_capabilities, priority
    )


def claim_task(task_id: str, agent_id: str) -> bool:
    """Convenience function to claim a task."""
    return _team_registry.claim_task(task_id, agent_id)


def get_available_agents(
    role: AgentRole | None = None,
    capability: str | None = None,
) -> list[AgentIdentity]:
    """Convenience function to get available agents."""
    return _team_registry.get_available_agents(role, capability)


def format_team_status() -> str:
    """Convenience function to format team status."""
    return _team_registry.format_team_status()
