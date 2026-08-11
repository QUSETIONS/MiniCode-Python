from __future__ import annotations

from benchmarks.runtime_profile_eval import (
    _classify_provider_diagnostic,
    _portable_provider_diagnostic,
)


def test_runtime_profile_provider_diagnostic_classifies_model_api_error() -> None:
    diagnostic = _classify_provider_diagnostic(
        label="headless-smoke",
        command="python -m minicode.headless Reply with exactly OK.",
        exit_code=0,
        stdout="Model API error (RuntimeError): error code: 1010\n",
        stderr="request id: abc123",
    )

    assert diagnostic.outcome == "provider_api_error"
    assert diagnostic.risk_scope == "external-provider"
    assert diagnostic.error_code == "1010"
    assert diagnostic.request_id == "abc123"
    assert diagnostic.failure_category == "provider-rejected-request"
    assert diagnostic.retryable is False
    assert diagnostic.ownership == "external-provider"
    assert "provider contract" in diagnostic.recovery_action
    assert diagnostic.guidance
    assert "provider error code" in diagnostic.guidance[0]


def test_runtime_profile_provider_diagnostic_includes_headless_trace_context(tmp_path) -> None:
    trace_path = tmp_path / "headless-trace.json"
    diagnostic = _classify_provider_diagnostic(
        label="headless-smoke",
        command="python -m minicode.headless Reply with exactly OK.",
        exit_code=1,
        stdout="Provider availability failure: all viable fallback models were unavailable.\n",
        stderr="",
        trace_artifact=trace_path,
        trace_payload={
            "readiness_report": {"status": "warning"},
            "repair_plan": [{"step": "diagnose"}, {"step": "verify"}],
        },
    )

    assert diagnostic.outcome == "provider_outage"
    assert diagnostic.readiness_status == "warning"
    assert diagnostic.repair_step_count == 2
    assert diagnostic.trace_artifact == str(trace_path)
    trace_guidance = [item for item in diagnostic.guidance if str(trace_path) in item]
    assert trace_guidance == [f"Inspect headless trace artifact: {trace_path}"]


def test_runtime_profile_provider_diagnostic_shares_local_channel_classification() -> None:
    diagnostic = _classify_provider_diagnostic(
        label="headless-smoke",
        command="python -m minicode.headless Reply with exactly OK.",
        exit_code=1,
        stdout="",
        stderr="No available channel for model.",
    )

    assert diagnostic.outcome == "provider_channel_unavailable"
    assert diagnostic.risk_scope == "provider-config"
    assert diagnostic.failure_category == "configuration"
    assert diagnostic.ownership == "local-configuration"


def test_runtime_profile_provider_diagnostic_classifies_local_config_failure() -> None:
    diagnostic = _classify_provider_diagnostic(
        label="headless-smoke",
        command="python -m minicode.headless Reply with exactly OK.",
        exit_code=1,
        stdout="",
        stderr="Config error: No model configured.",
    )

    assert diagnostic.outcome == "provider_channel_unavailable"
    assert diagnostic.risk_scope == "provider-config"
    assert diagnostic.failure_category == "configuration"
    assert diagnostic.retryable is False
    assert diagnostic.ownership == "local-configuration"


def test_runtime_profile_normalizes_diagnostic_before_markdown_truncation(tmp_path) -> None:
    repo = tmp_path / "repo"
    diagnostic = _classify_provider_diagnostic(
        label="headless-smoke",
        command=f"python {repo / 'minicode' / 'headless.py'}",
        exit_code=1,
        stdout="",
        stderr=f"Config error at {repo / '.mcp.json'}: No model configured.",
        trace_artifact=repo / ".temp" / "trace.json",
    )

    portable = _portable_provider_diagnostic(
        diagnostic,
        repo_root=repo,
        home=tmp_path,
    )

    assert str(repo) not in portable.command
    assert str(repo) not in portable.stderr
    assert portable.trace_artifact == ".temp/trace.json"
