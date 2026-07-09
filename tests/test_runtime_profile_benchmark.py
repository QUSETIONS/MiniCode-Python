from __future__ import annotations

from benchmarks.runtime_profile_eval import _classify_provider_diagnostic


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
    assert any(str(trace_path) in item for item in diagnostic.guidance)
