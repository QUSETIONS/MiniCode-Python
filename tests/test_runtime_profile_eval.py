from minicode.runtime_profile_eval import (
    ProviderDiagnostic,
    RuntimeEvalCondition,
    RuntimeEvalScenario,
    classify_provider_failure,
    evaluate_runtime_profiles,
    runtime_profile_eval_as_dict,
    runtime_profile_eval_as_markdown,
    summarize_runtime_profile_eval,
)
from minicode.tooling import ToolRegistry
from minicode.types import AgentStep, ChatMessage, ModelAdapter


class ScriptedModel(ModelAdapter):
    def __init__(self, steps: list[AgentStep]) -> None:
        self._steps = steps
        self.calls = 0

    def next(self, messages: list[ChatMessage], on_stream_chunk=None) -> AgentStep:
        step = self._steps[self.calls]
        self.calls += 1
        return step


def test_provider_error_1010_is_external_rejected_request() -> None:
    result = classify_provider_failure(
        outcome="provider_api_error",
        error_code="1010",
        summary="Model API error (RuntimeError): error code: 1010",
        risk_scope="external-provider",
    )

    assert result.category == "provider-rejected-request"
    assert result.retryable is False
    assert result.ownership == "external-provider"
    assert "provider contract" in result.recovery_action


def test_common_codes_have_stable_failure_classes() -> None:
    assert (
        classify_provider_failure(
            "provider_api_error", "401", "", "provider-config"
        ).category
        == "authentication"
    )
    assert (
        classify_provider_failure(
            "provider_api_error", "429", "", "external-provider"
        ).category
        == "rate-limited"
    )
    assert (
        classify_provider_failure(
            "provider_outage", "503", "", "external-provider"
        ).category
        == "provider-unavailable"
    )
    assert (
        classify_provider_failure("timeout", "", "", "external-provider").category
        == "timeout"
    )


def test_evaluate_runtime_profiles_compares_budget_floor_between_profiles() -> None:
    scenario = RuntimeEvalScenario(
        name="depth-budget-floor",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "repair the runtime policy"},
        ],
        model_factory=lambda: ScriptedModel(
            [
                AgentStep(
                    type="assistant",
                    content="scanning the relevant files",
                    kind="progress",
                ),
                AgentStep(type="assistant", content="done"),
            ]
        ),
        tools_factory=lambda: ToolRegistry([]),
        max_steps=1,
    )
    rows = evaluate_runtime_profiles(
        scenarios=[scenario],
        conditions=[
            RuntimeEvalCondition(
                label="single",
                runtime={"runtimeProfile": "single"},
                max_steps=1,
            ),
            RuntimeEvalCondition(
                label="single-deep",
                runtime={"runtimeProfile": "single-deep"},
                max_steps=1,
            ),
        ],
    )

    assert len(rows) == 2
    single_row = next(row for row in rows if row.condition == "single")
    deep_row = next(row for row in rows if row.condition == "single-deep")
    assert single_row.completed is False
    assert deep_row.completed is True
    assert single_row.model_calls == 1
    assert deep_row.model_calls == 2
    assert deep_row.runtime_events >= 1
    assert deep_row.stop_reason == "done"
    assert deep_row.runtime_trace[-1].startswith("stop:done")


def test_summarize_runtime_profile_eval_counts_widened_runs() -> None:
    scenario = RuntimeEvalScenario(
        name="widening-escalation",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "repair the runtime policy"},
        ],
        model_factory=lambda: ScriptedModel(
            [
                AgentStep(type="assistant", content="still exploring", kind="progress"),
                AgentStep(type="assistant", content="still exploring", kind="progress"),
                AgentStep(type="assistant", content="still exploring", kind="progress"),
                AgentStep(type="assistant", content="still exploring", kind="progress"),
                AgentStep(type="assistant", content="still exploring", kind="progress"),
                AgentStep(type="assistant", content=""),
                AgentStep(type="assistant", content=""),
                AgentStep(type="assistant", content=""),
                AgentStep(type="assistant", content=""),
                AgentStep(type="assistant", content="done with a broader plan"),
            ]
        ),
        tools_factory=lambda: ToolRegistry([]),
    )
    rows = evaluate_runtime_profiles(
        scenarios=[scenario],
        conditions=[
            RuntimeEvalCondition(
                label="single-deep",
                runtime={"runtimeProfile": "single-deep"},
                max_steps=1,
            ),
        ],
    )

    summary = summarize_runtime_profile_eval(rows)

    assert rows[0].widened is True
    assert rows[0].runtime_event_counts["widening"] >= 1
    assert rows[0].stop_reason == "done"
    assert any(token.startswith("widen:") for token in rows[0].runtime_trace)
    assert summary["single-deep"]["runs"] == 1
    assert summary["single-deep"]["widened_runs"] == 1
    assert summary["single-deep"]["completion_rate"] == 1.0


