---
title: "LongMemEval Preference Reader Repair Design"
date: 2026-06-03
comet_change: repair-longmemeval-preference-reader
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-03-repair-longmemeval-preference-reader
status: final
---

# LongMemEval Preference Reader Repair Design

## Goal

Drive the current `single-session-preference` repair line to a state where we can
separate three outcomes cleanly:

- local conversion and prompt assembly are correct
- live failures are caused by provider availability
- any remaining wrong answers are real answer-shape problems rather than outage noise

## Scope

This design only covers the active LongMemEval preference-reader repair work in:

- `paper_experiments/scripts/27_typeaware_reader_probe.py`
- `paper_experiments/scripts/28_typeaware_answer_extraction.py`
- `tests/test_typeaware_reader_probe.py`
- `tests/test_typeaware_answer_extraction.py`

It does not absorb or redefine the existing `study-code-mas-architecture` change.

## Current Baseline

The local repair line already has three important properties:

1. `single-session-preference` conversion now prefers durable anchors and broad-goal
   summaries over literalized assistant examples.
2. real-smoke rows record `model_used`, and the reader client can fall back from
   `ANTHROPIC_MODEL` to `ANTHROPIC_MODEL_FALLBACKS`
3. the regression suite is green, so current uncertainty is mostly external

The remaining ambiguity is that live smoke output can still collapse into
provider-shaped `HTTP 503` rows, which makes the result summary look like answer
failure even when retrieval and prompt assembly are behaving as intended.

## Design Direction

### 1. Treat provider availability as first-class result state

Real-run output should make outage rows obvious at both the per-example and summary
level. We should not force the user to infer from raw prediction strings whether a
failure is an upstream availability event or a model-quality regression.

### 2. Preserve broad-answer evaluation boundaries

For hard cases like `54026fce` and `1a1907b4`, the next quality decision should be
made only after at least one clean live response exists. Until then, prompt shaping
and context ordering should be judged locally, while live smoke remains an external
signal gate.

### 3. Keep implementation narrowly scoped

All follow-up changes should stay inside the current reader/extraction scripts and
their tests unless a new failure clearly demands a wider boundary.

## Workstreams

### Workstream A: Outage-Aware Reporting

- classify live rows into `provider_outage`, `empty_output`, `answer_error`, or
  `answered`
- surface those buckets in the run summary so `F1=0` outage rows are not mistaken
  for semantic regressions

### Workstream B: Clean Real-Smoke Signal

- rerun targeted real smokes for `54026fce` and `1a1907b4`
- keep model-candidate attribution in the saved artifact
- stop once at least one non-error response exists for answer-shape inspection

### Workstream C: Broad-Answer Re-evaluation

- once a clean live response exists, inspect whether the answer now stays at the
  level of `suggestions that ...` instead of latching onto one assistant example
- only then decide whether more prompt shaping is needed

## Task Routing

The remaining work naturally splits into three execution groups:

1. reporting changes in `28_typeaware_answer_extraction.py`
2. targeted real-smoke reruns and artifact review
3. post-smoke answer-shape judgement for the broad preference cases

This means the current Comet change is ready to leave `open`, enter `design`, and
hand off into a focused build/verify sequence without reopening scope.

## Exit Criteria

This design phase is complete when:

- the Design Doc is linked from `.comet.yaml`
- the Comet handoff package is generated and traceable
- the remaining tasks are explicit enough to route into build/verify work without
  revisiting change ownership
