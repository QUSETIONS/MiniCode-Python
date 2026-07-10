# Smoke Failure Annotation and Benchmark-Family Local-Equivalent Execution Note

Date: 2026-06-06

## Scope

This note updates the smoke-study evidence after the replacement-model restart
that successfully reached the real coding-agent harness path.

It now separates four things cleanly:

- what has now been executed and can be closed;
- what failure evidence is available from the executed smoke blocks;
- what was executed for the benchmark-family smoke requirement;
- what still remains outside the current claim boundary.

## Fixed-Setting Boundary

The protocol-level fixed setting remains:

- target model: `deepseek-v4-pro[1m]`
- budget: `max_steps = 5`
- primary architecture conditions:
  - `single-loop`
  - `single-loop-plus-scouts`
  - `object-governed-mas-plus-verifier`

However, the original provider path was unavailable. The live smoke was
therefore explicitly restarted under a single replacement model held constant
across all executed smoke runs:

- replacement model actually used for the executed smoke blocks:
  - `claude-haiku-4-5-20251001`

This keeps the smoke internally comparable:

- one model only;
- no mixed-model block;
- same budget across all executed families and conditions.

It does not change the protocol record that the original preferred fixed
setting was `deepseek-v4-pro[1m]`.

## Executed Real-Harness Smoke Evidence

### A. One tiny task per family sanity (`5.2`)

Artifact:

- `outputs/he_live_smoke_20260606_haiku45_sanity/results.json`

Observed:

- one real-harness calibration task was run for each of `B1-B5`;
- all five runs reached the real coding-agent harness path and completed at the
  runner layer;
- all five graded as `repair_failure`;
- all five ended with:
  - `Reached the maximum tool step limit for this turn.`

Interpretation:

- the harness path, trace path, and grading path are working for one tiny task
  per family;
- this closes `5.2` as a sanity execution task;
- it is not benchmark-family evidence by itself.

### B. Paired real-harness smoke across three core architectures (`1.46`, `5.3`)

Artifacts:

- `outputs/he_live_smoke_20260606_haiku45_paired3cond/results.json`
- `outputs/he_live_smoke_20260606_haiku45_paired3cond/summary.json`
- `outputs/harness_eval_pilot/paired_tasks_smoke/manifest.json`

Design actually executed:

- paired counterfactual/calibration task suite;
- `B1-B5` coverage;
- 10 task instances total;
- 3 architecture conditions:
  - `single_loop`
  - `single_loop_plus_scouts`
  - `object_governed_mas_plus_verifier`

Observed condition-level summary:

| Condition | Total | Repair success | Repair failure | Protocol failure | Utility/min |
| --- | ---: | ---: | ---: | ---: | ---: |
| `single_loop` | 10 | 2 | 7 | 1 | 0.4955 |
| `single_loop_plus_scouts` | 10 | 2 | 7 | 1 | 0.4806 |
| `object_governed_mas_plus_verifier` | 10 | 1 | 9 | 0 | 0.3076 |

Interpretation:

- the paired suite has now been run on real coding-agent harness conditions;
- the controlled perturbation smoke has now been run across the three required
  core architectures;
- this closes `1.46` and `5.3`.

## Failure Annotation for Executed Smoke (`5.5`)

### Bundle-level comparison

From `outputs/he_live_smoke_20260606_haiku45_paired3cond/results.json`:

| Bundle | Total | Repair success | Repair failure | Protocol failure | Readout |
| --- | ---: | ---: | ---: | ---: | --- |
| `B1` | 6 | 1 | 4 | 1 | one success, one timeout-bearing contrast |
| `B2` | 6 | 0 | 6 | 0 | uniformly hard at `max_steps = 5` |
| `B3` | 6 | 0 | 6 | 0 | uniformly hard at `max_steps = 5` |
| `B4` | 6 | 1 | 4 | 1 | one success, one timeout-bearing contrast |
| `B5` | 6 | 3 | 3 | 0 | strongest cross-condition success signal |

Current smoke-level readout:

