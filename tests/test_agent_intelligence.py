"""Comprehensive integration tests for Agent Loop intelligence features."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from minicode.agent_metrics import (
    AgentMetricsCollector,
    AgentTurnMetrics,
    ErrorCategory,
    ToolExecutionRecord,
    ToolHistoricalStats,
)
from minicode.agent_intelligence import (
    ClassifiedError,
    ErrorCategory as AIErrorCategory,
    ErrorClassifier,
    NudgeGenerator,
    RecoveryStrategy,
    ToolScheduler,
)
from minicode.memory_injector import InjectedMemory, MemoryInjector
from minicode.memory import MemoryManager, MemoryScope
from minicode.tooling import ToolCapability, ToolDefinition, ToolMetadata, ToolRegistry


# ---------------------------------------------------------------------------
# TestAgentMetricsCollector
# ---------------------------------------------------------------------------

class TestAgentMetricsCollector:
    """Integration tests for AgentMetricsCollector."""

    def test_start_end_turn(self, tmp_path):
        """Verify turn lifecycle recording."""
        storage = tmp_path / "metrics.json"
        collector = AgentMetricsCollector(storage_path=storage)

        collector.start_turn(turn_id=1)
        assert collector._current_turn is not None
        assert collector._current_turn.turn_id == 1

        result = collector.end_turn(total_tokens=42)
        assert isinstance(result, AgentTurnMetrics)
        assert result.turn_id == 1
        assert result.total_tokens == 42
        assert result.duration_ms >= 0
        assert collector._current_turn is None

    def test_tool_execution_record(self, tmp_path):
        """Verify tool execution tracking."""
        collector = AgentMetricsCollector()

        collector.start_turn(turn_id=1)
        collector.start_tool("read_file")
        record = collector.end_tool(success=True, error="", tokens=10)

        assert isinstance(record, ToolExecutionRecord)
        assert record.tool_name == "read_file"
        assert record.success is True
        assert record.tokens_consumed == 10
        assert record.duration_ms >= 0

        turn = collector.end_turn(total_tokens=10)
        assert len(turn.tool_records) == 1
        assert turn.tool_records[0].tool_name == "read_file"

    def test_error_classification_integration(self, tmp_path):
        """Verify errors are classified."""
        collector = AgentMetricsCollector()

        collector.start_turn(turn_id=1)
        collector.start_tool("web_fetch")
        record = collector.end_tool(
            success=False,
            error="Connection refused to remote host",
            tokens=0,
        )
        collector.end_turn(total_tokens=0)

        assert record.error_category == ErrorCategory.NETWORK

        stats = collector.get_tool_stats("web_fetch")
        assert stats.error_counts.get("network", 0) == 1

    def test_historical_stats(self, tmp_path):
        """Verify stats accumulation over multiple executions."""
        collector = AgentMetricsCollector()

        for turn_id in range(1, 4):
            collector.start_turn(turn_id=turn_id)
            collector.start_tool("read_file")
            collector.end_tool(success=True, error="", tokens=5)
            collector.start_tool("write_file")
            collector.end_tool(success=(turn_id != 2), error="Permission denied" if turn_id == 2 else "", tokens=5)
            collector.end_turn(total_tokens=10)

        read_stats = collector.get_tool_stats("read_file")
        assert read_stats.total_executions == 3
        assert read_stats.successful_executions == 3
        assert read_stats.success_rate == 1.0

        write_stats = collector.get_tool_stats("write_file")
        assert write_stats.total_executions == 3
        assert write_stats.successful_executions == 2
        assert abs(write_stats.success_rate - 0.6667) < 0.01
        assert write_stats.error_counts.get("permission", 0) == 1

    def test_persistence(self, tmp_path):
        """Verify save/load of metrics."""
        storage = tmp_path / "metrics.json"

        # Create and populate collector
        collector1 = AgentMetricsCollector(storage_path=storage)
        collector1.start_turn(turn_id=1)
        collector1.start_tool("read_file")
        collector1.end_tool(success=True, error="", tokens=5)
        collector1.end_turn(total_tokens=5)

        assert storage.exists()

        # Load into new collector
        collector2 = AgentMetricsCollector(storage_path=storage)
        stats = collector2.get_tool_stats("read_file")
        assert stats.total_executions == 1
        assert stats.successful_executions == 1


# ---------------------------------------------------------------------------
# TestErrorClassifier
# ---------------------------------------------------------------------------

class TestErrorClassifier:
    """Integration tests for ErrorClassifier."""

    def test_network_error_classification(self):
        """Classify connection errors."""
        result = ErrorClassifier.classify("Connection refused by host", "web_fetch")
        assert result.category == AIErrorCategory.NETWORK
        assert result.strategy == RecoveryStrategy.RETRY_EXPONENTIAL_BACKOFF
        assert result.confidence > 0.5
        assert result.context["tool_name"] == "web_fetch"

    def test_permission_error_classification(self):
        """Classify access denied."""
        result = ErrorClassifier.classify("Permission denied: cannot write to /etc/config", "write_file")
        assert result.category == AIErrorCategory.PERMISSION
        assert result.strategy == RecoveryStrategy.REQUEST_PERMISSION
        assert result.confidence > 0.5

    def test_resource_error_classification(self):
        """Classify out of memory."""
        result = ErrorClassifier.classify("Out of memory: cannot allocate buffer", "run_command")
        assert result.category == AIErrorCategory.RESOURCE
        assert result.strategy == RecoveryStrategy.WAIT_AND_RETRY
        assert result.confidence > 0.5

    def test_timeout_error_classification(self):
        """Classify timeout."""
        result = ErrorClassifier.classify("Operation timed out after 30 seconds", "web_fetch")
        assert result.category == AIErrorCategory.TIMEOUT
        assert result.strategy == RecoveryStrategy.WAIT_AND_RETRY
        assert result.confidence > 0.5

    def test_logic_error_classification(self):
        """Classify invalid input."""
        result = ErrorClassifier.classify("Invalid input: bad request format", "edit_file")
        assert result.category == AIErrorCategory.LOGIC
        assert result.strategy == RecoveryStrategy.FALLBACK_ALTERNATIVE
        assert result.confidence > 0.5

    def test_confidence_scoring(self):
        """Verify confidence levels."""
        # Strong match (multiple keywords)
        strong = ErrorClassifier.classify("connection timeout network refused unreachable", "web_fetch")
        assert strong.confidence >= 0.8

        # Weak match (single keyword)
        weak = ErrorClassifier.classify("timeout", "web_fetch")
        assert 0.5 <= weak.confidence < 0.8

        # No match
        none_result = ErrorClassifier.classify("something weird happened", "tool")
        assert none_result.category == AIErrorCategory.UNKNOWN
        assert none_result.confidence < 0.5


# ---------------------------------------------------------------------------
# TestNudgeGenerator
# ---------------------------------------------------------------------------

class TestNudgeGenerator:
    """Integration tests for NudgeGenerator."""

    def test_network_nudge(self):
        """Generate network error nudge."""
        error = ClassifiedError(
            category=AIErrorCategory.NETWORK,
            strategy=RecoveryStrategy.RETRY_EXPONENTIAL_BACKOFF,
            confidence=0.9,
            context={"tool_name": "web_fetch"},
        )
        nudge = NudgeGenerator.generate(error)
        assert "network" in nudge.lower() or "connectivity" in nudge.lower()
        assert "retry" in nudge.lower()

    def test_permission_nudge(self):
        """Generate permission error nudge."""
        error = ClassifiedError(
            category=AIErrorCategory.PERMISSION,
            strategy=RecoveryStrategy.REQUEST_PERMISSION,
            confidence=0.9,
            context={"tool_name": "write_file"},
        )
        nudge = NudgeGenerator.generate(error)
        assert "permission" in nudge.lower() or "privilege" in nudge.lower()

    def test_retry_count_appended(self):
        """Verify retry count in nudge."""
        error = ClassifiedError(
            category=AIErrorCategory.NETWORK,
            strategy=RecoveryStrategy.RETRY_EXPONENTIAL_BACKOFF,
            confidence=0.9,
            context={},
        )
        nudge = NudgeGenerator.generate(error, retry_count=2)
        assert "retry attempt 3" in nudge

    def test_progress_nudge_all_success(self):
        """All tools succeeded."""
        results = [("read_file", True), ("list_files", True)]
        nudge = NudgeGenerator.generate_progress_nudge(results)
        assert nudge is not None
        assert "2 tool(s) executed successfully" in nudge
        assert "final" in nudge.lower()

    def test_progress_nudge_mixed(self):
        """Mixed success/failure."""
        results = [("read_file", True), ("write_file", False), ("grep_files", True)]
        nudge = NudgeGenerator.generate_progress_nudge(results)
        assert nudge is not None
        assert "2 tool(s) succeeded, 1 failed" in nudge
        assert "Address the failures" in nudge


# ---------------------------------------------------------------------------
# TestToolScheduler
# ---------------------------------------------------------------------------

class TestToolScheduler:
    """Integration tests for ToolScheduler."""

    def _make_tool_def(self, name: str, concurrency_safe: bool = True) -> ToolDefinition:
        metadata = ToolMetadata(
            name=name,
            description=f"Test tool {name}",
            capabilities={ToolCapability.CONCURRENCY_SAFE} if concurrency_safe else set(),
        )
        return ToolDefinition(
            name=name,
            description=f"Test tool {name}",
            input_schema={},
            validator=lambda x: x,
            run=lambda x, ctx: MagicMock(),
            metadata=metadata,
        )

    def _make_registry(self, tools: list[ToolDefinition]) -> ToolRegistry:
        return ToolRegistry(tools=tools)

    def test_schedule_single_call(self):
        """Single call goes to concurrent."""
        scheduler = ToolScheduler()
        tool = self._make_tool_def("read_file")
        registry = self._make_registry([tool])
        calls = [{"id": "1", "toolName": "read_file", "input": {}}]

        concurrent, serial = scheduler.schedule_calls(calls, registry)
        assert len(concurrent) == 1
        assert len(serial) == 0

    def test_schedule_with_history(self, tmp_path):
        """High success rate tools prioritized."""
        storage = tmp_path / "metrics.json"
        metrics = AgentMetricsCollector(storage_path=storage)

        # Record 3 successes for read_file, 1 success + 2 failures for write_file
        for i in range(3):
            metrics.start_turn(turn_id=i + 1)
            metrics.start_tool("read_file")
            metrics.end_tool(success=True, error="", tokens=0)
            metrics.end_turn(total_tokens=0)

        for i in range(3):
            metrics.start_turn(turn_id=i + 10)
            metrics.start_tool("write_file")
            metrics.end_tool(success=(i == 0), error="fail" if i > 0 else "", tokens=0)
            metrics.end_turn(total_tokens=0)

        scheduler = ToolScheduler(metrics_collector=metrics)
        read_tool = self._make_tool_def("read_file")
        write_tool = self._make_tool_def("write_file")
        registry = self._make_registry([read_tool, write_tool])

        calls = [
            {"id": "1", "toolName": "write_file", "input": {}},
            {"id": "2", "toolName": "read_file", "input": {}},
        ]

        concurrent, serial = scheduler.schedule_calls(calls, registry)
        # read_file has higher success rate (1.0 vs 0.333), so it should be first
        assert concurrent[0]["toolName"] == "read_file"

    def test_conflict_detection(self):
        """Conflicting tools separated."""
        scheduler = ToolScheduler()
        t1 = self._make_tool_def("read_file")
        t2 = self._make_tool_def("write_file")
        registry = self._make_registry([t1, t2])

        # Record conflicts between read_file and write_file
        scheduler.record_conflict("read_file", "write_file")
        scheduler.record_conflict("read_file", "write_file")

        calls = [
            {"id": "1", "toolName": "read_file", "input": {}},
            {"id": "2", "toolName": "write_file", "input": {}},
        ]

        concurrent, serial = scheduler.schedule_calls(calls, registry)
        # One should be concurrent, the other serial due to conflict
        assert len(concurrent) + len(serial) == 2
        assert len(concurrent) == 1
        assert len(serial) == 1

    def test_max_workers_recommendation(self):
        """Worker limits for write/command tools."""
        scheduler = ToolScheduler()

        # Only read tools -> up to 8
        read_calls = [{"id": "1", "toolName": "read_file", "input": {}}] * 10
        assert scheduler.get_recommended_max_workers(read_calls) == 8

        # With write tools -> max 4
        write_calls = [
            {"id": "1", "toolName": "read_file", "input": {}},
            {"id": "2", "toolName": "write_file", "input": {}},
        ]
        assert scheduler.get_recommended_max_workers(write_calls) == 4

        # With command tools -> max 3
        cmd_calls = [
            {"id": "1", "toolName": "read_file", "input": {}},
            {"id": "2", "toolName": "run_command", "input": {}},
        ]
        assert scheduler.get_recommended_max_workers(cmd_calls) == 3

        # Empty -> 1
        assert scheduler.get_recommended_max_workers([]) == 1


# ---------------------------------------------------------------------------
# TestMemoryInjector
# ---------------------------------------------------------------------------

class TestMemoryInjector:
    """Integration tests for MemoryInjector."""

    def test_inject_for_task(self, memory_with_entries):
        """Memories injected for task."""
        injector = MemoryInjector(
            memory_manager=memory_with_entries,
            max_injected_memories=5,
            min_relevance=0.0,
        )
        memories = injector.inject_for_task("How does the API work?")
        assert len(memories) > 0
        assert all(isinstance(m, InjectedMemory) for m in memories)
        # Should find the architecture entry about FastAPI
        contents = [m.content.lower() for m in memories]
        assert any("fastapi" in c for c in contents)

    def test_inject_on_failure(self, memory_with_entries):
        """Recovery memories on failure."""
        injector = MemoryInjector(
            memory_manager=memory_with_entries,
            max_injected_memories=5,
        )
        memories = injector.inject_on_failure("pytest fixture error", "test_runner")
        # Should return memories (even if generic) since memory has entries
        assert isinstance(memories, list)

    def test_format_for_prompt(self):
        """Proper formatting."""
        injector = MemoryInjector()
        memories = [
            InjectedMemory(content="Use pytest", category="testing", relevance_score=0.9, source="project_search"),
            InjectedMemory(content="Use snake_case", category="convention", relevance_score=0.8, source="project_search"),
        ]
        formatted = injector.format_for_prompt(memories)
        assert "Relevant Context from Memory" in formatted
        assert "1. [testing] Use pytest" in formatted
        assert "2. [convention] Use snake_case" in formatted
        assert "Use the above context" in formatted

    def test_cooldown_prevention(self, memory_with_entries):
        """Same query within cooldown skipped."""
        injector = MemoryInjector(
            memory_manager=memory_with_entries,
            injection_cooldown=60.0,
        )
        first = injector.inject_for_task("test query")
        # Same query immediately after should be skipped
        second = injector.inject_for_task("test query")
        assert second == []

        # Different query should work
        third = injector.inject_for_task("different query")
        assert isinstance(third, list)

    def test_deduplication(self, memory_with_entries):
        """Duplicate memories removed."""
        # Add duplicate content across scopes
        memory_with_entries.add_entry(
            MemoryScope.LOCAL, "testing", "Tests use pytest with fixtures", ["test", "pytest"]
        )
        injector = MemoryInjector(
            memory_manager=memory_with_entries,
            max_injected_memories=10,
            min_relevance=0.0,
        )
        memories = injector.inject_for_task("pytest testing")
        contents = [m.content for m in memories]
        # The exact duplicate should appear only once
        assert contents.count("Tests use pytest with fixtures") <= 1


# ---------------------------------------------------------------------------
# TestAgentLoopIntegration
# ---------------------------------------------------------------------------

class TestAgentLoopIntegration:
    """Integration tests for Agent Loop intelligence features."""

    def test_metrics_collector_integration(self):
        """Metrics flow through agent loop."""
        from minicode.agent_loop import run_agent_turn
        from minicode.types import AgentStep

        metrics = AgentMetricsCollector()

        # Create a simple model that returns a final assistant message
        class FakeModel:
            def next(self, messages, on_stream_chunk=None, store=None):
                return AgentStep(type="assistant", content="Done")

        # Create minimal tool registry
        registry = ToolRegistry(tools=[])

        messages = [{"role": "user", "content": "hello"}]
        result = run_agent_turn(
            model=FakeModel(),
            tools=registry,
            messages=messages,
            cwd=".",
            metrics_collector=metrics,
            max_steps=1,
        )

        assert len(result) > len(messages)
        # Metrics should have recorded the turn
        recent = metrics.get_recent_turns(1)
        assert len(recent) == 1
        assert recent[0].turn_id == 1

    def test_error_recovery_integration(self):
        """Error classification in loop."""
        from minicode.agent_loop import run_agent_turn
        from minicode.types import AgentStep, ToolCall
        from minicode.tooling import ToolResult

        # Tool that always fails with a network error
        def failing_runner(args, ctx):
            return ToolResult(ok=False, output="Connection refused")

        failing_tool = ToolDefinition(
            name="web_fetch",
            description="Fetches web content",
            input_schema={},
            validator=lambda x: x,
            run=failing_runner,
        )

        class ToolModel:
            def __init__(self):
                self._called = False

            def next(self, messages, on_stream_chunk=None, store=None):
                if not self._called:
                    self._called = True
                    return AgentStep(
                        type="tool_calls",
                        content="",
                        calls=[ToolCall(id="1", toolName="web_fetch", input={"url": "http://example.com"})],
                    )
                return AgentStep(type="assistant", content="Done")

        registry = ToolRegistry(tools=[failing_tool])
        messages = [{"role": "user", "content": "fetch"}]

        result = run_agent_turn(
            model=ToolModel(),
            tools=registry,
            messages=messages,
            cwd=".",
            max_steps=2,
        )

        # The tool result should contain the classified error nudge
        tool_results = [m for m in result if m.get("role") == "tool_result"]
        assert len(tool_results) == 1
        assert "[System note:" in tool_results[0]["content"]
        assert "network" in tool_results[0]["content"].lower() or "retry" in tool_results[0]["content"].lower()

    def test_scheduler_integration(self):
        """Tool scheduling in loop."""
        from minicode.agent_loop import run_agent_turn
        from minicode.types import AgentStep, ToolCall
        from minicode.tooling import ToolResult

        results_log: list[str] = []

        def make_runner(name: str):
            def runner(args, ctx):
                results_log.append(name)
                return ToolResult(ok=True, output=f"{name} ok")
            return runner

        tools = [
            ToolDefinition(
                name="read_file",
                description="Reads a file",
                input_schema={},
                validator=lambda x: x,
                run=make_runner("read_file"),
                metadata=ToolMetadata(
                    name="read_file",
                    description="Reads a file",
                    capabilities={ToolCapability.READ_ONLY, ToolCapability.CONCURRENCY_SAFE},
                ),
            ),
            ToolDefinition(
                name="list_files",
                description="Lists files",
                input_schema={},
                validator=lambda x: x,
                run=make_runner("list_files"),
                metadata=ToolMetadata(
                    name="list_files",
                    description="Lists files",
                    capabilities={ToolCapability.READ_ONLY, ToolCapability.CONCURRENCY_SAFE},
                ),
            ),
        ]

        class MultiToolModel:
            def __init__(self):
                self._called = False

            def next(self, messages, on_stream_chunk=None, store=None):
                if not self._called:
                    self._called = True
                    return AgentStep(
                        type="tool_calls",
                        content="",
                        calls=[
                            ToolCall(id="1", toolName="read_file", input={"path": "/tmp/a"}),
                            ToolCall(id="2", toolName="list_files", input={"path": "/tmp"}),
                        ],
                    )
                return AgentStep(type="assistant", content="Done")

        registry = ToolRegistry(tools=tools)
        messages = [{"role": "user", "content": "do stuff"}]

        result = run_agent_turn(
            model=MultiToolModel(),
            tools=registry,
            messages=messages,
            cwd=".",
            max_steps=2,
        )

        # Both tools should have executed
        assert "read_file" in results_log
        assert "list_files" in results_log

        # Verify tool results are in the messages
        tool_results = [m for m in result if m.get("role") == "tool_result"]
        assert len(tool_results) == 2
