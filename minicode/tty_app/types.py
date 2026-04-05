"""Data types for the MiniCode TTY application.

This module defines the core data structures used by the TTY app,
including application arguments, screen state, and pending approval dialogs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minicode.permissions import PermissionManager
from minicode.session import AutosaveManager, SessionData
from minicode.state import AppState, Store
from minicode.tooling import ToolRegistry
from minicode.tui.types import TranscriptEntry
from minicode.types import ChatMessage, ModelAdapter


@dataclass
class TtyAppArgs:
    """Arguments passed to the TTY application.
    
    Attributes:
        runtime: Configuration dictionary (model, auth, MCP servers)
        tools: Tool registry with all available tools
        model: LLM adapter (real or mock)
        messages: Conversation history including system prompt
        cwd: Current working directory
        permissions: Permission manager for access control
    """
    runtime: dict | None
    tools: ToolRegistry
    model: ModelAdapter
    messages: list[ChatMessage]
    cwd: str
    permissions: PermissionManager


@dataclass
class PendingApproval:
    """Represents a pending permission approval dialog.
    
    Attributes:
        request: The permission request details
        resolve: Callback to resolve the approval
        details_expanded: Whether details are expanded in UI
        details_scroll_offset: Scroll position in expanded details
        selected_choice_index: Currently selected choice index
        feedback_mode: Whether user is typing feedback
        feedback_input: User feedback text
    """
    request: dict[str, Any]
    resolve: callable[[dict[str, Any]], None]
    details_expanded: bool = False
    details_scroll_offset: int = 0
    selected_choice_index: int = 0
    feedback_mode: bool = False
    feedback_input: str = ""


@dataclass
class AggregatedEditProgress:
    """Tracks progress of aggregated file edits.
    
    When the same file is edited multiple times in one turn,
    we aggregate the progress and show a single progress indicator.
    """
    entry_id: int
    tool_name: str
    path: str
    total: int = 1
    completed: int = 0
    errors: int = 0
    last_output: str = ""


@dataclass
class ScreenState:
    """Complete state of the TTY screen.
    
    Manages all mutable state displayed in the terminal UI,
    including transcript, input, scroll position, and approval dialogs.
    
    Attributes:
        input: Current user input text
        cursor_offset: Cursor position in input
        transcript: List of transcript entries (user, assistant, tool)
        transcript_scroll_offset: Scroll position in transcript
        selected_slash_index: Selected index in slash command menu
        status: Current status message
        active_tool: Name of currently running tool
        recent_tools: List of recently executed tools with status
        history: Command history
        history_index: Current position in history
        history_draft: Draft of command being edited
        next_entry_id: Next unique ID for transcript entries
        pending_approval: Current pending permission dialog
        is_busy: Whether agent is currently running
        session: Current session data
        autosave: Autosave manager
        app_state: Application state store
        cost_tracker: API cost tracker
        agent_thread: Background agent thread
        agent_result: Result from agent thread
        agent_lock: Lock for agent thread synchronization
        tool_start_time: Timestamp when current tool started
    """
    input: str = ""
    cursor_offset: int = 0
    transcript: list[TranscriptEntry] = field(default_factory=list)
    transcript_scroll_offset: int = 0
    selected_slash_index: int = 0
    status: str | None = None
    active_tool: str | None = None
    recent_tools: list[dict[str, str]] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    history_index: int = 0
    history_draft: str = ""
    next_entry_id: int = 1
    pending_approval: PendingApproval | None = None
    is_busy: bool = False
    # Session persistence
    session: SessionData | None = None
    autosave: AutosaveManager | None = None
    # State management
    app_state: Store[AppState] | None = None
    # Cost tracking
    cost_tracker: Any = None
    # Background agent thread
    agent_thread: Any = None
    agent_result: dict | None = None
    agent_lock: Any = None
    # Tool execution time tracking
    tool_start_time: float | None = None
