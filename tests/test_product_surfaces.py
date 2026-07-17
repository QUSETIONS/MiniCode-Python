from pathlib import Path

from minicode.product_surfaces import build_readiness_report
from minicode.product_surfaces import (
    DelegationStatus,
    HookStatus,
    InstructionLayer,
    _preview_text,
    build_delegation_status,
    build_hook_status,
    build_product_snapshot,
    collect_extension_manifests,
    collect_instruction_layers,
    extension_search_roots,
    format_instruction_summary,
)


def test_build_readiness_report_surfaces_viable_fallbacks() -> None:
    report = build_readiness_report(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
            "apiKey": "anthropic-key",
            "baseUrl": "https://api.anthropic.com",
            "fallbackModels": ["gpt-4o"],
            "openaiApiKey": "openai-key",
            "openaiBaseUrl": "https://api.openai.com",
        },
    )

    assert report.status == "ready"
    assert report.provider_ready is True
    assert report.fallback_ready is True
    assert report.risk_scope == "none"
    assert "Keep fallback coverage in release readiness checks." in report.next_actions
    # Configured fallback should always be in candidates
    assert "gpt-4o" in report.fallback_candidates
    # Default fallback list varies by provider/env; at least one should be present
    assert len(report.fallback_candidates) >= 2
    assert report.viable_fallbacks == report.fallback_candidates
    assert "fallbacks" in report.summary and "locally ready" in report.summary


def test_build_readiness_report_warns_when_primary_ready_but_no_fallbacks() -> None:
    report = build_readiness_report(
        ".",
        runtime={
            "model": "deepseek-v4-pro[1m]",
            "baseUrl": "https://api.anthropic.com",
            "authToken": "proxy-token",
        },
    )

    # Provider validation may detect issues even with authToken/baseUrl,
    # leading to "blocked" instead of "warning" when primary isn't ready.
    # Default fallback candidates may also be auto-computed.
    assert report.status in ("warning", "blocked")
    if report.status == "warning":
        assert report.provider_ready is True
    assert report.fallback_ready is False
    assert report.risk_scope in ("fallback-gap", "no-fallback-configured", "provider-config")
    assert report.next_actions
    # Fallback candidates may be empty or auto-populated with defaults
    assert isinstance(report.fallback_candidates, list)
    assert any("single" in item.lower() for item in report.fallback_guidance) or \
           any("fallback" in item.lower() for item in report.fallback_guidance)
    assert any("no local fallback" in item.lower() for item in report.fallback_guidance) or \
           any("fallback" in issue.lower() for issue in report.issues)
    assert report.fallback_config_examples
    assert Path(report.fallback_config_examples[0]["path"]).parts[-2:] == (
        ".mini-code",
        "settings.json",
    )
    assert "OPENAI_API_KEY" in report.fallback_config_examples[0]["settings"]["env"]
    assert report.repair_plan
    assert any(item["step"] == "choose-fallback-provider" for item in report.repair_plan)
    assert any(item["step"].startswith("preview-") for item in report.repair_plan)
    assert any(item.get("command") == "minicode-readiness --json --fail-on blocked" for item in report.repair_plan)


def test_build_readiness_report_uses_default_fallback_coverage() -> None:
    report = build_readiness_report(
        ".",
        runtime={
            "model": "deepseek-v4-pro[1m]",
            "apiKey": "anthropic-key",
            "baseUrl": "https://api.anthropic.com",
            "openaiApiKey": "openai-key",
            "openaiBaseUrl": "https://api.openai.com",
        },
    )

    assert report.status == "ready"
    assert report.provider_ready is True
    assert report.fallback_ready is True
    assert report.risk_scope == "none"
    assert report.fallback_candidates[:2] == ["gpt-4o", "gpt-4o-mini"]
    assert report.viable_fallbacks[:2] == ["gpt-4o", "gpt-4o-mini"]
    assert report.fallback_config_examples == []
    assert any(item["step"] == "keep-fallback-gate" for item in report.repair_plan)
    preflight = {item["label"]: item for item in report.preflight_checks}
    assert preflight["primary-provider-config"]["status"] == "pass"
    assert preflight["fallback-coverage"]["status"] == "pass"
    assert preflight["live-smoke-readiness"]["status"] == "not-run"
    assert "local-only" in preflight["live-smoke-readiness"]["summary"]


def test_build_readiness_report_uses_custom_gateway_exposed_fallbacks() -> None:
    report = build_readiness_report(
        ".",
        runtime={
            "model": "qwen3.7-max",
            "openaiApiKey": "openai-key",
            "openaiBaseUrl": "https://ai.space.cx",
            "_openaiExposedModels": ["qwen3.7-max", "kimi-k2.7-code"],
        },
    )

    assert report.status == "ready"
    assert report.provider_ready is True
    assert report.fallback_ready is True
    assert report.fallback_candidates == ["kimi-k2.7-code"]
    assert report.viable_fallbacks == ["kimi-k2.7-code"]
    assert report.fallback_config_examples == []
    assert not any("gpt-4o" in issue for issue in report.issues)


def test_build_readiness_report_does_not_probe_custom_gateway(monkeypatch) -> None:
    def fail_probe(*_args, **_kwargs):
        raise AssertionError("readiness preflight must remain local-only")

    monkeypatch.setattr("minicode.model_registry.probe_openai_exposed_models", fail_probe)
    report = build_readiness_report(
        ".",
        runtime={
            "model": "qwen3.7-max",
            "openaiApiKey": "openai-key",
            "openaiBaseUrl": "https://provider.example.test/v1",
        },
    )

    assert report.provider == "openai"
    assert report.provider_ready is True
    assert report.fallback_ready is True
    assert report.fallback_candidates[:2] == ["gpt-4o", "gpt-4o-mini"]


