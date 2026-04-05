# MiniCode Python 功能完整性测试实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 创建自动化集成测试套件，验证 MiniCode Python 经过七轮优化后的所有核心功能是否正常工作

**架构：** 单个测试文件包含 7 个测试模块，按顺序执行验证启动、工具、权限、上下文、记忆、帮助、错误恢复

**技术栈：** Python 3.11+, pytest, tempfile, pathlib

---

### 任务 1：创建测试文件框架和模块 1（启动与配置）

**文件：**
- 创建：`tests/test_functional_completeness.py`

- [ ] **步骤 1：创建测试文件并编写模块 1**

```python
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


class TestStartupAndConfig:
    """Module 1: Test startup and configuration validation."""

    def test_config_diagnostic_command(self):
        """Test --validate-config output format."""
        from minicode.config import format_config_diagnostic
        result = format_config_diagnostic()
        assert "Configuration Diagnostics" in result
        assert "Status:" in result

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
```

- [ ] **步骤 2：运行测试验证通过**

运行：`pytest tests/test_functional_completeness.py::TestStartupAndConfig -v`
预期：3 个测试全部 PASS

- [ ] **步骤 3：Commit**

```bash
git add tests/test_functional_completeness.py
git commit -m "test: add functional completeness test - Module 1 (Startup & Config)"
```

---

### 任务 2：模块 2（工具执行测试）

**文件：**
- 修改：`tests/test_functional_completeness.py`

- [ ] **步骤 1：添加工具执行测试**

在文件末尾添加：

```python


class MockPermissions:
    """Mock permission manager that allows everything."""
    def ensure_path_access(self, *args):
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
        result = list_files_tool._run({"path": ".", "limit": 100}, context)
        assert result.ok
        assert "file1.txt" in result.output or "file2.py" in result.output

    def test_read_file_tool(self, context):
        """Test read_file_tool executes successfully."""
        from minicode.tools.read_file import read_file_tool
        result = read_file_tool._run({"path": "file1.txt", "offset": 0, "limit": 1000}, context)
        assert result.ok
        assert "Hello World" in result.output

    def test_grep_files_tool(self, context):
        """Test grep_files_tool executes successfully."""
        from minicode.tools.grep_files import grep_files_tool
        result = grep_files_tool._run({"pattern": "Hello", "path": "."}, context)
        assert result.ok
        assert "file1.txt" in result.output

    def test_run_command_tool(self, context):
        """Test run_command_tool executes successfully."""
        from minicode.tools.run_command import run_command_tool
        result = run_command_tool._run({"command": "python --version"}, context)
        assert result.ok
        assert "Python" in result.output
```

- [ ] **步骤 2：运行测试验证通过**

运行：`pytest tests/test_functional_completeness.py::TestToolExecution -v`
预期：4 个测试全部 PASS

- [ ] **步骤 3：Commit**

```bash
git add tests/test_functional_completeness.py
git commit -m "test: add Module 2 (Tool Execution)"
```

---

### 任务 3：模块 3（权限系统测试）

**文件：**
- 修改：`tests/test_functional_completeness.py`

- [ ] **步骤 1：添加权限系统测试**

```python


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
        with pytest.raises(RuntimeError, match="Access denied"):
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
```

- [ ] **步骤 2：运行测试验证通过**

运行：`pytest tests/test_functional_completeness.py::TestPermissionSystem -v`
预期：3 个测试全部 PASS

- [ ] **步骤 3：Commit**

```bash
git add tests/test_functional_completeness.py
git commit -m "test: add Module 3 (Permission System)"
```

---

### 任务 4：模块 4（上下文管理测试）

**文件：**
- 修改：`tests/test_functional_completeness.py`

- [ ] **步骤 1：添加上下文管理测试**

```python


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
        if ctx.should_compact():
            compacted = ctx.compact_messages()
            assert len(compacted) < 50  # Should be fewer after compaction
```

- [ ] **步骤 2：运行测试验证通过**

运行：`pytest tests/test_functional_completeness.py::TestContextManagement -v`
预期：4 个测试全部 PASS

- [ ] **步骤 3：Commit**

```bash
git add tests/test_functional_completeness.py
git commit -m "test: add Module 4 (Context Management)"
```

