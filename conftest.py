"""Pytest collection controls for repository-local legacy smoke scripts."""

from __future__ import annotations


# These root-level scripts are manual smoke/integration utilities from earlier
# development rounds. Normal pytest coverage lives under tests/.
collect_ignore = [
    "smoke_test.py",
    "test_chinese_input.py",
    "test_integration.py",
    "test_optim.py",
    "test_run.py",
    "test_state_integration.py",
    "visual_test.py",
]

collect_ignore_glob = [
    "benchmarks/*.py",
]
