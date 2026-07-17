"""Verification that model switching (换模型) works after the
get_model_context_window fix.

Covers the three switch surfaces:
  1. ContextManager.update_model resolves the correct context window per model.
  2. /model <name> persists the override to settings.json.
  3. ModelSwitcher.switch_to builds a new adapter (success) and degrades
     gracefully when the adapter can't be built (failure) — no crash.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from minicode.context_manager import ContextManager
from minicode.model_switcher import ModelSwitcher, SwitchResult


# ---------------------------------------------------------------------------
# 1. Context window tracks the switched model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model,expected_window", [
    ("claude-opus-4-6", 200_000),
    ("claude-sonnet-4-6", 200_000),
    ("gpt-4o", 128_000),
    ("gpt-5", 128_000),
    ("deepseek-chat", 128_000),
    ("CLAUDE-OPUS-4-6", 200_000),          # case-insensitive
    ("some-unknown-model", 128_000),        # default
])
def test_context_manager_update_model_resolves_window(model, expected_window):
    """Switching the model must update the context window (used by auto-compact
    thresholds + /context display). Previously a fixed/exact-match table left
    most model ids at the 128k default."""
    cm = ContextManager(model="claude-sonnet-4-6")
    cm.update_model(model)
    assert cm.context_window == expected_window


def test_context_manager_window_changes_on_switch():
    cm = ContextManager(model="gpt-4o")
    assert cm.context_window == 128_000
    cm.update_model("gemini-2.5-pro")
    assert cm.context_window == 1_048_576  # switched to a 1M window
    cm.update_model("gpt-4o")
    assert cm.context_window == 128_000  # and back


# ---------------------------------------------------------------------------
# 2. /model <name> persists the override
# ---------------------------------------------------------------------------


def test_model_command_persists_override(monkeypatch, tmp_path):
    import minicode.cli_commands as cli_commands
    import minicode.config as config

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(cli_commands, "MINI_CODE_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(config, "MINI_CODE_SETTINGS_PATH", settings_path)

    result = cli_commands.try_handle_local_command("/model claude-opus-4-6")

    assert result is not None
    assert "claude-opus-4-6" in result
    assert settings_path.exists()
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved.get("model") == "claude-opus-4-6"


def test_model_command_show_current(monkeypatch):
    import minicode.cli_commands as cli_commands

    monkeypatch.setattr(
        "minicode.cli_commands.load_runtime_config",
        lambda: {"model": "deepseek-chat", "baseUrl": "https://x", "authToken": "t"},
    )
    result = cli_commands.try_handle_local_command("/model")
    assert result is not None
    assert "deepseek-chat" in result


# ---------------------------------------------------------------------------
# 3. ModelSwitcher.switch_to — success + graceful failure
# ---------------------------------------------------------------------------


class _FakeAdapter:
    pass


def test_switch_to_succeeds_and_updates_runtime(monkeypatch):
    built = {}

    def _fake_create(*, model, tools, runtime):
        built["model"] = model
        return _FakeAdapter()

    monkeypatch.setattr("minicode.model_switcher.create_model_adapter", _fake_create)

    runtime = {"model": "claude-sonnet-4-6", "baseUrl": "https://x", "authToken": "t"}
    switcher = ModelSwitcher(
        current_model="claude-sonnet-4-6",
        current_runtime=runtime,
        current_tools=object(),
    )

    result = switcher.switch_to("claude-opus-4-6", reason="user_request")

    assert isinstance(result, SwitchResult)
    assert result.success is True
    assert result.old_model == "claude-sonnet-4-6"
    assert result.new_model == "claude-opus-4-6"
    assert switcher.current_model == "claude-opus-4-6"
    assert runtime["model"] == "claude-opus-4-6"  # runtime updated
    assert built["model"] == "claude-opus-4-6"
    assert switcher.switch_count == 1


def test_switch_to_same_model_is_noop():
    runtime = {"model": "claude-sonnet-4-6"}
    switcher = ModelSwitcher("claude-sonnet-4-6", runtime, object())
    result = switcher.switch_to("claude-sonnet-4-6")
    assert result.success is False
    assert switcher.current_model == "claude-sonnet-4-6"


def test_switch_to_failure_does_not_crash_or_mutate(monkeypatch):
    """If the new adapter can't be built (e.g. missing creds for the target),
    switch_to must report failure without crashing or changing the active model."""

    def _boom(*, model, tools, runtime):
        raise RuntimeError("no channel for model")

    monkeypatch.setattr("minicode.model_switcher.create_model_adapter", _boom)

    runtime = {"model": "claude-sonnet-4-6", "authToken": "t"}
    switcher = ModelSwitcher("claude-sonnet-4-6", runtime, object())

    result = switcher.switch_to("claude-opus-4-6")

    assert result.success is False
    assert switcher.current_model == "claude-sonnet-4-6"  # unchanged
    assert runtime["model"] == "claude-sonnet-4-6"         # runtime unchanged


def test_fallback_candidates_exclude_models_without_tool_support(monkeypatch):
    monkeypatch.setattr(
        "minicode.model_switcher.build_provider_config",
        lambda model, runtime=None: type("Provider", (), {"api_key": "test-key"})(),
    )

    switcher = ModelSwitcher(
        current_model="claude-sonnet-4-6",
        current_runtime={
            "model": "claude-sonnet-4-6",
            "fallbackModels": ["o1", "gpt-4o-audio-preview", "gpt-4o"],
        },
        current_tools=object(),
    )

    candidates = switcher._fallback_candidates()
    assert "gpt-4o" in candidates
    assert "o1" not in candidates
    assert "gpt-4o-audio-preview" not in candidates
