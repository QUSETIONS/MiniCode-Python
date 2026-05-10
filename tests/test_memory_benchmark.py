"""Memory system performance benchmarks."""
import time
import pytest
from minicode.memory import MemoryManager, MemoryScope


@pytest.mark.benchmark
def test_search_performance_100_entries(memory_manager):
    """Test search performance with 100 entries."""
    from tests.test_helpers import create_memory_entries
    create_memory_entries(memory_manager, 100)
    
    start = time.perf_counter()
    for _ in range(10):
        memory_manager.search("testing")
    elapsed = time.perf_counter() - start
    
    # Should complete 10 searches in under 1 second
    assert elapsed < 1.0, f"Search too slow: {elapsed:.3f}s for 10 searches with 100 entries"


@pytest.mark.benchmark
def test_search_performance_500_entries(memory_manager):
    """Test search performance with 500 entries."""
    from tests.test_helpers import create_memory_entries
    create_memory_entries(memory_manager, 500)
    
    start = time.perf_counter()
    for _ in range(10):
        memory_manager.search("architecture")
    elapsed = time.perf_counter() - start
    
    # Should complete 10 searches in under 5 seconds
    assert elapsed < 5.0, f"Search too slow: {elapsed:.3f}s for 10 searches with 500 entries"


@pytest.mark.benchmark
def test_chinese_search_performance(memory_manager):
    """Test Chinese search performance."""
    from tests.test_helpers import create_chinese_memory_entries
    create_chinese_memory_entries(memory_manager, 50)
    
    start = time.perf_counter()
    for _ in range(10):
        memory_manager.search("测试")
    elapsed = time.perf_counter() - start
    
    assert elapsed < 2.0, f"Chinese search too slow: {elapsed:.3f}s"


def test_memory_size_limits(memory_manager):
    """Test that memory respects size limits."""
    # Add entries until limit is hit
    for i in range(250):  # More than max_entries (200)
        memory_manager.add_entry(
            MemoryScope.PROJECT,
            "test",
            f"Entry {i} with some content to take up space" * 10,
        )
    
    entries = memory_manager.memories[MemoryScope.PROJECT].entries
    assert len(entries) <= 200, f"Too many entries: {len(entries)}"
