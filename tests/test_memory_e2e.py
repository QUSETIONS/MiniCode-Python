"""End-to-end workflow tests for the MiniCode memory system.

Covers full agent loops with memory retrieval, multi-turn accumulation,
cross-session recovery, context-driven behavior, Chinese language support,
and corruption recovery — all from the perspective of a real workflow.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minicode.memory import (
    MemoryEntry,
    MemoryManager,
    MemoryScope,
    inject_memory_into_prompt,
    _tokenize,
)
from minicode.agent_loop import run_agent_turn
from minicode.mock_model import MockModelAdapter
from minicode.permissions import PermissionManager
from minicode.tools import create_default_tool_registry
from minicode.prompt import build_system_prompt
from minicode.context_manager import ContextManager
from minicode.types import AgentStep


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.txt").write_text("Hello, world!\n", encoding="utf-8")
    (ws / "src").mkdir()
    (ws / "src" / "main.py").write_text(
        textwrap.dedent("""\
            def greet(name: str) -> str:
                return f"Hello, {name}!"
        """),
        encoding="utf-8",
    )
    (ws / "src" / "utils.py").write_text(
        textwrap.dedent("""\
            def get_cwd() -> str:
                return "workspace"
        """),
        encoding="utf-8",
    )
    return ws


@pytest.fixture
def mock_model() -> MockModelAdapter:
    return MockModelAdapter()


@pytest.fixture
def tools(tmp_workspace: Path):
    return create_default_tool_registry(str(tmp_workspace), runtime=None)


@pytest.fixture
def auto_allow_permissions(tmp_workspace: Path):
    def _auto_allow(request: dict) -> dict:
        return {"decision": "allow_once"}
    return PermissionManager(str(tmp_workspace), prompt=_auto_allow)


@pytest.fixture
def system_messages(tmp_workspace: Path, auto_allow_permissions: PermissionManager):
    return [
        {
            "role": "system",
            "content": build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            ),
        }
    ]


# ---------------------------------------------------------------------------
# 1. Full Agent Loop with Memory Retrieval
# ---------------------------------------------------------------------------


class TestFullAgentLoopMemoryRetrieval:
    """Simulate a complete agent turn where memory flows end-to-end."""

    def test_full_loop_memory_injected_and_used(
        self, tmp_workspace, tools, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Project uses FastAPI for the REST API layer",
            ["fastapi", "api"],
        )
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "All route handlers must include error handling",
            ["convention", "error-handling"],
        )

        injected_prompt = inject_memory_into_prompt(
            build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            ),
            mm,
        )

        assert "FastAPI" in injected_prompt
        assert "error handling" in injected_prompt
        assert "## Project Memory & Context" in injected_prompt

        msgs = [
            {"role": "system", "content": injected_prompt},
            {"role": "user", "content": "/tools"},
        ]
        result = run_agent_turn(
            model=MockModelAdapter(),
            tools=tools,
            messages=msgs,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1

    def test_full_loop_memory_retrieval_creates_new_memory(
        self, tmp_workspace, tools, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "decision",
            "Use PostgreSQL for production, SQLite for dev",
            ["database"],
        )

        msgs = [
            {"role": "system", "content": build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            )},
            {"role": "user", "content": "/ls"},
        ]
        result = run_agent_turn(
            model=MockModelAdapter(),
            tools=tools,
            messages=msgs,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        assert any(m["role"] == "tool_result" for m in result)

        reloaded = MemoryManager(project_root=tmp_workspace)
        assert len(reloaded.memories[MemoryScope.PROJECT].entries) >= 1

    def test_full_loop_search_before_and_after_turn(
        self, tmp_workspace, tools, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "testing",
            "All tests must use pytest fixtures",
            ["pytest", "testing"],
        )

        results_before = mm.search("pytest fixtures")
        assert len(results_before) >= 1
        assert "pytest fixtures" in results_before[0].content

        msgs = [
            {"role": "system", "content": build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            )},
            {"role": "user", "content": "/read hello.txt"},
        ]
        run_agent_turn(
            model=MockModelAdapter(),
            tools=tools,
            messages=msgs,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        results_after = mm.search("pytest")
        assert len(results_after) >= 1


# ---------------------------------------------------------------------------
# 2. Multi-turn Conversation with Memory Accumulation
# ---------------------------------------------------------------------------


class TestMultiTurnMemoryAccumulation:
    """Simulate 5+ conversation turns with memory accumulation."""

    def test_five_turns_with_injected_memory(
        self, tmp_workspace, tools, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Use repository pattern for data access layer",
            ["repository", "data-access"],
        )
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "All functions must have type hints",
            ["typing", "convention"],
        )

        base_prompt = build_system_prompt(
            str(tmp_workspace),
            auto_allow_permissions.get_summary(),
            {"skills": [], "mcpServers": []},
        )
        injected = inject_memory_into_prompt(base_prompt, mm)

        turn_inputs = [
            "/ls",
            "/read hello.txt",
            "/read src/main.py",
            "/tools",
            "/read src/utils.py",
        ]

        results = []
        for user_input in turn_inputs:
            msgs = [
                {"role": "system", "content": injected},
                {"role": "user", "content": user_input},
            ]
            result = run_agent_turn(
                model=MockModelAdapter(),
                tools=tools,
                messages=msgs,
                cwd=str(tmp_workspace),
                permissions=auto_allow_permissions,
            )
            results.append(result)

        for i, result in enumerate(results):
            assert len(result) > 1, f"Turn {i} returned insufficient messages"

        final_mm = MemoryManager(project_root=tmp_workspace)
        assert len(final_mm.memories[MemoryScope.PROJECT].entries) >= 2

    def test_search_quality_improves_with_more_entries(
        self, tmp_workspace,
    ):
        mm = MemoryManager(project_root=tmp_workspace)

        assert len(mm.search("database")) == 0

        mm.add_entry(
            MemoryScope.PROJECT, "decision", "Use SQLite for development"
        )
        results_1 = mm.search("SQLite")
        assert len(results_1) >= 1

        mm.add_entry(
            MemoryScope.PROJECT, "decision", "Use pytest for testing"
        )
        mm.add_entry(
            MemoryScope.PROJECT, "architecture", "Database layer uses SQLAlchemy ORM"
        )
        mm.add_entry(
            MemoryScope.PROJECT, "convention", "Database migrations use Alembic"
        )

        results_4 = mm.search("database")
        assert len(results_4) >= len(results_1)

        mm.add_entry(
            MemoryScope.PROJECT, "testing", "Database tests use in-memory SQLite"
        )
        mm.add_entry(
            MemoryScope.LOCAL, "note", "Local DB port is 5433"
        )

        results_6 = mm.search("database")
        assert len(results_6) >= len(results_4)

        top_result = results_6[0]
        assert any(
            keyword in top_result.content.lower()
            for keyword in ["database", "sqlalchemy", "sqlite", "migration"]
        )

    def test_memory_accumulation_across_turns_persists_to_disk(
        self, tmp_workspace, tools, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT, "convention", "Use 4-space indentation"
        )

        base_prompt = build_system_prompt(
            str(tmp_workspace),
            auto_allow_permissions.get_summary(),
            {"skills": [], "mcpServers": []},
        )
        injected = inject_memory_into_prompt(base_prompt, mm)

        for i in range(5):
            msgs = [
                {"role": "system", "content": injected},
                {"role": "user", "content": "/ls"},
            ]
            run_agent_turn(
                model=MockModelAdapter(),
                tools=tools,
                messages=msgs,
                cwd=str(tmp_workspace),
                permissions=auto_allow_permissions,
            )

        memory_json = tmp_workspace / ".mini-code-memory" / "memory.json"
        assert memory_json.exists()

        data = json.loads(memory_json.read_text(encoding="utf-8"))
        assert len(data["entries"]) >= 1
        assert any("4-space indentation" in e["content"] for e in data["entries"])


# ---------------------------------------------------------------------------
# 3. Cross-session Memory Recovery and Continuity
# ---------------------------------------------------------------------------


class TestCrossSessionMemoryContinuity:
    """Memory survives session boundaries."""

    def test_memory_survives_session_close_and_reopen(
        self, tmp_workspace,
    ):
        mm1 = MemoryManager(project_root=tmp_workspace)
        mm1.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Backend uses FastAPI with async handlers",
            ["fastapi", "async"],
        )
        mm1.add_entry(
            MemoryScope.PROJECT,
            "decision",
            "Use Redis for caching layer",
            ["redis", "cache"],
        )
        mm1.add_entry(
            MemoryScope.LOCAL,
            "note",
            "Dev server runs on port 8080",
        )

        del mm1

        mm2 = MemoryManager(project_root=tmp_workspace)
        project_entries = mm2.memories[MemoryScope.PROJECT].entries
        assert len(project_entries) >= 2
        assert any("FastAPI" in e.content for e in project_entries)
        assert any("Redis" in e.content for e in project_entries)

        local_entries = mm2.memories[MemoryScope.LOCAL].entries
        assert len(local_entries) >= 1
        assert any("8080" in e.content for e in local_entries)

    def test_new_session_entries_coexist_with_old(
        self, tmp_workspace,
    ):
        mm1 = MemoryManager(project_root=tmp_workspace)
        mm1.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Use FastAPI for REST API",
            ["fastapi"],
        )

        del mm1

        mm2 = MemoryManager(project_root=tmp_workspace)
        mm2.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "All endpoints must use async def",
            ["async", "convention"],
        )

        all_entries = mm2.memories[MemoryScope.PROJECT].entries
        assert len(all_entries) >= 2
        assert any("FastAPI" in e.content for e in all_entries)
        assert any("async def" in e.content for e in all_entries)

    def test_cross_session_user_memory_shared(
        self, tmp_workspace,
    ):
        ws1 = tmp_workspace / "project_a"
        ws2 = tmp_workspace / "project_b"
        ws1.mkdir()
        ws2.mkdir()

        mm1 = MemoryManager(project_root=ws1)
        mm1.add_entry(
            MemoryScope.USER,
            "preference",
            "Always use TypeScript for new projects",
            ["typescript"],
        )

        del mm1

        mm2 = MemoryManager(project_root=ws2)
        user_entries = mm2.memories[MemoryScope.USER].entries
        assert any("TypeScript" in e.content for e in user_entries)

        mm2.add_entry(
            MemoryScope.USER,
            "preference",
            "Use pnpm as package manager",
            ["pnpm"],
        )

        all_user = mm2.memories[MemoryScope.USER].entries
        assert any("TypeScript" in e.content for e in all_user)
        assert any("pnpm" in e.content for e in all_user)

    def test_cross_session_context_retrieval_consistency(
        self, tmp_workspace,
    ):
        mm1 = MemoryManager(project_root=tmp_workspace)
        mm1.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Project uses microservices architecture with three services",
            ["microservices", "architecture"],
        )
        mm1.add_entry(
            MemoryScope.PROJECT,
            "decision",
            "Service A handles authentication, Service B handles data",
            ["services", "auth"],
        )

        context_1 = mm1.get_relevant_context(query="microservices")
        assert "microservices" in context_1

        del mm1

        mm2 = MemoryManager(project_root=tmp_workspace)
        context_2 = mm2.get_relevant_context(query="microservices")
        assert "microservices" in context_2

        mm2.add_entry(
            MemoryScope.PROJECT,
            "testing",
            "Integration tests cover all three services",
            ["testing", "microservices"],
        )

        context_3 = mm2.get_relevant_context(query="microservices")
        assert "microservices" in context_3
        assert len(context_3) >= len(context_2)


# ---------------------------------------------------------------------------
# 4. Memory-driven Context Adaptation
# ---------------------------------------------------------------------------


class TestMemoryDrivenContextAdaptation:
    """System adapts behavior based on injected memory context."""

    def test_naming_convention_memory_injected_into_prompt(
        self, tmp_workspace, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "USE_SNAKE_CASE_FOR_ALL_FUNCTION_NAMES",
            ["naming", "snake_case"],
        )

        injected = inject_memory_into_prompt(
            build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            ),
            mm,
        )

        assert "SNAKE_CASE" in injected or "snake_case" in injected
        assert "Project Memory & Context" in injected

    def test_mock_model_receives_memory_in_prompt(
        self, tmp_workspace, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "UNIQUE_MARKER_ADAPTION_TEST_XYZ789",
            ["marker"],
        )

        injected_prompt = inject_memory_into_prompt(
            build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            ),
            mm,
        )

        captured_messages: list[dict] = []

        class CapturingMockModel:
            def next(self, messages, on_stream_chunk=None):
                captured_messages.clear()
                captured_messages.extend(messages)
                return AgentStep(
                    type="assistant",
                    content="Acknowledged",
                )

        model = CapturingMockModel()
        tools = create_default_tool_registry(str(tmp_workspace), runtime=None)

        msgs = [
            {"role": "system", "content": injected_prompt},
            {"role": "user", "content": "/tools"},
        ]
        run_agent_turn(
            model=model,
            tools=tools,
            messages=msgs,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        system_content = ""
        for m in captured_messages:
            if m.get("role") == "system":
                system_content = m.get("content", "")
                break

        assert "UNIQUE_MARKER_ADAPTION_TEST_XYZ789" in system_content
        assert "Project Memory & Context" in system_content

    def test_security_convention_affects_prompt(
        self, tmp_workspace, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "security",
            "All user input must be sanitized before processing",
            ["security", "sanitization"],
        )
        mm.add_entry(
            MemoryScope.PROJECT,
            "security",
            "Use parameterized SQL queries only",
            ["sql", "security"],
        )

        injected = inject_memory_into_prompt(
            build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            ),
            mm,
        )

        assert "sanitized" in injected
        assert "parameterized SQL" in injected

    def test_multiple_scopes_combined_in_prompt(
        self, tmp_workspace, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Backend uses FastAPI",
            ["fastapi"],
        )
        mm.add_entry(
            MemoryScope.USER,
            "preference",
            "Always include type annotations",
            ["typing"],
        )
        mm.add_entry(
            MemoryScope.LOCAL,
            "note",
            "Local test DB is on port 5433",
            ["database"],
        )

        injected = inject_memory_into_prompt(
            build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            ),
            mm,
        )

        assert "FastAPI" in injected
        assert "type annotations" in injected
        assert "5433" in injected


# ---------------------------------------------------------------------------
# 5. Chinese Language Memory E2E
# ---------------------------------------------------------------------------


class TestChineseLanguageMemoryE2E:
    """Full workflow with Chinese memory entries."""

    def test_chinese_entry_add_and_search(
        self, tmp_workspace,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "使用 FastAPI 构建 REST API 后端",
            ["fastapi", "api"],
        )

        results = mm.search("FastAPI")
        assert len(results) >= 1
        assert "FastAPI" in results[0].content
        assert "REST API" in results[0].content

    def test_chinese_query_chinese_results(
        self, tmp_workspace,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "所有函数使用 snake_case 命名规范",
            ["naming", "convention"],
        )
        mm.add_entry(
            MemoryScope.PROJECT,
            "testing",
            "测试使用 pytest 框架和 fixtures",
            ["test", "pytest"],
        )

        results = mm.search("函数 命名")
        assert len(results) >= 1
        assert "snake_case" in results[0].content

    def test_chinese_context_injection(
        self, tmp_workspace, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "使用 FastAPI 构建 REST API 后端",
            ["fastapi"],
        )
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "所有函数使用 snake_case 命名规范",
            ["naming"],
        )

        injected = inject_memory_into_prompt(
            build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            ),
            mm,
        )

        assert "FastAPI" in injected
        assert "snake_case" in injected
        assert "Project Memory & Context" in injected

    def test_chinese_tokenization_and_bigram(
        self,
    ):
        tokens = _tokenize("使用异步函数处理并发请求")
        assert len(tokens) > 0

        cjk_chars = [t for t in tokens if any('\u4e00' <= c <= '\u9fff' for c in t)]
        assert len(cjk_chars) > 0

        bigrams = _tokenize("异步函数")
        assert len(bigrams) > 0

    def test_chinese_full_workflow_with_agent_loop(
        self, tmp_workspace, tools, auto_allow_permissions,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "项目使用 FastAPI 框架",
            ["fastapi"],
        )
        mm.add_entry(
            MemoryScope.PROJECT,
            "testing",
            "使用 pytest 进行测试",
            ["pytest", "testing"],
        )

        injected = inject_memory_into_prompt(
            build_system_prompt(
                str(tmp_workspace),
                auto_allow_permissions.get_summary(),
                {"skills": [], "mcpServers": []},
            ),
            mm,
        )

        assert "FastAPI" in injected
        assert "pytest" in injected

        msgs = [
            {"role": "system", "content": injected},
            {"role": "user", "content": "/ls"},
        ]
        result = run_agent_turn(
            model=MockModelAdapter(),
            tools=tools,
            messages=msgs,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        assert any(m["role"] == "tool_result" for m in result)

        reloaded = MemoryManager(project_root=tmp_workspace)
        results = reloaded.search("FastAPI")
        assert len(results) >= 1
        assert "FastAPI" in results[0].content

    def test_chinese_code_terminology_expansion(
        self, tmp_workspace,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "使用异步函数处理并发请求",
            ["async", "concurrency"],
        )

        results = mm.search("函数")
        assert len(results) >= 1
        assert "异步" in results[0].content or "function" in results[0].content.lower()

    def test_mixed_chinese_english_search(
        self, tmp_workspace,
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "使用 FastAPI 构建 REST API 后端",
            ["fastapi", "api"],
        )
        mm.add_entry(
            MemoryScope.PROJECT,
            "testing",
            "测试使用 pytest 框架",
            ["pytest"],
        )

        results_en = mm.search("FastAPI REST")
        results_zh = mm.search("后端 框架")

        assert len(results_en) >= 1
        assert len(results_zh) >= 1

        assert any("FastAPI" in r.content for r in results_en)
        assert any("pytest" in r.content for r in results_zh)


# ---------------------------------------------------------------------------
# 6. Memory Corruption and Recovery E2E
# ---------------------------------------------------------------------------


class TestMemoryCorruptionRecoveryE2E:
    """Corrupted memory file auto-recovery end-to-end."""

    def test_valid_then_corrupt_then_recover(
        self, tmp_workspace,
    ):
        mm1 = MemoryManager(project_root=tmp_workspace)
        mm1.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Valid entry 1: Uses FastAPI",
            ["fastapi"],
        )
        mm1.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "Valid entry 2: Use snake_case naming",
            ["naming"],
        )
        mm1.add_entry(
            MemoryScope.PROJECT,
            "testing",
            "Valid entry 3: Use pytest",
            ["pytest"],
        )

        project_entries_before = mm1.memories[MemoryScope.PROJECT].entries
        assert len(project_entries_before) == 3

        memory_json = tmp_workspace / ".mini-code-memory" / "memory.json"
        corrupted_data = {
            "scope": "project",
            "entries": [
                {"id": "valid-1", "scope": "project", "category": "test", "content": "Valid entry 1: Uses FastAPI"},
                {"id": "bad-scope", "scope": "invalid_scope", "category": "test", "content": "Bad scope entry"},
                {"id": "valid-2", "scope": "project", "category": "test", "content": "Valid entry 2: Use snake_case"},
                "not_a_dict_at_all",
                {"id": "valid-3", "scope": "project", "category": "test", "content": "Valid entry 3: Use pytest"},
            ],
        }
        memory_json.write_text(json.dumps(corrupted_data), encoding="utf-8")

        mm2 = MemoryManager(project_root=tmp_workspace)

        project_entries = mm2.memories[MemoryScope.PROJECT].entries
        valid_ids = {e.id for e in project_entries}
        assert "valid-1" in valid_ids
        assert "valid-2" in valid_ids
        assert "valid-3" in valid_ids
        assert "bad-scope" not in valid_ids

        backup = memory_json.with_suffix(".json.bak")
        assert backup.exists()

    def test_totally_corrupt_json_recovers_gracefully(
        self, tmp_workspace,
    ):
        memory_dir = tmp_workspace / ".mini-code-memory"
        memory_dir.mkdir()
        memory_json = memory_dir / "memory.json"

        memory_json.write_text("NOT VALID JSON {{{", encoding="utf-8")

        mm = MemoryManager(project_root=tmp_workspace)

        assert len(mm.memories[MemoryScope.PROJECT].entries) == 0

        mm.add_entry(
            MemoryScope.PROJECT,
            "test",
            "New entry after corruption",
        )

        entries = mm.memories[MemoryScope.PROJECT].entries
        assert len(entries) == 1
        assert "New entry after corruption" in entries[0].content

    def test_empty_json_file_recovers_gracefully(
        self, tmp_workspace,
    ):
        memory_dir = tmp_workspace / ".mini-code-memory"
        memory_dir.mkdir()
        memory_json = memory_dir / "memory.json"

        memory_json.write_text("", encoding="utf-8")

        mm = MemoryManager(project_root=tmp_workspace)

        assert len(mm.memories[MemoryScope.PROJECT].entries) == 0

    def test_partial_json_with_valid_entries_recovers(
        self, tmp_workspace,
    ):
        memory_dir = tmp_workspace / ".mini-code-memory"
        memory_dir.mkdir()
        memory_json = memory_dir / "memory.json"

        data = {
            "scope": "project",
            "entries": [
                {"id": "good-1", "scope": "project", "category": "test", "content": "Good entry one"},
                {"id": "good-2", "scope": "project", "category": "test", "content": "Good entry two"},
                {"id": "", "scope": "project", "category": "test", "content": "Empty id entry"},
            ],
        }
        memory_json.write_text(json.dumps(data), encoding="utf-8")

        mm = MemoryManager(project_root=tmp_workspace)

        project_entries = mm.memories[MemoryScope.PROJECT].entries
        contents = {e.content for e in project_entries}
        assert "Good entry one" in contents
        assert "Good entry two" in contents
        assert "Empty id entry" not in contents

    def test_local_memory_corruption_independent_of_project(
        self, tmp_workspace,
    ):
        mm1 = MemoryManager(project_root=tmp_workspace)
        mm1.add_entry(
            MemoryScope.PROJECT,
            "test",
            "Project entry should survive",
        )
        mm1.add_entry(
            MemoryScope.LOCAL,
            "test",
            "Local entry before corruption",
        )

        local_json = tmp_workspace / ".mini-code-memory-local" / "memory.json"
        local_json.write_text("corrupted data here", encoding="utf-8")

        mm2 = MemoryManager(project_root=tmp_workspace)

        project_entries = mm2.memories[MemoryScope.PROJECT].entries
        assert len(project_entries) >= 1
        assert any("Project entry should survive" in e.content for e in project_entries)

    def test_recovery_preserves_file_after_re_save(
        self, tmp_workspace,
    ):
        mm1 = MemoryManager(project_root=tmp_workspace)
        mm1.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Valid architecture entry",
        )

        memory_json = tmp_workspace / ".mini-code-memory" / "memory.json"

        corrupted = {
            "scope": "project",
            "entries": [
                {"id": "valid-1", "scope": "project", "category": "arch", "content": "Valid architecture entry"},
                {"id": "bad-1", "scope": "invalid", "category": "test", "content": "Bad scope"},
            ],
        }
        memory_json.write_text(json.dumps(corrupted), encoding="utf-8")

        mm2 = MemoryManager(project_root=tmp_workspace)

        mm2.add_entry(
            MemoryScope.PROJECT,
            "testing",
            "New entry after recovery",
        )

        final_data = json.loads(memory_json.read_text(encoding="utf-8"))
        valid_ids = {e["id"] for e in final_data["entries"]}
        assert "valid-1" in valid_ids
        assert "bad-1" not in valid_ids
        assert any("New entry after recovery" in e["content"] for e in final_data["entries"])
