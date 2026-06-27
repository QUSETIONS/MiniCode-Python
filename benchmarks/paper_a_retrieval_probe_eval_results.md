# Paper A Retrieval Probe Eval

This benchmark isolates the retrieval side of the memory-heavy story on a fixed 60-memory synthetic project corpus and 12 fixed queries.

## Claim Boundary

- `BM25 Only` and `Domain Weighted` are current executable retrieval results.
- `Oracle Ceiling` is a diagnostic upper bound only. It uses ground-truth-guided fake reranking and must not be cited as a deployable system score.

## Headline

Domain weighting raises average P@3 from `0.33` to `0.53` and lowers average cross-domain noise from `70%` to `47%`.

## Overall Summary

| stage | avg_precision_at_3 | avg_recall_at_5 | avg_noise_at_5 | diagnostic_upper_bound |
| --- | ---: | ---: | ---: | --- |
| BM25 Only | 0.333 | 0.378 | 0.700 | False |
| Domain Weighted | 0.528 | 0.617 | 0.467 | False |
| Oracle Ceiling | 0.778 | 0.806 | 0.153 | True |

## Family Breakdown

| stage | single_domain_p@3 | cross_domain_p@3 | single_domain_noise | cross_domain_noise |
| --- | ---: | ---: | ---: | ---: |
| BM25 Only | 0.333 | 0.333 | 0.700 | 0.700 |
| Domain Weighted | 0.533 | 0.500 | 0.440 | 0.600 |
| Oracle Ceiling | 0.833 | 0.500 | 0.133 | 0.250 |

## Query Details

| stage | query_id | family | precision_at_3 | recall_at_5 | noise_at_5 | retrieved_ids |
| --- | --- | --- | ---: | ---: | ---: | --- |
| BM25 Only | q1 | single_domain | 0.333 | 0.200 | 0.600 | fe-02, be-08, fe-13, te-01, be-04 |
| BM25 Only | q2 | single_domain | 0.667 | 0.667 | 0.600 | fe-06, be-02, fe-13, be-04, te-01 |
| BM25 Only | q3 | single_domain | 0.333 | 0.667 | 0.600 | fe-13, be-04, do-05, fe-06, be-03 |
| BM25 Only | q4 | single_domain | 0.667 | 0.667 | 0.600 | be-08, be-07, fe-06, fe-02, te-01 |
| BM25 Only | q5 | single_domain | 0.000 | 0.000 | 1.000 | fe-13, be-04, do-05, be-03, do-01 |
| BM25 Only | q6 | single_domain | 0.000 | 0.333 | 0.600 | fe-13, do-05, do-01, db-10, db-08 |
| BM25 Only | q7 | single_domain | 0.333 | 0.333 | 0.600 | do-01, fe-06, do-05, be-09, fe-02 |
| BM25 Only | q8 | single_domain | 0.667 | 0.667 | 0.600 | do-05, fe-09, do-04, fe-06, be-09 |
| BM25 Only | q9 | single_domain | 0.000 | 0.000 | 1.000 | be-03, db-06, be-04, fe-06, do-05 |
| BM25 Only | q10 | single_domain | 0.333 | 0.333 | 0.800 | te-04, fe-06, fe-09, fe-13, be-04 |
| BM25 Only | q11 | cross_domain | 0.333 | 0.333 | 0.400 | be-15, te-01, fe-06, be-07, be-03 |
| BM25 Only | q12 | cross_domain | 0.333 | 0.333 | 1.000 | fe-06, te-01, fe-02, fe-13, be-03 |
| Domain Weighted | q1 | single_domain | 0.333 | 0.400 | 0.200 | fe-02, be-04, fe-13, fe-01, fe-12 |
| Domain Weighted | q2 | single_domain | 0.667 | 0.667 | 0.200 | fe-06, be-02, fe-13, fe-02, fe-05 |
| Domain Weighted | q3 | single_domain | 0.667 | 0.667 | 0.600 | be-03, be-04, fe-13, do-05, db-08 |
| Domain Weighted | q4 | single_domain | 1.000 | 1.000 | 0.200 | be-08, be-07, be-01, be-03, fe-06 |
| Domain Weighted | q5 | single_domain | 0.000 | 0.333 | 0.600 | db-08, fe-13, be-04, do-05, db-02 |
| Domain Weighted | q6 | single_domain | 0.333 | 0.333 | 0.600 | db-10, db-08, fe-13, do-05, do-01 |
| Domain Weighted | q7 | single_domain | 0.333 | 0.333 | 0.600 | do-01, fe-06, do-05, be-09, fe-02 |
| Domain Weighted | q8 | single_domain | 0.667 | 1.000 | 0.400 | do-04, do-05, fe-09, do-01, fe-06 |
| Domain Weighted | q9 | single_domain | 0.667 | 1.000 | 0.600 | te-02, te-01, be-03, db-06, be-04 |
| Domain Weighted | q10 | single_domain | 0.667 | 0.667 | 0.400 | te-04, te-01, te-02, fe-09, fe-06 |
| Domain Weighted | q11 | cross_domain | 0.333 | 0.333 | 0.400 | be-15, fe-06, be-07, be-03, te-01 |
| Domain Weighted | q12 | cross_domain | 0.667 | 0.667 | 0.800 | db-08, fe-06, te-01, fe-02, fe-13 |
| Oracle Ceiling | q1 | single_domain | 1.000 | 1.000 | 0.000 | fe-02, fe-01, fe-05, fe-06, fe-04 |
| Oracle Ceiling | q2 | single_domain | 0.667 | 0.667 | 0.500 | fe-06, be-02 |
| Oracle Ceiling | q3 | single_domain | 1.000 | 1.000 | 0.000 | be-03, be-04, be-01 |
| Oracle Ceiling | q4 | single_domain | 1.000 | 1.000 | 0.000 | be-08, be-07, be-01 |
| Oracle Ceiling | q5 | single_domain | 1.000 | 1.000 | 0.000 | db-02, db-01, db-03 |
| Oracle Ceiling | q6 | single_domain | 0.333 | 0.333 | 0.000 | db-10 |
| Oracle Ceiling | q7 | single_domain | 0.667 | 0.667 | 0.500 | do-01, te-01 |
| Oracle Ceiling | q8 | single_domain | 1.000 | 1.000 | 0.000 | do-04, do-05, do-01 |
| Oracle Ceiling | q9 | single_domain | 0.667 | 1.000 | 0.000 | te-02, te-01 |
| Oracle Ceiling | q10 | single_domain | 1.000 | 1.000 | 0.333 | te-04, te-01, do-01 |
| Oracle Ceiling | q11 | cross_domain | 0.333 | 0.333 | 0.000 | be-15 |
| Oracle Ceiling | q12 | cross_domain | 0.667 | 0.667 | 0.500 | db-08, fe-06 |

## Non-Claim

This probe does not replace LongMemEval, does not provide answer-quality scoring, and does not turn the paper into a search-heavy winner story.