def test_runtime_profile_eval_as_markdown_renders_summary_and_rows() -> None:
    scenario = RuntimeEvalScenario(
        name="depth-budget-floor",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "repair the runtime policy"},
        ],
        model_factory=lambda: ScriptedModel(
            [
                AgentStep(
                    type="assistant",
                    content="scanning the relevant files",
                    kind="progress",
                ),
                AgentStep(type="assistant", content="done"),
            ]
        ),
        tools_factory=lambda: ToolRegistry([]),
        max_steps=1,
    )
    rows = evaluate_runtime_profiles(
        scenarios=[scenario],
        conditions=[
            RuntimeEvalCondition(
                label="single-deep",
                runtime={"runtimeProfile": "single-deep"},
                max_steps=1,
            ),
        ],
    )

    rendered = runtime_profile_eval_as_markdown(rows)

    assert "# Runtime Profile Eval" in rendered
    assert "| condition | runs | completion_rate |" in rendered
    assert "avg_runtime_events" in rendered
    assert "stop_reason" in rendered
    assert "## Runtime Timelines" in rendered
    assert "depth-budget-floor" in rendered
    assert "single-deep" in rendered
    assert "phase:" in rendered


def test_runtime_profile_eval_as_dict_includes_runtime_trace() -> None:
    scenario = RuntimeEvalScenario(
        name="depth-budget-floor",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "repair the runtime policy"},
        ],
        model_factory=lambda: ScriptedModel(
            [
                AgentStep(
                    type="assistant",
                    content="scanning the relevant files",
                    kind="progress",
                ),
                AgentStep(type="assistant", content="done"),
            ]
        ),
        tools_factory=lambda: ToolRegistry([]),
        max_steps=1,
    )
    rows = evaluate_runtime_profiles(
        scenarios=[scenario],
        conditions=[
            RuntimeEvalCondition(
                label="single-deep",
                runtime={"runtimeProfile": "single-deep"},
                max_steps=1,
            ),
        ],
    )

    payload = runtime_profile_eval_as_dict(rows)

    assert payload["rows"][0]["runtime_trace"]
    assert payload["rows"][0]["runtime_trace"][-1].startswith("stop:done")


def test_runtime_profile_eval_outputs_include_provider_diagnostics() -> None:
    scenario = RuntimeEvalScenario(
        name="depth-budget-floor",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "repair the runtime policy"},
        ],
        model_factory=lambda: ScriptedModel(
            [
                AgentStep(
                    type="assistant",
                    content="scanning the relevant files",
                    kind="progress",
                ),
                AgentStep(type="assistant", content="done"),
            ]
        ),
        tools_factory=lambda: ToolRegistry([]),
        max_steps=1,
    )
    rows = evaluate_runtime_profiles(
        scenarios=[scenario],
        conditions=[
            RuntimeEvalCondition(
                label="single-deep",
                runtime={"runtimeProfile": "single-deep"},
                max_steps=1,
            ),
        ],
    )
    diagnostics = [
        ProviderDiagnostic(
            label="headless-smoke",
            outcome="provider_outage",
            command="python -m minicode.headless \"Reply with exactly OK.\"",
            exit_code=1,
            summary="Provider availability failure: all viable fallback models were unavailable.",
            stdout="",
            stderr="Provider availability failure",
            risk_scope="external-provider",
            error_code="503",
            request_id="req-123",
            failure_category="provider-unavailable",
            retryable=True,
            ownership="external-provider",
            recovery_action="Retry the provider smoke or switch to a ready fallback.",
            guidance=["Configure a fallback model."],
        )
    ]

    payload = runtime_profile_eval_as_dict(rows, diagnostics)
    rendered = runtime_profile_eval_as_markdown(rows, diagnostics)

    assert payload["provider_diagnostics"][0]["label"] == "headless-smoke"
    assert payload["provider_diagnostics"][0]["outcome"] == "provider_outage"
    assert payload["provider_diagnostics"][0]["failure_category"] == "provider-unavailable"
    assert payload["provider_diagnostics"][0]["retryable"] is True
    assert "## Provider Diagnostics" in rendered
    assert "headless-smoke" in rendered
    assert "provider_outage" in rendered
    assert "external-provider" in rendered
    assert "503" in rendered
    assert "req-123" in rendered
    assert "provider-unavailable" in rendered
    assert "yes" in rendered
    assert "Retry the provider smoke or switch to a ready fallback." in rendered
    assert "Configure a fallback model." in rendered
