# MiniCode Release Readiness

- Generated at: 2026-07-17T06:54:02.128764+00:00
- Status: blocked
- Local gates: blocked
- Provider status: at-risk

## Status Reasons

- Local gates are blocked; inspect failed core or product smoke checks.
- Live provider status is at-risk: provider_channel_unavailable.
- Fallback coverage is not locally ready (provider-config).

## Core Gate

| check | status | exit_code | summary |
| --- | --- | ---: | --- |
| compileall | passed | 0 | compileall completed. |
| pytest-q | passed | 0 | 1310 passed, 2 skipped in 27.20s |
| runtime-profile-eval | passed | 0 | benchmarks/runtime_profile_eval_results.md |
| structure-compliance | passed | 0 | quality gate findings: 0 |

## Product Smokes

| check | status | exit_code | summary |
| --- | --- | ---: | --- |
| list-workspace-sessions | passed | 0 | Total: 1 session(s) |
| inspect-session | passed | 0 | - [tool:edit_file/success] Patched demo.txt |
| replay-session | passed | 0 | - [tool:edit_file/success] Patched demo.txt |
| preview-rewind | passed | 0 | Type: edit |
| readiness-cli | passed | 0 | readiness: blocked (unknown) [No model configured. Set ~/.mini-code/settings.json or ANTHROPIC_MODEL.] |
| readiness-json | passed | 0 | readiness blocked (provider-config) |
| readiness-script-json | passed | 0 | readiness blocked (provider-config) |
| readiness-threshold | failed | 1 | readiness blocked (provider-config) |
| readiness-examples | failed | 1 | fallback examples 2 (provider-config) |
| readiness-doctor | failed | 1 | doctor blocked (provider-config) |
| readiness-repair-plan | failed | 1 | repair plan 6 (provider-config) |
| readiness-patch-preview | failed | 1 | patch preview 2 (provider-config) |
| readiness-bundle-generate | failed | 1 | - repair_plan_json: .temp/readiness-bundle/readiness-repair-plan.json |
| readiness-artifacts | passed | 0 | readiness artifacts valid: 2 fallback example(s), 6 repair step(s), 2 patch preview(s) |
| fallback-patch-preview | passed | 0 | fallback patch preview valid: 2 preview(s) (provider-config) |
| fallback-simulation | passed | 0 | fallback simulations valid: 2 simulation(s) |
| fallback-switch-smoke | passed | 0 | fallback switch smoke valid: claude-sonnet-4-20250514 -> gpt-4o |
| readiness-bundle | passed | 0 | readiness bundle valid: 6 artifact(s) |
| headless-trace | passed | 0 | headless trace valid: exit_code=1 readiness=blocked repair_steps=6 |
| artifact-redaction | passed | 0 | artifact redaction valid: 7 artifact(s) |
| fallback-evidence | passed | 0 | fallback evidence valid: provider=at-risk fallback=not-ready repair_steps=6 |
| structure-compliance-artifact | passed | 0 | structure compliance artifact valid: focused_gates=19 materials=9 |
| artifact-manifest | passed | 0 | artifact manifest valid: 10 artifact(s) |

## Provider Diagnostics

| label | outcome | failure_category | retryable | ownership | recovery_action | risk_scope | error_code | request_id | exit_code | summary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| headless-smoke | provider_channel_unavailable | configuration | false | local-configuration | Repair model-to-provider channel configuration. | provider-config | - | - | 1 | 2026-07-17 14:57:56,583 [WARNING] minicode.config: Project .mcp.json found at .mcp.json but NOT loaded (security: use --trust-project-mcp or MINI_CODE_TRUST_PROJECT_MCP=1). |

## Provider Action Items

- `headless-smoke`: Verify the selected model group and provider channel configuration.
- `headless-smoke`: Add a viable fallback provider/model or credentials for the configured channel.
- `headless-smoke`: Inspect headless trace artifact: .temp/headless-provider-smoke-trace.json

## Provider Fallback Coverage

- Provider: unknown
- Provider ready: no
- Channel: unknown channel
- Fallback ready: no
- Risk scope: provider-config
- Summary: readiness: blocked (unknown) [No model configured. Set ~/.mini-code/settings.json or ANTHROPIC_MODEL.]
- Guidance:
  - Add fallbackModels or fallbackModels to enable model failover.