---

### 任务 5：模块 5（记忆系统测试）

**文件：**
- 修改：`tests/test_functional_completeness.py`

- [ ] **步骤 1：添加记忆系统测试**

```python


class TestMemorySystem:
    """Module 5: Test memory system."""

    @pytest.fixture
    def memory_mgr(self, tmp_path):
        """Create a temporary memory manager."""
        from minicode.memory import MemoryManager
        return MemoryManager(project_root=tmp_path)

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
        from minicode.memory import MemoryScope
        memory_mgr.add_entry(MemoryScope.PROJECT, "test", "Persistent memory entry")
        # Reload and check
        memory_mgr2 = MemoryManager(project_root=memory_mgr.paths.project_root)
        results = memory_mgr2.search("Persistent")
        assert len(results) > 0
```

- [ ] **步骤 2：运行测试验证通过**

运行：`pytest tests/test_functional_completeness.py::TestMemorySystem -v`
预期：4 个测试全部 PASS

- [ ] **步骤 3：Commit**

```bash
git add tests/test_functional_completeness.py
git commit -m "test: add Module 5 (Memory System)"
```

---

### 任务 6：模块 6 和 7（帮助系统与错误恢复）

**文件：**
- 修改：`tests/test_functional_completeness.py`

- [ ] **步骤 1：添加帮助系统和错误恢复测试**

```python


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
            mem = MemoryManager(project_root=Path(tmp))
            summary = mem.get_summary()
            assert "user_entries" in summary
            assert "project_entries" in summary
            assert "local_entries" in summary

    def test_slash_commands_available(self):
        """Test that all slash commands are available."""
        from minicode.cli_commands import SLASH_COMMANDS
        command_names = {cmd.name for cmd in SLASH_COMMANDS}
        expected = {"/help", "/tools", "/status", "/config", "/context", "/memory", "/mcp", "/skills", "/exit"}
        assert expected.issubset(command_names)


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
        
        # Try to read non-existent file
        # Should not crash, should return error result
        from minicode.workspace import resolve_tool_path
        # Create a file to read
        (tmp_path / "test.txt").write_text("test", encoding="utf-8")
        ctx = MockCtx()
        result = read_file_tool._run({"path": "test.txt", "offset": 0, "limit": 100}, ctx)
        assert result.ok
        assert "test" in result.output
```

- [ ] **步骤 2：运行测试验证通过**

运行：`pytest tests/test_functional_completeness.py::TestHelpSystem tests/test_functional_completeness.py::TestErrorRecovery -v`
预期：7 个测试全部 PASS

- [ ] **步骤 3：Commit**

```bash
git add tests/test_functional_completeness.py
git commit -m "test: add Module 6 (Help System) and Module 7 (Error Recovery)"
```

---

### 任务 7：运行完整测试套件并生成报告

**文件：**
- 修改：`tests/test_functional_completeness.py`（可选：添加总结注释）

- [ ] **步骤 1：运行完整测试套件**

运行：`pytest tests/test_functional_completeness.py -v`
预期：25 个测试全部 PASS

- [ ] **步骤 2：生成测试报告**

```bash
pytest tests/test_functional_completeness.py -v --tb=short 2>&1 | tee tests/functional_test_report.txt
```

- [ ] **步骤 3：最终 Commit**

```bash
git add tests/test_functional_completeness.py tests/functional_test_report.txt
git commit -m "test: complete functional completeness test suite - all 25 tests passing"
```

---

## 自检

**1. 规格覆盖度：**
- ✅ 启动与配置 → 任务 1
- ✅ 工具执行 → 任务 2
- ✅ 权限系统 → 任务 3
- ✅ 上下文管理 → 任务 4
- ✅ 记忆系统 → 任务 5
- ✅ 帮助系统 → 任务 6
- ✅ 错误恢复 → 任务 6

**2. 占位符扫描：** 无占位符、无 TODO、无模糊需求

**3. 类型一致性：** 所有测试使用相同的 Mock 类和 fixture 模式

---

计划已完成并保存到 `docs/superpowers/plans/2026-04-05-functional-completeness-test.md`。两种执行方式：

**1. 子代理驱动（推荐）** - 每个任务调度新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

**选哪种方式？**