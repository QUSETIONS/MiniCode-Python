from __future__ import annotations

import json
from pathlib import Path

from minicode.paper_a_external_projection_eval import (
    HeadlessExecution,
    build_external_projection_prompt,
    evaluate_external_projection,
    external_projection_eval_as_markdown,
    load_external_projection_corpus,
    write_external_projection_artifacts,
)


def _write_bridge_fixture(path: Path) -> None:
    payload = {
        "rows": [
            {
                "condition": "memory_off",
                "condition_label": "Memory-Off",
                "query_id": "q1",
                "family": "single_hop",
                "prompt": "What state management library does the project use?",
                "required_phrases": ["zustand"],
                "retrieved_ids": [],
                "retrieved_contents": [],
            },
            {
                "condition": "weak_session",
                "condition_label": "Weak-Session",
                "query_id": "q1",
                "family": "single_hop",
                "prompt": "What state management library does the project use?",
                "required_phrases": ["zustand"],
                "retrieved_ids": ["s1_store"],
                "retrieved_contents": ["State management uses Zustand v4."],
            },
            {
                "condition": "memory_backed_continuity",
                "condition_label": "Memory-Backed Continuity",
                "query_id": "q1",
                "family": "single_hop",
                "prompt": "What state management library does the project use?",
                "required_phrases": ["zustand"],
                "retrieved_ids": ["s1_store", "s5_migrate"],
                "retrieved_contents": [
                    "State management uses Zustand v4.",
                    "The Redux migration is complete.",
                ],
            },
            {
                "condition": "memory_off",
                "condition_label": "Memory-Off",
                "query_id": "q2",
                "family": "multi_hop",
                "prompt": "What database version and extension are used?",
                "required_phrases": ["postgresql 16", "postgis"],
                "retrieved_ids": [],
                "retrieved_contents": [],
            },
            {
                "condition": "weak_session",
                "condition_label": "Weak-Session",
                "query_id": "q2",
                "family": "multi_hop",
                "prompt": "What database version and extension are used?",
                "required_phrases": ["postgresql 16", "postgis"],
                "retrieved_ids": ["s3_db"],
                "retrieved_contents": ["The stack uses PostgreSQL 16 with PostGIS."],
            },
            {
                "condition": "memory_backed_continuity",
                "condition_label": "Memory-Backed Continuity",
                "query_id": "q2",
                "family": "multi_hop",
                "prompt": "What database version and extension are used?",
                "required_phrases": ["postgresql 16", "postgis"],
                "retrieved_ids": ["s3_db", "s3_ops"],
                "retrieved_contents": [
                    "The stack uses PostgreSQL 16 with PostGIS.",
                    "Operational docs pin PostgreSQL 16 and PostGIS for local and CI runs.",
                ],
            },
        ]
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_load_external_projection_corpus_deduplicates_queries(tmp_path: Path) -> None:
    fixture = tmp_path / "bridge.json"
    _write_bridge_fixture(fixture)

    corpus = load_external_projection_corpus(fixture)

    assert corpus["source_path"] == str(fixture)
    assert [query.query_id for query in corpus["queries"]] == ["q1", "q2"]
    assert corpus["support_map"][("weak_session", "q1")].retrieved_contents == (
        "State management uses Zustand v4.",
    )
    prompt = build_external_projection_prompt(
        corpus["queries"][0],
        corpus["support_map"][("memory_backed_continuity", "q1")],
    )
    assert "Recovered notes:" in prompt
    assert "State management uses Zustand v4." in prompt


def test_external_projection_preflight_block_marks_all_rows_blocked(tmp_path: Path) -> None:
    fixture = tmp_path / "bridge.json"
    _write_bridge_fixture(fixture)
    output_root = tmp_path / "outputs"

    def _blocked_runner(prompt: str, *, cwd, trace_path):
        if "Reply with exactly OK." in prompt:
            return HeadlessExecution(
                command="python -m minicode.headless [projection-prompt]",
                exit_code=0,
                stdout="Provider availability failure: all viable fallback models were unavailable.",
                stderr="",
                trace_path=str(trace_path),
            )
        raise AssertionError("query rows should not run after blocked preflight")

    result = evaluate_external_projection(
        bridge_results_path=fixture,
        output_root=output_root,
        repo_root=tmp_path,
        headless_runner=_blocked_runner,
    )

    assert result["termination_reason"] == "provider_preflight_blocked"
    assert result["provider_preflight"]["status"] == "provider_outage"
    assert result["summary"]["blocked_rows"] == 6
    assert result["summary"]["answered_rows"] == 0
    assert all(row["status"] == "blocked" for row in result["rows"])


def test_external_projection_scores_answered_rows_and_writes_artifacts(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "bridge.json"
    _write_bridge_fixture(fixture)
    output_root = tmp_path / "outputs"
    prompts: list[str] = []

    def _runner(prompt: str, *, cwd, trace_path):
        prompts.append(prompt)
        if "Reply with exactly OK." in prompt:
            return HeadlessExecution(
                command="python -m minicode.headless [projection-prompt]",
                exit_code=0,
                stdout="OK",
                stderr="",
                trace_path=str(trace_path),
            )
        if "What state management library does the project use?" in prompt:
            if "(none)" in prompt:
                stdout = "INSUFFICIENT_SUPPORT"
            else:
                stdout = "The project uses Zustand."
        elif "What database version and extension are used?" in prompt:
            if "(none)" in prompt:
                stdout = "INSUFFICIENT_SUPPORT"
            else:
                stdout = "It uses PostgreSQL 16 with PostGIS."
        else:
            raise AssertionError(f"unexpected prompt: {prompt}")
        return HeadlessExecution(
            command="python -m minicode.headless [projection-prompt]",
            exit_code=0,
            stdout=stdout,
            stderr="",
            trace_path=str(trace_path),
        )

    result = evaluate_external_projection(
        bridge_results_path=fixture,
        output_root=output_root,
        repo_root=tmp_path,
        headless_runner=_runner,
    )

    assert result["termination_reason"] == "completed"
    assert result["summary"]["answered_rows"] == 6
    assert result["summary"]["blocked_rows"] == 0
    assert result["condition_summary"]["memory_off"]["exact_support_rate_on_answered"] == 0.0
    assert result["condition_summary"]["weak_session"]["exact_support_rate_on_answered"] == 1.0
    assert (
        result["condition_summary"]["memory_backed_continuity"][
            "exact_support_rate_on_answered"
        ]
        == 1.0
    )
    assert result["condition_summary"]["memory_off"]["abstention_rate_on_answered"] == 1.0
    assert any(
        row["condition"] == "memory_backed_continuity" and row["exact_support"]
        for row in result["rows"]
    )

    enriched = write_external_projection_artifacts(
        result,
        output_json=tmp_path / "paper_a_external_projection_results.json",
        output_md=tmp_path / "paper_a_external_projection_results.md",
    )
    rendered = external_projection_eval_as_markdown(enriched)

    assert "## Condition Summary" in rendered
    assert "Memory-Backed Continuity" in rendered
    assert "bounded external-material projection" in rendered
    assert Path(enriched["artifacts"]["json"]).exists()
    assert Path(enriched["artifacts"]["markdown"]).exists()
    assert Path(enriched["artifacts"]["query_rows"]).exists()
    assert Path(enriched["artifacts"]["answered_rows"]).exists()
    assert Path(enriched["artifacts"]["provider_preflight"]).exists()
    assert len(prompts) == 7
