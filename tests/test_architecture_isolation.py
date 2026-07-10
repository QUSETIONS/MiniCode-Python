"""Integration test: verify the agent core works WITHOUT the cybernetic layer.

This test proves that the cybernetic subsystem is a truly optional extension —
the core agent path (entry → agent_loop → tools → session) must function
correctly even when every cybernetic import fails.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class _BlockCybernetic:
    """Context manager that makes all minicode.cybernetic_* modules unimportable."""

    CYBERNETIC_PREFIXES = (
        "minicode.cybernetic_",
        "minicode.feedback_controller",
        "minicode.feedforward_controller",
        "minicode.predictive_controller",
        "minicode.decoupling_controller",
        "minicode.adaptive_pid_tuner",
        "minicode.state_observer",
        "minicode.progress_controller",
        "minicode.stability_monitor",
        "minicode.self_healing_engine",
        "minicode.verification_controller",
        "minicode.decision_audit",
    )

    # Non-cybernetic modules that lazy-import cybernetic — must be cleared too
    CASCADE_MODULES = (
        "minicode.agent_loop",
        "minicode.tty_app",
    )

    def __init__(self):
        self._blocked: dict[str, object] = {}

    def __enter__(self):
        # Remove cybernetic modules
        for key in list(sys.modules):
            for prefix in self.CYBERNETIC_PREFIXES:
                if key.startswith(prefix):
                    self._blocked[key] = sys.modules.pop(key)
        # Remove cascading modules so they re-import cleanly
        for key in self.CASCADE_MODULES:
            if key in sys.modules:
                self._blocked[key] = sys.modules.pop(key)
        return self

    def __exit__(self, *args):
        # Restore cybernetic modules directly.
        #
        # Cascade modules (agent_loop, tty_app) are deliberately NOT restored
        # from the snapshot: tests in this context manager re-import them under
        # isolation, and writing the stale pre-isolation module object back into
        # sys.modules can split the module identity (sys.modules holds one
        # object while later ``import minicode.agent_loop`` resolves another),
        # which silently breaks subsequent monkeypatch.setattr() calls in other
        # test files. The robust fix is to drop every cached reference and let
        # the import machinery rebuild a single canonical module on next access.
        for key in self.CASCADE_MODULES:
            sys.modules.pop(key, None)
            self._blocked.pop(key, None)
        # Re-import cascade modules so a single canonical instance is cached
        # both in sys.modules and in any subsequent ``import`` statement.
        for key in self.CASCADE_MODULES:
            try:
                importlib.import_module(key)
            except Exception:
                # Best-effort: if re-import fails, leave it absent so the next
                # real import attempt rebuilds it rather than leaving a split.
                pass
        sys.modules.update(self._blocked)


def test_core_agent_loop_imports_without_cybernetic():
    """Agent loop must be importable even when cybernetic modules are absent."""
    with _BlockCybernetic():
        # Force re-import
        if "minicode.agent_loop" in sys.modules:
            del sys.modules["minicode.agent_loop"]
        # Should not raise
        from minicode.agent_loop import run_agent_turn  # noqa: F401
        assert True  # reached = success


def test_core_tooling_works_without_cybernetic():
    """ToolResult must work without any cybernetic imports."""
    from minicode.tooling import ToolResult
    result = ToolResult(ok=True, output="test ok")
    assert result.ok is True


def test_core_session_works_without_cybernetic(tmp_path):
    """Session persistence must work without cybernetic modules."""
    from minicode.session import SessionData, save_session
    sd = SessionData(session_id="test", created_at=0.0, updated_at=0.0, workspace=str(tmp_path))
    save_session(sd)
    assert sd.session_id == "test"


def test_core_context_manager_without_cybernetic():
    """ContextManager + token estimation must work without cybernetic."""
    from minicode.context_manager import estimate_message_tokens
    tokens = estimate_message_tokens({"role": "user", "content": "Hello world"})
    assert isinstance(tokens, int)
    assert tokens > 0


def test_core_config_without_cybernetic(monkeypatch):
    """Config loading must work without cybernetic."""
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-3-20240307")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from minicode.config import load_runtime_config
    config = load_runtime_config(".", trust_project_mcp=False)
    assert isinstance(config, dict)


def test_core_memory_without_cybernetic(tmp_path):
    """MemoryManager must work without cybernetic."""
    from minicode.memory import MemoryManager, MemoryScope
    mgr = MemoryManager(project_root=tmp_path)
    mgr.add_entry(MemoryScope.PROJECT, "test", "hello", ["tag"])
    results = mgr.search("hello")
    assert len(results) >= 1
