from minicode.model_registry import (
    ModelSelectionController,
    ModelSelectionSignal,
    ReasoningEffort,
    format_model_status,
    model_id_supports_agent_tools,
    resolve_model_info,
)


class TestModelSelectionController:
    def test_complex_task_prefers_stronger_model(self):
        controller = ModelSelectionController()
        decision = controller.decide(
            ModelSelectionSignal(task_complexity="complex", budget_pressure=0.0)
        )
        info = resolve_model_info(decision.model)
        assert decision.reasoning_effort in {ReasoningEffort.HIGH, ReasoningEffort.XHIGH}
        assert info.supports_tools is True
        assert decision.score > 0

    def test_high_budget_pressure_selects_cheaper_model(self):
        controller = ModelSelectionController()
        cheap = controller.decide(
            ModelSelectionSignal(task_complexity="moderate", budget_pressure=0.9)
        )
        expensive = controller.decide(
            ModelSelectionSignal(task_complexity="complex", budget_pressure=0.0)
        )

        cheap_info = resolve_model_info(cheap.model)
        expensive_info = resolve_model_info(expensive.model)
        cheap_cost = cheap_info.pricing_input + cheap_info.pricing_output
        expensive_cost = expensive_info.pricing_input + expensive_info.pricing_output

        assert cheap_cost <= expensive_cost
        assert cheap.reasoning_effort in {ReasoningEffort.LOW, ReasoningEffort.MEDIUM}
        assert "high budget pressure" in cheap.reasons

    def test_requires_tools_excludes_no_tools_models(self):
        controller = ModelSelectionController()
        decision = controller.decide(
            ModelSelectionSignal(task_complexity="complex", requires_tools=True)
        )
        assert resolve_model_info(decision.model).supports_tools is True

    def test_long_context_requirement_prefers_large_context(self):
        controller = ModelSelectionController()
        decision = controller.decide(
            ModelSelectionSignal(task_complexity="moderate", requires_long_context=True)
        )
        assert resolve_model_info(decision.model).context_window >= 128_000
        assert "long context required" in decision.reasons

    def test_recent_failures_raise_reasoning_effort(self):
        controller = ModelSelectionController()
        normal = controller.decide(ModelSelectionSignal(task_complexity="moderate"))
        recovered = controller.decide(
            ModelSelectionSignal(task_complexity="moderate", recent_failures=3)
        )
        effort_order = {
            ReasoningEffort.LOW: 0,
            ReasoningEffort.MEDIUM: 1,
            ReasoningEffort.HIGH: 2,
            ReasoningEffort.XHIGH: 3,
        }
        assert effort_order[recovered.reasoning_effort] >= effort_order[normal.reasoning_effort]
        assert "recent failures: 3" in recovered.reasons

    def test_decision_serializes_to_dict(self):
        controller = ModelSelectionController()
        decision = controller.decide(ModelSelectionSignal(task_complexity="simple"))
        data = decision.to_dict()
        assert data["model"] == decision.model
        assert data["provider"] == decision.provider.value
        assert data["reasoning_effort"] == decision.reasoning_effort.value

    def test_model_status_includes_cybernetic_recommendation(self):
        status = format_model_status("gpt-4o-mini", {"openaiApiKey": "sk-test"})
        assert "Cybernetic Recommendation" in status
        assert "Effort:" in status
        assert "Score:" in status

    def test_dynamic_model_ids_filter_non_agent_modalities(self):
        assert model_id_supports_agent_tools("qwen3.7-max") is True
        assert model_id_supports_agent_tools("kimi-k2.7-code") is True
        assert model_id_supports_agent_tools("gpt-image-1.5") is False
        assert model_id_supports_agent_tools("gpt-4o-audio-preview") is False
        assert model_id_supports_agent_tools("gpt-4o-realtime-preview") is False
        assert model_id_supports_agent_tools("o1") is False
