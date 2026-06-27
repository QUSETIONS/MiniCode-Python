# Paper A External Projection

- Generated at: 2026-06-23T01:42:09.820002+00:00
- Scope: This run is a bounded external-material projection built from the paper-facing multisession bridge query set. It is not an official external benchmark rerun.
- Metric: bounded external-material answer support with provider-blocked accounting
- Termination reason: completed
- Query count: 15
- Condition count: 3

## Provider Preflight

- Status: answered
- Summary: OK
- Trace: D:\Desktop\minicode\outputs\paper_a_external_projection_eval\provider_preflight_trace.json

## Summary

| total_rows | answered_rows | blocked_rows | excluded_rows | exact_support_rate_on_answered | clause_recall_on_answered | abstention_rate_on_answered |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 45 | 45 | 0 | 0 | 0.3556 | 0.4 | 0.4889 |

## Condition Summary

| condition | answered_rows | blocked_rows | excluded_rows | exact_support_rate_on_answered | clause_recall_on_answered | abstention_rate_on_answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Memory-Off | 15 | 0 | 0 | 0.0 | 0.0 | 1.0 |
| Weak-Session | 15 | 0 | 0 | 0.2 | 0.3 | 0.4667 |
| Memory-Backed Continuity | 15 | 0 | 0 | 0.8667 | 0.9 | 0.0 |

## Family Breakdown

| family | condition | answered_rows | blocked_rows | exact_support_rate_on_answered | clause_recall_on_answered |
| --- | --- | ---: | ---: | ---: | ---: |
| multi_hop | Memory-Off | 5 | 0 | 0.0 | 0.0 |
| multi_hop | Weak-Session | 5 | 0 | 0.0 | 0.1 |
| multi_hop | Memory-Backed Continuity | 5 | 0 | 1.0 | 1.0 |
| single_hop | Memory-Off | 5 | 0 | 0.0 | 0.0 |
| single_hop | Weak-Session | 5 | 0 | 0.6 | 0.7 |
| single_hop | Memory-Backed Continuity | 5 | 0 | 1.0 | 1.0 |
| temporal | Memory-Off | 5 | 0 | 0.0 | 0.0 |
| temporal | Weak-Session | 5 | 0 | 0.0 | 0.1 |
| temporal | Memory-Backed Continuity | 5 | 0 | 0.6 | 0.7 |

## Interpretation

- This run is a bounded external-material projection built from the paper-facing multisession bridge query set. It is not an official external benchmark rerun.
- Memory-backed continuity projects stronger exact answer support than weak session on the bounded external-material slice.
- Memory-off remains a negative control on the projected query set.

## Answered Query Details

| condition | query_id | family | exact_support | clause_recall | abstained | matched_phrases |
| --- | --- | --- | --- | ---: | --- | --- |
| Memory-Off | q1 | single_hop | no | 0.0 | yes | - |
| Memory-Off | q2 | single_hop | no | 0.0 | yes | - |
| Memory-Off | q3 | single_hop | no | 0.0 | yes | - |
| Memory-Off | q4 | single_hop | no | 0.0 | yes | - |
| Memory-Off | q5 | single_hop | no | 0.0 | yes | - |
| Memory-Off | q6 | multi_hop | no | 0.0 | yes | - |
| Memory-Off | q7 | multi_hop | no | 0.0 | yes | - |
| Memory-Off | q8 | multi_hop | no | 0.0 | yes | - |
| Memory-Off | q9 | multi_hop | no | 0.0 | yes | - |
| Memory-Off | q10 | multi_hop | no | 0.0 | yes | - |
| Memory-Off | q11 | temporal | no | 0.0 | yes | - |
| Memory-Off | q12 | temporal | no | 0.0 | yes | - |
| Memory-Off | q13 | temporal | no | 0.0 | yes | - |
| Memory-Off | q14 | temporal | no | 0.0 | yes | - |
| Memory-Off | q15 | temporal | no | 0.0 | yes | - |
| Weak-Session | q1 | single_hop | no | 0.0 | yes | - |
| Weak-Session | q2 | single_hop | yes | 1.0 | no | fastapi |
| Weak-Session | q3 | single_hop | no | 0.5 | no | postgis |
| Weak-Session | q4 | single_hop | yes | 1.0 | no | github actions |
| Weak-Session | q5 | single_hop | yes | 1.0 | no | playwright |
| Weak-Session | q6 | multi_hop | no | 0.5 | no | react-hook-form |
| Weak-Session | q7 | multi_hop | no | 0.0 | no | - |
| Weak-Session | q8 | multi_hop | no | 0.0 | yes | - |
| Weak-Session | q9 | multi_hop | no | 0.0 | yes | - |
| Weak-Session | q10 | multi_hop | no | 0.0 | yes | - |
| Weak-Session | q11 | temporal | no | 0.0 | no | - |
| Weak-Session | q12 | temporal | no | 0.0 | yes | - |
| Weak-Session | q13 | temporal | no | 0.0 | yes | - |
| Weak-Session | q14 | temporal | no | 0.5 | no | redis sliding window |
| Weak-Session | q15 | temporal | no | 0.0 | yes | - |
| Memory-Backed Continuity | q1 | single_hop | yes | 1.0 | no | zustand |
| Memory-Backed Continuity | q2 | single_hop | yes | 1.0 | no | fastapi |
| Memory-Backed Continuity | q3 | single_hop | yes | 1.0 | no | postgresql 16, postgis |
| Memory-Backed Continuity | q4 | single_hop | yes | 1.0 | no | github actions |
| Memory-Backed Continuity | q5 | single_hop | yes | 1.0 | no | playwright |
| Memory-Backed Continuity | q6 | multi_hop | yes | 1.0 | no | react-hook-form, zod |
| Memory-Backed Continuity | q7 | multi_hop | yes | 1.0 | no | refresh-token rotation, 15 minutes |
| Memory-Backed Continuity | q8 | multi_hop | yes | 1.0 | no | 2 to 10 pods, 70 percent |
| Memory-Backed Continuity | q9 | multi_hop | yes | 1.0 | no | pytest-asyncio, conftest.py |
| Memory-Backed Continuity | q10 | multi_hop | yes | 1.0 | no | postgresql 16, pgbouncer |
| Memory-Backed Continuity | q11 | temporal | no | 0.0 | no | - |
| Memory-Backed Continuity | q12 | temporal | yes | 1.0 | no | never edited manually |
| Memory-Backed Continuity | q13 | temporal | yes | 1.0 | no | python:3.12-slim |
| Memory-Backed Continuity | q14 | temporal | no | 0.5 | no | redis sliding window |
| Memory-Backed Continuity | q15 | temporal | yes | 1.0 | no | jsonb, gin |