- `B5` is the only bundle with success signal in all three conditions;
- `B2` and `B3` remain uniformly unsolved at this budget;
- `B1` and `B4` each show one protocol timeout in the executed 30-run block.

### Protocol-failure rows

There are exactly two protocol failures in the executed paired smoke:

1. `B1`, `single_loop_plus_scouts`, `G1-evidence-needle-counterfactual`
   - terminal error:
     - `Model API timeout: The read operation timed out`
2. `B4`, `single_loop`, `G4-verification-trap-counterfactual`
   - terminal error:
     - `Model API timeout: The read operation timed out`

These are not provider-channel outages like the earlier
`deepseek-v4-pro[1m]` failures. They are task-attempt-time protocol failures
under the replacement-model restart.

For the executed smoke block, annotate these as:

- `PF2 model_api_timeout`

with run-layer status:

- `protocol_failure`

### Mechanism-label counts across executed smoke

Observed diagnostic label totals:

- `adapter_not_grounded_in_public_api`: 5
- `missing_general_rounding_fix`: 3
- `stale_round_down_logic`: 3
- `generator_not_run`: 3
- `incomplete_regeneration`: 3
- `fixture_table_ignored`: 3
- `rule_not_generalized`: 3
- `authority_misranked`: 2
- `stale_policy_source`: 2
- `fixture_not_built`: 3
- `resource_manifest_ignored`: 2
- `missing_recovery_command`: 2
- `missing_recovery_env`: 2
- `source_truth_not_updated`: 1

Interpretation:

- the most common executed-smoke failure mode is verification/integration
  grounding (`adapter_not_grounded_in_public_api`);
- rounding/repair generalization errors and regeneration failures also recur
  strongly;
- the failure comparison is now concrete enough to close `5.5` for the smoke
  blocks that have actually been executed.

## Benchmark-Family Local-Equivalent Smoke (`5.4`)

### Why a local-equivalent execution was needed

The benchmark smoke subset was already frozen at the protocol level in:

- `openspec/changes/study-code-mas-architecture/benchmark-smoke-subset.md`

That protocol file explicitly allowed local fallbacks when the official
benchmark payloads were not vendored:

- SWE-style patch repair -> fresh local patch task with hidden integration check
- repository construction -> locally curated empty-repo requirement-to-package task
- research-code -> PaperBench-style local-equivalent bounded mini task

The current repository still does not contain the official benchmark payloads
expected by the loader path:

- `benchmarks/swe_bench/swe_bench_verified.jsonl` -> missing
- `benchmarks/nl2repo/tasks.jsonl` -> missing
- `benchmarks/mle_bench/tasks.jsonl` -> missing
- `benchmarks/paper_bench/tasks.jsonl` -> missing

That means the honest way to satisfy `5.4` is not to overclaim official
benchmark execution, but to execute the benchmark-family smoke on a
study-local-equivalent manifest that matches the three family contracts.

### What was executed

Task root:

- `outputs/benchmark_family_local_smoke_tasks/`

Manifest:

- `outputs/benchmark_family_local_smoke_tasks/manifest.json`

Family slots bound and executed:

- `PATCH-BENCH-LOCAL`
  - bundle: `patch_repair`
  - path:
    - `outputs/benchmark_family_local_smoke_tasks/patch_repair_local_equiv/`
- `REPO-BENCH-LOCAL`
  - bundle: `repository_construction`
  - path:
    - `outputs/benchmark_family_local_smoke_tasks/repository_construction_local_equiv/`
- `RES-BENCH-LOCAL`
  - bundle: `research_code`
  - path:
    - `outputs/benchmark_family_local_smoke_tasks/research_code_local_equiv/`

Execution artifacts:

- `outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/results.json`
- `outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/summary.json`
- `outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/manual_grader_replay.json`

Execution design:

- real sealed runner path through:
  - `py-src/experiments/harness_eval_pilot/sealed_mini_study.py`
- one constant replacement model:
  - `claude-haiku-4-5-20251001`
- same budget:
  - `max_steps = 5`