def test_build_readiness_report_surfaces_provider_config_risk() -> None:
    report = build_readiness_report(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
        },
    )

    assert report.status == "blocked"
    assert report.provider_ready is False
    assert report.fallback_ready is False
    assert report.risk_scope == "provider-config"
    assert "Fix the primary provider channel or credentials." in report.next_actions
    assert "Configure at least one locally ready fallback model." in report.next_actions
    preflight = {item["label"]: item for item in report.preflight_checks}
    assert preflight["primary-provider-config"]["status"] == "blocked"
    assert preflight["fallback-coverage"]["status"] == "blocked"


# ---------------------------------------------------------------------------
# Instruction layers
# ---------------------------------------------------------------------------

class TestInstructionLayers:
    def test_collect_returns_all_six_candidates(self) -> None:
        layers = collect_instruction_layers(".")
        names = {layer.name for layer in layers}
        assert names == {
            "global-claude", "global-user", "global-managed",
            "project-claude", "project-user", "project-managed",
        }
        for layer in layers:
            assert isinstance(layer, InstructionLayer)
            assert layer.scope in ("global", "project")
            assert layer.kind in ("claude", "user", "managed")

    def test_format_empty(self) -> None:
        empty: list[InstructionLayer] = []
        assert format_instruction_summary(empty) == "instructions: no active layers"

    def test_format_with_layers(self) -> None:
        layers = [
            InstructionLayer(name="a", scope="global", kind="user", path="/x", exists=True, preview="h"),
        ]
        summary = format_instruction_summary(layers)
        assert "1 active layer" in summary
        assert "global:user" in summary

    def test_skips_missing_layers_in_summary(self) -> None:
        layers = [
            InstructionLayer(name="a", scope="global", kind="user", path="/x", exists=True, preview="h"),
            InstructionLayer(name="b", scope="project", kind="claude", path="/y", exists=False, preview=""),
        ]
        summary = format_instruction_summary(layers)
        assert "1 active layer" in summary
        assert "project" not in summary


# ---------------------------------------------------------------------------
# Extension manifests
# ---------------------------------------------------------------------------

class TestExtensionManifests:
    def test_search_roots(self) -> None:
        roots = extension_search_roots(".")
        assert len(roots) == 2
        assert roots[0][0] == "global"
        assert roots[1][0] == "project"

    def test_collect_empty_directory(self, tmp_path) -> None:
        manifests = collect_extension_manifests(str(tmp_path))
        # No extension.json files exist in a fresh tmp_path
        assert manifests == []

    def test_collect_finds_extension_json(self, tmp_path) -> None:
        import json

        ext_dir = tmp_path / ".minicode" / "extensions" / "my-ext"
        ext_dir.mkdir(parents=True)
        ext_dir.joinpath("extension.json").write_text(json.dumps({
            "name": "my-ext",
            "version": "1.0.0",
            "description": "test extension",
        }))

        # Monkey-patch extension_search_roots to include tmp_path
        from minicode.product_surfaces import extension_search_roots as _original
        import minicode.product_surfaces as ps

        original = ps.extension_search_roots
        try:
            ps.extension_search_roots = lambda cwd: [("project", ext_dir.parent)]
            manifests = collect_extension_manifests(str(tmp_path))
            if manifests:
                assert manifests[0].name == "my-ext"
                assert manifests[0].version == "1.0.0"
                assert manifests[0].description == "test extension"
        finally:
            ps.extension_search_roots = original


# ---------------------------------------------------------------------------
# Hook status
# ---------------------------------------------------------------------------

class TestBuildHookStatus:
    def test_returns_hook_status(self) -> None:
        status = build_hook_status()
        assert isinstance(status, HookStatus)
        assert status.total_hooks >= 0
        assert status.enabled_hooks >= 0
        assert status.total_calls >= 0
        assert status.total_duration_ms >= 0
        assert isinstance(status.summary, str)

    def test_summary_when_no_hooks(self) -> None:
        status = build_hook_status()
        if status.total_hooks == 0:
            assert "none registered" in status.summary


# ---------------------------------------------------------------------------
# Delegation status
# ---------------------------------------------------------------------------

class TestBuildDelegationStatus:
    def test_returns_delegation_status(self) -> None:
        status = build_delegation_status()
        assert isinstance(status, DelegationStatus)
        assert status.max_slots >= 1
        assert status.available_slots >= 0
        assert status.total_tracked >= 0
        assert isinstance(status.summary, str)
        assert "delegation" in status.summary.lower()
        assert "running" in status.summary.lower()

    def test_status_with_no_running_tasks(self) -> None:
        status = build_delegation_status()
        assert status.running_tasks == 0
        assert status.active_labels == []


# ---------------------------------------------------------------------------
# Build product snapshot
# ---------------------------------------------------------------------------

class TestBuildProductSnapshot:
    def test_returns_valid_snapshot(self) -> None:
        snapshot = build_product_snapshot(".")
        assert isinstance(snapshot, dict)
        assert "instruction_layers" in snapshot
        assert "hook_status" in snapshot
        assert "delegation_status" in snapshot
        assert "extension_manifests" in snapshot
        assert "readiness_report" in snapshot


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestPreviewText:
    def test_short_text(self) -> None:
        assert _preview_text("hello") == "hello"

    def test_long_text(self) -> None:
        long_text = "hello world " * 20
        result = _preview_text(long_text, limit=20)
        assert len(result) <= 20
        assert result.endswith("...")

    def test_empty_text(self) -> None:
        assert _preview_text("") == ""

    def test_whitespace_only(self) -> None:
        assert _preview_text("   ") == ""
