from __future__ import annotations

import json
from pathlib import Path

import pytest

from minicode.tooling import ToolRegistry
from minicode.types import AgentStep, ChatMessage, ModelAdapter


class _DummyPermissions:
    def __init__(self, cwd: str, prompt=None) -> None:
        self.cwd = cwd
        self.prompt = prompt

    def get_summary(self) -> list[str]:
        return ["workspace writes allowed"]


class _DummyMemoryManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def get_relevant_context(self) -> dict[str, str]:
        return {}


class _ProviderUnavailableModel(ModelAdapter):
    model_id = "deepseek-v4-pro[1m]"

    def next(
        self,
        messages: list[ChatMessage],
        on_stream_chunk=None,
        store=None,
    ) -> AgentStep:
        raise RuntimeError(
            "No available channel for model deepseek-v4-pro[1m] under group cc"
        )


def test_run_headless_forwards_runtime_to_agent_turn(monkeypatch, tmp_path: Path) -> None:
    import minicode.headless

    runtime = {
        "model": "deepseek-v4-pro[1m]",
        "baseUrl": "https://openai-proxy.example/v1",
        "authToken": "test-token",
    }
    captured: dict[str, object] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "minicode.config.load_runtime_config",
        lambda cwd: runtime,
    )
    monkeypatch.setattr(
        "minicode.tools.create_default_tool_registry",
        lambda cwd, runtime=None: ToolRegistry([]),
    )
    monkeypatch.setattr("minicode.permissions.PermissionManager", _DummyPermissions)
    monkeypatch.setattr("minicode.memory.MemoryManager", _DummyMemoryManager)
    monkeypatch.setattr(
        "minicode.prompt.build_system_prompt",
        lambda cwd, permissions, context: "sys",
    )
    monkeypatch.setattr(
        "minicode.model_registry.create_model_adapter",
        lambda model, tools, runtime=None: object(),
    )

    def _fake_run_agent_turn(**kwargs):
        captured["runtime"] = kwargs["runtime"]
        captured["memory_manager"] = kwargs["memory_manager"]
        return [{"role": "assistant", "content": "ok"}]

    monkeypatch.setattr("minicode.agent_loop.run_agent_turn", _fake_run_agent_turn)

    response = minicode.headless.run_headless("Reply with exactly OK.")

    assert response == "ok"
    assert captured["runtime"] is runtime
    assert isinstance(captured["memory_manager"], _DummyMemoryManager)
    assert captured["memory_manager"].project_root == tmp_path


