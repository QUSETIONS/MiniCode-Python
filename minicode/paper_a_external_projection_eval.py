from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from minicode.release_readiness import classify_provider_outcome


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "paper_a_external_projection_eval"
BRIDGE_RESULTS_PATH = BENCHMARKS_DIR / "paper_a_multisession_bridge_eval_results.json"

EVAL_TITLE = "Paper A External Projection"
EVAL_METRIC = (
    "bounded external-material answer support with provider-blocked accounting"
)
EVAL_SCOPE = (
    "This run is a bounded external-material projection built from the paper-facing "
    "multisession bridge query set. It is not an official external benchmark rerun."
)
INSUFFICIENT_SUPPORT_TOKEN = "INSUFFICIENT_SUPPORT"


@dataclass(frozen=True, slots=True)
class ProjectionCondition:
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class ProjectionQuery:
    query_id: str
    family: str
    prompt: str
    required_phrases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SupportBundle:
    retrieved_ids: tuple[str, ...]
    retrieved_contents: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HeadlessExecution:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    trace_path: str = ""


@dataclass(frozen=True, slots=True)
class ProjectionRow:
    condition: str
    condition_label: str
    query_id: str
    family: str
    prompt: str
    required_phrases: tuple[str, ...]
    context_ids: tuple[str, ...]
    context_snippets: tuple[str, ...]
    context_count: int
    status: str
    provider_outcome: str
    provider_summary: str
    response_text: str
    matched_phrases: tuple[str, ...]
    exact_support: bool
    clause_recall: float
    abstained: bool
    blocked_reason: str
    trace_path: str


