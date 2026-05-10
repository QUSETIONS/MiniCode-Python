"""Pytest collection controls for repository-local legacy smoke scripts."""

from __future__ import annotations

import pytest


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


@pytest.fixture
def memory_manager(tmp_path):
    """Create a MemoryManager with temporary paths."""
    from minicode.memory import MemoryManager
    return MemoryManager(project_root=tmp_path)


@pytest.fixture
def memory_with_entries(memory_manager):
    """Create a MemoryManager pre-populated with test entries."""
    from minicode.memory import MemoryScope
    entries = [
        ("project", "architecture", "Uses FastAPI for REST API backend", ["api", "fastapi"]),
        ("project", "code-pattern", "All functions use snake_case naming", ["convention", "naming"]),
        ("project", "testing", "Tests use pytest with fixtures", ["test", "pytest"]),
        ("user", "preference", "Always respond in Chinese", ["language", "chinese"]),
        ("local", "decision", "Use SQLite for development database", ["database", "sqlite"]),
    ]
    for scope, category, content, tags in entries:
        memory_manager.add_entry(
            MemoryScope(scope.upper()), category, content, tags
        )
    return memory_manager


@pytest.fixture
def mock_memory_search():
    """Mock search function for testing prompt injection."""
    def mock_search(query, scope=None, limit=20, min_relevance=0.1):
        from minicode.memory import MemoryEntry, MemoryScope
        return [
            MemoryEntry(id="test-1", scope=MemoryScope.PROJECT, category="test", content=f"Mock result for: {query}"),
        ]
    return mock_search


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace with basic structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "tests").mkdir()
    (workspace / "src" / "main.py").write_text("# Main file\n")
    return str(workspace)
