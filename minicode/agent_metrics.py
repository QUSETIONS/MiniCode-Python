from dataclasses import dataclass, field, asdict
from typing import Any
from enum import Enum
import time
import json
from pathlib import Path


class ErrorCategory(Enum):
    NETWORK = "network"          # Connection errors, timeouts
    PERMISSION = "permission"    # Access denied, auth errors
    RESOURCE = "resource"        # Out of memory, disk full
    LOGIC = "logic"              # Tool logic errors, invalid input
    UNKNOWN = "unknown"          # Unclassified errors


@dataclass
class ToolExecutionRecord:
    """Record of a single tool execution."""
    tool_name: str
    start_time: float
    end_time: float = 0.0
    success: bool = False
    error_category: ErrorCategory = ErrorCategory.UNKNOWN
    error_message: str = ""
    tokens_consumed: int = 0
    
    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


@dataclass
class AgentTurnMetrics:
    """Metrics for a single agent turn."""
    turn_id: int
    start_time: float
    end_time: float = 0.0
    tool_records: list[ToolExecutionRecord] = field(default_factory=list)
    model_calls: int = 0
    total_tokens: int = 0
    
    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000
    
    @property
    def tool_success_rate(self) -> float:
        if not self.tool_records:
            return 1.0
        successful = sum(1 for r in self.tool_records if r.success)
        return successful / len(self.tool_records)


@dataclass
class ToolHistoricalStats:
    """Historical statistics for a specific tool."""
    tool_name: str
    total_executions: int = 0
    successful_executions: int = 0
    total_duration_ms: float = 0.0
    error_counts: dict[str, int] = field(default_factory=dict)
    
    @property
    def success_rate(self) -> float:
        if self.total_executions == 0:
            return 1.0
        return self.successful_executions / self.total_executions
    
    @property
    def avg_duration_ms(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.total_duration_ms / self.total_executions


class AgentMetricsCollector:
    """Collects and persists agent execution metrics."""
    
    def __init__(self, storage_path: Path | None = None):
        self._turns: list[AgentTurnMetrics] = []
        self._tool_stats: dict[str, ToolHistoricalStats] = {}
        self._current_turn: AgentTurnMetrics | None = None
        self._current_tool: ToolExecutionRecord | None = None
        self._storage_path = storage_path
        if storage_path and storage_path.exists():
            self._load()
    
    def start_turn(self, turn_id: int) -> None:
        """Start recording a new agent turn."""
        self._current_turn = AgentTurnMetrics(turn_id=turn_id, start_time=time.time())
    
    def end_turn(self, total_tokens: int = 0) -> AgentTurnMetrics:
        """End the current turn and return metrics."""
        if self._current_turn is None:
            raise RuntimeError("No turn in progress")
        self._current_turn.end_time = time.time()
        self._current_turn.total_tokens = total_tokens
        self._turns.append(self._current_turn)
        
        # Update historical stats
        for record in self._current_turn.tool_records:
            self._update_tool_stats(record)
        
        result = self._current_turn
        self._current_turn = None
        self._save()
        return result
    
    def start_tool(self, tool_name: str) -> None:
        """Start recording a tool execution."""
        self._current_tool = ToolExecutionRecord(
            tool_name=tool_name,
            start_time=time.time(),
        )
    
    def end_tool(self, success: bool, error: str = "", tokens: int = 0) -> ToolExecutionRecord:
        """End the current tool execution."""
        if self._current_tool is None:
            raise RuntimeError("No tool execution in progress")
        self._current_tool.end_time = time.time()
        self._current_tool.success = success
        self._current_tool.error_message = error
        self._current_tool.tokens_consumed = tokens
        self._current_tool.error_category = self._classify_error(error)
        
        if self._current_turn:
            self._current_turn.tool_records.append(self._current_tool)
        
        result = self._current_tool
        self._current_tool = None
        return result
    
    def get_tool_stats(self, tool_name: str) -> ToolHistoricalStats:
        """Get historical stats for a tool."""
        return self._tool_stats.get(tool_name, ToolHistoricalStats(tool_name=tool_name))
    
    def get_all_tool_stats(self) -> dict[str, ToolHistoricalStats]:
        """Get all tool historical stats."""
        return dict(self._tool_stats)
    
    def get_recent_turns(self, count: int = 10) -> list[AgentTurnMetrics]:
        """Get recent turn metrics."""
        return self._turns[-count:]
    
    def _classify_error(self, error_message: str) -> ErrorCategory:
        """Classify error into category based on message content."""
        error_lower = error_message.lower()
        if any(kw in error_lower for kw in ["connection", "timeout", "network", "refused", "unreachable"]):
            return ErrorCategory.NETWORK
        if any(kw in error_lower for kw in ["permission", "access denied", "unauthorized", "forbidden"]):
            return ErrorCategory.PERMISSION
        if any(kw in error_lower for kw in ["memory", "disk", "space", "resource", "quota"]):
            return ErrorCategory.RESOURCE
        if error_message:
            return ErrorCategory.LOGIC
        return ErrorCategory.UNKNOWN
    
    def _update_tool_stats(self, record: ToolExecutionRecord) -> None:
        """Update historical stats with a new record."""
        name = record.tool_name
        if name not in self._tool_stats:
            self._tool_stats[name] = ToolHistoricalStats(tool_name=name)
        
        stats = self._tool_stats[name]
        stats.total_executions += 1
        if record.success:
            stats.successful_executions += 1
        stats.total_duration_ms += record.duration_ms
        
        cat = record.error_category.value
        stats.error_counts[cat] = stats.error_counts.get(cat, 0) + 1
    
    def _save(self) -> None:
        """Persist metrics to disk."""
        if self._storage_path is None:
            return
        try:
            data = {
                "tool_stats": {
                    name: {
                        "tool_name": s.tool_name,
                        "total_executions": s.total_executions,
                        "successful_executions": s.successful_executions,
                        "total_duration_ms": s.total_duration_ms,
                        "error_counts": s.error_counts,
                    }
                    for name, s in self._tool_stats.items()
                },
                "recent_turns": [
                    {
                        "turn_id": t.turn_id,
                        "duration_ms": t.duration_ms,
                        "tool_success_rate": t.tool_success_rate,
                        "total_tokens": t.total_tokens,
                        "tool_count": len(t.tool_records),
                    }
                    for t in self._turns[-50:]  # Keep last 50 turns
                ],
            }
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass  # Metrics persistence is best-effort
    
    def _load(self) -> None:
        """Load metrics from disk."""
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for name, s in data.get("tool_stats", {}).items():
                self._tool_stats[name] = ToolHistoricalStats(
                    tool_name=s["tool_name"],
                    total_executions=s["total_executions"],
                    successful_executions=s["successful_executions"],
                    total_duration_ms=s["total_duration_ms"],
                    error_counts=s.get("error_counts", {}),
                )
        except Exception:
            pass
