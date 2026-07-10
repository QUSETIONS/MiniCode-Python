from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from minicode.paper_a_retrieval_probe_eval import (
    OUTPUT_ROOT,
    evaluate_retrieval_probe,
    retrieval_probe_eval_as_dict,
    retrieval_probe_eval_as_markdown,
)


ROOT = Path(__file__).resolve().parent.parent


def _load_benchmark_module():
    benchmark_path = ROOT / "benchmarks" / "paper_a_retrieval_probe_eval.py"
    spec = importlib.util.spec_from_file_location(
        "paper_a_retrieval_probe_eval_benchmark",
        benchmark_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retrieval_probe_rows_load_from_canonical_seed() -> None:
    rows = evaluate_retrieval_probe()

    assert len(rows) == 36
    assert rows[0]["stage"] == "bm25_only"
    assert rows[0]["query_id"] == "q1"
    assert rows[1]["stage"] == "domain_weighted"
    assert rows[2]["stage"] == "oracle_ceiling"
    assert rows[-1]["stage"] == "oracle_ceiling"
    assert rows[-1]["query_id"] == "q12"


def test_retrieval_probe_summary_matches_committed_claim_boundary() -> None:
    payload = retrieval_probe_eval_as_dict(evaluate_retrieval_probe())

    assert payload["memory_count"] == 60
    assert payload["query_count"] == 12
    assert payload["stage_summary"]["bm25_only"]["overall"]["avg_precision_at_3"] == (
        0.3333333333333333
    )
    assert payload["stage_summary"]["domain_weighted"]["overall"]["avg_precision_at_3"] == (
        0.5277777777777778
    )
    assert payload["stage_summary"]["domain_weighted"]["overall"]["avg_recall_at_5"] == (
        0.6166666666666666
    )
    assert payload["stage_summary"]["domain_weighted"]["overall"]["avg_noise_at_5"] == (
        0.4666666666666666
    )
    assert payload["headline_metrics"]["real_precision_gain"] == 0.19444444444444448
    assert payload["claim_boundary"]["diagnostic_upper_bound_stage"] == "oracle_ceiling"


def test_retrieval_probe_markdown_renders_expected_sections() -> None:
    rendered = retrieval_probe_eval_as_markdown(evaluate_retrieval_probe())

    assert "# Paper A Retrieval Probe Eval" in rendered
    assert "## Overall Summary" in rendered
    assert "| Domain Weighted | 0.528 | 0.617 | 0.467 | False |" in rendered
    assert "This probe does not replace LongMemEval" in rendered


def test_benchmark_script_main_writes_artifacts(tmp_path: Path) -> None:
    module = _load_benchmark_module()
    module.BENCHMARKS_DIR = tmp_path / "benchmarks"
    module.OUTPUT_ROOT = tmp_path / "outputs"

    module.main()

    json_path = module.BENCHMARKS_DIR / "paper_a_retrieval_probe_eval_results.json"
    md_path = module.BENCHMARKS_DIR / "paper_a_retrieval_probe_eval_results.md"
    rows_path = module.OUTPUT_ROOT / "query_rows.json"

    assert json_path.exists()
    assert md_path.exists()
    assert rows_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["output_root"] == str(module.OUTPUT_ROOT)
    assert payload["repo_root"] == str(ROOT)
    assert payload["stage_summary"]["oracle_ceiling"]["overall"]["avg_precision_at_3"] == (
        0.7777777777777778
    )

    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    assert len(rows) == 36
    assert rows[0]["stage"] == "bm25_only"
    assert rows[1]["stage"] == "domain_weighted"
    assert rows[2]["stage"] == "oracle_ceiling"
    assert "Domain weighting raises average P@3" in md_path.read_text(encoding="utf-8")
