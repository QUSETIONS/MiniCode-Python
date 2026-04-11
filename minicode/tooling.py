from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol
from abc import abstractmethod


# ---------------------------------------------------------------------------
# Constants for smart truncation
# ---------------------------------------------------------------------------

# Default max output size (characters) — per tool type
_DEFAULT_MAX_OUTPUT = 30_000       # ~8K tokens, safe for context
_LARGE_OUTPUT_THRESHOLD = 50_000   # Trigger smart truncation above this

# Tool-specific output limits (characters)
_TOOL_OUTPUT_LIMITS: dict[str, int] = {
    "read_file": 40_000,
    "grep_files": 20_000,
    "run_command": 30_000,
    "run_with_debug": 30_000,
    "web_fetch": 20_000,
    "web_search": 15_000,
    "list_files": 15_000,
    "file_tree": 15_000,
    "code_review": 20_000,
    "diff_viewer": 20_000,
    "db_explorer": 20_000,
    "docker_helper": 20_000,
    "test_runner": 25_000,
    "api_tester": 15_000,
}


def _smart_truncate_output(output: str, tool_name: str, max_chars: int | None = None) -> str:
    """Intelligently truncate large tool output to preserve context window.
    
    Strategy:
    1. If output fits within limit, return as-is
    2. For file reads: keep head + tail (beginning and end of file)
    3. For command output: keep head + tail + error lines
    4. For grep/search: keep first N matches + summary
    5. Generic: keep head + tail with line count summary
    """
    if not output:
        return output
    
    limit = max_chars or _TOOL_OUTPUT_LIMITS.get(tool_name, _DEFAULT_MAX_OUTPUT)
    
    if len(output) <= limit:
        return output
    
    lines = output.split("\n")
    total_lines = len(lines)
    total_chars = len(output)
    
    # Calculate how many lines we can keep (rough estimate)
    avg_line_len = total_chars / max(1, total_lines)
    max_lines = int(limit / max(40, avg_line_len))
    
    if tool_name == "read_file":
        # Keep head + tail — most important for understanding file structure
        head_lines = max(1, int(max_lines * 0.6))
        tail_lines = max(1, max_lines - head_lines)
        head = "\n".join(lines[:head_lines])
        tail = "\n".join(lines[-tail_lines:])
        omitted = total_lines - head_lines - tail_lines
        return (
            f"{head}\n"
            f"\n... [{omitted} lines omitted (output too large: {total_chars:,} chars)] ...\n\n"
            f"{tail}"
        )
    
    if tool_name in ("run_command", "run_with_debug"):
        # Keep head + error lines + tail
        head_lines = max(1, int(max_lines * 0.4))
        tail_lines = max(1, int(max_lines * 0.4))
        
        # Also extract error/warning lines
        error_pattern = re.compile(r'(?i)(error|fail|exception|traceback|warning)', re.IGNORECASE)
        error_lines = [
            (i, line) for i, line in enumerate(lines)
            if error_pattern.search(line) and head_lines <= i < total_lines - tail_lines
        ]
        error_text = ""
        if error_lines:
            error_text = "\n\n[Key errors/warnings from omitted section:]\n" + "\n".join(
                f"L{i+1}: {line[:200]}" for i, line in error_lines[:20]
            )
        
        head = "\n".join(lines[:head_lines])
        tail = "\n".join(lines[-tail_lines:])
        omitted = total_lines - head_lines - tail_lines
        return (
            f"{head}\n"
            f"\n... [{omitted} lines omitted (output too large: {total_chars:,} chars)] ...{error_text}\n\n"
            f"{tail}"
        )
    
    if tool_name in ("grep_files", "web_search"):
        # Keep first N matches + summary
        head = "\n".join(lines[:max_lines])
        omitted = total_lines - max_lines
        return (
            f"{head}\n"
            f"\n... [{omitted} more lines omitted (output too large: {total_chars:,} chars, {total_lines} total lines)] ..."
        )
    
    # Generic: head + tail
    head_lines = max(1, int(max_lines * 0.5))
    tail_lines = max(1, max_lines - head_lines)
    head = "\n".join(lines[:head_lines])
    tail = "\n".join(lines[-tail_lines:])
    omitted = total_lines - head_lines - tail_lines
    return (
        f"{head}\n"
        f"\n... [{omitted} lines omitted (output too large: {total_chars:,} chars)] ...\n\n"
        f"{tail}"
    )


# ---------------------------------------------------------------------------
# Tool metadata (inspired by Claude Code's Tool type)
# ---------------------------------------------------------------------------

class ToolCapability(str, Enum):
    """Tool capability flags."""
    READ_ONLY = "read_only"
    DESTRUCTIVE = "destructive"
    CONCURRENCY_SAFE = "concurrency_safe"
    REQUIRES_PERMISSION = "requires_permission"


@dataclass
class ToolMetadata:
    """Tool metadata for classification and discovery.
    
    Inspired by Claude Code's Tool type definition.
    """
    name: str
    description: str
    capabilities: set[ToolCapability] = field(default_factory=set)
    input_schema: dict[str, Any] = field(default_factory=dict)
    is_enabled: bool = True
    max_result_size_chars: int = 10_000
    tags: list[str] = field(default_factory=list)
    
    @property
    def is_read_only(self) -> bool:
        """Check if tool is read-only."""
        return ToolCapability.READ_ONLY in self.capabilities
    
    @property
    def is_destructive(self) -> bool:
        """Check if tool can modify/delete data."""
        return ToolCapability.DESTRUCTIVE in self.capabilities
    
    @property
    def is_concurrency_safe(self) -> bool:
        """Check if tool is safe for concurrent execution."""
        return ToolCapability.CONCURRENCY_SAFE in self.capabilities