def test_run_headless_provider_failure_uses_runtime_channel_details(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import minicode.headless

    runtime = {
        "model": "deepseek-v4-pro[1m]",
        "baseUrl": "https://openai-proxy.example/v1",
        "authToken": "test-token",
    }

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MINI_CODE_MODEL_FALLBACKS", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL_FALLBACKS", raising=False)
    monkeypatch.delenv("OPENAI_MODEL_FALLBACKS", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_FALLBACKS", raising=False)
    monkeypatch.setattr(
        "minicode.config.load_runtime_config",
        lambda cwd: runtime,
    )
    monkeypatch.setattr(
        "minicode.tools.create_default_tool_registry",
        lambda cwd, runtime=None: ToolRegistry([]),
    )
    monkeypatch.setattr("minicode.permissions.PermissionManager", _DummyPermissions)
    monkeypatch.setattr("minicode.memory.MemoryManager", _DummyMemoryManager)
    monkeypatch.setattr(
        "minicode.prompt.build_system_prompt",
        lambda cwd, permissions, context: "sys",
    )
    monkeypatch.setattr(
        "minicode.model_registry.create_model_adapter",
        lambda model, tools, runtime=None: _ProviderUnavailableModel(),
    )

    response = minicode.headless.run_headless("Reply with exactly OK.")

    assert "Provider availability failure:" in response
    # Channel and fallback details vary by runtime env; verify the response
    # contains structural diagnostic pieces (model name + guidance).
    assert "deepseek-v4-pro" in response
    assert "fallback" in response.lower()


def test_headless_response_exit_code_marks_terminal_failures() -> None:
    from minicode.headless import _headless_response_exit_code

    assert _headless_response_exit_code("OK") == 0
    assert _headless_response_exit_code("Model API error (RuntimeError): error code: 1010") == 1
    assert _headless_response_exit_code("Provider availability failure: no channel") == 1
    assert _headless_response_exit_code("Error: empty prompt") == 1


def test_headless_main_returns_nonzero_for_provider_failure(monkeypatch, capsys) -> None:
    import minicode.headless

    monkeypatch.setattr(
        minicode.headless,
        "run_headless",
        lambda prompt, allow_edits=False: "Model API error (RuntimeError): error code: 1010",
    )

    exit_code = minicode.headless.main(["Reply with exactly OK."])

    assert exit_code == 1
    assert "error code: 1010" in capsys.readouterr().out


def test_headless_main_returns_zero_for_success(monkeypatch, capsys) -> None:
    import minicode.headless

    monkeypatch.setattr(
        minicode.headless,
        "run_headless",
        lambda prompt, allow_edits=False: "OK",
    )

    exit_code = minicode.headless.main(["Reply with exactly OK."])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "OK"


def test_headless_main_help_does_not_load_config(monkeypatch, capsys) -> None:
    import minicode.headless

    monkeypatch.setattr(
        minicode.headless,
        "run_headless",
        lambda *args, **kwargs: pytest.fail("--help must not run headless"),
    )

    with pytest.raises(SystemExit) as raised:
        minicode.headless.main(["--help"])

    assert raised.value.code == 0
    assert "usage: minicode-headless" in capsys.readouterr().out


def test_run_headless_writes_messages_trace_when_requested(monkeypatch, tmp_path: Path) -> None:
    import minicode.headless

    runtime = {
        "model": "deepseek-v4-pro[1m]",
        "baseUrl": "https://openai-proxy.example/v1",
        "authToken": "test-token",
    }
    trace_path = tmp_path / "artifacts" / "messages.json"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINI_CODE_HEADLESS_MESSAGES_OUT", str(trace_path))
    monkeypatch.setattr(
        "minicode.config.load_runtime_config",
        lambda cwd: runtime,
    )
    monkeypatch.setattr(
        "minicode.tools.create_default_tool_registry",
        lambda cwd, runtime=None: ToolRegistry([]),
    )
    monkeypatch.setattr("minicode.permissions.PermissionManager", _DummyPermissions)
    monkeypatch.setattr("minicode.memory.MemoryManager", _DummyMemoryManager)
    monkeypatch.setattr(
        "minicode.prompt.build_system_prompt",
        lambda cwd, permissions, context: "sys",
    )
    monkeypatch.setattr(
        "minicode.model_registry.create_model_adapter",
        lambda model, tools, runtime=None: object(),
    )
    monkeypatch.setattr(
        "minicode.agent_loop.run_agent_turn",
        lambda **kwargs: [
            {"role": "assistant", "content": "traceable"},
            {"role": "tool", "content": "python -m unittest"},
        ],
    )

    response = minicode.headless.run_headless("Run the visible tests.")

    assert response == "traceable"
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload["cwd"] == str(tmp_path)
    assert payload["prompt"] == "Run the visible tests."
    assert payload["model"] == "deepseek-v4-pro[1m]"
    assert payload["exit_code"] == 0
    assert payload["readiness_report"]["status"] in {"ready", "warning", "blocked"}
    assert isinstance(payload["repair_plan"], list)
    assert payload["assistant_response"] == "traceable"
    assert payload["error"] is None
    assert payload["messages"][0]["role"] == "assistant"


def test_run_headless_writes_trace_when_runtime_config_is_invalid(
    monkeypatch, tmp_path: Path
) -> None:
    import minicode.headless

    trace_path = tmp_path / "artifacts" / "config-failure.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINI_CODE_HEADLESS_MESSAGES_OUT", str(trace_path))
    monkeypatch.setattr(
        "minicode.config.load_runtime_config",
        lambda cwd: (_ for _ in ()).throw(RuntimeError("No model configured.")),
    )

    with pytest.raises(SystemExit) as raised:
        minicode.headless.run_headless("Reply with exactly OK.")

    assert raised.value.code == 1
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload["exit_code"] == 1
    assert payload["error"] == "No model configured."
    assert payload["messages"] == []
    assert payload["readiness_report"]["status"] in {"warning", "blocked", "unknown"}
    assert payload["repair_plan"]


