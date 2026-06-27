# Paper A Multi-Session Bridge Eval

- Sessions: 5 simulated coding sessions
- Conditions: Memory-Off, Weak-Session, Memory-Backed Continuity
- Query families: 5 single-hop, 5 multi-hop, 5 temporal
- Metric: exact support over top-5 retrieved text plus clause recall

## Condition Summary

| condition | single_exact | multi_exact | temporal_exact | overall_exact | overall_clause_recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Memory-Off | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Weak-Session | 0.60 | 0.00 | 0.40 | 0.33 | 0.43 |
| Memory-Backed Continuity | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## Category Breakdown

| condition | family | exact_support_rate | clause_recall | queries |
| --- | --- | ---: | ---: | ---: |
| Memory-Off | single-hop | 0.000 | 0.000 | 5 |
| Memory-Off | multi-hop | 0.000 | 0.000 | 5 |
| Memory-Off | temporal | 0.000 | 0.000 | 5 |
| Memory-Off | overall | 0.000 | 0.000 | 15 |
| Weak-Session | single-hop | 0.600 | 0.700 | 5 |
| Weak-Session | multi-hop | 0.000 | 0.100 | 5 |
| Weak-Session | temporal | 0.400 | 0.500 | 5 |
| Weak-Session | overall | 0.333 | 0.433 | 15 |
| Memory-Backed Continuity | single-hop | 1.000 | 1.000 | 5 |
| Memory-Backed Continuity | multi-hop | 1.000 | 1.000 | 5 |
| Memory-Backed Continuity | temporal | 1.000 | 1.000 | 5 |
| Memory-Backed Continuity | overall | 1.000 | 1.000 | 15 |

## Query Details

| condition | query_id | family | exact_support | clause_recall | retrieved_ids |
| --- | --- | --- | ---: | ---: | --- |
| Memory-Off | q1 | single-hop | 0 | 0.000 | none |
| Memory-Off | q2 | single-hop | 0 | 0.000 | none |
| Memory-Off | q3 | single-hop | 0 | 0.000 | none |
| Memory-Off | q4 | single-hop | 0 | 0.000 | none |
| Memory-Off | q5 | single-hop | 0 | 0.000 | none |
| Memory-Off | q6 | multi-hop | 0 | 0.000 | none |
| Memory-Off | q7 | multi-hop | 0 | 0.000 | none |
| Memory-Off | q8 | multi-hop | 0 | 0.000 | none |
| Memory-Off | q9 | multi-hop | 0 | 0.000 | none |
| Memory-Off | q10 | multi-hop | 0 | 0.000 | none |
| Memory-Off | q11 | temporal | 0 | 0.000 | none |
| Memory-Off | q12 | temporal | 0 | 0.000 | none |
| Memory-Off | q13 | temporal | 0 | 0.000 | none |
| Memory-Off | q14 | temporal | 0 | 0.000 | none |
| Memory-Off | q15 | temporal | 0 | 0.000 | none |
| Weak-Session | q1 | single-hop | 0 | 0.000 | none |
| Weak-Session | q2 | single-hop | 1 | 1.000 | w2_back, w3_db |
| Weak-Session | q3 | single-hop | 0 | 0.500 | w3_db, w5_test, w1_front |
| Weak-Session | q4 | single-hop | 1 | 1.000 | w4_ops |
| Weak-Session | q5 | single-hop | 1 | 1.000 | w5_test, w3_db, w2_back |
| Weak-Session | q6 | multi-hop | 0 | 0.500 | w5_test, w4_ops, w2_back, w1_front |
| Weak-Session | q7 | multi-hop | 0 | 0.000 | w2_back, w5_test, w3_db, w4_ops, w1_front |
| Weak-Session | q8 | multi-hop | 0 | 0.000 | w4_ops |
| Weak-Session | q9 | multi-hop | 0 | 0.000 | w2_back, w5_test, w3_db, w1_front, w4_ops |
| Weak-Session | q10 | multi-hop | 0 | 0.000 | w3_db, w5_test, w2_back, w1_front |
| Weak-Session | q11 | temporal | 1 | 1.000 | w5_test, w1_front, w3_db, w2_back |
| Weak-Session | q12 | temporal | 0 | 0.000 | w4_ops |
| Weak-Session | q13 | temporal | 0 | 0.000 | w4_ops, w3_db, w2_back |
| Weak-Session | q14 | temporal | 1 | 1.000 | w2_back, w3_db |
| Weak-Session | q15 | temporal | 0 | 0.500 | w3_db, w2_back, w1_front |
| Memory-Backed Continuity | q1 | single-hop | 1 | 1.000 | s1_store, s5_migrate, s1_forms, s3_db, s5_e2e |
| Memory-Backed Continuity | q2 | single-hop | 1 | 1.000 | s2_api, s3_db, s5_tests, s2_rate, s5_migrate |
| Memory-Backed Continuity | q3 | single-hop | 1 | 1.000 | s3_mig, s3_db, s2_api, s1_store, s4_ci |
| Memory-Backed Continuity | q4 | single-hop | 1 | 1.000 | s4_ci, s5_e2e, s3_db, s5_migrate, s1_forms |
| Memory-Backed Continuity | q5 | single-hop | 1 | 1.000 | s5_e2e, s3_db, s4_k8s, s5_migrate, s2_api |
| Memory-Backed Continuity | q6 | multi-hop | 1 | 1.000 | s1_forms, s5_migrate, s1_store, s3_db, s5_e2e |
| Memory-Backed Continuity | q7 | multi-hop | 1 | 1.000 | s2_auth, s2_api, s3_db, s5_migrate, s2_rate |
| Memory-Backed Continuity | q8 | multi-hop | 1 | 1.000 | s4_k8s, s4_docker, s5_e2e, s1_forms, s5_tests |
| Memory-Backed Continuity | q9 | multi-hop | 1 | 1.000 | s2_api, s5_tests, s3_mig, s4_ci, s2_auth |
| Memory-Backed Continuity | q10 | multi-hop | 1 | 1.000 | s3_db, s3_mig, s5_migrate, s2_api, s4_k8s |
| Memory-Backed Continuity | q11 | temporal | 1 | 1.000 | s5_migrate, s1_store, s1_forms, s3_db, s2_api |
| Memory-Backed Continuity | q12 | temporal | 1 | 1.000 | s3_mig, s3_db, s4_k8s |
| Memory-Backed Continuity | q13 | temporal | 1 | 1.000 | s4_docker, s3_db, s4_k8s, s5_migrate, s2_api |
| Memory-Backed Continuity | q14 | temporal | 1 | 1.000 | s2_rate, s2_api, s3_db, s5_migrate, s5_tests |
| Memory-Backed Continuity | q15 | temporal | 1 | 1.000 | s3_jsonb, s3_db, s1_forms, s5_migrate, s2_api |
