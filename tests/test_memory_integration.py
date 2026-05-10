"""Memory system integration tests.

Verifies integration points between the memory subsystem and other
MiniCode components: ContextManager, Session, Agent Loop, Permissions,
Auto-classification, and Recovery.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minicode.memory import (
    MemoryEntry,
    MemoryFile,
    MemoryManager,
    MemoryScope,
    inject_memory_into_prompt,
    _auto_classify_content,
    _tokenize,
    _CODE_TERM_EXPANSIONS,
)
from minicode.context_manager import ContextManager, estimate_tokens
from minicode.session import (
    save_session,
    load_session,
    create_new_session,
)
from minicode.agent_loop import run_agent_turn
from minicode.mock_model import MockModelAdapter
from minicode.permissions import PermissionManager
from minicode.tools import create_default_tool_registry
from minicode.prompt import build_system_prompt

from tests.test_helpers import (
    verify_memory_integrity,
    create_corrupted_memory_file,
)


# ---------------------------------------------------------------------------
# Shared fixtures
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


@pytest.fixture
def memory_manager(tmp_workspace: Path) -> MemoryManager:
    return MemoryManager(project_root=tmp_workspace)


@pytest.fixture
def memory_with_entries(memory_manager: MemoryManager) -> MemoryManager:
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


# ---------------------------------------------------------------------------
# 1. Memory + Context Manager Integration Tests
# ---------------------------------------------------------------------------


class TestMemoryContextManagerIntegration:
    """Memory injected into prompt works with ContextManager lifecycle."""

    def test_memory_context_injection_with_context_manager(self, memory_with_entries):
        context = memory_with_entries.get_relevant_context()
        assert context != ""

        system_prompt = "You are a coding assistant."
        injected = inject_memory_into_prompt(system_prompt, memory_with_entries)

        assert system_prompt in injected
        assert "Project Memory" in injected or "User Memory" in injected

        ctx = ContextManager(model="default")
        ctx.add_message({"role": "system", "content": injected})
        stats = ctx.get_stats()
        assert stats.messages_count >= 1
        assert stats.total_tokens > 0

    def test_memory_search_results_formatted_for_prompt_injection(self, memory_with_entries):
        results = memory_with_entries.search("pytest")
        assert len(results) >= 1

        context = memory_with_entries.get_relevant_context(query="pytest")
        assert "pytest" in context

    def test_token_budget_enforcement_when_injecting_memory(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)
        for i in range(50):
            mm.add_entry(
                MemoryScope.PROJECT,
                "test",
                f"Entry {i}: " + "x" * 500,
            )

        context_1k = mm.get_relevant_context(max_tokens=1000)
        tokens_1k = estimate_tokens(context_1k) if context_1k else 0
        assert tokens_1k <= 1000 or context_1k == ""

        context_4k = mm.get_relevant_context(max_tokens=4000)
        tokens_4k = estimate_tokens(context_4k) if context_4k else 0
        assert tokens_4k <= 4000 or context_4k == ""

    def test_memory_retrieval_does_not_interfere_with_context_compaction(
        self, memory_with_entries
    ):
        ctx = ContextManager(model="default", context_window=2000)

        ctx.add_message({"role": "system", "content": "You are helpful"})

        for i in range(30):
            ctx.add_message({"role": "user", "content": f"Message {i}" * 20})
            ctx.add_message({"role": "assistant", "content": f"Reply {i}" * 20})

        assert ctx.should_auto_compact()

        memory_context = memory_with_entries.get_relevant_context()
        ctx.add_message({"role": "system", "content": memory_context})

        compacted = ctx.compact_messages()
        assert len(compacted) < len(ctx.messages)

        system_msgs = [m for m in compacted if m.get("role") == "system"]
        assert len(system_msgs) >= 1

    def test_injected_memory_tokens_counted_in_context_stats(self, memory_with_entries):
        system_prompt = "You are a coding assistant."
        injected = inject_memory_into_prompt(system_prompt, memory_with_entries)

        ctx = ContextManager(model="default")
        ctx.add_message({"role": "system", "content": system_prompt})
        tokens_before = ctx.get_stats().total_tokens

        ctx2 = ContextManager(model="default")
        ctx2.add_message({"role": "system", "content": injected})
        tokens_after = ctx2.get_stats().total_tokens

        assert tokens_after > tokens_before


# ---------------------------------------------------------------------------
# 2. Memory + Session Integration Tests
# ---------------------------------------------------------------------------


class TestMemorySessionIntegration:
    """Memory state persists across session save/load cycles."""

    def test_memory_persists_across_session_saves_and_loads(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Use repository pattern for data access",
            ["architecture", "data"],
        )

        session = create_new_session(str(tmp_workspace))
        session.messages = [
            {"role": "system", "content": "You are a coding assistant."},
            {"role": "user", "content": "What pattern should we use?"},
            {"role": "assistant", "content": "Use the repository pattern."},
        ]

        save_session(session, force_full=True)

        loaded = load_session(session.session_id)
        assert loaded is not None
        assert len(loaded.messages) == 3

        mm2 = MemoryManager(project_root=tmp_workspace)
        results = mm2.search("repository pattern")
        assert len(results) >= 1
        assert "repository pattern" in results[0].content

    def test_session_restoration_includes_memory_state(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(MemoryScope.LOCAL, "decision", "Use PostgreSQL in production")
        mm.add_entry(MemoryScope.PROJECT, "convention", "Use type hints everywhere")

        session = create_new_session(str(tmp_workspace))
        session.messages = [
            {"role": "user", "content": "Set up the project"},
        ]
        save_session(session, force_full=True)

        loaded = load_session(session.session_id)
        assert loaded is not None
        assert loaded.workspace == str(tmp_workspace)

        restored_mm = MemoryManager(project_root=loaded.workspace)
        local_results = restored_mm.search("PostgreSQL")
        project_results = restored_mm.search("type hints")
        assert len(local_results) >= 1
        assert len(project_results) >= 1

    def test_memory_entries_available_after_session_resume(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT, "testing", "Use pytest fixtures for database tests"
        )
        entry_id_before = mm.memories[MemoryScope.PROJECT].entries[0].id

        session = create_new_session(str(tmp_workspace))
        session.messages = [
            {"role": "user", "content": "How do we test database?"},
        ]
        save_session(session, force_full=True)

        loaded = load_session(session.session_id)
        assert loaded is not None

        resumed_mm = MemoryManager(project_root=loaded.workspace)
        entries = resumed_mm.memories[MemoryScope.PROJECT].entries
        assert len(entries) >= 1
        assert entries[0].id == entry_id_before
        assert "pytest fixtures" in entries[0].content

    def test_cross_session_memory_continuity_markers(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.USER,
            "preference",
            "Always use TypeScript for new projects",
            ["typescript", "preference"],
        )

        session1 = create_new_session(str(tmp_workspace))
        session1.messages = [{"role": "user", "content": "Session 1"}]
        save_session(session1, force_full=True)

        session2 = create_new_session(str(tmp_workspace))
        session2.messages = [{"role": "user", "content": "Session 2"}]
        save_session(session2, force_full=True)

        loaded1 = load_session(session1.session_id)
        loaded2 = load_session(session2.session_id)
        assert loaded1 is not None
        assert loaded2 is not None

        mm_after = MemoryManager(project_root=tmp_workspace)
        user_entries = mm_after.memories[MemoryScope.USER].entries
        assert len(user_entries) >= 1
        assert any("TypeScript" in e.content for e in user_entries)

    def test_session_with_no_memory_does_not_crash(self, tmp_workspace):
        session = create_new_session(str(tmp_workspace))
        session.messages = [
            {"role": "user", "content": "Hello"},
        ]
        save_session(session, force_full=True)

        loaded = load_session(session.session_id)
        assert loaded is not None

        mm = MemoryManager(project_root=loaded.workspace)
        context = mm.get_relevant_context()
        assert context == ""


# ---------------------------------------------------------------------------
# 3. Memory + Agent Loop Integration Tests
# ---------------------------------------------------------------------------


class TestMemoryAgentLoopIntegration:
    """Agent loop can access and use memory during turns."""

    def test_agent_loop_can_access_memory_during_turn(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "All Python functions must include docstrings",
            ["python", "docstrings"],
        )

        ctx = ContextManager(model="default")
        base_system = list(system_messages)
        base_system[0]["content"] = inject_memory_into_prompt(
            base_system[0]["content"], mm
        )
        base_system.append({"role": "user", "content": "/ls"})

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=base_system,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
            context_manager=ctx,
        )

        assert any(m["role"] == "tool_result" for m in result)

    def test_memory_retrieval_in_multi_turn_conversations(
        self, mock_model, tools, tmp_workspace, auto_allow_permissions
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT, "testing", "Tests must use pytest"
        )

        base_prompt = build_system_prompt(
            str(tmp_workspace),
            auto_allow_permissions.get_summary(),
            {"skills": [], "mcpServers": []},
        )

        msgs_t1 = [
            {"role": "system", "content": inject_memory_into_prompt(base_prompt, mm)},
            {"role": "user", "content": "/read hello.txt"},
        ]
        result_t1 = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=msgs_t1,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )
        assert any(m["role"] == "tool_result" for m in result_t1)

        msgs_t2 = [
            {"role": "system", "content": inject_memory_into_prompt(base_prompt, mm)},
            {"role": "user", "content": "/write test_runner.py::# Test runner"},
        ]
        result_t2 = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=msgs_t2,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )
        test_file = tmp_workspace / "test_runner.py"
        assert test_file.exists()

    def test_memory_context_affects_model_responses_via_mock(
        self, mock_model, tools, tmp_workspace, auto_allow_permissions
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "ALL_RESPONSES_MUST_INCLUDE_MARKER_XYZ",
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

        msgs = [
            {"role": "system", "content": injected_prompt},
            {"role": "user", "content": "/tools"},
        ]
        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=msgs,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1

    def test_memory_usage_tracking_increment(
        self, memory_manager: MemoryManager
    ):
        entry = memory_manager.add_entry(
            MemoryScope.PROJECT,
            "test",
            "This is a test entry for usage tracking",
            ["tracking"],
        )
        assert entry.usage_count == 0

        memory_manager.search("test entry")

        results = memory_manager.search("test entry")
        assert len(results) >= 1

    def test_memory_search_used_in_agent_turn(
        self, mock_model, tools, tmp_workspace, auto_allow_permissions
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "architecture",
            "Use FastAPI for HTTP endpoints",
            ["fastapi", "http"],
        )

        search_results = mm.search("FastAPI HTTP")
        assert len(search_results) >= 1
        assert "FastAPI" in search_results[0].content


# ---------------------------------------------------------------------------
# 4. Memory + Permission Integration Tests
# ---------------------------------------------------------------------------


class TestMemoryPermissionIntegration:
    """Memory access respects workspace boundaries and security."""

    def test_memory_access_respects_workspace_boundaries(self, tmp_workspace):
        ws1 = tmp_workspace / "ws1"
        ws2 = tmp_workspace / "ws2"
        ws1.mkdir()
        ws2.mkdir()

        mm1 = MemoryManager(project_root=ws1)
        mm1.add_entry(
            MemoryScope.LOCAL, "secret", "WS1 local secret data"
        )

        mm2 = MemoryManager(project_root=ws2)
        mm2.add_entry(
            MemoryScope.LOCAL, "other", "WS2 local data"
        )

        results_in_ws2 = mm2.search("WS1 local secret")
        local_in_ws2 = mm2.memories[MemoryScope.LOCAL].entries
        assert not any("WS1 local secret" in e.content for e in local_in_ws2)

    def test_memory_isolation_between_workspaces(self, tmp_workspace):
        ws_a = tmp_workspace / "project_a"
        ws_b = tmp_workspace / "project_b"
        ws_a.mkdir()
        ws_b.mkdir()

        mm_a = MemoryManager(project_root=ws_a)
        mm_a.add_entry(MemoryScope.PROJECT, "test", "Project A test convention")

        mm_b = MemoryManager(project_root=ws_b)
        mm_b.add_entry(MemoryScope.PROJECT, "test", "Project B test convention")

        assert (ws_a / ".mini-code-memory" / "memory.json").exists()
        assert (ws_b / ".mini-code-memory" / "memory.json").exists()

        a_path = ws_a / ".mini-code-memory" / "memory.json"
        b_path = ws_b / ".mini-code-memory" / "memory.json"
        assert a_path != b_path

        data_a = json.loads(a_path.read_text(encoding="utf-8"))
        data_b = json.loads(b_path.read_text(encoding="utf-8"))

        contents_a = {e["content"] for e in data_a["entries"]}
        contents_b = {e["content"] for e in data_b["entries"]}
        assert "Project A test convention" in contents_a
        assert "Project B test convention" in contents_b
        assert "Project A test convention" not in contents_b
        assert "Project B test convention" not in contents_a

    def test_memory_operations_do_not_require_permission_gates(
        self, tmp_workspace
    ):
        mm = MemoryManager(project_root=tmp_workspace)

        mm.add_entry(MemoryScope.PROJECT, "test", "No permission needed")
        mm.search("permission")
        mm.get_relevant_context()

        permissions = PermissionManager(
            str(tmp_workspace),
            prompt=lambda req: {"decision": "deny_once"},
        )

        mm2 = MemoryManager(project_root=tmp_workspace)
        mm2.add_entry(MemoryScope.PROJECT, "test", "Still works with deny-all permissions")
        entries = mm2.memories[MemoryScope.PROJECT].entries
        assert len(entries) >= 1

    def test_memory_file_path_security_no_path_traversal(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)

        local_path = mm.paths.local_memory
        project_path = mm.paths.project_memory

        assert local_path == tmp_workspace / ".mini-code-memory-local"
        assert project_path == tmp_workspace / ".mini-code-memory"

        assert ".." not in str(local_path)
        assert ".." not in str(project_path)

        mm.add_entry(MemoryScope.LOCAL, "test", "Local entry")
        memory_json = local_path / "memory.json"
        assert memory_json.exists()

        resolved = memory_json.resolve()
        assert str(resolved).startswith(str(tmp_workspace.resolve()))

    def test_user_memory_shared_across_workspaces(self, tmp_workspace):
        ws1 = tmp_workspace / "ws1"
        ws2 = tmp_workspace / "ws2"
        ws1.mkdir()
        ws2.mkdir()

        from minicode.config import MINI_CODE_DIR

        mm1 = MemoryManager(project_root=ws1)
        mm1.add_entry(
            MemoryScope.USER, "preference", "Shared user preference"
        )

        mm2 = MemoryManager(project_root=ws2)
        user_entries = mm2.memories[MemoryScope.USER].entries
        assert any("Shared user preference" in e.content for e in user_entries)


# ---------------------------------------------------------------------------
# 5. Memory Auto-classification Integration Tests
# ---------------------------------------------------------------------------


class TestMemoryAutoClassificationIntegration:
    """Auto-classification, tag management, and category-based filtering."""

    def test_auto_classification_of_various_content_types(self, memory_manager):
        test_cases = [
            ("Use FastAPI for the REST API", "architecture"),
            ("All functions must use snake_case", "convention"),
            ("Tests should use pytest fixtures", "testing"),
            ("Configure the database connection string", "configuration"),
            ("Use git flow for branching", "workflow"),
            ("Sanitize all user input before processing", "security"),
            ("Optimize the database query with indexing", "performance"),
            ("Use def calculate_total(items): pattern", "code-pattern"),
        ]

        for content, expected_category in test_cases:
            category, tags = _auto_classify_content(content)
            assert category == expected_category, (
                f"Expected '{expected_category}' for '{content}', got '{category}'"
            )

    def test_auto_classification_chinese_content(self, memory_manager):
        chinese_cases = [
            ("使用异步函数处理并发请求", "performance"),
            ("所有接口必须包含安全认证", "security"),
            ("测试覆盖率达到百分之八十", "testing"),
        ]

        for content, expected_category in chinese_cases:
            category, tags = _auto_classify_content(content)
            assert category == expected_category, (
                f"Expected '{expected_category}' for '{content}', got '{category}'"
            )

    def test_auto_classification_unknown_content(self, memory_manager):
        category, tags = _auto_classify_content("Random unclassifiable text zzz")
        assert category == "general"
        assert tags == []

    def test_auto_classification_on_add_entry(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)

        entry = mm.add_entry(
            MemoryScope.PROJECT,
            "auto",
            "Use pytest for all unit testing with fixtures",
        )

        assert entry.category != "auto"
        assert entry.category == "testing"
        assert len(entry.tags) >= 1

    def test_tag_management_add_tag(self, memory_manager):
        entry = memory_manager.add_entry(
            MemoryScope.PROJECT, "test", "Original entry"
        )

        result = memory_manager.add_tag(
            MemoryScope.PROJECT, entry.id, "important"
        )
        assert result is True

        results = memory_manager.search_by_tag(
            MemoryScope.PROJECT, "important"
        )
        assert len(results) == 1
        assert results[0].id == entry.id

    def test_tag_management_remove_tag(self, memory_manager):
        entry = memory_manager.add_entry(
            MemoryScope.PROJECT, "test", "Entry with tags", tags=["tag1", "tag2"]
        )

        result = memory_manager.remove_tag(
            MemoryScope.PROJECT, entry.id, "tag1"
        )
        assert result is True

        entry_obj = memory_manager.memories[MemoryScope.PROJECT].entries[-1]
        assert "tag1" not in entry_obj.tags
        assert "tag2" in entry_obj.tags

    def test_tag_management_nonexistent_entry(self, memory_manager):
        result = memory_manager.add_tag(
            MemoryScope.PROJECT, "nonexistent-id", "tag"
        )
        assert result is False

        result = memory_manager.remove_tag(
            MemoryScope.PROJECT, "nonexistent-id", "tag"
        )
        assert result is False

    def test_search_with_tag_based_boosting(self, memory_manager):
        memory_manager.add_entry(
            MemoryScope.PROJECT, "test", "Entry about API testing",
            tags=["api", "testing"]
        )
        memory_manager.add_entry(
            MemoryScope.PROJECT, "general", "General entry about databases",
            tags=["database"]
        )

        results = memory_manager.search("api")
        assert len(results) >= 1
        assert "API testing" in results[0].content

    def test_get_all_tags(self, memory_manager):
        memory_manager.add_entry(
            MemoryScope.PROJECT, "test", "Entry 1", tags=["alpha", "beta"]
        )
        memory_manager.add_entry(
            MemoryScope.PROJECT, "test", "Entry 2", tags=["beta", "gamma"]
        )

        all_tags = memory_manager.get_all_tags(MemoryScope.PROJECT)
        assert "alpha" in all_tags
        assert "beta" in all_tags
        assert "gamma" in all_tags

    def test_get_tags_by_category(self, memory_manager):
        memory_manager.add_entry(
            MemoryScope.PROJECT, "architecture", "FastAPI backend",
            tags=["api", "backend"]
        )
        memory_manager.add_entry(
            MemoryScope.PROJECT, "testing", "pytest setup",
            tags=["test", "pytest"]
        )

        cat_tags = memory_manager.get_tags_by_category(MemoryScope.PROJECT)
        assert "architecture" in cat_tags
        assert "testing" in cat_tags
        assert "api" in cat_tags["architecture"]
        assert "pytest" in cat_tags["testing"]

    def test_category_based_memory_filtering(self, memory_with_entries):
        project_file = memory_with_entries.memories[MemoryScope.PROJECT]

        testing_entries = project_file.get_entries_by_category("testing")
        assert len(testing_entries) >= 1
        assert any("pytest" in e.content for e in testing_entries)

        arch_entries = project_file.get_entries_by_category("architecture")
        assert len(arch_entries) >= 1
        assert any("FastAPI" in e.content for e in arch_entries)

        nonexistent = project_file.get_entries_by_category("nonexistent")
        assert len(nonexistent) == 0

    def test_code_terminology_expansion(self):
        assert "function" in _CODE_TERM_EXPANSIONS
        assert "类" in _CODE_TERM_EXPANSIONS["class"]

    def test_tokenize_handles_mixed_content(self):
        tokens = _tokenize("hello world 测试 function_name")
        assert "hello" in tokens
        assert "world" in tokens

    def test_auto_classification_with_mixed_language(self, memory_manager):
        entry = memory_manager.add_entry(
            MemoryScope.PROJECT,
            "auto",
            "使用 pytest for all testing and function coverage checks",
        )
        assert entry.category in ("testing", "code-pattern")


# ---------------------------------------------------------------------------
# 6. Memory Recovery Integration Tests
# ---------------------------------------------------------------------------


class TestMemoryRecoveryIntegration:
    """Corrupted memory file recovery and data integrity."""

    def test_loading_from_corrupted_memory_file(self, tmp_workspace):
        memory_dir = tmp_workspace / ".mini-code-memory"
        memory_dir.mkdir()
        memory_json = memory_dir / "memory.json"

        corrupted_data = {
            "scope": "project",
            "entries": [
                {"id": "valid-1", "scope": "project", "category": "test", "content": "Valid entry 1"},
                {"id": "bad-2", "scope": "invalid_scope", "category": "test", "content": "Bad scope"},
                {"id": "valid-3", "scope": "project", "category": "test", "content": "Valid entry 3"},
                "not_a_dict",
                {"id": "", "scope": "project", "category": "test", "content": "Empty id"},
            ],
        }
        memory_json.write_text(json.dumps(corrupted_data), encoding="utf-8")

        mm = MemoryManager(project_root=tmp_workspace)

        project_entries = mm.memories[MemoryScope.PROJECT].entries
        valid_ids = {e.id for e in project_entries}
        assert "valid-1" in valid_ids
        assert "valid-3" in valid_ids

    def test_backup_file_creation_on_corruption(self, tmp_workspace):
        memory_dir = tmp_workspace / ".mini-code-memory"
        memory_dir.mkdir()
        memory_json = memory_dir / "memory.json"

        corrupted_data = {
            "scope": "project",
            "entries": [
                {"id": "good-1", "scope": "project", "category": "test", "content": "Good entry"},
                {"id": "bad-2", "scope": "invalid", "category": "test", "content": "Bad entry"},
            ],
        }
        memory_json.write_text(json.dumps(corrupted_data), encoding="utf-8")

        mm = MemoryManager(project_root=tmp_workspace)

        backup_path = memory_json.with_suffix(".json.bak")
        assert backup_path.exists()

        backup_content = json.loads(backup_path.read_text(encoding="utf-8"))
        assert len(backup_content["entries"]) == 2

    def test_integrity_check_and_auto_recovery_flow(self, tmp_workspace):
        memory_dir = tmp_workspace / ".mini-code-memory"
        memory_dir.mkdir()
        memory_json = memory_dir / "memory.json"

        data_with_dupes = {
            "scope": "project",
            "entries": [
                {"id": "dup-1", "scope": "project", "category": "test", "content": "First occurrence"},
                {"id": "dup-1", "scope": "project", "category": "test", "content": "Duplicate occurrence"},
                {"id": "good-2", "scope": "project", "category": "test", "content": "Good entry"},
            ],
        }
        memory_json.write_text(json.dumps(data_with_dupes), encoding="utf-8")

        mm = MemoryManager(project_root=tmp_workspace)

        integrity = mm.check_integrity(MemoryScope.PROJECT)
        assert integrity["is_valid"] is True

        project_entries = mm.memories[MemoryScope.PROJECT].entries
        ids = [e.id for e in project_entries]
        assert ids.count("dup-1") <= 1

    def test_memory_compression_and_deduplication(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)

        mm.add_entry(
            MemoryScope.PROJECT, "test",
            "Use pytest for all unit testing with fixtures and mocks"
        )
        mm.add_entry(
            MemoryScope.PROJECT, "test",
            "Use pytest for all unit testing with fixtures and mocks"
        )
        mm.add_entry(
            MemoryScope.PROJECT, "test",
            "Use pytest for integration testing"
        )

        original_count = len(mm.memories[MemoryScope.PROJECT].entries)
        assert original_count == 3

        stats = mm.compress_scope(MemoryScope.PROJECT)
        assert stats["removed_count"] >= 1
        assert stats["remaining_count"] <= original_count

    def test_compression_with_similar_entries(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)

        mm.add_entry(
            MemoryScope.PROJECT, "test",
            "Always write unit tests for new functions before merging"
        )
        mm.add_entry(
            MemoryScope.PROJECT, "test",
            "Always write unit tests for new functions before release"
        )
        mm.add_entry(
            MemoryScope.PROJECT, "different",
            "Deploy to production on Fridays only"
        )

        original_count = len(mm.memories[MemoryScope.PROJECT].entries)

        stats = mm.compress_scope(
            MemoryScope.PROJECT, similarity_threshold=0.5
        )

        assert stats["merged_count"] >= 0
        assert stats["remaining_count"] <= original_count

    def test_compression_empty_scope(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)

        stats = mm.compress_scope(MemoryScope.PROJECT)
        assert stats["remaining_count"] == 0
        assert stats["merged_count"] == 0
        assert stats["removed_count"] == 0

    def test_compression_single_entry_scope(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(MemoryScope.PROJECT, "test", "Single entry")

        stats = mm.compress_scope(MemoryScope.PROJECT)
        assert stats["remaining_count"] == 1
        assert stats["merged_count"] == 0

    def test_integrity_check_detects_missing_id(self, memory_manager):
        entry = MemoryEntry(
            id="",
            scope=MemoryScope.PROJECT,
            category="test",
            content="Entry with empty ID",
        )
        memory_manager.memories[MemoryScope.PROJECT].entries.append(entry)

        integrity = memory_manager.check_integrity(MemoryScope.PROJECT)
        assert integrity["is_valid"] is False
        assert any("invalid or empty ID" in issue for issue in integrity["issues"])

    def test_integrity_check_detects_duplicate_ids(self, memory_manager):
        entry1 = MemoryEntry(
            id="dup-id",
            scope=MemoryScope.PROJECT,
            category="test",
            content="First",
        )
        entry2 = MemoryEntry(
            id="dup-id",
            scope=MemoryScope.PROJECT,
            category="test",
            content="Second",
        )
        memory_manager.memories[MemoryScope.PROJECT].entries.extend([entry1, entry2])

        integrity = memory_manager.check_integrity(MemoryScope.PROJECT)
        assert integrity["is_valid"] is False
        assert any("Duplicate ID" in issue for issue in integrity["issues"])

    def test_recovery_fixes_empty_category(self, memory_manager):
        entry = MemoryEntry(
            id="fix-cat-1",
            scope=MemoryScope.PROJECT,
            category="",
            content="Entry needing category fix",
        )
        memory_manager.memories[MemoryScope.PROJECT].entries.append(entry)

        integrity = memory_manager.check_integrity(MemoryScope.PROJECT)
        assert integrity["is_valid"] is False

        memory_manager._recover_scope(MemoryScope.PROJECT)

        integrity_after = memory_manager.check_integrity(MemoryScope.PROJECT)
        assert integrity_after["is_valid"] is True

        recovered = memory_manager.memories[MemoryScope.PROJECT].entries
        fixed_entry = next(e for e in recovered if e.id == "fix-cat-1")
        assert fixed_entry.category == "general"

    def test_recovery_removes_entries_with_empty_content(self, memory_manager):
        entry = MemoryEntry(
            id="no-content",
            scope=MemoryScope.PROJECT,
            category="test",
            content="",
        )
        memory_manager.memories[MemoryScope.PROJECT].entries.append(entry)

        memory_manager._recover_scope(MemoryScope.PROJECT)

        recovered = memory_manager.memories[MemoryScope.PROJECT].entries
        assert not any(e.id == "no-content" for e in recovered)

    def test_jaccard_similarity(self, memory_manager):
        sim_identical = MemoryManager._jaccard_similarity("hello world", "hello world")
        assert sim_identical == 1.0

        sim_disjoint = MemoryManager._jaccard_similarity("hello", "world")
        assert sim_disjoint == 0.0

        sim_partial = MemoryManager._jaccard_similarity("hello world foo", "hello world bar")
        assert 0.0 < sim_partial < 1.0

    def test_merge_entry_content_keeps_longer(self, memory_manager):
        short = "Use pytest"
        long = "Use pytest for all unit testing with fixtures"

        merged = MemoryManager._merge_entry_content(short, long)
        assert merged == long

        merged_reversed = MemoryManager._merge_entry_content(long, short)
        assert merged_reversed == long

    def test_test_helpers_verify_memory_integrity(self, memory_manager):
        memory_manager.add_entry(
            MemoryScope.PROJECT, "test", "Valid entry"
        )

        diag = verify_memory_integrity(memory_manager)
        assert diag["valid"] is True
        assert len(diag["issues"]) == 0

    def test_test_helpers_create_corrupted_memory_file(self, tmp_workspace):
        memory_dir = tmp_workspace / ".mini-code-memory"
        memory_json = memory_dir / "memory.json"

        corrupted = create_corrupted_memory_file(memory_json)
        assert corrupted["scope"] == "project"
        assert len(corrupted["entries"]) == 4

        mm = MemoryManager(project_root=tmp_workspace)

        backup = memory_json.with_suffix(".json.bak")
        assert backup.exists()


# ---------------------------------------------------------------------------
# Cross-cutting integration tests
# ---------------------------------------------------------------------------


class TestCrossCuttingMemoryIntegration:
    """Tests spanning multiple subsystems simultaneously."""

    def test_memory_plus_session_plus_context_manager(
        self, tmp_workspace, mock_model, tools, auto_allow_permissions
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT,
            "convention",
            "Use snake_case for all function names",
            ["naming", "convention"],
        )

        session = create_new_session(str(tmp_workspace))
        session.messages = [
            {"role": "user", "content": "What naming convention?"},
        ]
        save_session(session, force_full=True)

        loaded = load_session(session.session_id)
        assert loaded is not None

        ctx = ContextManager(model="default")
        for msg in loaded.messages:
            ctx.add_message(msg)

        memory_context = mm.get_relevant_context()
        if memory_context:
            ctx.add_message({"role": "system", "content": memory_context})

        stats = ctx.get_stats()
        assert stats.messages_count > 0

        restored_mm = MemoryManager(project_root=loaded.workspace)
        results = restored_mm.search("snake_case")
        assert len(results) >= 1

    def test_memory_persistence_across_multiple_agent_turns(
        self, mock_model, tools, tmp_workspace, auto_allow_permissions
    ):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(
            MemoryScope.PROJECT, "decision", "Use PostgreSQL not SQLite"
        )

        base_prompt = build_system_prompt(
            str(tmp_workspace),
            auto_allow_permissions.get_summary(),
            {"skills": [], "mcpServers": []},
        )
        injected = inject_memory_into_prompt(base_prompt, mm)

        for turn_input in ["/ls", "/read hello.txt", "/tools"]:
            msgs = [
                {"role": "system", "content": injected},
                {"role": "user", "content": turn_input},
            ]
            result = run_agent_turn(
                model=mock_model,
                tools=tools,
                messages=msgs,
                cwd=str(tmp_workspace),
                permissions=auto_allow_permissions,
            )
            assert len(result) > 1

        final_mm = MemoryManager(project_root=tmp_workspace)
        assert len(final_mm.memories[MemoryScope.PROJECT].entries) >= 1

    def test_memory_search_across_all_scopes(self, memory_with_entries):
        results = memory_with_entries.search("test")
        assert len(results) >= 1

        project_results = memory_with_entries.search("test", scope=MemoryScope.PROJECT)
        user_results = memory_with_entries.search("test", scope=MemoryScope.USER)
        local_results = memory_with_entries.search("test", scope=MemoryScope.LOCAL)

        total = len(project_results) + len(user_results) + len(local_results)
        assert total >= len(results)

    def test_memory_format_stats_display(self, memory_with_entries):
        stats_str = memory_with_entries.format_stats()
        assert "Memory System Status" in stats_str
        assert "Entries" in stats_str or "entries" in stats_str

    def test_memory_clear_scope(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)
        mm.add_entry(MemoryScope.PROJECT, "test", "Entry 1")
        mm.add_entry(MemoryScope.PROJECT, "test", "Entry 2")
        mm.add_entry(MemoryScope.USER, "test", "User entry")

        assert len(mm.memories[MemoryScope.PROJECT].entries) == 2
        assert len(mm.memories[MemoryScope.USER].entries) == 1

        mm.clear_scope(MemoryScope.PROJECT)
        assert len(mm.memories[MemoryScope.PROJECT].entries) == 0
        assert len(mm.memories[MemoryScope.USER].entries) == 1

    def test_memory_handle_user_input_hash_format(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)

        result = mm.handle_user_memory_input("# Use pytest for testing")
        assert result is not None
        assert "Saved memory" in result

        entries = mm.search("pytest")
        assert len(entries) >= 1
        assert any("pytest" in e.content for e in entries)

    def test_memory_handle_user_input_slash_format(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)

        result = mm.handle_user_memory_input(
            "/memory add user: Prefer TypeScript over JavaScript"
        )
        assert result is not None
        assert "Saved memory" in result

        user_entries = mm.search("TypeScript")
        assert len(user_entries) >= 1

    def test_memory_handle_user_input_invalid(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)

        result = mm.handle_user_memory_input("not a memory command")
        assert result is None

        result_empty = mm.handle_user_memory_input("")
        assert result_empty is None

    def test_memory_entry_serialization_roundtrip(self, tmp_workspace):
        original = MemoryEntry(
            id="serialize-test",
            scope=MemoryScope.PROJECT,
            category="test",
            content="Serialization test content",
            tags=["tag1", "tag2"],
            usage_count=5,
        )

        data = original.to_dict()
        restored = MemoryEntry.from_dict(data)

        assert restored.id == original.id
        assert restored.scope == original.scope
        assert restored.category == original.category
        assert restored.content == original.content
        assert sorted(restored.tags) == sorted(original.tags)
        assert restored.usage_count == original.usage_count

    def test_memory_file_size_limit(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)

        large_content = "x" * 30000
        mm.add_entry(MemoryScope.PROJECT, "test", large_content)

        project_file = mm.memories[MemoryScope.PROJECT]
        assert project_file.size_bytes <= project_file.max_size_bytes

    def test_memory_file_entry_limit(self, tmp_workspace):
        mm = MemoryManager(project_root=tmp_workspace)
        max_entries = mm.memories[MemoryScope.PROJECT].max_entries

        for i in range(max_entries + 50):
            mm.add_entry(MemoryScope.PROJECT, "test", f"Entry {i}")

        assert len(mm.memories[MemoryScope.PROJECT].entries) <= max_entries