def test_run_headless_failure_trace_includes_redacted_repair_context(monkeypatch, tmp_path: Path) -> None:
    import minicode.headless

    runtime = {
        "model": "gpt-4o",
        "openaiBaseUrl": "https://api.openai.com",
        "openaiApiKey": "sk-real-secret-1234567890",
        "fallbackModels": ["openrouter/auto"],
    }
    trace_path = tmp_path / "artifacts" / "failed-messages.json"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINI_CODE_HEADLESS_MESSAGES_OUT", str(trace_path))
    monkeypatch.setattr(
        "minicode.config.load_runtime_config",
        lambda cwd: runtime,
    )
    monkeypatch.setattr(
        "minicode.tools.create_default_tool_registry",
        lambda cwd, runtime=None: ToolRegistry([]),
    )
    monkeypatch.setattr("minicode.permissions.PermissionManager", _DummyPermissions)
    monkeypatch.setattr("minicode.memory.MemoryManager", _DummyMemoryManager)
    monkeypatch.setattr(
        "minicode.prompt.build_system_prompt",
        lambda cwd, permissions, context: "sys",
    )
    monkeypatch.setattr(
        "minicode.model_registry.create_model_adapter",
        lambda model, tools, runtime=None: object(),
    )

    def _raise_provider_error(**kwargs):
        raise RuntimeError("Model API error: OPENAI_API_KEY=sk-real-secret-1234567890")

    monkeypatch.setattr(
        "minicode.agent_loop.run_agent_turn",
        _raise_provider_error,
    )

    response = minicode.headless.run_headless(
        "Run with OPENAI_API_KEY=sk-real-secret-1234567890"
    )

    assert response.startswith("Error:")
    raw_trace = trace_path.read_text(encoding="utf-8")
    assert "sk-real-secret" not in raw_trace
    payload = json.loads(raw_trace)
    assert payload["exit_code"] == 1
    assert payload["prompt"] == "Run with OPENAI_API_KEY=[REDACTED]"
    assert payload["error"] == "Model API error: OPENAI_API_KEY=[REDACTED]"
    assert payload["readiness_report"]["status"] in {"ready", "warning", "blocked"}
    assert isinstance(payload["repair_plan"], list)


# ---------------------------------------------------------------------------
# Opt-in non-interactive allow-edits path (headless can otherwise not edit files)
# ---------------------------------------------------------------------------


def test_allow_edits_flag_and_env(monkeypatch) -> None:
    from minicode.headless import _allow_edits_requested

    monkeypatch.delenv("MINI_CODE_ALLOW_EDITS", raising=False)
    assert _allow_edits_requested(cli_flag=False) is False
    assert _allow_edits_requested(cli_flag=True) is True
    monkeypatch.setenv("MINI_CODE_ALLOW_EDITS", "true")
    assert _allow_edits_requested() is True
    monkeypatch.setenv("MINI_CODE_ALLOW_EDITS", "0")
    assert _allow_edits_requested() is False


def test_allow_edits_auto_approve_grants_edits_and_out_of_cwd(tmp_path: Path) -> None:
    """With the auto-approve prompt, headless can edit files and reach
    out-of-cwd paths — the wall that previously made headless unusable for
    edits."""
    from minicode.headless import _make_auto_approve_prompt
    from minicode.permissions import PermissionManager

    perm = PermissionManager(str(tmp_path), prompt=_make_auto_approve_prompt())
    # Previously raised: "Edit requires approval ... Start minicode in TTY mode"
    perm.ensure_edit(str(tmp_path / "x.txt"), "diff")
    # Out-of-cwd access is also auto-approved (session-scoped, not persisted).
    perm.ensure_path_access(str(tmp_path.parent / "elsewhere"), "read")


def test_allow_edits_off_still_blocks_edits(tmp_path: Path) -> None:
    """Without the flag/env, headless edits remain blocked (no prompt)."""
    from minicode.permissions import PermissionManager

    perm = PermissionManager(str(tmp_path), prompt=None)
    with pytest.raises(RuntimeError, match="approval"):
        perm.ensure_edit(str(tmp_path / "y.txt"), "diff")
