"""Polyorphic command system for MiniCode Python.

Inspired by Claude Code's three command types:
- PromptCommand: Expands into system prompt
- LocalCommand: Executes locally
- InteractiveCommand: Interactive UI

Provides a complete command lifecycle with metadata,
availability checks, and multi-source loading.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from minicode.state import AppState, Store


# ---------------------------------------------------------------------------
# Command types
# ---------------------------------------------------------------------------

class CommandType(str, Enum):
    """Command execution types (inspired by Claude Code)."""
    PROMPT = "prompt"           # Expands into system prompt
    LOCAL = "local"             # Executes and returns result
    INTERACTIVE = "interactive" # Interactive UI mode


class CommandAvailability(str, Enum):
    """Command availability contexts."""
    CLAUDE_AI = "claude-ai"
    CONSOLE = "console"
    TTY = "tty"
    REPL = "repl"


# ---------------------------------------------------------------------------
# Command metadata
# ---------------------------------------------------------------------------

@dataclass
class CommandMetadata:
    """Command metadata for discovery and filtering.
    
    Inspired by Claude Code's CommandBase type.
    """
    name: str
    description: str
    usage: str = ""
    aliases: list[str] = field(default_factory=list)
    availability: list[CommandAvailability] = field(default_factory=lambda: [CommandAvailability.CONSOLE])
    paths: list[str] = field(default_factory=list)  # File path matching
    context: str = "inline"  # inline | fork
    is_hidden: bool = False
    tags: list[str] = field(default_factory=list)
    is_enabled: Callable[[], bool] = field(default=lambda: True)
    
    def meets_availability(self, mode: CommandAvailability = CommandAvailability.CONSOLE) -> bool:
        """Check if command is available in current mode."""
        if self.is_hidden:
            return False
        if not self.is_enabled():
            return False
        return mode in self.availability or CommandAvailability.CONSOLE in self.availability


# ---------------------------------------------------------------------------
# Command base classes
# ---------------------------------------------------------------------------

class CommandBase(ABC):
    """Abstract base for all commands."""
    
    def __init__(self, metadata: CommandMetadata):
        self.metadata = metadata
    
    @property
    def name(self) -> str:
        return self.metadata.name
    
    @property
    def description(self) -> str:
        return self.metadata.description
    
    @abstractmethod
    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        """Execute the command."""
        ...
    
    def is_enabled(self) -> bool:
        return self.metadata.is_enabled()
    
    def meets_availability(self, mode: CommandAvailability = CommandAvailability.CONSOLE) -> bool:
        return self.metadata.meets_availability(mode)


class CommandResult:
    """Command execution result."""
    
    def __init__(
        self,
        output: str,
        success: bool = True,
        command_type: CommandType = CommandType.LOCAL,
        metadata: dict[str, Any] | None = None,
    ):
        self.output = output
        self.success = success
        self.command_type = command_type
        self.metadata = metadata or {}


# ---------------------------------------------------------------------------
# Local commands (direct execution)
# ---------------------------------------------------------------------------

class LocalCommand(CommandBase):
    """Local command that executes and returns result.
    
    Inspired by Claude Code's LocalCommand type.
    """
    
    def __init__(self, metadata: CommandMetadata, handler: Callable[[str, dict], str]):
        super().__init__(metadata)
        self.handler = handler
        self.metadata.context = "inline"
    
    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        try:
            output = self.handler(args, context)
            return CommandResult(
                output=output,
                success=True,
                command_type=CommandType.LOCAL,
            )
        except Exception as e:
            return CommandResult(
                output=f"Error: {e}",
                success=False,
                command_type=CommandType.LOCAL,
            )


# ---------------------------------------------------------------------------
# Prompt commands (expand into system prompt)
# ---------------------------------------------------------------------------

class PromptCommand(CommandBase):
    """Prompt command that expands into system prompt.
    
    Inspired by Claude Code's PromptCommand type.
    """
    
    def __init__(self, metadata: CommandMetadata, prompt_builder: Callable[[str, dict], str]):
        super().__init__(metadata)
        self.prompt_builder = prompt_builder
        self.metadata.context = "inline"
    
    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        try:
            prompt = self.prompt_builder(args, context)
            return CommandResult(
                output=prompt,
                success=True,
                command_type=CommandType.PROMPT,
            )
        except Exception as e:
            return CommandResult(
                output=f"Error: {e}",
                success=False,
                command_type=CommandType.PROMPT,
            )


# ---------------------------------------------------------------------------
# Interactive commands (UI mode)
# ---------------------------------------------------------------------------

class InteractiveCommand(CommandBase):
    """Interactive command with UI mode.
    
    Inspired by Claude Code's LocalJSXCommand type.
    """
    
    def __init__(self, metadata: CommandMetadata, ui_handler: Callable[[str, dict], str]):
        super().__init__(metadata)
        self.ui_handler = ui_handler
        self.metadata.context = "inline"
    
    async def execute(self, args: str, context: dict[str, Any]) -> CommandResult:
        try:
            output = self.ui_handler(args, context)
            return CommandResult(
                output=output,
                success=True,
                command_type=CommandType.INTERACTIVE,
            )
        except Exception as e:
            return CommandResult(
                output=f"Error: {e}",
                success=False,
                command_type=CommandType.INTERACTIVE,
            )


# ---------------------------------------------------------------------------
# Command Registry
# ---------------------------------------------------------------------------

class CommandRegistry:
    """Registry for polyorphic commands.
    
    Inspired by Claude Code's command loading system.
    """
    
    def __init__(self):
        self._commands: dict[str, CommandBase] = {}
        self._loaders: list[Callable[[], list[CommandBase]]] = []
    
    def register(self, command: CommandBase) -> None:
        """Register a command."""
        self._commands[command.name] = command
        for alias in command.metadata.aliases:
            self._commands[alias] = command
    
    def register_loader(self, loader: Callable[[], list[CommandBase]]) -> None:
        """Register a command loader function."""
        self._loaders.append(loader)
    
    def get(self, name: str) -> CommandBase | None:
        """Get command by name or alias."""
        return self._commands.get(name)
    
    def list_commands(
        self,
        mode: CommandAvailability = CommandAvailability.CONSOLE,
    ) -> list[CommandBase]:
        """List all available commands with filtering."""
        # Load from all sources
        for loader in self._loaders:
            try:
                commands = loader()
                for cmd in commands:
                    if cmd.name not in self._commands:
                        self.register(cmd)
            except Exception:
                pass
        
        # Filter by availability
        return [
            cmd for cmd in self._commands.values()
            if cmd.meets_availability(mode)
        ]
    
    async def execute(
        self,
        name: str,
        args: str = "",
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Execute a command by name."""
        command = self.get(name)
        if not command:
            return CommandResult(
                output=f"Unknown command: {name}",
                success=False,
            )
        
        return await command.execute(args, context or {})


