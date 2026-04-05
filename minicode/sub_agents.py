"""Lightweight sub-agent system for MiniCode Python.

Inspired by Claude Code's AgentTool and coordinator/ system.
Provides specialized agents for different task types:
- Explore: Read-only, fast, for codebase exploration
- Plan: Read-only, thorough, for context gathering
- General-purpose: Full tools, for complex multi-step tasks

Each agent runs in isolation with its own context window,
preventing main conversation context from bloating.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from minicode.context_manager import ContextManager
from minicode.state import AppState, Store


# ---------------------------------------------------------------------------
# Agent types
# ---------------------------------------------------------------------------

class AgentType(str, Enum):
    """Sub-agent types (inspired by Claude Code's built-in agents)."""
    EXPLORE = "explore"           # Read-only, fast (like Haiku)
    PLAN = "plan"                 # Read-only, thorough (like Sonnet in plan mode)
    GENERAL = "general"           # Full tools, complex tasks


@dataclass
class AgentDefinition:
    """Sub-agent definition.
    
    Inspired by Claude Code's agent definitions with custom system prompts,
    tool whitelists, and model selection.
    """
    type: AgentType
    name: str
    description: str
    system_prompt_template: str
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    model: str = "inherit"  # inherit from parent or specific model
    max_turns: int = 10
    is_read_only: bool = False
    
    @classmethod
    def explore_agent(cls) -> "AgentDefinition":
        """Create Explore agent - fast, read-only exploration."""
        return cls(
            type=AgentType.EXPLORE,
            name="Explore",
            description="Fast, read-only agent for codebase exploration and search",
            system_prompt_template=(
                "You are an exploration agent. Your job is to quickly search and "
                "understand codebases. You should be fast and focused on finding "
                "relevant files and understanding structure. "
                "You can only use read-only tools."
            ),
            allowed_tools=["read_file", "list_files", "grep_files"],
            is_read_only=True,
            max_turns=5,
        )
    
    @classmethod
    def plan_agent(cls) -> "AgentDefinition":
        """Create Plan agent - thorough context gathering."""
        return cls(
            type=AgentType.PLAN,
            name="Plan",
            description="Thorough agent for gathering context and understanding code",
            system_prompt_template=(
                "You are a planning agent. Your job is to thoroughly understand "
                "the codebase and task before acting. Read multiple files, trace "
                "code paths, and build a complete mental model. "
                "You can only use read-only tools."
            ),
            allowed_tools=["read_file", "list_files", "grep_files"],
            is_read_only=True,
            max_turns=8,
        )
    
    @classmethod
    def general_agent(cls) -> "AgentDefinition":
        """Create General-purpose agent - full capabilities."""
        return cls(
            type=AgentType.GENERAL,
            name="General",
            description="Full-featured agent for complex multi-step tasks",
            system_prompt_template=(
                "You are a general-purpose coding agent. You can read, write, "
                "and modify code. Follow best practices and explain your changes. "
                "Break complex tasks into smaller steps."
            ),
            is_read_only=False,
            max_turns=15,
        )


# ---------------------------------------------------------------------------
# Agent instance (runtime)
# ---------------------------------------------------------------------------

@dataclass
class AgentInstance:
    """Running agent instance."""
    id: str
    definition: AgentDefinition
    parent_session_id: str
    task_description: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    context_manager: ContextManager | None = None
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    status: str = "running"  # running, completed, failed, cancelled
    result: str | None = None
    error: str | None = None
    turn_count: int = 0


# ---------------------------------------------------------------------------
# Sub-agent manager
# ---------------------------------------------------------------------------

class SubAgentManager:
    """Manages sub-agent lifecycle.
    
    Inspired by Claude Code's coordinator/ system.
    """
    
    def __init__(self, parent_session_id: str, app_state: Store[AppState] | None = None):
        self.parent_session_id = parent_session_id
        self.app_state = app_state
        self.agents: dict[str, AgentInstance] = {}
        self.definitions: dict[AgentType, AgentDefinition] = {
            AgentType.EXPLORE: AgentDefinition.explore_agent(),
            AgentType.PLAN: AgentDefinition.plan_agent(),
            AgentType.GENERAL: AgentDefinition.general_agent(),
        }
    
    def get_definition(self, agent_type: AgentType) -> AgentDefinition:
        """Get agent definition."""
        return self.definitions[agent_type]
    
    def spawn_agent(
        self,
        agent_type: AgentType,
        task_description: str,
        model: str | None = None,
    ) -> AgentInstance:
        """Spawn a new sub-agent.
        
        Args:
            agent_type: Type of agent to spawn
            task_description: Task description for the agent
            model: Optional model override
        
        Returns:
            AgentInstance
        """
        definition = self.get_definition(agent_type)
        
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        
        # Create context manager for isolated context
        context_manager = ContextManager(
            model=model or definition.model,
        )
        
        # Build system message
        system_message = {
            "role": "system",
            "content": definition.system_prompt_template,
        }
        
        instance = AgentInstance(
            id=agent_id,
            definition=definition,
            parent_session_id=self.parent_session_id,
            task_description=task_description,
            messages=[system_message],
            context_manager=context_manager,
        )
        
        self.agents[agent_id] = instance
        return instance
    
    def add_message(self, agent_id: str, message: dict[str, Any]) -> bool:
        """Add message to agent conversation."""
        instance = self.agents.get(agent_id)
        if not instance or instance.status != "running":
            return False
        
        instance.messages.append(message)
        instance.turn_count += 1
        
        # Update context
        if instance.context_manager:
            instance.context_manager.add_message(message)
        
        return True
    
    def complete_agent(self, agent_id: str, result: str) -> bool:
        """Mark agent as completed with result."""
        instance = self.agents.get(agent_id)
        if not instance:
            return False
        
        instance.status = "completed"
        instance.result = result
        instance.completed_at = time.time()
        
        return True
    
    def fail_agent(self, agent_id: str, error: str) -> bool:
        """Mark agent as failed."""
        instance = self.agents.get(agent_id)
        if not instance:
            return False
        
        instance.status = "failed"
        instance.error = error
        instance.completed_at = time.time()
        
        return False
    
    def cancel_agent(self, agent_id: str) -> bool:
        """Cancel a running agent."""
        instance = self.agents.get(agent_id)
        if not instance:
            return False
        
        instance.status = "cancelled"
        instance.completed_at = time.time()
        
        return True
    
    def get_agent(self, agent_id: str) -> AgentInstance | None:
        """Get agent instance by ID."""
        return self.agents.get(agent_id)
    
    def get_active_agents(self) -> list[AgentInstance]:
        """Get all running agents."""
        return [
            agent for agent in self.agents.values()
            if agent.status == "running"
        ]
    
    def format_agent_status(self) -> str:
        """Format status report for all agents."""
        if not self.agents:
            return "No sub-agents spawned."
        
        lines = ["Sub-Agents Status", "=" * 50, ""]
        
        for agent_id, instance in self.agents.items():
            status_icon = {
                "running": "◐",
                "completed": "✓",
                "failed": "✗",
                "cancelled": "⊘",
            }.get(instance.status, "?")
            
            duration = time.time() - instance.started_at
            if instance.completed_at:
                duration = instance.completed_at - instance.started_at
            
            lines.extend([
                f"{status_icon} {instance.definition.name} ({agent_id})",
                f"  Task: {instance.task_description[:60]}",
                f"  Status: {instance.status}",
                f"  Turns: {instance.turn_count}/{instance.definition.max_turns}",
                f"  Duration: {duration:.0f}s",
            ])
            
            if instance.result:
                result_preview = instance.result[:100]
                lines.append(f"  Result: {result_preview}...")
            
            if instance.error:
                lines.append(f"  Error: {instance.error}")
            
            lines.append("")
        
        active = len(self.get_active_agents())
        lines.append(f"Active: {active} | Total: {len(self.agents)}")
        
        return "\n".join(lines)
    
    def compile_result_summary(self, agent_id: str) -> str:
        """Compile a summary of agent execution for parent context."""
        instance = self.agents.get(agent_id)
        if not instance:
            return f"Agent {agent_id} not found."
        
        lines = [
            f"[Sub-agent {instance.definition.name} completed]",
            f"  Turns: {instance.turn_count}",
            f"  Status: {instance.status}",
        ]
        
        if instance.result:
            lines.append(f"  Result: {instance.result[:200]}")
        
        if instance.context_manager:
            stats = instance.context_manager.get_stats()
            lines.append(f"  Tokens used: {stats.total_tokens:,}")
        
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------

def should_use_sub_agent(
    task_complexity: str,
    available_context: float,
) -> bool:
    """Decide if a task should be delegated to a sub-agent.
    
    Args:
        task_complexity: "simple", "moderate", "complex"
        available_context: Percentage of context window available
    
    Returns:
        True if should use sub-agent
    """
    # Use sub-agent for complex tasks or when context is limited
    if task_complexity == "complex":
        return True
    if task_complexity == "moderate" and available_context < 50:
        return True
    return False


def choose_agent_type(task_description: str) -> AgentType:
    """Choose appropriate agent type based on task.
    
    Args:
        task_description: User's task description
    
    Returns:
        Recommended AgentType
    """
    desc_lower = task_description.lower()
    
    # Exploration tasks
    exploration_keywords = ["explore", "search", "find", "understand", "explain"]
    if any(kw in desc_lower for kw in exploration_keywords):
        return AgentType.EXPLORE
    
    # Planning/context-gathering tasks
    planning_keywords = ["plan", "analyze", "review", "audit", "survey"]
    if any(kw in desc_lower for kw in planning_keywords):
        return AgentType.PLAN
    
    # Default to general-purpose
    return AgentType.GENERAL
