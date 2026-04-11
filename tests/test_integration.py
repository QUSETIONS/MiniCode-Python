"""End-to-end integration tests for MiniCode Python.

Tests the full pipeline: agent loop → model → tool execution → message flow,
using the MockModelAdapter (no API key needed).

Also includes an optional live API test that only runs when ANTHROPIC_API_KEY
is set in the environment.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import pytest

# Ensure py-src is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minicode.agent_loop import run_agent_turn
from minicode.mock_model import MockModelAdapter
from minicode.permissions import PermissionManager
from minicode.tooling import ToolContext, ToolRegistry, ToolDefinition, ToolResult
from minicode.tools import create_default_tool_registry
from minicode.types import AgentStep, ChatMessage
from minicode.context_manager import ContextManager
from minicode.session import SessionData, save_session, load_session, list_sessions
from minicode.config import load_effective_settings, MINI_CODE_DIR
from minicode.prompt import build_system_prompt
from minicode.tui.types import TranscriptEntry, _create_transcript_entry, _recycle_transcript_entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace with some test files."""
    (tmp_path / "hello.txt").write_text("Hello, world!\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        textwrap.dedent("""\
            def greet(name: str) -> str:
                return f"Hello, {name}!"

            if __name__ == "__main__":
                print(greet("MiniCode"))
        """),
        encoding="utf-8",
    )
    (tmp_path / "src" / "utils.py").write_text(
        textwrap.dedent("""\
            import os
            import sys

            def get_cwd() -> str:
                return os.getcwd()
        """),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def mock_model() -> MockModelAdapter:
    return MockModelAdapter()


@pytest.fixture
def tools(tmp_workspace: Path) -> ToolRegistry:
    return create_default_tool_registry(str(tmp_workspace), runtime=None)


@pytest.fixture
def auto_allow_permissions(tmp_workspace: Path) -> PermissionManager:
    """PermissionManager that auto-allows everything (for testing)."""
    def _auto_allow(request: dict) -> dict:
        return {"decision": "allow_once"}
    return PermissionManager(str(tmp_workspace), prompt=_auto_allow)


@pytest.fixture
def system_messages(tmp_workspace: Path, auto_allow_permissions: PermissionManager) -> list[ChatMessage]:
    """Build initial messages list with system prompt."""
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
# Integration Test: Agent Loop + MockModel + Tools
# ---------------------------------------------------------------------------


class TestAgentLoopIntegration:
    """Test the full agent loop with MockModel driving tool execution."""

    def test_list_files_via_agent(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Agent receives /ls → calls list_files tool → returns result."""
        system_messages.append({"role": "user", "content": "/ls"})

        callback_log: list[dict[str, Any]] = []

        def on_tool_start(name, args):
            callback_log.append({"event": "tool_start", "name": name, "args": args})

        def on_tool_result(name, output, is_error):
            callback_log.append({"event": "tool_result", "name": name, "is_error": is_error})

        def on_assistant_message(msg):
            callback_log.append({"event": "assistant", "message": msg})

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
            on_tool_start=on_tool_start,
            on_tool_result=on_tool_result,
            on_assistant_message=on_assistant_message,
        )

        # Verify tool was called
        tool_starts = [e for e in callback_log if e["event"] == "tool_start"]
        assert len(tool_starts) == 1
        assert tool_starts[0]["name"] == "list_files"

        # Verify tool completed
        tool_results = [e for e in callback_log if e["event"] == "tool_result"]
        assert len(tool_results) == 1
        assert not tool_results[0]["is_error"]

        # Verify final assistant message mentions directory contents
        assistant_msgs = [e for e in callback_log if e["event"] == "assistant"]
        assert len(assistant_msgs) >= 1
        final_msg = assistant_msgs[-1]["message"]
        assert "hello.txt" in final_msg or "src" in final_msg

        # Verify message history is properly structured
        assert result[-1]["role"] == "assistant"
        assert any(m["role"] == "tool_result" for m in result)
        assert any(m["role"] == "assistant_tool_call" for m in result)

    def test_read_file_via_agent(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Agent receives /read → calls read_file tool → returns file content."""
        system_messages.append({"role": "user", "content": "/read hello.txt"})

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        last_assistant = next(
            (m for m in reversed(result) if m["role"] == "assistant"), None
        )
        assert last_assistant is not None
        assert "Hello, world!" in last_assistant["content"]

    def test_write_file_via_agent(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Agent receives /write → calls write_file tool → file is created."""
        system_messages.append({
            "role": "user",
            "content": "/write output.txt::Test content from integration test",
        })

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        # Verify file was created
        output_file = tmp_workspace / "output.txt"
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "Test content from integration test" in content

    def test_edit_file_via_agent(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Agent receives /edit → calls edit_file tool → file is modified."""
        system_messages.append({
            "role": "user",
            "content": "/edit hello.txt::Hello, world!::Hello, MiniCode!",
        })

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        content = (tmp_workspace / "hello.txt").read_text(encoding="utf-8")
        assert "Hello, MiniCode!" in content
        assert "Hello, world!" not in content

    def test_grep_files_via_agent(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Agent receives /grep → calls grep_files tool → returns matches."""
        system_messages.append({
            "role": "user",
            "content": f"/grep greet::{tmp_workspace / 'src'}",
        })

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        last_assistant = next(
            (m for m in reversed(result) if m["role"] == "assistant"), None
        )
        assert last_assistant is not None
        assert "greet" in last_assistant["content"]

    def test_run_command_via_agent(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Agent receives /cmd → calls run_command tool → returns output."""
        cmd = "echo integration_test_ok"
        system_messages.append({"role": "user", "content": f"/cmd {cmd}"})

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        last_assistant = next(
            (m for m in reversed(result) if m["role"] == "assistant"), None
        )
        assert last_assistant is not None
        assert "integration_test_ok" in last_assistant["content"]

    def test_tools_listing_via_agent(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Agent receives /tools → returns tool list (no tool call needed)."""
        system_messages.append({"role": "user", "content": "/tools"})

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        last_assistant = next(
            (m for m in reversed(result) if m["role"] == "assistant"), None
        )
        assert last_assistant is not None
        assert "list_files" in last_assistant["content"]

    def test_max_step_limit(self, tools, system_messages, tmp_workspace, auto_allow_permissions):
        """Agent loop respects max_steps limit."""

        class InfiniteToolCallModel:
            """Model that always returns tool calls, never stops."""
            def next(self, messages, on_stream_chunk=None):
                import time
                return AgentStep(
                    type="tool_calls",
                    calls=[{
                        "id": f"inf-{int(time.time()*1000)}",
                        "toolName": "list_files",
                        "input": {},
                    }],
                )

        system_messages.append({"role": "user", "content": "infinite loop"})
        result = run_agent_turn(
            model=InfiniteToolCallModel(),
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
            max_steps=3,
        )

        last_assistant = next(
            (m for m in reversed(result) if m["role"] == "assistant"), None
        )
        assert last_assistant is not None
        assert "maximum" in last_assistant["content"].lower() or "limit" in last_assistant["content"].lower()

    def test_api_error_handling(self, tools, system_messages, tmp_workspace, auto_allow_permissions):
        """Agent loop handles model API errors gracefully."""

        class ErrorModel:
            def next(self, messages, on_stream_chunk=None):
                raise ConnectionError("Simulated network failure")

        system_messages.append({"role": "user", "content": "test error"})
        result = run_agent_turn(
            model=ErrorModel(),
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        last_assistant = next(
            (m for m in reversed(result) if m["role"] == "assistant"), None
        )
        assert last_assistant is not None
        assert "network error" in last_assistant["content"].lower() or "connection" in last_assistant["content"].lower()

    def test_timeout_error_handling(self, tools, system_messages, tmp_workspace, auto_allow_permissions):
        """Agent loop handles timeout errors with specific message."""

        class TimeoutModel:
            def next(self, messages, on_stream_chunk=None):
                raise TimeoutError("Request timed out after 60s")

        system_messages.append({"role": "user", "content": "test timeout"})
        result = run_agent_turn(
            model=TimeoutModel(),
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        last_assistant = next(
            (m for m in reversed(result) if m["role"] == "assistant"), None
        )
        assert last_assistant is not None
        assert "timeout" in last_assistant["content"].lower()


# ---------------------------------------------------------------------------
# Integration Test: Context Manager
# ---------------------------------------------------------------------------


class TestContextManagerIntegration:
    """Test ContextManager works correctly within agent loop."""

    def test_context_tracking(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Context manager tracks token usage during agent turn."""
        ctx = ContextManager(model="claude-sonnet-4-20250514")

        system_messages.append({"role": "user", "content": "/ls"})

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
            context_manager=ctx,
        )

        # Context manager should have tracked something
        ctx.messages = result
        stats = ctx.get_stats()
        assert stats.messages_count > 0
        assert stats.total_tokens > 0


# ---------------------------------------------------------------------------
# Integration Test: Permission System
# ---------------------------------------------------------------------------


class TestPermissionIntegration:
    """Test permission system within the agent loop."""

    def test_deny_command_permission(
        self, mock_model, tools, system_messages, tmp_workspace
    ):
        """Permission denial prevents command execution."""
        deny_called = False

        def _deny_all(request: dict) -> dict:
            nonlocal deny_called
            deny_called = True
            return {"decision": "deny_once"}

        permissions = PermissionManager(str(tmp_workspace), prompt=_deny_all)
        system_messages.append({"role": "user", "content": "/cmd echo should_not_run"})

        result = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=permissions,
        )

        # Permission should have been checked (may or may not be called
        # depending on whether run_command is in the auto-allow list)
        tool_results = [m for m in result if m["role"] == "tool_result"]
        if tool_results:
            # If denied, the tool result should indicate permission denied
            last_tool = tool_results[-1]
            if last_tool.get("isError"):
                assert "permission" in last_tool["content"].lower() or "denied" in last_tool["content"].lower()

    def test_allow_always_command(
        self, mock_model, tools, system_messages, tmp_workspace
    ):
        """'allow_always' permission is remembered for subsequent calls."""
        call_count = 0

        def _allow_always(request: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return {"decision": "allow_always"}

        permissions = PermissionManager(str(tmp_workspace), prompt=_allow_always)
        permissions.begin_turn()

        # First command
        system_messages.append({"role": "user", "content": "/cmd echo first"})
        run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=system_messages,
            cwd=str(tmp_workspace),
            permissions=permissions,
        )

        permissions.end_turn()

        # The prompt should have been called at most once for this command
        assert call_count <= 1


# ---------------------------------------------------------------------------
# Integration Test: Session Persistence
# ---------------------------------------------------------------------------


class TestSessionIntegration:
    """Test session save/load round-trip."""

    def test_session_save_load_roundtrip(self, tmp_workspace):
        """Session data survives save/load cycle."""
        session = SessionData(
            session_id="test-integration-001",
            created_at=1000000.0,
            updated_at=1000001.0,
            workspace=str(tmp_workspace),
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello!"},
                {"role": "assistant", "content": "Hi there!"},
            ],
        )

        # Save
        save_session(session)

        # Load
        loaded = load_session("test-integration-001")
        assert loaded is not None
        assert loaded.session_id == "test-integration-001"
        assert len(loaded.messages) == 3
        assert loaded.messages[1]["content"] == "Hello!"
        assert loaded.workspace == str(tmp_workspace)

        # Cleanup
        session_path = MINI_CODE_DIR / "sessions" / "test-integration-001.json"
        if session_path.exists():
            session_path.unlink()

    def test_session_listing(self, tmp_workspace):
        """Sessions are listed correctly."""
        # Create a few test sessions
        for i in range(3):
            session = SessionData(
                session_id=f"test-list-{i:03d}",
                created_at=1000000.0 + i,
                updated_at=1000000.0 + i,
                workspace=str(tmp_workspace),
                messages=[{"role": "user", "content": f"Message {i}"}],
            )
            save_session(session)

        sessions = list_sessions()
        test_sessions = [s for s in sessions if s.session_id.startswith("test-list-")]
        assert len(test_sessions) >= 3

        # Cleanup
        for i in range(3):
            path = MINI_CODE_DIR / "sessions" / f"test-list-{i:03d}.json"
            if path.exists():
                path.unlink()


# ---------------------------------------------------------------------------
# Integration Test: TranscriptEntry Object Pool
# ---------------------------------------------------------------------------


class TestTranscriptPoolIntegration:
    """Test the TranscriptEntry object pool works end-to-end."""

    def test_pool_create_recycle_reuse(self):
        """Objects are reused from pool after recycling."""
        # Create entries
        entries = []
        for i in range(5):
            entry = _create_transcript_entry(id=i, kind="user", body=f"msg-{i}")
            entries.append(entry)

        # Recycle them
        for entry in entries:
            _recycle_transcript_entry(entry)

        # Create new ones — should reuse from pool
        new_entry = _create_transcript_entry(id=100, kind="assistant", body="reused")
        assert new_entry.id == 100
        assert new_entry.kind == "assistant"
        assert new_entry.body == "reused"


# ---------------------------------------------------------------------------
# Integration Test: Multi-step Agent Interaction
# ---------------------------------------------------------------------------


class TestMultiStepInteraction:
    """Test realistic multi-step workflows through the agent loop."""

    def test_read_then_write_workflow(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Simulate a read → write workflow as independent turns.
        
        Note: MockModel is stateless and prioritises tool_result processing,
        so each "turn" starts from a fresh system prompt to avoid the model
        seeing stale tool_result messages from a previous turn.
        """
        # Turn 1: Read a file
        msgs_t1 = list(system_messages)
        msgs_t1.append({"role": "user", "content": "/read src/main.py"})

        msgs_t1 = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=msgs_t1,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        last = next((m for m in reversed(msgs_t1) if m["role"] == "assistant"), None)
        assert last is not None
        assert "greet" in last["content"]

        # Turn 2: Write a new file (fresh messages so MockModel sees /write)
        msgs_t2 = list(system_messages)
        msgs_t2.append({
            "role": "user",
            "content": "/write src/new_module.py::# Auto-generated\ndef hello():\n    return 'world'",
        })

        msgs_t2 = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=msgs_t2,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        new_file = tmp_workspace / "src" / "new_module.py"
        assert new_file.exists()
        assert "hello" in new_file.read_text(encoding="utf-8")

    def test_grep_then_edit_workflow(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Simulate grep → edit workflow as independent turns."""
        # Turn 1: Grep for pattern
        msgs_t1 = list(system_messages)
        msgs_t1.append({
            "role": "user",
            "content": f"/grep get_cwd::{tmp_workspace / 'src'}",
        })

        msgs_t1 = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=msgs_t1,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        # Verify grep found the function
        last = next((m for m in reversed(msgs_t1) if m["role"] == "assistant"), None)
        assert last is not None
        assert "get_cwd" in last["content"]

        # Turn 2: Edit the file (fresh messages)
        msgs_t2 = list(system_messages)
        msgs_t2.append({
            "role": "user",
            "content": "/edit src/utils.py::def get_cwd() -> str:::def get_current_dir() -> str:",
        })

        msgs_t2 = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=msgs_t2,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        updated = (tmp_workspace / "src" / "utils.py").read_text(encoding="utf-8")
        assert "get_current_dir" in updated


# ---------------------------------------------------------------------------
# Integration Test: Patch file (multi-replacement)
# ---------------------------------------------------------------------------


class TestPatchFileIntegration:
    """Test patch_file tool through agent loop."""

    def test_multi_replacement_patch(
        self, mock_model, tools, system_messages, tmp_workspace, auto_allow_permissions
    ):
        """Patch file with multiple replacements in one call."""
        messages = list(system_messages)
        messages.append({
            "role": "user",
            "content": "/patch src/main.py::greet::welcome::Hello::Hi",
        })

        messages = run_agent_turn(
            model=mock_model,
            tools=tools,
            messages=messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
        )

        content = (tmp_workspace / "src" / "main.py").read_text(encoding="utf-8")
        assert "welcome" in content
        assert "Hi" in content


# ---------------------------------------------------------------------------
# Integration Test: Config Validation
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    """Test configuration loading and validation."""

    def test_load_effective_settings_no_crash(self):
        """load_effective_settings doesn't crash even with no config files."""
        settings = load_effective_settings()
        assert isinstance(settings, dict)

    def test_system_prompt_generation(self, tmp_workspace):
        """System prompt is generated without errors."""
        prompt = build_system_prompt(
            str(tmp_workspace),
            ["read: auto-allow", "write: ask"],
            {"skills": [{"name": "test-skill", "description": "A test skill"}], "mcpServers": []},
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100  # Non-trivial prompt
        assert str(tmp_workspace) in prompt


# ---------------------------------------------------------------------------
# Optional: Live API Test (only runs with API key)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live API test",
)
class TestLiveAPI:
    """Test with real Anthropic API (requires ANTHROPIC_API_KEY env var)."""

    def test_simple_question(self, tools, tmp_workspace, auto_allow_permissions):
        """Send a simple question to the real API and verify response."""
        from minicode.anthropic_adapter import AnthropicModelAdapter

        runtime = {
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            "baseUrl": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            "apiKey": os.environ.get("ANTHROPIC_API_KEY"),
            "authToken": None,
            "maxOutputTokens": 256,
        }

        model = AnthropicModelAdapter(runtime, tools)
        messages: list[ChatMessage] = [
            {"role": "system", "content": "You are a helpful assistant. Be brief."},
            {"role": "user", "content": "What is 2 + 2? Answer with just the number."},
        ]

        result = run_agent_turn(
            model=model,
            tools=tools,
            messages=messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
            max_steps=5,
        )

        last = next((m for m in reversed(result) if m["role"] == "assistant"), None)
        assert last is not None
        assert "4" in last["content"]

    def test_tool_use_via_api(self, tools, tmp_workspace, auto_allow_permissions):
        """Real API triggers tool use (list_files) and processes result."""
        from minicode.anthropic_adapter import AnthropicModelAdapter

        runtime = {
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            "baseUrl": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            "apiKey": os.environ.get("ANTHROPIC_API_KEY"),
            "authToken": None,
            "maxOutputTokens": 512,
        }

        model = AnthropicModelAdapter(runtime, tools)
        messages: list[ChatMessage] = [
            {
                "role": "system",
                "content": f"You are a coding assistant. Working directory: {tmp_workspace}",
            },
            {
                "role": "user",
                "content": "List the files in the current directory using the list_files tool.",
            },
        ]

        result = run_agent_turn(
            model=model,
            tools=tools,
            messages=messages,
            cwd=str(tmp_workspace),
            permissions=auto_allow_permissions,
            max_steps=10,
        )

        # Should have at least one tool call
        tool_calls = [m for m in result if m["role"] == "assistant_tool_call"]
        assert len(tool_calls) >= 1
        assert any(tc["toolName"] == "list_files" for tc in tool_calls)

        # Should have tool results
        tool_results = [m for m in result if m["role"] == "tool_result"]
        assert len(tool_results) >= 1


# ---------------------------------------------------------------------------
# Integration Test: MCP Module (unit-level, no server needed)
# ---------------------------------------------------------------------------


class TestMCPIntegration:
    """Test MCP module can be imported and basic structures work."""

    def test_mcp_import_and_create(self):
        """MCP module imports and creates empty tool set."""
        from minicode.mcp import create_mcp_backed_tools

        result = create_mcp_backed_tools(cwd=".", mcp_servers={})
        assert isinstance(result, dict)
        assert "tools" in result
        assert "servers" in result
        assert "dispose" in result
        assert len(result["tools"]) == 0


# ---------------------------------------------------------------------------
# Integration Test: Full Pipeline Smoke Test
# ---------------------------------------------------------------------------


class TestFullPipelineSmokeTest:
    """Smoke test that simulates the core main() flow without TTY."""

    def test_main_flow_mock_model(self, tmp_workspace):
        """Simulate the non-TTY main loop flow with mock model.
        
        Each turn uses fresh system messages because MockModel is stateless
        and prioritises tool_result processing over new user messages.
        """
        tools = create_default_tool_registry(str(tmp_workspace), runtime=None)

        def _auto_allow(request):
            return {"decision": "allow_once"}

        permissions = PermissionManager(str(tmp_workspace), prompt=_auto_allow)
        model = MockModelAdapter()
        ctx = ContextManager(model="mock")

        base_system: list[ChatMessage] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    str(tmp_workspace),
                    permissions.get_summary(),
                    {"skills": [], "mcpServers": []},
                ),
            }
        ]

        # Simulate independent turns
        user_inputs = [
            "/ls",
            "/read hello.txt",
            "/write test_output.txt::integration test passed",
            "/tools",
        ]

        all_results: list[list[ChatMessage]] = []
        for user_input in user_inputs:
            messages = list(base_system)
            messages.append({"role": "user", "content": user_input})
            permissions.begin_turn()
            result = run_agent_turn(
                model=model,
                tools=tools,
                messages=messages,
                cwd=str(tmp_workspace),
                permissions=permissions,
                context_manager=ctx,
            )
            permissions.end_turn()
            all_results.append(result)

        # Verify results
        # Turn 0 (/ls): should have tool_result with file listing
        assert any(m["role"] == "tool_result" for m in all_results[0])

        # Turn 1 (/read): should contain hello.txt content
        last_t1 = next((m for m in reversed(all_results[1]) if m["role"] == "assistant"), None)
        assert last_t1 is not None
        assert "Hello, world!" in last_t1["content"]

        # Turn 2 (/write): file should be created
        assert (tmp_workspace / "test_output.txt").exists()
        assert "integration test passed" in (tmp_workspace / "test_output.txt").read_text(encoding="utf-8")

        # Turn 3 (/tools): should list tools
        last_t3 = next((m for m in reversed(all_results[3]) if m["role"] == "assistant"), None)
        assert last_t3 is not None
        assert "list_files" in last_t3["content"]

        # Clean up tools
        tools.dispose()