# ---------------------------------------------------------------------------
# Built-in command factory
# ---------------------------------------------------------------------------

def create_builtin_commands(
    app_state: Store[AppState] | None = None,
    cost_tracker: Any = None,
) -> list[CommandBase]:
    """Create all built-in commands.
    
    Args:
        app_state: Application state store
        cost_tracker: Cost tracker instance
    
    Returns:
        List of built-in commands
    """
    commands = []
    
    # /cost - Show cost report
    def cost_handler(args: str, context: dict) -> str:
        if cost_tracker:
            detailed = "--detailed" in args or "-d" in args
            return cost_tracker.format_cost_report(detailed=detailed)
        return "Cost tracking not initialized."
    
    commands.append(LocalCommand(
        metadata=CommandMetadata(
            name="/cost",
            description="Show API cost and usage report",
            usage="/cost [--detailed]",
            aliases=["/cost-report"],
            tags=["cost", "usage"],
        ),
        handler=cost_handler,
    ))
    
    # /status - Show app state summary
    def status_handler(args: str, context: dict) -> str:
        if app_state:
            from minicode.state import format_app_state_summary
            return format_app_state_summary(app_state.get_state())
        return "App state not initialized."
    
    commands.append(LocalCommand(
        metadata=CommandMetadata(
            name="/status",
            description="Show application state summary",
            usage="/status",
            aliases=["/state"],
            tags=["status", "state"],
        ),
        handler=status_handler,
    ))
    
    # /context - Show context window usage
    def context_handler(args: str, context: dict) -> str:
        if app_state:
            state = app_state.get_state()
            lines = [
                "Context Window Usage",
                "=" * 50,
                f"Model: {state.model}",
                f"Context window: {state.context_window_size:,} tokens",
                f"Used: {state.token_usage:,} tokens ({state.context_usage_percentage:.1f}%)",
                f"Messages: {state.message_count}",
                f"Tool calls: {state.tool_call_count}",
                "",
            ]
            
            if state.context_usage_percentage > 80:
                lines.append("⚠️  WARNING: Context is near capacity!")
                if state.context_usage_percentage > 95:
                    lines.append("🔴 Auto-compaction will trigger soon.")
            
            return "\n".join(lines)
        return "Context tracking not initialized."
    
    commands.append(LocalCommand(
        metadata=CommandMetadata(
            name="/context",
            description="Show context window usage",
            usage="/context",
            aliases=["/ctx"],
            tags=["context", "tokens"],
        ),
        handler=context_handler,
    ))
    
    # /memory - Show memory status
    def memory_handler(args: str, context: dict) -> str:
        try:
            from minicode.memory import MemoryManager
            workspace = context.get("workspace", ".")
            mm = MemoryManager(workspace)
            return mm.format_stats()
        except Exception as e:
            return f"Memory system error: {e}"
    
    commands.append(LocalCommand(
        metadata=CommandMetadata(
            name="/memory",
            description="Show memory system status",
            usage="/memory",
            aliases=["/mem"],
            tags=["memory"],
        ),
        handler=memory_handler,
    ))
    
    # /tasks - Show task list
    def tasks_handler(args: str, context: dict) -> str:
        try:
            from minicode.task_tracker import TaskManager
            tm = TaskManager()
            if tm.active_list:
                return tm.format_details()
            return "No active task list. Tasks are auto-detected from multi-step requests."
        except Exception as e:
            return f"Task system error: {e}"
    
    commands.append(LocalCommand(
        metadata=CommandMetadata(
            name="/tasks",
            description="Show current task list",
            usage="/tasks",
            aliases=["/task"],
            tags=["tasks", "progress"],
        ),
        handler=tasks_handler,
    ))
    
    return commands
