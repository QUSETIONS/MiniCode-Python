# Runtime Profile Eval

## Summary

| condition | runs | completion_rate | widened_rate | verification_guard_rate | avg_model_calls | avg_runtime_events | avg_wall_time_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| single | 2 | 0.00 | 0.00 | 0.00 | 1.00 | 2.00 | 11.22 |
| single-deep | 2 | 1.00 | 0.50 | 0.00 | 6.00 | 4.50 | 5.67 |

## Scenario Rows

| scenario | condition | completed | stop_reason | widened | verification_guard | runtime_events | model_calls | wall_time_ms | final_message |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| depth-budget-floor | single | no | max_steps | no | no | 2 | 1 | 19.30 | Reached the maximum tool step limit for this turn. |
| depth-budget-floor | single-deep | yes | done | no | no | 2 | 2 | 3.92 | done |
| widening-escalation | single | no | max_steps | no | no | 2 | 1 | 3.13 | Reached the maximum tool step limit for this turn. |
| widening-escalation | single-deep | yes | done | yes | no | 7 | 10 | 7.43 | done with a broader plan |

## Runtime Timelines

- `depth-budget-floor` / `single`: phase:explore@1 -> stop:max_steps@1
- `depth-budget-floor` / `single-deep`: phase:explore@1 -> stop:done@2
- `widening-escalation` / `single`: phase:explore@1 -> stop:max_steps@1
- `widening-escalation` / `single-deep`: phase:explore@1 -> phase:execute@3 -> phase:verify@4 -> phase:verify@9 -> widen:the model stalled repeatedly before producing new evidence@9 -> phase:execute@10 -> stop:done@10

## Provider Diagnostics

| label | outcome | category | retryable | ownership | recovery_action | risk_scope | readiness | repair_steps | trace | error_code | request_id | exit_code | summary |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | ---: | --- |
| headless-smoke | provider_channel_unavailable | configuration | no | local-configuration | Repair model-to-provider channel configuration. | provider-config | blocked | 6 | .temp/headless-provider-smoke-trace.json | - | - | 1 | 2026-07-10 11:56:00,864 [WARNING] minicode.config: Project .mcp.json found at .mcp.json but NOT loaded (security: use --... |

Guidance for `headless-smoke`:
- Verify the selected model group and provider channel configuration.
- Add a viable fallback provider/model or credentials for the configured channel.
- Inspect headless trace artifact: .temp/headless-provider-smoke-trace.json