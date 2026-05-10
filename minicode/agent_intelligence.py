from enum import Enum, auto
from dataclasses import dataclass
from typing import Any


class ErrorCategory(Enum):
    NETWORK = "network"
    PERMISSION = "permission"
    RESOURCE = "resource"
    LOGIC = "logic"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class RecoveryStrategy(Enum):
    RETRY_EXPONENTIAL_BACKOFF = "retry_exponential_backoff"
    RETRY_IMMEDIATE = "retry_immediate"
    FALLBACK_ALTERNATIVE = "fallback_alternative"
    REQUEST_PERMISSION = "request_permission"
    WAIT_AND_RETRY = "wait_and_retry"
    SKIP_AND_CONTINUE = "skip_and_continue"
    ABORT = "abort"


@dataclass
class ClassifiedError:
    category: ErrorCategory
    strategy: RecoveryStrategy
    confidence: float  # 0.0 - 1.0
    context: dict[str, Any]


class ErrorClassifier:
    """Classifies errors and recommends recovery strategies."""

    # Keyword patterns for each error category
    PATTERNS = {
        ErrorCategory.NETWORK: [
            "connection", "timeout", "network", "refused", "unreachable",
            "reset", "closed", "dns", "ssl", "certificate",
        ],
        ErrorCategory.PERMISSION: [
            "permission", "access denied", "unauthorized", "forbidden",
            "privilege", "not allowed", "restricted", "admin",
        ],
        ErrorCategory.RESOURCE: [
            "memory", "disk", "space", "resource", "quota", "limit",
            "exceeded", "out of", "no space", "too large",
        ],
        ErrorCategory.TIMEOUT: [
            "timeout", "timed out", "deadline", "expired", "took too long",
        ],
        ErrorCategory.LOGIC: [
            "invalid", "not found", "does not exist", "already exists",
            "bad request", "syntax", "parse", "format", "type error",
        ],
    }

    # Strategy mapping based on category
    STRATEGY_MAP = {
        ErrorCategory.NETWORK: RecoveryStrategy.RETRY_EXPONENTIAL_BACKOFF,
        ErrorCategory.TIMEOUT: RecoveryStrategy.WAIT_AND_RETRY,
        ErrorCategory.PERMISSION: RecoveryStrategy.REQUEST_PERMISSION,
        ErrorCategory.RESOURCE: RecoveryStrategy.WAIT_AND_RETRY,
        ErrorCategory.LOGIC: RecoveryStrategy.FALLBACK_ALTERNATIVE,
        ErrorCategory.UNKNOWN: RecoveryStrategy.RETRY_IMMEDIATE,
    }

    @classmethod
    def classify(cls, error_message: str, tool_name: str = "") -> ClassifiedError:
        """Classify an error message and recommend a strategy."""
        error_lower = error_message.lower()

        scores: dict[ErrorCategory, int] = {}
        for category, patterns in cls.PATTERNS.items():
            score = sum(1 for p in patterns if p in error_lower)
            if score > 0:
                scores[category] = score

        if scores:
            best_category = max(scores, key=scores.get)
            confidence = min(0.95, 0.5 + max(scores.values()) * 0.15)
        else:
            best_category = ErrorCategory.UNKNOWN
            confidence = 0.3

        strategy = cls.STRATEGY_MAP.get(best_category, RecoveryStrategy.RETRY_IMMEDIATE)

        # Adjust strategy based on tool name
        if tool_name in ["read_file", "list_files", "grep_files"] and best_category == ErrorCategory.LOGIC:
            strategy = RecoveryStrategy.SKIP_AND_CONTINUE

        return ClassifiedError(
            category=best_category,
            strategy=strategy,
            confidence=confidence,
            context={"tool_name": tool_name, "error_snippet": error_message[:200]},
        )


