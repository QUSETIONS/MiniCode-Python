"""Tests for new core features: context management, API retry, task tracking, memory."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from minicode.api_retry import (
    APIRetryExhaustedError,
    HTTPError,
    RetryState,
    calculate_backoff,
    format_retry_state,
    is_retryable_error,
    retry_with_backoff,
)
from minicode.context_manager import (
    ContextManager,
    ContextStats,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    load_context_state,
    save_context_state,
)
from minicode.memory import (
    MemoryEntry,
    MemoryFile,
    MemoryManager,
    MemoryScope,
    inject_memory_into_prompt,
)
from minicode.task_tracker import (
    Task,
    TaskList,
    TaskManager,
    TaskStatus,
    format_task_progress_bar,
    format_task_update,
)


# ---------------------------------------------------------------------------
# Context Manager Tests
# ---------------------------------------------------------------------------

def test_estimate_tokens_basic():
    """Test basic token estimation."""
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") > 0
    # Rough estimate: 4 chars per token
    assert estimate_tokens("hello world") <= 3  # 11 chars / 4 ≈ 2-3 tokens


def test_estimate_message_tokens():
    """Test message token estimation."""
    msg = {"role": "user", "content": "Hello world"}
    tokens = estimate_message_tokens(msg)
    assert tokens > 0
    assert tokens > len("Hello world") / 10  # Should be reasonable estimate


def test_estimate_messages_tokens():
    """Test multiple messages token estimation."""
    messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
    ]
    tokens = estimate_messages_tokens(messages)
    assert tokens > 0


def test_context_manager_initial_stats():
    """Test context manager starts empty."""
    manager = ContextManager(model="default")
    stats = manager.get_stats()
    assert stats.total_tokens == 0
    assert stats.messages_count == 0
    assert stats.usage_percentage == 0.0


def test_context_manager_add_messages():
    """Test adding messages updates stats."""
    manager = ContextManager(model="default")
    manager.add_message({"role": "user", "content": "Hello world"})
    
    stats = manager.get_stats()
    assert stats.messages_count == 1
    assert stats.total_tokens > 0


def test_context_manager_should_compact():
    """Test auto-compaction trigger."""
    # Create manager with small window
    manager = ContextManager(model="default", context_window=1000)
    
    # Add messages to exceed 95%
    for i in range(50):
        manager.add_message({"role": "user", "content": "x" * 100})
    
    assert manager.should_auto_compact()


def test_context_manager_compact():
    """Test message compaction."""
    manager = ContextManager(model="default", context_window=1000)
    
    # Add system prompt
    manager.add_message({"role": "system", "content": "You are helpful"})
    
    # Add many messages to trigger compaction
    for i in range(50):
        manager.add_message({"role": "user", "content": f"Message {i}" * 50})
        manager.add_message({"role": "assistant", "content": f"Response {i}" * 50})
    
    initial_count = len(manager.messages)
    compacted = manager.compact_messages()
    
    assert len(compacted) < initial_count
    assert len(manager.compaction_history) == 1


def test_context_manager_format_summary():
    """Test context summary formatting."""
    manager = ContextManager(model="default")
    manager.add_message({"role": "user", "content": "Hello"})
    
    summary = manager.get_context_summary()
    assert "Context:" in summary
    assert "tokens" in summary.lower() or "msgs" in summary


def test_context_manager_persistence(tmp_path):
    """Test saving and loading context state."""
    with patch("minicode.context_manager.MINI_CODE_DIR", tmp_path):
        manager = ContextManager(model="claude-sonnet-4-20250514")
        manager.add_message({"role": "user", "content": "Test"})
        
        save_context_state(manager)
        loaded = load_context_state()
        
        assert loaded is not None
        assert loaded.model == "claude-sonnet-4-20250514"
        assert len(loaded.messages) == 1


# ---------------------------------------------------------------------------
# API Retry Tests
# ---------------------------------------------------------------------------

def test_calculate_backoff_base():
    """Test basic backoff calculation."""
    backoff = calculate_backoff(0, base=1.0, max_wait=60.0, jitter=0.0)
    assert backoff == pytest.approx(1.0, abs=0.1)


def test_calculate_backoff_exponential():
    """Test exponential backoff."""
    backoff_0 = calculate_backoff(0, base=1.0, max_wait=60.0, jitter=0.0)
    backoff_1 = calculate_backoff(1, base=1.0, max_wait=60.0, jitter=0.0)
    backoff_2 = calculate_backoff(2, base=1.0, max_wait=60.0, jitter=0.0)
    
    assert backoff_1 > backoff_0
    assert backoff_2 > backoff_1


def test_calculate_backoff_retry_after():
    """Test respecting Retry-After header."""
    backoff = calculate_backoff(0, retry_after=10.0, base=1.0, max_wait=60.0)
    assert backoff == 10.0


def test_calculate_backoff_max_cap():
    """Test backoff doesn't exceed max."""
    backoff = calculate_backoff(10, base=1.0, max_wait=5.0, jitter=0.0)
    assert backoff <= 5.0


