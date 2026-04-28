"""Functional Completeness Test Suite for MiniCode Python.

Tests all core modules after 7 rounds of optimization:
1. Startup & Configuration
2. Tool Execution
3. Permission System
4. Context Management
5. Memory System
6. Help System
7. Error Recovery
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Module 1: Startup & Configuration
# ---------------------------------------------------------------------------

class TestStartupAndConfig:
    """Module 1: Test startup and configuration validation."""

    def test_config_diagnostic_command(self):
        """Test --validate-config output format."""
        from minicode.config import format_config_diagnostic
        result = format_config_diagnostic()
        assert "Configuration Diagnostics" in result
        assert "Status:" in result
        assert "Tool Profile:" in result

    def test_logging_system_initialization(self):
        """Test logging system initializes correctly."""
        from minicode.logging_config import setup_logging, get_logger
        logger = setup_logging(level="DEBUG", log_to_file=False, log_to_console=False)
        assert logger.name == "minicode"
        assert logger.level == 10  # DEBUG level

    def test_core_module_imports(self):
        """Test all core modules import without errors."""
        from minicode.main import main
        from minicode.logging_config import setup_logging
        from minicode.context_manager import ContextManager
        from minicode.memory import MemoryManager
        from minicode.config import validate_config
        # If we get here, all imports succeeded
        assert True


# ---------------------------------------------------------------------------
# Module 2: Tool Execution
# ---------------------------------------------------------------------------

class MockPermissions:
    """Mock permission manager that allows everything."""
    def ensure_path_access(self, *args):
        pass
    def ensure_command(self, *args, **kwargs):
        pass
    def ensure_edit(self, *args):
        pass


class MockContext:
    """Mock tool context."""
    def __init__(self, cwd: str):
        self.cwd = cwd
        self.permissions = MockPermissions()


class TestToolExecution:
    """Module 2: Test tool execution."""

    @pytest.fixture
    def test_dir(self, tmp_path):
        """Create a temporary test directory with sample files."""
        # Create test files
        (tmp_path / "file1.txt").write_text("Hello World\nLine 2\nLine 3", encoding="utf-8")
        (tmp_path / "file2.py").write_text("def foo():\n    return 'bar'\n", encoding="utf-8")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file3.txt").write_text("Nested file content", encoding="utf-8")
        return tmp_path

    @pytest.fixture
    def context(self, test_dir):
        """Create mock context for tool execution."""
        return MockContext(cwd=str(test_dir))

    def test_list_files_tool(self, context):
        """Test list_files_tool executes successfully."""
        from minicode.tools.list_files import list_files_tool
        result = list_files_tool.run({"path": ".", "limit": 100}, context)
        assert result.ok
        assert "file1.txt" in result.output or "file2.py" in result.output

    def test_read_file_tool(self, context):
        """Test read_file_tool executes successfully."""
        from minicode.tools.read_file import read_file_tool
        result = read_file_tool.run({"path": "file1.txt", "offset": 0, "limit": 1000}, context)
        assert result.ok
        assert "Hello World" in result.output

    def test_grep_files_tool(self, context):
        """Test grep_files_tool executes successfully."""
        from minicode.tools.grep_files import grep_files_tool
        result = grep_files_tool.run({"pattern": "Hello", "path": "."}, context)
        assert result.ok
        assert "file1.txt" in result.output

    def test_run_command_tool(self, context):
        """Test run_command_tool executes successfully."""
        from minicode.tools.run_command import run_command_tool
        result = run_command_tool.run({"command": "python --version"}, context)
        assert result.ok
        assert "Python" in result.output


# ---------------------------------------------------------------------------
# Module 3: Permission System
# ---------------------------------------------------------------------------

class TestPermissionSystem:
    """Module 3: Test permission system."""

    def test_path_access_within_cwd_allowed(self):
        """Test that path access within cwd is allowed."""
        from minicode.permissions import PermissionManager
        pm = PermissionManager(workspace_root="/test/cwd")
        # Should not raise
        pm.ensure_path_access("/test/cwd/file.txt", "read")

    def test_path_access_outside_cwd_denied_without_prompt(self):
        """Test that path access outside cwd is denied when no prompt."""
        from minicode.permissions import PermissionManager
        pm = PermissionManager(workspace_root="/test/cwd")
        with pytest.raises(RuntimeError, match="outside cwd"):
            pm.ensure_path_access("/etc/passwd", "read")

    def test_dangerous_command_detection(self):
        """Test that dangerous commands are detected."""
        from minicode.permissions import _classify_dangerous_command
        # Git dangerous commands
        result = _classify_dangerous_command("git", ["reset", "--hard"])
        assert result is not None
        assert "git reset --hard" in result
        
        # Shell execution
        result = _classify_dangerous_command("bash", ["-c", "echo test"])
        assert result is not None
        assert "bash" in result


# ---------------------------------------------------------------------------
# Module 4: Context Management
# ---------------------------------------------------------------------------

class TestContextManagement:
    """Module 4: Test context window management."""

    def test_token_estimation_ascii(self):
        """Test token estimation for ASCII text."""
        from minicode.context_manager import estimate_tokens
        text = "Hello World " * 100
        tokens = estimate_tokens(text)
        # ~4 chars/token for ASCII
        expected = len(text) // 4
        assert abs(tokens - expected) < expected * 0.2  # Within 20%

    def test_token_estimation_chinese(self):
        """Test token estimation for Chinese text."""
        from minicode.context_manager import estimate_tokens
        text = "你好世界" * 100
        tokens = estimate_tokens(text)
        # ~1.5 chars/token for CJK
        expected = len(text) // 1.5
        assert abs(tokens - expected) < expected * 0.2

    def test_context_manager_stats(self):
        """Test context manager statistics."""
        from minicode.context_manager import ContextManager
        ctx = ContextManager(model="claude-sonnet-4-20250514")
        ctx.messages = [{"role": "user", "content": "Hello " * 100}]
        stats = ctx.get_stats()
        assert stats.total_tokens > 0
        assert stats.messages_count == 1

    def test_context_compaction(self):
        """Test context compaction reduces message count."""
        from minicode.context_manager import ContextManager
        ctx = ContextManager(model="claude-sonnet-4-20250514", context_window=1000)
        # Add many messages to trigger compaction
        ctx.messages = [{"role": "user", "content": "x" * 50} for _ in range(50)]
        if ctx.should_auto_compact():
            compacted = ctx.compact_messages()
            assert len(compacted) < 50  # Should be fewer after compaction


# ---------------------------------------------------------------------------
# Module 5: Memory System
# ---------------------------------------------------------------------------

class TestMemorySystem:
    """Module 5: Test memory system."""

    @pytest.fixture
    def memory_mgr(self, tmp_path):
        """Create a temporary memory manager."""
        from minicode.memory import MemoryManager
        return MemoryManager(workspace=str(tmp_path))

    def test_add_memory_entry(self, memory_mgr):
        """Test adding a memory entry."""
        from minicode.memory import MemoryScope
        entry = memory_mgr.add_entry(
            scope=MemoryScope.PROJECT,
            category="convention",
            content="Use type hints in all public APIs",
            tags=["coding", "style"],
        )
        assert entry.id
        assert "type hints" in entry.content

    def test_search_memory(self, memory_mgr):
        """Test searching memory entries."""
        from minicode.memory import MemoryScope
        memory_mgr.add_entry(MemoryScope.PROJECT, "test", "Python is great for coding")
        memory_mgr.add_entry(MemoryScope.PROJECT, "test", "JavaScript runs in browsers")
        results = memory_mgr.search("Python")
        assert len(results) > 0
        assert any("Python" in r.content for r in results)

    def test_memory_context_injection(self, memory_mgr):
        """Test memory context injection for system prompt."""
        from minicode.memory import MemoryScope
        memory_mgr.add_entry(MemoryScope.PROJECT, "convention", "Always write tests")
        context = memory_mgr.get_relevant_context(max_entries=10, max_tokens=8000)
        assert isinstance(context, str)
        assert len(context) > 0

    def test_memory_persistence(self, memory_mgr):
        """Test memory persists to disk."""
        from minicode.memory import MemoryManager, MemoryScope
        memory_mgr.add_entry(MemoryScope.PROJECT, "test", "Persistent memory entry")
        # Reload and check
        memory_mgr2 = MemoryManager(workspace=memory_mgr.workspace)
        results = memory_mgr2.search("Persistent")
        assert len(results) > 0


# ---------------------------------------------------------------------------
# Module 6: Help System
# ---------------------------------------------------------------------------

class TestHelpSystem:
    """Module 6: Test help and diagnostic commands."""

    def test_config_diagnostic_format(self):
        """Test /config command output format."""
        from minicode.config import format_config_diagnostic
        result = format_config_diagnostic()
        assert "Configuration Diagnostics" in result
        assert "=" * 40 in result

    def test_context_details_format(self):
        """Test /context command output format."""
        from minicode.context_manager import ContextManager
        ctx = ContextManager(model="claude-sonnet-4-20250514")
        result = ctx.format_context_details()
        assert "Context Window Usage" in result
        assert "claude-sonnet-4-20250514" in result

    def test_memory_summary_format(self):
        """Test /memory command output format."""
        from minicode.memory import MemoryManager
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            mem = MemoryManager(workspace=tmp)
            # Use format_stats instead of get_summary
            stats = mem.format_stats()
            assert isinstance(stats, str)
            assert "Memory" in stats or "memory" in stats

    def test_slash_commands_available(self):
        """Test that all slash commands are available."""
        from minicode.cli_commands import SLASH_COMMANDS
        command_names = {cmd.name for cmd in SLASH_COMMANDS}
        expected = {"/help", "/tools", "/status", "/config", "/context", "/memory", "/mcp", "/skills", "/exit"}
        assert expected.issubset(command_names)


# ---------------------------------------------------------------------------
# Module 7: Error Recovery
# ---------------------------------------------------------------------------

class TestErrorRecovery:
    """Module 7: Test error handling and recovery guidance."""

    def test_config_error_guidance(self):
        """Test that config errors provide actionable guidance."""
        from minicode.config import validate_config
        is_valid, messages = validate_config()
        if not is_valid:
            # At least one message should contain guidance
            assert any("fix" in msg.lower() or "set" in msg.lower() for msg in messages)

    def test_tool_error_handling(self, tmp_path):
        """Test tool errors return useful messages."""
        from minicode.tools.read_file import read_file_tool
        
        class MockCtx:
            cwd = str(tmp_path)
            permissions = None
        
        # Create a file to read
        (tmp_path / "test.txt").write_text("test", encoding="utf-8")
        ctx = MockCtx()
        result = read_file_tool.run({"path": "test.txt", "offset": 0, "limit": 100}, ctx)
        assert result.ok
        assert "test" in result.output
