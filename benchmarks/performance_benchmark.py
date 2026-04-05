"""Performance benchmark suite for MiniCode Python.

Measures performance across key areas:
1. Rendering performance (terminal UI)
2. Tool execution performance (file operations, commands)
3. Memory usage patterns
4. Context management (token estimation, compaction)
5. Agent loop throughput
"""

from __future__ import annotations

import cProfile
import io
import os
import pstats
import tempfile
import time
import timeit
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add parent directory to path to import minicode
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from minicode.context_manager import estimate_tokens, estimate_message_tokens
from minicode.cost_tracker import CostTracker
from minicode.tools.grep_files import grep_files_tool
from minicode.tools.list_files import list_files_tool
from minicode.tools.read_file import read_file_tool
from minicode.tooling import ToolContext, ToolRegistry


@dataclass
class BenchmarkResult:
    name: str
    duration_ms: float
    ops_per_sec: float
    memory_mb: float = 0.0
    details: str = ""


def format_result(result: BenchmarkResult) -> str:
    return (
        f"{result.name:<40} {result.duration_ms:>8.2f} ms  "
        f"({result.ops_per_sec:>8.2f} ops/sec)  "
        f"{result.memory_mb:>6.1f} MB  {result.details}"
    )


# ---------------------------------------------------------------------------
# 1. Rendering benchmarks
# ---------------------------------------------------------------------------

def benchmark_terminal_rendering() -> list[BenchmarkResult]:
    """Benchmark terminal rendering performance."""
    results = []

    from minicode.tui.chrome import (
        render_panel,
        render_banner,
        render_footer_bar,
        render_permission_prompt,
        render_slash_menu,
        _cached_terminal_size,
        string_display_width,
        truncate_plain,
        wrap_panel_body_line,
    )
    from minicode.tui.transcript import render_transcript

    cols, rows = _cached_terminal_size()

    # 1a. Panel rendering
    def render_panel_bench():
        body = "Line " * 100
        return render_panel("test", body, right_title="right")

    panel_time = timeit.timeit(render_panel_bench, number=1000) * 1000 / 1000
    results.append(BenchmarkResult(
        name="render_panel (100 lines)",
        duration_ms=panel_time,
        ops_per_sec=1000 / panel_time * 1000,
        details=f"{cols}x{rows}",
    ))

    # 1b. Banner rendering
    def render_banner_bench():
        return render_banner(
            {"model": "claude-sonnet-4-20250514", "baseUrl": "https://api.anthropic.com"},
            str(Path.cwd()),
            ["cwd: /test"],
            {"transcriptCount": 10, "messageCount": 20, "skillCount": 5, "mcpCount": 1},
        )

    banner_time = timeit.timeit(render_banner_bench, number=1000) * 1000 / 1000
    results.append(BenchmarkResult(
        name="render_banner",
        duration_ms=banner_time,
        ops_per_sec=1000 / banner_time * 1000,
    ))

    # 1c. String display width (CJK aware)
    test_strings = [
        "Hello World",
        "你好世界",
        "混合 mixed 文本 text 🚀",
        "a" * 1000,
    ]

    def width_bench():
        for s in test_strings:
            string_display_width(s)

    width_time = timeit.timeit(width_bench, number=10000) * 1000 / 10000
    results.append(BenchmarkResult(
        name="string_display_width (avg)",
        duration_ms=width_time,
        ops_per_sec=1000 / width_time * 1000,
        details=f"{len(test_strings)} strings",
    ))

    # 1d. Footer bar
    def footer_bench():
        return render_footer_bar(
            status="Running edit_file...",
            tools_enabled=True,
            skills_enabled=True,
            background_tasks=[],
        )

    footer_time = timeit.timeit(footer_bench, number=1000) * 1000 / 1000
    results.append(BenchmarkResult(
        name="render_footer_bar",
        duration_ms=footer_time,
        ops_per_sec=1000 / footer_time * 1000,
    ))

    return results


# ---------------------------------------------------------------------------
# 2. Token estimation benchmarks
# ---------------------------------------------------------------------------

def benchmark_token_estimation() -> list[BenchmarkResult]:
    """Benchmark token estimation performance and accuracy."""
    results = []

    # Test strings of various types
    test_cases = [
        ("ASCII only", "Hello World " * 100),
        ("Chinese only", "你好世界" * 100),
        ("Mixed CJK/ASCII", "Hello 你好 World 世界 " * 50),
        ("Code sample", "def foo(x): return x + 1\n" * 50),
        ("Long text", "Lorem ipsum " * 500),
    ]

    for name, text in test_cases:
        tokens = estimate_tokens(text)
        
        def estimate():
            return estimate_tokens(text)

        duration = timeit.timeit(estimate, number=10000) * 1000 / 10000
        results.append(BenchmarkResult(
            name=f"estimate_tokens ({name})",
            duration_ms=duration,
            ops_per_sec=1000 / duration * 1000,
            details=f"{len(text)} chars -> {tokens} tokens",
        ))

    return results


# ---------------------------------------------------------------------------
# 3. File operation benchmarks
# ---------------------------------------------------------------------------