# ---------------------------------------------------------------------------
# Tool Protocol (inspired by Claude Code's Tool interface)
# ---------------------------------------------------------------------------

class Tool(Protocol):
    """Tool protocol defining a complete tool lifecycle.
    
    Inspired by Claude Code's Tool type which includes:
    - call: Execution logic
    - description: Dynamic description generation
    - validate_input: Input validation
    - check_permissions: Permission checking
    - Metadata: is_read_only, is_destructive, etc.
    """
    
    @property
    def name(self) -> str: ...
    
    @property
    def description_template(self) -> str: ...
    
    def get_description(self, args: dict[str, Any], options: dict[str, Any] | None = None) -> str: ...
    def validate_input(self, args: dict[str, Any]) -> tuple[bool, str]: ...
    def check_permissions(self, args: dict[str, Any], context: ToolContext) -> tuple[bool, str]: ...
    def call(
        self,
        args: dict[str, Any],
        context: ToolContext,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult: ...
    def is_enabled(self) -> bool: ...
    def is_read_only(self, args: dict[str, Any]) -> bool: ...
    def is_destructive(self, args: dict[str, Any]) -> bool: ...


@dataclass(slots=True)
class BackgroundTaskResult:
    taskId: str
    type: str
    command: str
    pid: int
    status: str
    startedAt: int


@dataclass(slots=True)
class ToolResult:
    ok: bool
    output: str
    backgroundTask: BackgroundTaskResult | None = None
    awaitUser: bool = False


@dataclass(slots=True)
class ToolContext:
    cwd: str
    permissions: Any | None = None
    _runtime: dict | None = None


Validator = Callable[[Any], Any]
Runner = Callable[[Any, ToolContext], ToolResult]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    validator: Validator
    run: Runner
    metadata: ToolMetadata | None = None
    
    @property
    def is_read_only(self) -> bool:
        """Check if this tool is read-only (safe for concurrent execution)."""
        if self.metadata:
            return self.metadata.is_read_only
        # Fallback: heuristic based on tool name
        return self.name in _READ_ONLY_TOOL_NAMES
    
    @property
    def is_concurrency_safe(self) -> bool:
        """Check if this tool is safe for concurrent execution."""
        if self.metadata:
            return self.metadata.is_concurrency_safe or self.metadata.is_read_only
        return self.is_read_only


# Heuristic: tool names that are known to be read-only
_READ_ONLY_TOOL_NAMES: frozenset[str] = frozenset({
    "read_file", "list_files", "grep_files", "file_tree",
    "find_symbols", "find_references", "get_ast_info",
    "code_review", "diff_viewer", "db_explorer",
    "web_fetch", "web_search", "api_tester",
    "ask_user", "todo_write",
})


class ToolRegistry:
    def __init__(
        self,
        tools: list[ToolDefinition],
        skills: list[dict[str, Any]] | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
        disposer: Callable[[], Any] | None = None,
    ) -> None:
        self._tools = tools
        self._skills = skills or []
        self._mcp_servers = mcp_servers or []
        self._disposer = disposer
        # 工具查找缓存 - O(1) 查找代替 O(n) 遍历
        self._tool_index: dict[str, ToolDefinition] = {t.name: t for t in tools}

    def list(self) -> list[ToolDefinition]:
        return list(self._tools)

    def get_skills(self) -> list[dict[str, Any]]:
        return list(self._skills)

    def get_mcp_servers(self) -> list[dict[str, Any]]:
        return list(self._mcp_servers)

    def find(self, name: str) -> ToolDefinition | None:
        # O(1) lookup via cached index
        return self._tool_index.get(name)

    def execute(self, tool_name: str, input_data: Any, context: ToolContext) -> ToolResult:
        """Execute a tool with comprehensive error protection.
        
        The global exception safety net catches ALL exceptions (except
        KeyboardInterrupt/SystemExit) and converts them to error ToolResults,
        preventing a single tool crash from cascading into a full session failure.
        
        Protection layers:
        1. Tool not found → error result
        2. Validation error → error result with input details
        3. Execution error → error result with traceback excerpt
        4. Output too large → smart truncation
        5. Unexpected errors → error result (never propagates to caller)
        """
        tool = self.find(tool_name)
        if tool is None:
            return ToolResult(ok=False, output=f"Unknown tool: {tool_name}")

        try:
            # Phase 1: Input validation (with error context)
            try:
                parsed = tool.validator(input_data)
            except (ValueError, TypeError, KeyError) as ve:
                return ToolResult(
                    ok=False,
                    output=f"Input validation error in {tool_name}: {ve}\n"
                           f"Input was: {str(input_data)[:200]}"
                )
            
            # Phase 2: Execution (with crash protection)
            result = tool.run(parsed, context)
            
            # Phase 3: Output sanitization
            if result.output is None:
                result.output = ""
            
            # Smart truncation for large outputs
            if result.output and len(result.output) > _LARGE_OUTPUT_THRESHOLD:
                result.output = _smart_truncate_output(result.output, tool_name)
            
            return result
            
        except (KeyboardInterrupt, SystemExit):
            # These should always propagate upward
            raise
        except Exception as error:  # noqa: BLE001
            # Global safety net: convert any unhandled exception to error result
            # This prevents a single buggy tool from crashing the entire session
            import traceback
            tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
            # Include last 5 lines of traceback for debugging
            tb_excerpt = "".join(tb_lines[-5:]).strip()
            error_type = type(error).__name__
            
            return ToolResult(
                ok=False,
                output=f"[{error_type}] Tool {tool_name} crashed: {error}\n"
                       f"Traceback (most recent):\n{tb_excerpt}"
            )

    def dispose(self) -> None:
        if self._disposer is not None:
            self._disposer()