- Next actions:
  - Fix the primary provider channel or credentials.
  - Configure at least one locally ready fallback model.
  - Add fallbackModels or fallbackModels to enable model failover.
  - No model configured. Set ~/.mini-code/settings.json or ANTHROPIC_MODEL.
- Repair plan:
  - diagnose-local-readiness [blocked]: Inspect local provider and fallback readiness without calling the model provider.
    command: `minicode-readiness --json --fail-on blocked`
  - choose-fallback-provider [manual]: Choose one fallback provider, replace placeholder credentials locally, and merge only the selected settings into the target settings file.
  - preview-openai-fallback [preview]: Preview settings for OpenAI fallback.
  - preview-openrouter-fallback [preview]: Preview settings for OpenRouter fallback.
  - verify-local-readiness [verify]: Verify that local provider config and fallback coverage are no longer blocked.
    command: `minicode-readiness --json --fail-on blocked`
  - verify-release-readiness [verify]: Run the release smoke after local readiness is configured.
    command: `python benchmarks/release_readiness.py --fail-on at-risk`
- Config examples:
  - OpenAI fallback (~/.mini-code/settings.json): `{"env": {"OPENAI_API_KEY": "sk-...", "OPENAI_BASE_URL": "https://api.openai.com"}, "fallbackModels": ["gpt-4o", "gpt-4o-mini"]}`
  - OpenRouter fallback (~/.mini-code/settings.json): `{"env": {"OPENROUTER_API_KEY": "[REDACTED]", "OPENROUTER_BASE_URL": "https://openrouter.ai/api"}, "fallbackModels": ["openrouter/auto"]}`

### Local Preflight

| check | status | summary | action |
| --- | --- | --- | --- |
| primary-provider-config | blocked | unknown channel | Run a live provider smoke before release. |
| fallback-coverage | blocked | No configured or default fallback models are available. | Configure at least one locally ready fallback model. |
| configured-fallbacks | warning | No explicit fallbackModels are configured. | Add fallbackModels for deterministic release behavior. |
| default-fallbacks | warning | No default fallback model is locally viable for this provider. | Use explicit fallbackModels when defaults are unavailable. |
| live-smoke-readiness | not-run | Readiness preflight is local-only and does not call the model provider. | Run benchmarks/release_readiness.py for the live provider smoke. |

## Runtime Profile Artifacts

- JSON: benchmarks/runtime_profile_eval_results.json
- Markdown: benchmarks/runtime_profile_eval_results.md
- headless_trace: .temp/headless-provider-smoke-trace.json

## Readiness Artifacts

- bundle_directory: .temp/readiness-bundle
- bundle_manifest_json: .temp/readiness-bundle/readiness-artifact-manifest.json
- doctor_markdown: .temp/readiness-doctor.md
- fallback_examples_json: .temp/readiness-fallback-examples.json
- fallback_simulations_json: .temp/readiness-bundle/readiness-fallback-simulations.json
- patch_preview_json: .temp/readiness-fallback-patch-preview.json
- repair_plan_json: .temp/readiness-repair-plan.json

## Artifact Manifest

| label | exists | size_bytes | sha256 | path |
| --- | --- | ---: | --- | --- |
| bundle_manifest_json | yes | 1346 | e1756d9f9d97 | .temp/readiness-bundle/readiness-artifact-manifest.json |
| doctor_markdown | yes | 3277 | 1cee8e1f80c8 | .temp/readiness-doctor.md |
| fallback_examples_json | yes | 882 | f3664ba7de4a | .temp/readiness-fallback-examples.json |
| fallback_simulations_json | yes | 875 | 1355d9236755 | .temp/readiness-bundle/readiness-fallback-simulations.json |
| headless_trace | yes | 7935 | 1bfddc2dd3f9 | .temp/headless-provider-smoke-trace.json |
| json | yes | 6289 | 12acb4235389 | benchmarks/runtime_profile_eval_results.json |
| markdown | yes | 2373 | 5a41364c9693 | benchmarks/runtime_profile_eval_results.md |
| patch_preview_json | yes | 1617 | 87f7c97f4566 | .temp/readiness-fallback-patch-preview.json |
| repair_plan_json | yes | 2482 | 5d9d0551e73c | .temp/readiness-repair-plan.json |
| structure_compliance | yes | 98320 | a0d95a4c996e | .temp/structure-compliance.json |