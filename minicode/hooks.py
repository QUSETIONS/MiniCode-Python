"""Hooks event system for MiniCode Python.

Inspired by Claude Code's hooks system (PreToolUse, PostToolUse, Stop, etc.)
and plugin event listeners.

Provides lifecycle hooks for:
- Tool execution (pre/post)
- Agent lifecycle (start/stop)
- Session events (save/resume)
- User interactions (input/output)

Hooks can trigger external scripts, logging, or custom behaviors.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Hook events
# ---------------------------------------------------------------------------

class HookEvent(str, Enum):
    """Lifecycle hook events."""
    # Tool lifecycle
    PRE_TOOL_USE = "pre_tool_use"       # Before tool execution
    POST_TOOL_USE = "post_tool_use"     # After tool execution
    
    # Agent lifecycle
    AGENT_START = "agent_start"         # Agent turn started
    AGENT_STOP = "agent_stop"           # Agent turn stopped
    SUBAGENT_START = "subagent_start"   # Sub-agent spawned
    SUBAGENT_STOP = "subagent_stop"     # Sub-agent completed
    
    # Session events
    SESSION_SAVE = "session_save"       # Session autosaved
    SESSION_RESUME = "session_resume"   # Session restored
    
    # User interactions
    USER_INPUT = "user_input"           # User submitted input
    ASSISTANT_OUTPUT = "assistant_output"  # Assistant responded
    
    # System
    STARTUP = "startup"                 # Application started
    SHUTDOWN = "shutdown"               # Application shutting down


# ---------------------------------------------------------------------------
# Hook context
# ---------------------------------------------------------------------------

@dataclass
class HookContext:
    """Context passed to hook handlers."""
    event: HookEvent
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @property
    def tool_name(self) -> str | None:
        return self.data.get("tool_name")
    
    @property
    def tool_input(self) -> Any:
        return self.data.get("tool_input")
    
    @property
    def tool_output(self) -> str | None:
        return self.data.get("tool_output")
    
    @property
    def is_error(self) -> bool:
        return self.data.get("is_error", False)
    
    @property
    def session_id(self) -> str | None:
        return self.data.get("session_id")
    
    @property
    def user_input(self) -> str | None:
        return self.data.get("user_input")
    
    @property
    def assistant_output(self) -> str | None:
        return self.data.get("assistant_output")


# ---------------------------------------------------------------------------
# Hook handler
# ---------------------------------------------------------------------------

HookHandler = Callable[[HookContext], None]
AsyncHookHandler = Callable[[HookContext], Any]


@dataclass
class HookRegistration:
    """Registered hook with metadata."""
    event: HookEvent
    handler: HookHandler | AsyncHookHandler
    is_async: bool = False
    enabled: bool = True
    description: str = ""
    created_at: float = field(default_factory=time.time)
    call_count: int = 0
    last_called: float | None = None
    total_duration_ms: int = 0


# ---------------------------------------------------------------------------
# Hook manager
# ---------------------------------------------------------------------------

class HookManager:
    """Manages hook registrations and executions.
    
    Inspired by Claude Code's hooks system and plugin event listeners.
    """
    
    def __init__(self):
        self._hooks: dict[HookEvent, list[HookRegistration]] = {
            event: [] for event in HookEvent
        }
        self._enabled = True
    
    def register(
        self,
        event: HookEvent,
        handler: HookHandler | AsyncHookHandler,
        description: str = "",
    ) -> Callable[[], None]:
        """Register a hook for an event.
        
        Args:
            event: Event to hook into
            handler: Handler function (sync or async)
            description: Human-readable description
        
        Returns:
            Unregister function
        """
        import asyncio
        
        registration = HookRegistration(
            event=event,
            handler=handler,
            is_async=asyncio.iscoroutinefunction(handler),
            description=description,
        )
        
        self._hooks[event].append(registration)
        
        def unregister():
            if registration in self._hooks[event]:
                self._hooks[event].remove(registration)
        
        return unregister
    
    async def fire(self, event: HookEvent, **kwargs: Any) -> list[Any]:
        """Fire an event, calling all registered hooks.
        
        Args:
            event: Event to fire
            **kwargs: Data to pass to hooks
        
        Returns:
            List of hook results
        """
        if not self._enabled:
            return []
        
        context = HookContext(event=event, data=kwargs)
        results = []
        
        for registration in self._hooks[event]:
            if not registration.enabled:
                continue
            
            start_time = time.time()
            try:
                if registration.is_async:
                    result = await registration.handler(context)
                else:
                    result = registration.handler(context)
                
                registration.call_count += 1
                registration.last_called = time.time()
                
                duration_ms = int((time.time() - start_time) * 1000)
                registration.total_duration_ms += duration_ms
                
                results.append(result)
            
            except Exception as e:
                # Don't let hook errors break main flow
                results.append(f"Hook error: {e}")
        
        return results
    
    def fire_sync(self, event: HookEvent, **kwargs: Any) -> list[Any]:
        """Fire event synchronously (for sync hooks only)."""
        if not self._enabled:
            return []
        
        context = HookContext(event=event, data=kwargs)
        results = []
        
        for registration in self._hooks[event]:
            if not registration.enabled or registration.is_async:
                continue
            
            start_time = time.time()
            try:
                result = registration.handler(context)
                registration.call_count += 1
                registration.last_called = time.time()
                
                duration_ms = int((time.time() - start_time) * 1000)
                registration.total_duration_ms += duration_ms
                
                results.append(result)
            
            except Exception as e:
                results.append(f"Hook error: {e}")
        
        return results
    
    def enable(self) -> None:
        """Enable all hooks."""
        self._enabled = True
    
    def disable(self) -> None:
        """Disable all hooks."""
        self._enabled = False
    
    def get_hook_stats(self, event: HookEvent | None = None) -> dict[str, Any]:
        """Get hook execution statistics."""
        if event:
            hooks = self._hooks.get(event, [])
        else:
            hooks = [h for hooks_list in self._hooks.values() for h in hooks_list]
        
        return {
            "total_hooks": len(hooks),
            "enabled_hooks": sum(1 for h in hooks if h.enabled),
            "total_calls": sum(h.call_count for h in hooks),
            "total_duration_ms": sum(h.total_duration_ms for h in hooks),
        }
    
    def format_hook_status(self) -> str:
        """Format hook status for display."""
        lines = ["Hooks Status", "=" * 50, ""]
        
        for event in HookEvent:
            hooks = self._hooks[event]
            if not hooks:
                continue
            
            lines.append(f"{event.value}:")
            for hook in hooks:
                status = "✓" if hook.enabled else "✗"
                lines.append(
                    f"  {status} {hook.description or hook.handler.__name__} "
                    f"({hook.call_count} calls, {hook.total_duration_ms}ms)"
                )
            lines.append("")
        
        stats = self.get_hook_stats()
        lines.extend([
            "-" * 50,
            f"Total hooks: {stats['total_hooks']}",
            f"Enabled: {stats['enabled_hooks']}",
            f"Total calls: {stats['total_calls']}",
            f"Total duration: {stats['total_duration_ms']}ms",
        ])
        
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Built-in hooks
# ---------------------------------------------------------------------------

def create_logging_hook(log_file: Path | None = None) -> HookHandler:
    """Create a logging hook that records all events.
    
    Args:
        log_file: Optional file to log to
    
    Returns:
        Hook handler function
    """
    def handler(ctx: HookContext) -> None:
        timestamp = time.strftime("%H:%M:%S", time.localtime(ctx.timestamp))
        message = f"[{timestamp}] {ctx.event.value}"
        
        if ctx.tool_name:
            message += f" tool={ctx.tool_name}"
        if ctx.session_id:
            message += f" session={ctx.session_id[:8]}"
        
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(message + "\n")
    
    return handler


def create_script_hook(script_path: Path) -> AsyncHookHandler:
    """Create a hook that executes an external script.
    
    Args:
        script_path: Path to script to execute
    
    Returns:
        Async hook handler function
    """
    async def handler(ctx: HookContext) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                str(script_path),
                ctx.event.value,
                *([str(v) for v in ctx.data.values()]),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return stdout.decode("utf-8", errors="replace")
            else:
                return f"Script failed: {stderr.decode('utf-8', errors='replace')}"
        
        except Exception as e:
            return f"Script execution failed: {e}"
    
    return handler


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_hook_manager = HookManager()


def get_hook_manager() -> HookManager:
    """Get global hook manager."""
    return _hook_manager


def register_hook(
    event: HookEvent,
    handler: HookHandler | AsyncHookHandler,
    description: str = "",
) -> Callable[[], None]:
    """Register a hook (convenience function)."""
    return _hook_manager.register(event, handler, description)


async def fire_hook(event: HookEvent, **kwargs: Any) -> list[Any]:
    """Fire a hook event (convenience function)."""
    return await _hook_manager.fire(event, **kwargs)


def fire_hook_sync(event: HookEvent, **kwargs: Any) -> list[Any]:
    """Fire a hook event synchronously (convenience function)."""
    return _hook_manager.fire_sync(event, **kwargs)
