# 2026-06-21 Paper A Retrieval Probe

## Goal

Add a current, reproducible search-side benchmark artifact for Paper A without promoting retrieval-only evidence into the paper's main claim.

## Setup

- Corpus: 60 fixed seeded project memories
- Queries: 12 fixed queries
- Families:
  - 10 `single_domain`
  - 2 `cross_domain`
- Stages:
  - `BM25 Only`
  - `Domain Weighted`
  - `Oracle Ceiling`

## Headline Result

- Real retrieval result:
  - `Domain Weighted` improves average `P@3` from `0.333` to `0.528`
  - `Domain Weighted` improves average `R@5` from `0.378` to `0.617`
  - `Domain Weighted` reduces average cross-domain noise from `0.700` to `0.467`
- Diagnostic upper bound:
  - `Oracle Ceiling` reaches `0.778` average `P@3`
  - This stage is ground-truth-guided and is not a deployable pipeline score

## Evidence Paths

- Benchmark summary JSON:
  - `benchmarks/paper_a_retrieval_probe_eval_results.json`
- Benchmark summary Markdown:
  - `benchmarks/paper_a_retrieval_probe_eval_results.md`
- Per-query rows:
  - `outputs/paper_a_retrieval_probe_eval/query_rows.json`

## Paper Use Policy

- Safe use:
  - show that current retrieval is non-trivial and that domain-aware retrieval suppresses cross-domain noise
  - reinforce that search-heavy evidence is secondary
- Unsafe use:
  - claim a fresh LongMemEval rerun
  - cite `Oracle Ceiling` as a real system result
  - convert this paper into a generic search benchmark story
