---
title: "LongMemEval Preference Reader Build Plan"
date: 2026-06-03
change: repair-longmemeval-preference-reader
design-doc: Docs/Documentation/superpowers/specs/2026-06-03-longmemeval-preference-reader-design.md
build-mode: subagent-driven-development
isolation: branch
status: complete
archived-with: 2026-06-03-repair-longmemeval-preference-reader
---

# LongMemEval Preference Reader Build Plan

> Execute this plan with `subagent-driven-development`. Each task is intentionally
> narrow and should stay inside the current `paper_experiments/` reader/extraction
> scripts plus their tests.

## Shared Context

- Archived change: `repair-longmemeval-preference-reader`
- OpenSpec artifacts:
  - `openspec/changes/archive/2026-06-03-repair-longmemeval-preference-reader/proposal.md`
  - `openspec/changes/archive/2026-06-03-repair-longmemeval-preference-reader/design.md`
  - `openspec/changes/archive/2026-06-03-repair-longmemeval-preference-reader/tasks.md`
- Design Doc:
  - `Docs/Documentation/superpowers/specs/2026-06-03-longmemeval-preference-reader-design.md`
- Current live-run artifact:
  - `paper_experiments/results/longmemeval_answer_extraction_typeaware_preference2_real_2026-06-02_modelfallback.json`

## Task 1: Outage-Aware Live-Smoke Reporting

Goal: separate provider outages from genuine answer-quality failures in saved run
artifacts and top-level summary output.

- [x] Add explicit row-level outcome classification to
      `paper_experiments/scripts/28_typeaware_answer_extraction.py`
- [x] Include summary buckets for `provider_outage`, `empty_output`,
      `answer_error`, and `answered`
- [x] Add or extend tests in `tests/test_typeaware_answer_extraction.py`
- [x] Run targeted local validation for the touched tests

Deliverable:

- updated answer-extraction summary that makes outage rows unmistakable
- fast preflight hard-fail guard so obvious provider outages stop after a
  single probe call instead of a full reader attempt

## Task 2: Clean Real-Smoke Retry

Goal: obtain at least one non-error real-model response for `54026fce` or
`1a1907b4` without broadening scope.

- [x] Reuse the current targeted real-run entrypoint and current model fallback chain
- [x] Save a new result artifact under `paper_experiments/results/`
- [x] Record which model answered, or confirm that the run is still blocked by
      provider availability

Deliverable:

- one new real-smoke artifact plus a short blocker reading

## Task 3: Broad-Answer Re-evaluation

Goal: judge whether the latest broad-answer shaping actually reduces example
latching once a clean live response exists.

- [x] Inspect the new real-smoke output for `54026fce` and `1a1907b4`
- [x] Decide whether the answer stays at the `suggestions that ...` level or
      still collapses onto one assistant example
- [x] Update the result note if further prompt work is still needed

Deliverable:

- concise evaluation note that separates availability blocker from answer-shape outcome

## Exit Condition

This build plan is complete when tasks 1-3 have been executed, the related OpenSpec
tasks are checked off, and the change is ready to move into verify with a concrete
verification report path.

Completion snapshot:

- OpenSpec tasks are fully checked off in the archived change directory.
- Verification report path is `Docs/Documentation/superpowers/reports/2026-06-03-repair-longmemeval-preference-reader-verify.md`.
- The change is already archived under `openspec/changes/archive/2026-06-03-repair-longmemeval-preference-reader/`.
