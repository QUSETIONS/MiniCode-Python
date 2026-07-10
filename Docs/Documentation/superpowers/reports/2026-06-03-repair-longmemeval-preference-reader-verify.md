# Verify Report: repair-longmemeval-preference-reader

Date: 2026-06-03
Change: `repair-longmemeval-preference-reader`
Mode: `full` (manual fallback + Comet state checks)
Status: pass; change archived

## Verification scope

- Type-aware reader fallback and preference-reader behavior
- Type-aware answer extraction outage-aware reporting
- Provider-preflight hard-fail behavior for outage periods
- Targeted real-smoke evidence for `54026fce` and `1a1907b4`
- OpenSpec change artifacts and results notes

## Evidence

1. Local regression/build checks passed

```bash
pytest -q tests/test_typeaware_reader_probe.py tests/test_typeaware_answer_extraction.py
python -m py_compile paper_experiments/scripts/27_typeaware_reader_probe.py paper_experiments/scripts/28_typeaware_answer_extraction.py tests/test_typeaware_reader_probe.py tests/test_typeaware_answer_extraction.py
```

Observed result: `99 passed in 1.82s`

2. Outage-aware reporting is implemented and covered by tests in:

- `paper_experiments/scripts/28_typeaware_answer_extraction.py`
- `tests/test_typeaware_answer_extraction.py`

3. Fast provider-preflight hard-fail is implemented and produces an explicit blocked result when the provider path is unavailable:

- `paper_experiments/results/longmemeval_answer_extraction_typeaware_preference_preflight_hardfail_2026-06-03.json`

Key fields:

- `run_status = blocked`
- `termination_reason = provider_preflight_blocked`
- `provider_preflight.status = provider_outage`
- `api_calls = 1`
- `evaluated = 0`

4. Fresh live retries on 2026-06-03 still hit provider instability, but the failure class is now explicit:

- `paper_experiments/results/longmemeval_answer_extraction_typeaware_preference1_real_54026fce_2026-06-03_cleanretry_a.json`
- `paper_experiments/results/longmemeval_answer_extraction_typeaware_preference1_real_1a1907b4_2026-06-03_cleanretry_b.json`

Both rows end as `provider_outage`, with fallback reaching `qwen3.6-plus` and `answer_session_in_context=true`.

5. Historical clean live evidence exists and remains the last non-error anchor for answer-shape inspection:

- `paper_experiments/results/longmemeval_answer_extraction_typeaware_preference3_real_2026-05-31_optimize.json`
- `paper_experiments/results/2026-06-03_preference_answer_shape_recheck.md`

This confirms at least one non-error real-model answer for `54026fce`, but no fresh answered row was produced on 2026-06-03, so answer quality cannot be re-scored from today's live runs.

6. Comet/OpenSpec closeout state is already complete:

- archived change directory:
  `openspec/changes/archive/2026-06-03-repair-longmemeval-preference-reader/`
- archived `.comet.yaml` records:
  - `phase = archive`
  - `verify_result = pass`
  - `branch_status = handled`
  - `archived = true`

## Findings

- Build/test status for the scoped reader and answer-extraction changes is PASS.
- Provider/model fallback and outage-aware reporting are working as designed.
- Provider-preflight hard-fail now fails fast and labels the run as blocked instead of spending a full reader pass on a global outage.
- The current live blocker is provider availability, not a newly confirmed reader-context regression.
- Today's live retries produced no answered rows, so answer quality on broad preferences still depends on the older clean artifact rather than a fresh 2026-06-03 answer.

## Verify caveat

`openspec-verify-change` was not available in this environment, so full verification was completed manually against the design doc, task checklist, local tests, and saved live artifacts.

## Closeout

The change has already passed verify and been archived. The remaining cleanup work was documentary only: align this report with the archived Comet/OpenSpec state and the latest `99 passed` regression snapshot.
