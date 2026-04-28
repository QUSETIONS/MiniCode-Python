from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from minicode.agent_loop import run_agent_turn
from minicode.memory import MemoryManager
from minicode.permissions import PermissionManager
from minicode.prompt import build_system_prompt
from minicode.tooling import ToolRegistry
from minicode.tools import create_default_tool_registry
from minicode.tui.event_flow import _handle_event
from minicode.tui.input_handler import _handle_input
from minicode.tui.input_parser import KeyEvent
from minicode.tui.state import ScreenState, TtyAppArgs
from minicode.types import AgentStep


REPO_ROOT = Path(__file__).resolve().parent.parent


def _release_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT)
            + os.pathsep
            + env.get("PYTHONPATH", ""),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "MINI_CODE_MODEL": "gpt-4o",
            "MINI_CODE_MODEL_MODE": "mock",
            "MINI_CODE_TOOL_PROFILE": "core",
            "MINI_CODE_SHOW_GUIDE": "0",
            "OPENAI_API_KEY": "test-openai-key",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "OPENROUTER_API_KEY": "",
            "CUSTOM_API_KEY": "",
            "CUSTOM_API_BASE_URL": "",
        }
    )
    return env


def test_release_cli_valid_config_runs_as_black_box(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    completed = subprocess.run(
        [sys.executable, "-m", "minicode.main", "valid-config"],
        cwd=workspace,
        env=_release_env(tmp_path),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Configuration Diagnostics" in completed.stdout
    assert "Status: OK" in completed.stdout
    assert "Provider: openai" in completed.stdout
    assert "Tool Profile: core" in completed.stdout
    assert "UnicodeEncodeError" not in completed.stderr


def test_release_non_tty_main_handles_memory_and_local_commands(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    completed = subprocess.run(
        [sys.executable, "-m", "minicode.main"],
        cwd=workspace,
        env=_release_env(tmp_path),
        input="# Prefer pytest before release\n/memory\n/tools\n/exit\n",
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Saved memory (project): Prefer pytest before release" in completed.stdout
    assert "Memory System Status" in completed.stdout
    assert "read_file:" in completed.stdout
    assert "base64_encode:" not in completed.stdout

    memory_file = workspace / ".mini-code-memory" / "MEMORY.md"
    assert memory_file.exists()
    assert "Prefer pytest before release" in memory_file.read_text(encoding="utf-8")


class ReadFileReleaseModel:
    def __init__(self) -> None:
        self.calls = 0

    def next(self, messages, on_stream_chunk=None):
        self.calls += 1
        if self.calls == 1:
            return AgentStep(
                type="tool_calls",
                calls=[
                    {
                        "id": "release-read",
                        "toolName": "read_file",
                        "input": {"path": "README.md"},
                    }
                ],
            )
        tool_result = next(
            message for message in reversed(messages) if message["role"] == "tool_result"
        )
        return AgentStep(
            type="assistant",
            content=f"release final saw: {tool_result['content'][:80]}",
        )


def test_release_agent_loop_executes_real_tool_chain(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Release Fixture\n", encoding="utf-8")

    tools = create_default_tool_registry(str(workspace), runtime={"toolProfile": "core"})
    permissions = PermissionManager(
        str(workspace),
        prompt=lambda _request: {"decision": "allow_once"},
    )

    messages = run_agent_turn(
        model=ReadFileReleaseModel(),
        tools=tools,
        messages=[
            {"role": "system", "content": "release integration system"},
            {"role": "user", "content": "read the release fixture"},
        ],
        cwd=str(workspace),
        permissions=permissions,
        max_steps=5,
    )

    assert any(message["role"] == "assistant_tool_call" for message in messages)
    assert any(
        message["role"] == "tool_result" and "# Release Fixture" in message["content"]
        for message in messages
    )
    assert messages[-1]["role"] == "assistant"
    assert "Release Fixtur" in messages[-1]["content"]


class PromptCapturingModel:
    def __init__(self) -> None:
        self.system_prompt = ""

    def next(self, messages, on_stream_chunk=None):
        self.system_prompt = messages[0]["content"]
        return AgentStep(type="assistant", content="ok")


def test_release_memory_is_injected_into_next_agent_turn(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = MemoryManager(workspace)
    assert memory.handle_user_memory_input("# Prefer pytest before release")

    model = PromptCapturingModel()
    messages = [
        {
            "role": "system",
            "content": build_system_prompt(
                str(workspace),
                [],
                {
                    "skills": [],
                    "mcpServers": [],
                    "memory_context": memory.get_relevant_context(query="release tests"),
                },
            ),
        },
        {"role": "user", "content": "How should I verify release tests?"},
    ]

    run_agent_turn(
        model=model,
        tools=ToolRegistry([]),
        messages=messages,
        cwd=str(workspace),
        max_steps=1,
    )

    assert "Project Memory & Context" in model.system_prompt
    assert "Prefer pytest before release" in model.system_prompt


def test_release_tty_return_routes_memory_without_agent_turn(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = MemoryManager(workspace)
    state = ScreenState(input="# Prefer pytest before release", cursor_offset=30)
    args = TtyAppArgs(
        runtime=None,
        tools=ToolRegistry([]),
        model=None,
        messages=[{"role": "system", "content": "sys"}],
        cwd=str(workspace),
        permissions=PermissionManager(str(workspace)),
        memory_manager=memory,
    )
    renders: list[bool] = []

    _handle_event(
        args,
        state,
        KeyEvent(name="return", ctrl=False, meta=False),
        lambda: renders.append(True),
        threading.Event(),
        {},
        _handle_input,
    )

    assert renders
    assert state.is_busy is False
    assert len(state.transcript) == 2
    assert state.transcript[0].kind == "user"
    assert state.transcript[1].kind == "assistant"
    assert "Saved memory" in state.transcript[1].body
    assert any("pytest" in entry.content for entry in memory.search("pytest"))