def test_retry_with_backoff_success():
    """Test successful call doesn't retry."""
    call_count = 0
    
    def success_func():
        nonlocal call_count
        call_count += 1
        return "ok"
    
    result = retry_with_backoff(success_func, max_retries=3)
    assert result == "ok"
    assert call_count == 1


def test_retry_with_backoff_retryable_error():
    """Test retry on retryable HTTP errors."""
    call_count = 0
    
    def failing_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise HTTPError("Service unavailable", 503)
        return "ok"
    
    result = retry_with_backoff(failing_func, max_retries=3, base_backoff=0.01)
    assert result == "ok"
    assert call_count == 3


def test_retry_with_backoff_non_retryable():
    """Test non-retryable errors raise immediately."""
    def bad_request():
        raise HTTPError("Bad request", 400)
    
    with pytest.raises(HTTPError) as exc_info:
        retry_with_backoff(bad_request, max_retries=3)
    
    assert exc_info.value.status_code == 400


def test_retry_exhausted():
    """Test error when all retries fail."""
    def always_fail():
        raise HTTPError("Server error", 500)
    
    with pytest.raises(APIRetryExhaustedError):
        retry_with_backoff(always_fail, max_retries=2, base_backoff=0.01)


def test_is_retryable_error():
    """Test retryable error detection."""
    assert is_retryable_error(HTTPError("Rate limited", 429))
    assert is_retryable_error(HTTPError("Server error", 503))
    assert not is_retryable_error(HTTPError("Bad request", 400))


def test_format_retry_state():
    """Test retry state formatting."""
    state = RetryState(attempts=3, succeeded=True)
    formatted = format_retry_state(state)
    assert "Succeeded" in formatted


# ---------------------------------------------------------------------------
# Task Tracker Tests
# ---------------------------------------------------------------------------

def test_task_list_creation():
    """Test creating task list."""
    tl = TaskList(title="Test tasks")
    assert tl.title == "Test tasks"
    assert tl.total == 0


def test_add_tasks():
    """Test adding tasks."""
    tl = TaskList(title="Test")
    t1 = tl.add_task("Task 1")
    t2 = tl.add_task("Task 2")
    
    assert tl.total == 2
    assert t1.id == "1"
    assert t2.id == "2"


def test_complete_task():
    """Test completing tasks."""
    tl = TaskList()
    tl.add_task("Task 1")
    tl.add_task("Task 2")
    
    tl.mark_completed("1")
    assert tl.completed_count == 1
    assert tl.progress_percentage == 50.0


def test_task_list_completion():
    """Test full completion detection."""
    tl = TaskList()
    tl.add_task("Task 1")
    tl.add_task("Task 2")
    
    assert not tl.is_complete
    
    tl.mark_completed("1")
    tl.mark_completed("2")
    
    assert tl.is_complete


def test_task_manager():
    """Test task manager."""
    tm = TaskManager()
    tm.create_list("Test")
    tm.add_task("Task 1")
    tm.add_task("Task 2")
    
    assert tm.active_list is not None
    assert tm.active_list.total == 2


def test_auto_detect_tasks_numbered():
    """Test auto-detecting numbered tasks."""
    tm = TaskManager()
    tasks = tm.auto_detect_tasks("1. First task\n2. Second task\n3. Third task")
    assert tasks is not None
    assert len(tasks) == 3


def test_auto_detect_tasks_bullets():
    """Test auto-detecting bullet tasks."""
    tm = TaskManager()
    tasks = tm.auto_detect_tasks("- First\n- Second\n- Third")
    assert tasks is not None
    assert len(tasks) == 3


def test_format_task_progress_bar():
    """Test progress bar formatting."""
    tl = TaskList()
    tl.add_task("Task 1")
    tl.add_task("Task 2")
    tl.mark_completed("1")
    
    bar = format_task_progress_bar(tl, width=10)
    assert "█" in bar
    assert "50%" in bar