- same three core conditions:
  - `single_loop`
  - `single_loop_plus_scouts`
  - `object_governed_mas_plus_verifier`

### Condition-level summary

From `outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/summary.json`:

| Condition | Total | Patch repair | Repository construction | Research-code | Outcome profile | Step-limit rows |
| --- | ---: | --- | --- | --- | --- | ---: |
| `single_loop` | 3 | `repair_failure` | `repair_failure` | `repair_failure` | all three `repair_failure` | 3 |
| `single_loop_plus_scouts` | 3 | `repair_failure` | `repair_failure` | `repair_failure` | all three `repair_failure` | 3 |
| `object_governed_mas_plus_verifier` | 3 | `repair_failure` | `repair_failure` | `repair_failure` | all three `repair_failure` | 3 |

All nine runs:

- completed at the runner layer;
- returned `repair_failure` rather than protocol failure;
- ended with:
  - `Reached the maximum tool step limit for this turn.`

### Family-level failure evidence

#### Patch repair

The live results already carry structured labels in
`outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/results.json`:

- `visible_pass: false`
- `hidden_pass: false`
- `diagnostic_labels`:
  - `missing_general_normalization`

This label is stable across all three conditions.

#### Repository construction

The live results reached `repair_failure`, but the structured grader fields in
`results.json` were null for this family. To recover exact failure semantics, the
copied work directories were replayed through their own graders and written to:

- `outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/manual_grader_replay.json`

Recovered label pattern for all three conditions:

- `visible_pass: false`
- `hidden_pass: false`
- `diagnostic_labels`:
  - `requirements_not_implemented`
  - `cli_contract_missing`

#### Research-code

The same replay method was used for the research-code family via:

- `outputs/he_live_smoke_20260606_benchmark_local_equiv_haiku45/manual_grader_replay.json`

Recovered label pattern for all three conditions:

- `visible_pass: false`
- `hidden_pass: false`
- `diagnostic_labels`:
  - `analysis_not_implemented`
  - `report_contract_missing`

### Why this closes `5.4`

`5.4` asked for benchmark smoke across:

- patch repair;
- repository construction;
- research-code families.

That requirement is now satisfied at the smoke-study level because:

- all three families were bound to explicit local-equivalent task packages;
- all three families were executed through the real coding-agent harness path;
- all three required architecture conditions were run;
- outcome and failure evidence were saved as durable artifacts.

This closes `5.4` as a study-local-equivalent benchmark-family smoke execution
task.

It does not upgrade the claim to official SWE-bench, NL2Repo, MLE-bench, or
PaperBench instance performance.

## What We Can and Cannot Claim

We can now say:

- real coding-agent harness smoke has been executed under one constant
  replacement model;
- one tiny task per `B1-B5` family has been run successfully through the
  harness path;
- the paired perturbation suite has been run across the three required core
  architectures;
- the benchmark-family smoke has been executed across patch repair,
  repository construction, and research-code using study-local-equivalent task
  bindings;
- executed-smoke failures are now annotated and comparable by bundle family;
- benchmark-family local-equivalent failures are now annotated and comparable by
  family.

We still cannot say:

- official SWE-bench vs NL2Repo vs PaperBench-style leaderboard performance;
- outcome differences on the missing official benchmark payloads;
- anything stronger than study-local smoke evidence for the benchmark-family
  block.

## Task-Level Consequence

This note supports marking complete:

- `1.46` real paired task suite on real coding-agent harness conditions
- `5.2` one tiny task per family sanity
- `5.3` controlled perturbation smoke across core architectures
- `5.4` benchmark smoke across patch repair / repository construction / research-code families
- `5.5` annotate all failures and compare results by task family

At this point, all tasks in
`openspec/changes/study-code-mas-architecture/tasks.md`
can be treated as complete.

## Decision

The smoke-study execution is no longer blocked for the current study scope.

The remaining honesty boundary is narrow and stable:

- official benchmark payload binding is still absent locally;
- this change therefore closes on study-local-equivalent smoke evidence rather
  than official benchmark-instance execution evidence.