DEFAULT_CONDITIONS: tuple[ProjectionCondition, ...] = (
    ProjectionCondition(key="memory_off", label="Memory-Off"),
    ProjectionCondition(key="weak_session", label="Weak-Session"),
    ProjectionCondition(
        key="memory_backed_continuity",
        label="Memory-Backed Continuity",
    ),
)


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _normalize_phrase_list(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return tuple(normalized)


def _query_sort_key(query_id: str) -> tuple[int, str]:
    suffix = "".join(character for character in query_id if character.isdigit())
    if suffix.isdigit():
        return (int(suffix), query_id)
    return (10**9, query_id)


def load_external_projection_corpus(
    bridge_results_path: Path = BRIDGE_RESULTS_PATH,
) -> dict[str, Any]:
    payload = json.loads(bridge_results_path.read_text(encoding="utf-8"))
    rows = list(payload.get("rows", []) or [])
    query_map: dict[str, ProjectionQuery] = {}
    support_map: dict[tuple[str, str], SupportBundle] = {}
    labels = {condition.key: condition.label for condition in DEFAULT_CONDITIONS}

    for row in rows:
        condition = str(row.get("condition", "")).strip()
        query_id = str(row.get("query_id", "")).strip()
        if not condition or not query_id:
            continue
        if condition not in labels:
            continue

        prompt = str(row.get("prompt", "")).strip()
        family = str(row.get("family", "")).strip() or "unknown"
        required_phrases = _normalize_phrase_list(row.get("required_phrases", []))
        condition_label = str(row.get("condition_label", "")).strip()
        if condition_label:
            labels[condition] = condition_label

        existing = query_map.get(query_id)
        if existing is None:
            query_map[query_id] = ProjectionQuery(
                query_id=query_id,
                family=family,
                prompt=prompt,
                required_phrases=required_phrases,
            )
        else:
            if existing.prompt != prompt or existing.family != family:
                raise ValueError(
                    f"Bridge query {query_id} is inconsistent across rows."
                )
            if existing.required_phrases != required_phrases:
                raise ValueError(
                    f"Bridge query {query_id} changed required phrases across rows."
                )

        support_map[(condition, query_id)] = SupportBundle(
            retrieved_ids=_normalize_phrase_list(row.get("retrieved_ids", [])),
            retrieved_contents=_normalize_phrase_list(row.get("retrieved_contents", [])),
        )

    queries = sorted(query_map.values(), key=lambda query: _query_sort_key(query.query_id))
    conditions = tuple(
        ProjectionCondition(key=condition.key, label=labels[condition.key])
        for condition in DEFAULT_CONDITIONS
    )
    query_rows = [asdict(query) for query in queries]
    return {
        "source_path": str(bridge_results_path),
        "queries": queries,
        "conditions": conditions,
        "support_map": support_map,
        "query_rows": query_rows,
    }


def build_external_projection_prompt(
    query: ProjectionQuery,
    bundle: SupportBundle,
) -> str:
    lines = [
        "You are running a bounded continuity benchmark over recovered project notes.",
        "Answer the question using only the recovered notes below.",
        f"If the notes do not support a confident answer, reply exactly {INSUFFICIENT_SUPPORT_TOKEN}.",
        "",
        f"Question: {query.prompt}",
        "",
        "Recovered notes:",
    ]
    if bundle.retrieved_contents:
        for index, snippet in enumerate(bundle.retrieved_contents, start=1):
            lines.append(f"{index}. {snippet}")
    else:
        lines.append("(none)")
    lines.extend(
        [
            "",
            "Return a short plain-text answer with no bullets.",
        ]
    )
    return "\n".join(lines)


def run_headless_prompt(
    prompt: str,
    *,
    cwd: str | Path,
    trace_path: str | Path | None = None,
    timeout_seconds: int = 180,
) -> HeadlessExecution:
    command = [sys.executable, "-m", "minicode.headless"]
    env = os.environ.copy()
    if trace_path:
        env["MINI_CODE_HEADLESS_MESSAGES_OUT"] = str(trace_path)

    try:
        completed = subprocess.run(
            command,
            input=prompt,
            cwd=str(cwd),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        return HeadlessExecution(
            command="python -m minicode.headless [projection-prompt]",
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            trace_path=str(trace_path or ""),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return HeadlessExecution(
            command="python -m minicode.headless [projection-prompt]",
            exit_code=124,
            stdout=stdout,
            stderr=stderr,
            trace_path=str(trace_path or ""),
        )


def classify_projection_outcome(execution: HeadlessExecution) -> tuple[str, str]:
    base_status, base_summary = classify_provider_outcome(
        exit_code=execution.exit_code,
        stdout=execution.stdout,
        stderr=execution.stderr,
    )
    if base_status in {"provider_outage", "empty_output", "timeout"}:
        return base_status, base_summary

    stdout = (execution.stdout or "").strip()
    stderr = (execution.stderr or "").strip()
    combined = " ".join(f"{stdout}\n{stderr}".lower().split())

    if stdout and not stdout.lower().startswith("error:"):
        summary = stdout.splitlines()[0].strip()
        return "answered", summary or "Headless projection answered."
    if "config error:" in combined:
        return "error", stdout or stderr or "Config error during projection."
    return "error", base_summary or stdout or stderr or "Projection prompt failed."


def _matched_phrases(response_text: str, required_phrases: tuple[str, ...]) -> tuple[str, ...]:
    normalized_response = _normalize_text(response_text)
    matched: list[str] = []
    for phrase in required_phrases:
        if _normalize_text(phrase) in normalized_response:
            matched.append(phrase)
    return tuple(matched)


def _is_abstention(response_text: str) -> bool:
    normalized = _normalize_text(response_text.replace("_", " "))
    return normalized == "insufficient support"


def _build_blocked_row(
    *,
    condition: ProjectionCondition,
    query: ProjectionQuery,
    bundle: SupportBundle | None,
    provider_outcome: str,
    provider_summary: str,
    blocked_reason: str,
    trace_path: str = "",
) -> ProjectionRow:
    support_bundle = bundle or SupportBundle(retrieved_ids=(), retrieved_contents=())
    return ProjectionRow(
        condition=condition.key,
        condition_label=condition.label,
        query_id=query.query_id,
        family=query.family,
        prompt=query.prompt,
        required_phrases=query.required_phrases,
        context_ids=support_bundle.retrieved_ids,
        context_snippets=support_bundle.retrieved_contents,
        context_count=len(support_bundle.retrieved_contents),
        status="blocked",
        provider_outcome=provider_outcome,
        provider_summary=provider_summary,
        response_text="",
        matched_phrases=(),
        exact_support=False,
        clause_recall=0.0,
        abstained=False,
        blocked_reason=blocked_reason,
        trace_path=trace_path,
    )


def _build_excluded_row(
    *,
    condition: ProjectionCondition,
    query: ProjectionQuery,
    bundle: SupportBundle | None,
    reason: str,
) -> ProjectionRow:
    support_bundle = bundle or SupportBundle(retrieved_ids=(), retrieved_contents=())
    return ProjectionRow(
        condition=condition.key,
        condition_label=condition.label,
        query_id=query.query_id,
        family=query.family,
        prompt=query.prompt,
        required_phrases=query.required_phrases,
        context_ids=support_bundle.retrieved_ids,
        context_snippets=support_bundle.retrieved_contents,
        context_count=len(support_bundle.retrieved_contents),
        status="excluded",
        provider_outcome="excluded",
        provider_summary=reason,
        response_text="",
        matched_phrases=(),
        exact_support=False,
        clause_recall=0.0,
        abstained=False,
        blocked_reason=reason,
        trace_path="",
    )


def _summarize_subset(rows: list[ProjectionRow]) -> dict[str, Any]:
    answered = [row for row in rows if row.status == "answered"]
    blocked = [row for row in rows if row.status == "blocked"]
    excluded = [row for row in rows if row.status == "excluded"]
    exact_rate = None
    clause_recall = None
    abstention_rate = None
    if answered:
        exact_rate = round(
            sum(1 for row in answered if row.exact_support) / len(answered),
            4,
        )
        clause_recall = round(
            sum(row.clause_recall for row in answered) / len(answered),
            4,
        )
        abstention_rate = round(
            sum(1 for row in answered if row.abstained) / len(answered),
            4,
        )
    return {
        "total_rows": len(rows),
        "answered_rows": len(answered),
        "blocked_rows": len(blocked),
        "excluded_rows": len(excluded),
        "exact_support_rate_on_answered": exact_rate,
        "clause_recall_on_answered": clause_recall,
        "abstention_rate_on_answered": abstention_rate,
    }


def _build_interpretation(result: dict[str, Any]) -> list[str]:
    if result["termination_reason"] == "provider_preflight_blocked":
        return [
            "Provider preflight blocked before query execution, so this run only supports blocked-state accounting.",
            EVAL_SCOPE,
        ]

    interpretation = [EVAL_SCOPE]
    summary = dict(result.get("summary", {}) or {})
    if summary.get("answered_rows", 0) == 0:
        interpretation.append(
            "No clean answered rows were collected, so answer-quality interpretation is not justified."
        )
        return interpretation

    condition_summary = dict(result.get("condition_summary", {}) or {})
    weak = dict(condition_summary.get("weak_session", {}) or {})
    continuity = dict(condition_summary.get("memory_backed_continuity", {}) or {})
    memory_off = dict(condition_summary.get("memory_off", {}) or {})

    weak_exact = weak.get("exact_support_rate_on_answered")
    continuity_exact = continuity.get("exact_support_rate_on_answered")
    memory_off_exact = memory_off.get("exact_support_rate_on_answered")

    if weak_exact is not None and continuity_exact is not None:
        if continuity_exact > weak_exact:
            interpretation.append(
                "Memory-backed continuity projects stronger exact answer support than weak session on the bounded external-material slice."
            )
        elif continuity_exact == weak_exact:
            interpretation.append(
                "Memory-backed continuity and weak session land at the same exact-support rate on answered rows in this bounded slice."
            )
    if memory_off_exact == 0:
        interpretation.append(
            "Memory-off remains a negative control on the projected query set."
        )
    if summary.get("blocked_rows", 0):
        interpretation.append(
            "Blocked rows remain separated from answered rows; support rates are computed on answered rows only."
        )
    if summary.get("excluded_rows", 0):
        interpretation.append(
            "Excluded rows reflect malformed or missing projection inputs rather than model behavior."
        )
    return interpretation


def evaluate_external_projection(
    *,
    bridge_results_path: Path = BRIDGE_RESULTS_PATH,
    output_root: Path = OUTPUT_ROOT,
    repo_root: Path = REPO_ROOT,
    headless_runner: Callable[..., HeadlessExecution] = run_headless_prompt,
    max_queries: int | None = None,
) -> dict[str, Any]:
    corpus = load_external_projection_corpus(bridge_results_path)
    queries: list[ProjectionQuery] = list(corpus["queries"])
    if max_queries is not None:
        queries = queries[:max(0, max_queries)]
    conditions: tuple[ProjectionCondition, ...] = tuple(corpus["conditions"])
    support_map: dict[tuple[str, str], SupportBundle] = dict(corpus["support_map"])

    output_root.mkdir(parents=True, exist_ok=True)
    traces_root = output_root / "traces"
    traces_root.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()
    provider_preflight_trace = output_root / "provider_preflight_trace.json"
    preflight_execution = headless_runner(
        "Reply with exactly OK.",
        cwd=repo_root,
        trace_path=provider_preflight_trace,
    )
    preflight_status, preflight_summary = classify_provider_outcome(
        exit_code=preflight_execution.exit_code,
        stdout=preflight_execution.stdout,
        stderr=preflight_execution.stderr,
    )
    provider_preflight = {
        "status": preflight_status,
        "summary": preflight_summary,
        "exit_code": preflight_execution.exit_code,
        "command": preflight_execution.command,
        "stdout": preflight_execution.stdout,
        "stderr": preflight_execution.stderr,
        "trace_path": str(provider_preflight_trace),
    }

    rows: list[ProjectionRow] = []
    termination_reason = "completed"

    if preflight_status != "answered":
        termination_reason = "provider_preflight_blocked"
        for condition in conditions:
            for query in queries:
                bundle = support_map.get((condition.key, query.query_id))
                rows.append(
                    _build_blocked_row(
                        condition=condition,
                        query=query,
                        bundle=bundle,
                        provider_outcome=preflight_status,
                        provider_summary=preflight_summary,
                        blocked_reason="provider_preflight_blocked",
                        trace_path=str(provider_preflight_trace),
                    )
                )
    else:
        for condition in conditions:
            for query in queries:
                bundle = support_map.get((condition.key, query.query_id))
                if not query.prompt or not query.required_phrases:
                    rows.append(
                        _build_excluded_row(
                            condition=condition,
                            query=query,
                            bundle=bundle,
                            reason="missing_query_prompt_or_required_phrases",
                        )
                    )
                    continue
                if bundle is None:
                    rows.append(
                        _build_excluded_row(
                            condition=condition,
                            query=query,
                            bundle=None,
                            reason="missing_condition_support_bundle",
                        )
                    )
                    continue

                prompt = build_external_projection_prompt(query, bundle)
                trace_path = traces_root / condition.key / f"{query.query_id}.json"
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                execution = headless_runner(
                    prompt,
                    cwd=repo_root,
                    trace_path=trace_path,
                )
                provider_outcome, provider_summary = classify_projection_outcome(execution)
                response_text = (execution.stdout or "").strip()
                if provider_outcome != "answered":
                    rows.append(
                        _build_blocked_row(
                            condition=condition,
                            query=query,
                            bundle=bundle,
                            provider_outcome=provider_outcome,
                            provider_summary=provider_summary,
                            blocked_reason=provider_outcome,
                            trace_path=str(trace_path),
                        )
                    )
                    continue

                matched_phrases = _matched_phrases(response_text, query.required_phrases)
                clause_recall = 0.0
                if query.required_phrases:
                    clause_recall = round(
                        len(matched_phrases) / len(query.required_phrases),
                        4,
                    )
                exact_support = bool(query.required_phrases) and len(matched_phrases) == len(
                    query.required_phrases
                )

                rows.append(
                    ProjectionRow(
                        condition=condition.key,
                        condition_label=condition.label,
                        query_id=query.query_id,
                        family=query.family,
                        prompt=query.prompt,
                        required_phrases=query.required_phrases,
                        context_ids=bundle.retrieved_ids,
                        context_snippets=bundle.retrieved_contents,
                        context_count=len(bundle.retrieved_contents),
                        status="answered",
                        provider_outcome=provider_outcome,
                        provider_summary=provider_summary,
                        response_text=response_text,
                        matched_phrases=matched_phrases,
                        exact_support=exact_support,
                        clause_recall=clause_recall,
                        abstained=_is_abstention(response_text),
                        blocked_reason="",
                        trace_path=str(trace_path),
                    )
                )

    row_dicts = [asdict(row) for row in rows]
    condition_summary = {
        condition.key: _summarize_subset(
            [row for row in rows if row.condition == condition.key]
        )
        for condition in conditions
    }
    family_summary: dict[str, dict[str, Any]] = {}
    families = sorted({row.family for row in rows})
    for family in families:
        family_summary[family] = {
            condition.key: _summarize_subset(
                [
                    row
                    for row in rows
                    if row.family == family and row.condition == condition.key
                ]
            )
            for condition in conditions
        }

    result = {
        "title": EVAL_TITLE,
        "metric": EVAL_METRIC,
        "scope": EVAL_SCOPE,
        "generated_at": generated_at,
        "repo_root": str(repo_root),
        "output_root": str(output_root),
        "source_path": corpus["source_path"],
        "termination_reason": termination_reason,
        "provider_preflight": provider_preflight,
        "query_count": len(queries),
        "condition_count": len(conditions),
        "query_rows": corpus["query_rows"][: len(queries)],
        "rows": row_dicts,
        "summary": _summarize_subset(rows),
        "condition_summary": condition_summary,
        "family_summary": family_summary,
    }
    result["interpretation"] = _build_interpretation(result)
    return result


def external_projection_eval_as_markdown(result: dict[str, Any]) -> str:
    summary = dict(result.get("summary", {}) or {})
    provider_preflight = dict(result.get("provider_preflight", {}) or {})
    lines = [
        f"# {result.get('title', EVAL_TITLE)}",
        "",
        f"- Generated at: {result.get('generated_at', '')}",
        f"- Scope: {result.get('scope', EVAL_SCOPE)}",
        f"- Metric: {result.get('metric', EVAL_METRIC)}",
        f"- Termination reason: {result.get('termination_reason', 'completed')}",
        f"- Query count: {result.get('query_count', 0)}",
        f"- Condition count: {result.get('condition_count', 0)}",
        "",
        "## Provider Preflight",
        "",
        f"- Status: {provider_preflight.get('status', '-')}",
        f"- Summary: {provider_preflight.get('summary', '-')}",
        f"- Trace: {provider_preflight.get('trace_path', '-')}",
        "",
        "## Summary",
        "",
        "| total_rows | answered_rows | blocked_rows | excluded_rows | exact_support_rate_on_answered | clause_recall_on_answered | abstention_rate_on_answered |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {summary.get('total_rows', 0)} | {summary.get('answered_rows', 0)} | "
            f"{summary.get('blocked_rows', 0)} | {summary.get('excluded_rows', 0)} | "
            f"{summary.get('exact_support_rate_on_answered')} | "
            f"{summary.get('clause_recall_on_answered')} | "
            f"{summary.get('abstention_rate_on_answered')} |"
        ),
        "",
        "## Condition Summary",
        "",
        "| condition | answered_rows | blocked_rows | excluded_rows | exact_support_rate_on_answered | clause_recall_on_answered | abstention_rate_on_answered |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for condition in DEFAULT_CONDITIONS:
        metrics = dict(result.get("condition_summary", {}).get(condition.key, {}) or {})
        lines.append(
            f"| {condition.label} | {metrics.get('answered_rows', 0)} | "
            f"{metrics.get('blocked_rows', 0)} | {metrics.get('excluded_rows', 0)} | "
            f"{metrics.get('exact_support_rate_on_answered')} | "
            f"{metrics.get('clause_recall_on_answered')} | "
            f"{metrics.get('abstention_rate_on_answered')} |"
        )

    lines.extend(
        [
            "",
            "## Family Breakdown",
            "",
            "| family | condition | answered_rows | blocked_rows | exact_support_rate_on_answered | clause_recall_on_answered |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )

    family_summary = dict(result.get("family_summary", {}) or {})
    for family in sorted(family_summary):
        for condition in DEFAULT_CONDITIONS:
            metrics = dict(family_summary.get(family, {}).get(condition.key, {}) or {})
            lines.append(
                f"| {family} | {condition.label} | {metrics.get('answered_rows', 0)} | "
                f"{metrics.get('blocked_rows', 0)} | "
                f"{metrics.get('exact_support_rate_on_answered')} | "
                f"{metrics.get('clause_recall_on_answered')} |"
            )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
        ]
    )
    for item in list(result.get("interpretation", []) or []):
        lines.append(f"- {item}")

    answered_rows = [
        row
        for row in list(result.get("rows", []) or [])
        if row.get("status") == "answered"
    ]
    lines.extend(
        [
            "",
            "## Answered Query Details",
            "",
            "| condition | query_id | family | exact_support | clause_recall | abstained | matched_phrases |",
            "| --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in answered_rows:
        matched = ", ".join(list(row.get("matched_phrases", []) or []))
        lines.append(
            f"| {row.get('condition_label', row.get('condition', ''))} | "
            f"{row.get('query_id', '')} | {row.get('family', '')} | "
            f"{'yes' if row.get('exact_support') else 'no'} | "
            f"{row.get('clause_recall', 0.0)} | "
            f"{'yes' if row.get('abstained') else 'no'} | "
            f"{matched or '-'} |"
        )

    return "\n".join(lines) + "\n"


def write_external_projection_artifacts(
    result: dict[str, Any],
    *,
    output_json: Path,
    output_md: Path,
) -> dict[str, Any]:
    output_root = Path(result["output_root"])
    output_root.mkdir(parents=True, exist_ok=True)

    query_rows_path = output_root / "query_rows.json"
    answered_rows_path = output_root / "answered_rows.json"
    blocked_rows_path = output_root / "blocked_rows.json"
    excluded_rows_path = output_root / "excluded_rows.json"
    provider_preflight_path = output_root / "provider_preflight.json"

    answered_rows = [
        row for row in list(result.get("rows", []) or []) if row.get("status") == "answered"
    ]
    blocked_rows = [
        row for row in list(result.get("rows", []) or []) if row.get("status") == "blocked"
    ]
    excluded_rows = [
        row for row in list(result.get("rows", []) or []) if row.get("status") == "excluded"
    ]

    query_rows_path.write_text(
        json.dumps(result.get("query_rows", []), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    answered_rows_path.write_text(
        json.dumps(answered_rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    blocked_rows_path.write_text(
        json.dumps(blocked_rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    excluded_rows_path.write_text(
        json.dumps(excluded_rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    provider_preflight_path.write_text(
        json.dumps(result.get("provider_preflight", {}), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    enriched = dict(result)
    enriched["artifacts"] = {
        "json": str(output_json),
        "markdown": str(output_md),
        "query_rows": str(query_rows_path),
        "answered_rows": str(answered_rows_path),
        "blocked_rows": str(blocked_rows_path),
        "excluded_rows": str(excluded_rows_path),
        "provider_preflight": str(provider_preflight_path),
    }

    output_json.write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    output_md.write_text(
        external_projection_eval_as_markdown(enriched),
        encoding="utf-8",
    )
    return enriched


def main() -> None:
    result = evaluate_external_projection()
    enriched = write_external_projection_artifacts(
        result,
        output_json=BENCHMARKS_DIR / "paper_a_external_projection_results.json",
        output_md=BENCHMARKS_DIR / "paper_a_external_projection_results.md",
    )
    artifacts = dict(enriched.get("artifacts", {}) or {})
    print(f"Wrote {artifacts.get('json')}")
    print(f"Wrote {artifacts.get('markdown')}")
    print(f"Wrote {artifacts.get('query_rows')}")
    print(f"Wrote {artifacts.get('answered_rows')}")
    print(f"Wrote {artifacts.get('blocked_rows')}")
    print(f"Wrote {artifacts.get('provider_preflight')}")


if __name__ == "__main__":
    main()