def test_task_update_format():
    """Test task update formatting."""
    task = Task(id="1", description="Test")
    formatted = format_task_update(task, TaskStatus.COMPLETED)
    assert "✓" in formatted or "Task 1" in formatted


# ---------------------------------------------------------------------------
# Memory System Tests
# ---------------------------------------------------------------------------

def test_memory_entry_creation():
    """Test memory entry creation."""
    entry = MemoryEntry(
        id="test-1",
        scope=MemoryScope.USER,
        category="convention",
        content="Use snake_case for functions",
        tags=["python", "naming"],
    )
    assert entry.scope == MemoryScope.USER
    assert "snake_case" in entry.content


def test_memory_file_add_entry():
    """Test adding entries to memory file."""
    mf = MemoryFile(scope=MemoryScope.PROJECT)
    entry = MemoryEntry(
        id="p-1",
        scope=MemoryScope.PROJECT,
        category="architecture",
        content="Use repository pattern",
    )
    mf.add_entry(entry)
    assert len(mf.entries) == 1


def test_memory_file_enforce_limits():
    """Test memory file enforces entry limits."""
    mf = MemoryFile(scope=MemoryScope.USER, max_entries=5)
    
    for i in range(10):
        entry = MemoryEntry(
            id=f"u-{i}",
            scope=MemoryScope.USER,
            category="test",
            content=f"Entry {i}",
        )
        mf.add_entry(entry)
    
    assert len(mf.entries) <= 5


def test_memory_file_search():
    """Test searching memory entries."""
    mf = MemoryFile(scope=MemoryScope.PROJECT)
    mf.add_entry(MemoryEntry(
        id="p-1", scope=MemoryScope.PROJECT, category="python",
        content="Use pytest for testing", tags=["testing"]
    ))
    mf.add_entry(MemoryEntry(
        id="p-2", scope=MemoryScope.PROJECT, category="python",
        content="Use black for formatting", tags=["formatting"]
    ))
    
    results = mf.search("pytest")
    assert len(results) == 1
    assert "pytest" in results[0].content


def test_memory_file_format_markdown():
    """Test formatting as MEMORY.md."""
    mf = MemoryFile(scope=MemoryScope.USER)
    mf.add_entry(MemoryEntry(
        id="u-1", scope=MemoryScope.USER, category="convention",
        content="Use type hints", tags=["python"]
    ))
    
    markdown = mf.format_as_markdown()
    assert "# User Memory" in markdown
    assert "Use type hints" in markdown


def test_memory_manager_add_entry(tmp_path):
    """Test memory manager add entry."""
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    
    mm = MemoryManager(workspace)
    mm.add_entry(
        scope=MemoryScope.LOCAL,
        category="convention",
        content="Use fastapi for APIs",
        tags=["python", "web"]
    )
    
    assert len(mm.memories[MemoryScope.LOCAL].entries) == 1


def test_memory_manager_search(tmp_path):
    """Test memory manager search."""
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    
    mm = MemoryManager(workspace)
    mm.add_entry(MemoryScope.PROJECT, "python", "Use pytest")
    mm.add_entry(MemoryScope.PROJECT, "python", "Use black")
    
    results = mm.search("pytest")
    assert len(results) == 1


def test_memory_manager_get_context(tmp_path):
    """Test getting relevant context."""
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    
    mm = MemoryManager(workspace)
    mm.add_entry(MemoryScope.LOCAL, "test", "Entry 1")
    mm.add_entry(MemoryScope.PROJECT, "test", "Entry 2")
    mm.add_entry(MemoryScope.USER, "test", "Entry 3")
    
    context = mm.get_relevant_context()
    assert "Entry 1" in context or "Entry 2" in context or "Entry 3" in context


def test_inject_memory_into_prompt(tmp_path):
    """Test memory injection into system prompt."""
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    
    mm = MemoryManager(workspace)
    mm.add_entry(MemoryScope.PROJECT, "convention", "Use snake_case")
    
    system_prompt = "You are a helpful assistant."
    injected = inject_memory_into_prompt(system_prompt, mm)
    
    assert "You are a helpful assistant." in injected
    assert "Project Memory" in injected
    assert "snake_case" in injected


def test_memory_manager_format_stats(tmp_path):
    """Test memory stats formatting."""
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    
    mm = MemoryManager(workspace)
    mm.add_entry(MemoryScope.USER, "test", "Entry")
    
    stats = mm.format_stats()
    assert "Memory System Status" in stats
