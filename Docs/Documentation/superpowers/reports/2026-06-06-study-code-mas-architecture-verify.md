# Verify Report: study-code-mas-architecture

Date: 2026-06-06
Change: `study-code-mas-architecture`
Mode: manual OpenSpec + artifact-backed verify
Status: pass; change complete at smoke-gated study-package level

## Verification scope

- OpenSpec validity and task completion
- protocol and architecture-contract artifact integrity
- smoke-setting record
- paired real-harness smoke evidence
- benchmark-family local-equivalent smoke evidence
- post-smoke paper decision gate and claim boundary

## Evidence

1. OpenSpec state is complete and valid

```bash
openspec status --change study-code-mas-architecture --json
openspec validate study-code-mas-architecture --no-color
```

Observed result:

- `isComplete: true`
- `Change 'study-code-mas-architecture' is valid`

2. The task checklist is fully closed

- `openspec/changes/study-code-mas-architecture/tasks.md`
- no unchecked tasks remain

3. The smoke-setting record is explicit and honest

- `openspec/changes/study-code-mas-architecture/smoke-study-fixed-setting.md`

The file now distinguishes:

- the original protocol target model: `deepseek-v4-pro[1m]`
- the actually executed replacement model:
  `claude-haiku-4-5-20251001`
- the shared smoke budget: `max_steps = 5`

4. Real-harness paired smoke evidence exists and is summarized

- `openspec/changes/study-code-mas-architecture/smoke-failure-annotation-and-blocker-note.md`
- `outputs/he_live_smoke_20260606_haiku45_paired3cond/results.json`
- `outputs/he_live_smoke_20260606_haiku45_paired3cond/summary.json`

Key executed summary:

- `single_loop`: 10 total, 2 repair success, 7 repair failure, 1 protocol failure
- `single_loop_plus_scouts`: 10 total, 2 repair success, 7 repair failure, 1 protocol failure
- `object_governed_mas_plus_verifier`: 10 total, 1 repair success, 9 repair failure, 0 protocol failure

5. Benchmark-family smoke evidence exists and is summarized

- `outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/results.json`
- `outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/summary.json`
- `outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/manual_grader_replay.json`

Observed result:

- 9 total rows
- 3 families:
  - patch repair
  - repository construction
  - research code
- 3 architecture conditions
- all 9 rows runner-complete
- all 9 rows `repair_failure`
- all 9 rows hit the `max_steps = 5` ceiling

Recovered family-level labels include:

- patch repair: `missing_general_normalization`
- repository construction:
  `requirements_not_implemented`, `cli_contract_missing`
- research code:
  `analysis_not_implemented`, `report_contract_missing`

6. The post-smoke decision gate is updated to current truth

- `openspec/changes/study-code-mas-architecture/paper-decision-gate-after-smoke.md`

Current verified decision:

- strong positive alignment claim is **not yet** supported
- smoke-backed failure/stress framing **is** supported
- official benchmark-leaderboard claims remain out of scope

## Findings

- The OpenSpec change is structurally complete and valid.
- The protocol did not remain theory-only; the smoke gate was actually
  executed.
- The benchmark-family smoke was closed honestly through study-local-equivalent
  bindings rather than overclaiming official payload execution.
- The current evidence does not validate a strong positive
  task-architecture-alignment claim.
- The current evidence does support a bounded failure/stress readout under one
  replacement model and one low-budget setting.

## Verify caveat

This verify pass is artifact-backed and manual. There is no change-local
`.comet.yaml` state file to update in this OpenSpec directory, so closeout is
documented through OpenSpec validity, the fully checked task file, and the
saved smoke artifacts.

## Closeout

This change is complete as a smoke-gated study package.

What is complete:

- theory and protocol package
- architecture contracts
- telemetry and failure taxonomy
- real-harness paired smoke
- benchmark-family local-equivalent smoke
- final post-smoke claim boundary

What is still future work:

- a stronger rerun for positive alignment evidence, or
- a paper written as a failure/stress study rather than a validated routing
  rule.