def benchmark_file_operations() -> list[BenchmarkResult]:
    """Benchmark file operation performance."""
    results = []
    
    # Create temp directory with test files
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        
        # Create test files
        for i in range(50):
            (tmp / f"file_{i}.txt").write_text(f"Content {i}\n" * 100, encoding="utf-8")
        
        # Create subdirectories
        for i in range(5):
            subdir = tmp / f"subdir_{i}"
            subdir.mkdir()
            for j in range(10):
                (subdir / f"sub_{j}.txt").write_text(f"Sub content {j}\n" * 50, encoding="utf-8")

        # Mock context
        class MockPermissions:
            def ensure_path_access(self, *args): pass
        
        context = ToolContext(cwd=str(tmp), permissions=MockPermissions())

        # 3a. List files
        def list_files():
            return list_files_tool._run({"path": ".", "limit": 200}, context)

        list_time = timeit.timeit(list_files, number=100) * 1000 / 100
        results.append(BenchmarkResult(
            name="list_files (100 files)",
            duration_ms=list_time,
            ops_per_sec=1000 / list_time * 1000,
        ))

        # 3b. Read file
        def read_file():
            return read_file_tool._run({"path": "file_0.txt", "offset": 0, "limit": 1000}, context)

        read_time = timeit.timeit(read_file, number=100) * 1000 / 100
        results.append(BenchmarkResult(
            name="read_file (100 lines)",
            duration_ms=read_time,
            ops_per_sec=1000 / read_time * 1000,
        ))

        # 3c. Grep files
        def grep_files():
            return grep_files_tool._run({"pattern": "Content", "path": "."}, context)

        grep_time = timeit.timeit(grep_files, number=50) * 1000 / 50
        results.append(BenchmarkResult(
            name="grep_files (100 files)",
            duration_ms=grep_time,
            ops_per_sec=1000 / grep_time * 1000,
        ))

    return results


# ---------------------------------------------------------------------------
# 4. Context manager benchmarks
# ---------------------------------------------------------------------------

def benchmark_context_manager() -> list[BenchmarkResult]:
    """Benchmark context management operations."""
    results = []

    from minicode.context_manager import ContextManager

    # Create messages for testing
    messages = []
    for i in range(100):
        messages.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Message {i} " * 50,
        })

    # 4a. Initial stats
    cm = ContextManager(model="claude-sonnet-4-20250514")
    
    def add_messages():
        cm.add_messages(messages)

    add_time = timeit.timeit(add_messages, number=10) * 1000 / 10
    results.append(BenchmarkResult(
        name="context_manager.add_messages (100 msgs)",
        duration_ms=add_time,
        ops_per_sec=100 / add_time * 1000,
        details=f"{cm.total_tokens} tokens",
    ))

    # 4b. Should compact check
    def should_compact():
        return cm.should_compact()

    compact_check_time = timeit.timeit(should_compact, number=1000) * 1000 / 1000
    results.append(BenchmarkResult(
        name="context_manager.should_compact",
        duration_ms=compact_check_time,
        ops_per_sec=1000 / compact_check_time * 1000,
    ))

    return results


# ---------------------------------------------------------------------------
# 5. Cost tracker benchmarks
# ---------------------------------------------------------------------------

def benchmark_cost_tracker() -> list[BenchmarkResult]:
    """Benchmark cost tracking operations."""
    results = []

    ct = CostTracker()

    def record_usage():
        ct.record_usage(
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
            cost=0.015,
            duration_ms=1500,
        )

    record_time = timeit.timeit(record_usage, number=10000) * 1000 / 10000
    results.append(BenchmarkResult(
        name="cost_tracker.record_usage",
        duration_ms=record_time,
        ops_per_sec=1000 / record_time * 1000,
    ))

    return results


# ---------------------------------------------------------------------------
# Main benchmark runner
# ---------------------------------------------------------------------------

def run_all_benchmarks() -> list[BenchmarkResult]:
    """Run all benchmarks and return results."""
    all_results = []
    
    print("=" * 80)
    print("MiniCode Python Performance Benchmark")
    print("=" * 80)
    print()

    benchmarks = [
        ("Terminal Rendering", benchmark_terminal_rendering),
        ("Token Estimation", benchmark_token_estimation),
        ("File Operations", benchmark_file_operations),
        ("Context Manager", benchmark_context_manager),
        ("Cost Tracker", benchmark_cost_tracker),
    ]

    for name, func in benchmarks:
        print(f"📊 Running {name} benchmarks...")
        try:
            results = func()
            all_results.extend(results)
            print(f"   ✅ {len(results)} benchmarks completed\n")
        except Exception as e:
            print(f"   ❌ Failed: {e}\n")

    return all_results


def print_results(results: list[BenchmarkResult]):
    """Print formatted benchmark results."""
    print("=" * 80)
    print("Benchmark Results")
    print("=" * 80)
    print(f"{'Test':<40} {'Duration':>10} {'Ops/sec':>12} {'Memory':>8} {'Details'}")
    print("-" * 80)

    for r in results:
        print(format_result(r))

    print("-" * 80)
    print(f"\nTotal benchmarks: {len(results)}")


def profile_key_functions():
    """Profile key functions to identify bottlenecks."""
    print("\n" + "=" * 80)
    print("Profiling Key Functions")
    print("=" * 80)

    profiler = cProfile.Profile()
    profiler.enable()

    # Run some operations
    from minicode.context_manager import estimate_tokens
    large_text = "Hello 你好 " * 10000
    for _ in range(1000):
        estimate_tokens(large_text)

    profiler.disable()

    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    ps.print_stats(20)
    print(s.getvalue())


if __name__ == "__main__":
    results = run_all_benchmarks()
    print_results(results)
    profile_key_functions()

    # Save results
    output_file = Path(__file__).parent / "benchmark_results.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("MiniCode Python Benchmark Results\n")
        f.write("=" * 80 + "\n\n")
        for r in results:
            f.write(format_result(r) + "\n")
    
    print(f"\nResults saved to {output_file}")
