#!/usr/bin/env python3
"""Cluster stress test runner for MiniCode.

Runs multiple agent loops concurrently to test system stability.
Usage:
    python cluster_stress_test.py --workers 8 --turns 10 --tools 5
"""

from __future__ import annotations

import argparse
import concurrent.futures
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).parent.parent))

from minicode.agent_loop import run_agent_turn
from minicode.agent_metrics import AgentMetricsCollector
from minicode.tooling import ToolDefinition, ToolRegistry, ToolResult
from minicode.types import AgentStep, ChatMessage, ModelAdapter


class StressModel(ModelAdapter):
    """Model adapter that simulates failures and delays for stress testing."""

    def __init__(self, failure_rate: float = 0.0, delay: float = 0.0):
        self.failure_rate = failure_rate
        self.delay = delay
        self.calls = 0

    def next(
        self,
        messages: list[ChatMessage],
        on_stream_chunk: Callable[[str], None] | None = None,
        store: Any | None = None,
    ) -> AgentStep:
        time.sleep(self.delay)
        self.calls += 1
        if self.failure_rate > 0 and self.calls % int(1 / self.failure_rate) == 0:
            raise ConnectionError("Simulated failure")
        return AgentStep(type="assistant", content="done")


def run_stress_test(
    workers: int, turns: int, tools: int, failure_rate: float
) -> bool:
    """Run the cluster stress test and return True if no errors occurred."""
    collector = AgentMetricsCollector()
    latencies: list[float] = []
    errors: list[str] = []

    def worker_task(worker_id: int) -> tuple[list[float], list[str]]:
        registry_tools = [
            ToolDefinition(
                name=f"tool_{i}",
                description=f"Tool {i}",
                input_schema={"type": "object"},
                validator=lambda v: v,
                run=lambda input_data, ctx: ToolResult(ok=True, output=f"result_{i}"),
                is_concurrency_safe=True,
            )
            for i in range(tools)
        ]
        registry = ToolRegistry(registry_tools)
        model = StressModel(failure_rate=failure_rate, delay=0.001)

        worker_latencies: list[float] = []
        worker_errors: list[str] = []

        for turn in range(turns):
            start = time.time()
            try:
                collector.start_turn(worker_id * 1000 + turn)
                messages = run_agent_turn(
                    model=model,
                    tools=registry,
                    messages=[{"role": "system", "content": "sys"}],
                    cwd=".",
                    max_steps=5,
                )
                collector.end_turn()
                worker_latencies.append(time.time() - start)
            except Exception as e:
                worker_errors.append(str(e))
                collector.end_turn()

        return worker_latencies, worker_errors

    print(
        f"Starting cluster stress test: {workers} workers, {turns} turns each, {tools} tools"
    )
    print("=" * 60)

    overall_start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker_task, i) for i in range(workers)]
        for future in concurrent.futures.as_completed(futures):
            wl, we = future.result()
            latencies.extend(wl)
            errors.extend(we)

    overall_time = time.time() - overall_start

    # Report
    print(f"\nResults:")
    print(f"  Total time: {overall_time:.2f}s")
    print(f"  Total turns: {workers * turns}")
    print(f"  Successful turns: {len(latencies)}")
    print(f"  Failed turns: {len(errors)}")

    if latencies:
        print(f"  Avg latency: {statistics.mean(latencies)*1000:.1f}ms")
        print(f"  Median latency: {statistics.median(latencies)*1000:.1f}ms")
        print(f"  Max latency: {max(latencies)*1000:.1f}ms")

    # Tool stats
    all_stats = collector.get_all_tool_stats()
    if all_stats:
        print(f"\nTool Statistics:")
        for name, stats in all_stats.items():
            print(
                f"  {name}: {stats.success_rate*100:.0f}% success ({stats.total_executions} runs)"
            )

    print(
        f"\n{'PASS' if len(errors) == 0 else 'FAIL'}: {len(errors)} errors out of {workers * turns} turns"
    )
    return len(errors) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MiniCode Cluster Stress Test")
    parser.add_argument(
        "--workers", type=int, default=4, help="Number of concurrent workers"
    )
    parser.add_argument(
        "--turns", type=int, default=5, help="Turns per worker"
    )
    parser.add_argument(
        "--tools", type=int, default=3, help="Number of tools"
    )
    parser.add_argument(
        "--failure-rate",
        type=float,
        default=0.0,
        help="Simulated failure rate (0.0-1.0)",
    )
    args = parser.parse_args()

    success = run_stress_test(args.workers, args.turns, args.tools, args.failure_rate)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
