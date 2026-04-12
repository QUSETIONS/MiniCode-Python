"""Sub-agent context isolation system.

Inspired by Learn Claude Code best practices:
- Sub-agent context sandboxing to prevent context pollution
- Isolated tool registries per sub-agent
- Context window management for spawned agents

Provides:
- AgentContext: Isolated context container for sub-agents
- ContextSandbox: Manages multiple isolated contexts
"""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from minicode.types import ChatMessage


@dataclass
class AgentContext:
    """Isolated context container for a sub-agent.

    Each sub-agent gets its own:
    - Message history
    - Tool registry view (filtered)
    - Working directory
    - Permission scope
    """

    agent_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent_type: str = "general"  # explore, plan, general
    messages: list[ChatMessage] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    cwd: str = "."
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    token_count: int = 0
    max_tokens: int = 50000  # Context window limit for this sub-agent

    def add_message(self, message: ChatMessage) -> None:
        """Add a message to the agent's context."""
        self.messages.append(message)
        self.updated_at = time.time()

    def add_messages(self, messages: list[ChatMessage]) -> None:
        """Add multiple messages."""
        self.messages.extend(messages)
        self.updated_at = time.time()

    def get_recent_messages(self, limit: int = 20) -> list[ChatMessage]:
        """Get recent messages within token limit."""
        result = []
        total_tokens = 0
        for msg in reversed(self.messages):
            content = msg.get("content", "")
            msg_tokens = len(content) // 4  # Rough estimate
            if total_tokens + msg_tokens > self.max_tokens:
                break
            result.insert(0, msg)
            total_tokens += msg_tokens
        return result

    def get_context_summary(self) -> dict[str, Any]:
        """Get a summary of the agent's context."""
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "message_count": len(self.messages),
            "token_count": self.token_count,
            "allowed_tools": self.allowed_tools,
            "cwd": self.cwd,
            "created_at": self.created_at,
        }

    def clear_history(self) -> None:
        """Clear message history (keeps system prompt if present)."""
        system_msgs = [m for m in self.messages if m.get("role") == "system"]
        self.messages = system_msgs
        self.updated_at = time.time()

    def clone(self) -> AgentContext:
        """Create a deep copy of this context."""
        return copy.deepcopy(self)


class ContextSandbox:
    """Manages multiple isolated agent contexts.

    Provides:
    - Creation of isolated contexts for sub-agents
    - Context cleanup when agents complete
    - Token budget management across agents
    """

    def __init__(self, total_token_budget: int = 150000) -> None:
        self._contexts: dict[str, AgentContext] = {}
        self.total_token_budget = total_token_budget
        self.used_tokens = 0

    def create_context(
        self,
        agent_type: str = "general",
        allowed_tools: list[str] | None = None,
        cwd: str = ".",
        max_tokens: int = 50000,
    ) -> AgentContext:
        """Create a new isolated context for a sub-agent."""
        # Check token budget
        if self.used_tokens + max_tokens > self.total_token_budget:
            raise ValueError(
                f"Token budget exceeded: {self.used_tokens}/{self.total_token_budget}"
            )

        context = AgentContext(
            agent_type=agent_type,
            allowed_tools=allowed_tools or [],
            cwd=cwd,
            max_tokens=max_tokens,
        )
        self._contexts[context.agent_id] = context
        self.used_tokens += max_tokens
        return context

    def get_context(self, agent_id: str) -> AgentContext | None:
        """Get an agent context by ID."""
        return self._contexts.get(agent_id)

    def release_context(self, agent_id: str) -> None:
        """Release an agent context and free its token budget."""
        context = self._contexts.pop(agent_id, None)
        if context:
            self.used_tokens -= context.max_tokens

    def release_all(self) -> None:
        """Release all contexts."""
        self._contexts.clear()
        self.used_tokens = 0

    def get_active_count(self) -> int:
        """Get count of active contexts."""
        return len(self._contexts)

    def get_sandbox_stats(self) -> dict[str, Any]:
        """Get sandbox statistics."""
        return {
            "active_contexts": len(self._contexts),
            "used_tokens": self.used_tokens,
            "total_budget": self.total_token_budget,
            "budget_percentage": (self.used_tokens / self.total_token_budget) * 100
            if self.total_token_budget > 0
            else 0,
        }

    def format_sandbox_status(self) -> str:
        """Format sandbox status for display."""
        stats = self.get_sandbox_stats()
        lines = [
            "Context Sandbox Status",
            "=" * 50,
            f"Active contexts: {stats['active_contexts']}",
            f"Token usage: {stats['used_tokens']:,}/{stats['total_budget']:,} ({stats['budget_percentage']:.0f}%)",
            "",
        ]

        if self._contexts:
            lines.append("Active Agents:")
            for ctx in self._contexts.values():
                lines.append(
                    f"  • [{ctx.agent_type}] {ctx.agent_id} "
                    f"({len(ctx.messages)} msgs, {ctx.cwd})"
                )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_sandbox = ContextSandbox()


def get_sandbox() -> ContextSandbox:
    """Get the global context sandbox."""
    return _sandbox


def create_subagent_context(
    agent_type: str = "general",
    allowed_tools: list[str] | None = None,
    cwd: str = ".",
    max_tokens: int = 50000,
) -> AgentContext:
    """Convenience function to create a sub-agent context."""
    return _sandbox.create_context(agent_type, allowed_tools, cwd, max_tokens)


def release_subagent_context(agent_id: str) -> None:
    """Convenience function to release a sub-agent context."""
    _sandbox.release_context(agent_id)