class NudgeGenerator:
    """Generates intelligent nudge messages based on failure context."""

    TEMPLATES = {
        ErrorCategory.NETWORK: {
            RecoveryStrategy.RETRY_EXPONENTIAL_BACKOFF: (
                "Network error detected. The previous attempt failed due to connectivity issues. "
                "Please retry the same operation. If it fails again, consider checking your "
                "network connection or trying an alternative approach."
            ),
            RecoveryStrategy.RETRY_IMMEDIATE: (
                "A transient network issue occurred. Please retry the operation immediately."
            ),
        },
        ErrorCategory.PERMISSION: {
            RecoveryStrategy.REQUEST_PERMISSION: (
                "Permission denied. You don't have sufficient privileges for this operation. "
                "Consider: (1) running with elevated permissions if appropriate, "
                "(2) using a different approach that doesn't require elevated access, or "
                "(3) asking the user for permission to proceed."
            ),
            RecoveryStrategy.FALLBACK_ALTERNATIVE: (
                "Access was denied. Try an alternative approach that works with current permissions."
            ),
        },
        ErrorCategory.RESOURCE: {
            RecoveryStrategy.WAIT_AND_RETRY: (
                "Resource limit reached (memory/disk/quota). Consider: "
                "(1) freeing up resources before retrying, "
                "(2) processing in smaller batches, or "
                "(3) using a more efficient approach."
            ),
        },
        ErrorCategory.TIMEOUT: {
            RecoveryStrategy.WAIT_AND_RETRY: (
                "The operation timed out. This may be due to heavy load or a long-running process. "
                "Consider: (1) retrying after a brief wait, "
                "(2) breaking the task into smaller steps, or "
                "(3) using a more efficient approach."
            ),
        },
        ErrorCategory.LOGIC: {
            RecoveryStrategy.FALLBACK_ALTERNATIVE: (
                "The previous approach encountered an error. Consider using a different strategy: "
                "try alternative tools, adjust parameters, or break the task into smaller steps."
            ),
            RecoveryStrategy.SKIP_AND_CONTINUE: (
                "This step encountered an issue but it's not critical. "
                "You can skip this and continue with the remaining tasks."
            ),
        },
        ErrorCategory.UNKNOWN: {
            RecoveryStrategy.RETRY_IMMEDIATE: (
                "An unexpected error occurred. Please retry the operation. "
                "If the error persists, try a different approach."
            ),
        },
    }

    @classmethod
    def generate(cls, classified_error: ClassifiedError, retry_count: int = 0) -> str:
        """Generate a nudge message based on classified error."""
        category = classified_error.category
        strategy = classified_error.strategy

        # Get base template
        category_templates = cls.TEMPLATES.get(category, cls.TEMPLATES[ErrorCategory.UNKNOWN])
        base_message = category_templates.get(
            strategy,
            category_templates.get(RecoveryStrategy.RETRY_IMMEDIATE, "Please retry."),
        )

        # Add retry context
        if retry_count > 0:
            base_message += f" (This is retry attempt {retry_count + 1})"

        # Add tool-specific hints
        tool_name = classified_error.context.get("tool_name", "")
        if tool_name == "run_command" and category == ErrorCategory.PERMISSION:
            base_message += " For command execution, consider using 'sudo' only if explicitly approved by the user."
        elif tool_name in ["write_file", "edit_file"] and category == ErrorCategory.LOGIC:
            base_message += " For file operations, verify the path exists and you have write permissions."

        return base_message

    @classmethod
    def generate_progress_nudge(cls, tool_results: list[tuple[str, bool]]) -> str | None:
        """Generate a nudge when tools have been executed but model returns empty/progress."""
        if not tool_results:
            return None

        success_count = sum(1 for _, ok in tool_results if ok)
        failure_count = len(tool_results) - success_count

        if failure_count == 0:
            return (
                f"All {success_count} tool(s) executed successfully. "
                "Continue with the next concrete step or provide a <final> answer if complete."
            )
        elif failure_count == len(tool_results):
            return (
                f"All {failure_count} tool(s) failed. "
                "Review the errors, adjust your approach, and try again with corrected parameters."
            )
        else:
            return (
                f"{success_count} tool(s) succeeded, {failure_count} failed. "
                "Address the failures first, then continue with remaining tasks."
            )


class ToolScheduler:
    """Intelligently schedules tool execution based on historical performance."""

    def __init__(self, metrics_collector: "AgentMetricsCollector | None" = None):
        self._metrics = metrics_collector
        self._conflict_history: dict[frozenset[str], int] = {}  # Track tool pair conflicts

    def schedule_calls(self, calls: list[dict], tools: Any) -> tuple[list[dict], list[dict]]:
        """Partition calls into concurrent and serial batches based on intelligence.

        Returns:
            Tuple of (concurrent_calls, serial_calls)
        """
        if len(calls) <= 1:
            return calls, []

        # Score each call based on historical success rate
        scored_calls: list[tuple[float, dict]] = []
        for call in calls:
            tool_name = call["toolName"]
            score = self._get_tool_score(tool_name)
            scored_calls.append((score, call))

        # Sort by score (highest first = most reliable)
        scored_calls.sort(key=lambda x: x[0], reverse=True)

        # Identify conflicting tool pairs
        concurrent_calls: list[dict] = []
        serial_calls: list[dict] = []

        for score, call in scored_calls:
            tool_name = call["toolName"]
            tool_def = tools.find(tool_name)

            if not tool_def or not tool_def.is_concurrency_safe:
                serial_calls.append(call)
                continue

            # Check if this tool conflicts with already-selected concurrent tools
            conflicts = self._has_conflicts(tool_name, concurrent_calls)
            if conflicts:
                serial_calls.append(call)
            else:
                concurrent_calls.append(call)

        return concurrent_calls, serial_calls

    def _get_tool_score(self, tool_name: str) -> float:
        """Get reliability score for a tool (0.0 - 1.0)."""
        if self._metrics is None:
            return 1.0
        stats = self._metrics.get_tool_stats(tool_name)
        return stats.success_rate

    def _has_conflicts(self, tool_name: str, concurrent_calls: list[dict]) -> bool:
        """Check if tool has known conflicts with concurrent calls."""
        for other_call in concurrent_calls:
            other_name = other_call["toolName"]
            pair = frozenset({tool_name, other_name})
            conflict_count = self._conflict_history.get(pair, 0)
            if conflict_count >= 2:  # Known conflict threshold
                return True
        return False

    def record_conflict(self, tool1: str, tool2: str) -> None:
        """Record that two tools had a conflict when run concurrently."""
        pair = frozenset({tool1, tool2})
        self._conflict_history[pair] = self._conflict_history.get(pair, 0) + 1

    def get_recommended_max_workers(self, concurrent_calls: list[dict]) -> int:
        """Recommend max workers based on call characteristics."""
        if not concurrent_calls:
            return 1

        base = min(len(concurrent_calls), 8)

        # Reduce workers if we have file write operations
        write_tools = {"write_file", "edit_file", "patch_file", "modify_file"}
        write_count = sum(1 for c in concurrent_calls if c["toolName"] in write_tools)
        if write_count > 0:
            base = min(base, 4)

        # Reduce further if we have command executions
        command_tools = {"run_command", "execute_command", "bash"}
        cmd_count = sum(1 for c in concurrent_calls if c["toolName"] in command_tools)
        if cmd_count > 0:
            base = min(base, 3)

        return max(1, base)
