from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
import re
from typing import Any, Callable

from minicode.agent_loop import run_agent_turn
from minicode.tooling import ToolRegistry
from minicode.types import ChatMessage, ModelAdapter, RuntimeEvent


@dataclass(frozen=True, slots=True)
class RuntimeEvalCondition:
    label: str
    runtime: dict[str, Any] | None = None
    max_steps: int = 50

    @property
    def runtime_profile(self) -> str:
        if not self.runtime:
            return "single"
        value = str(self.runtime.get("runtimeProfile") or "single").strip()
        return value or "single"


@dataclass(frozen=True, slots=True)
class RuntimeEvalScenario:
    name: str
    messages: list[ChatMessage]
    model_factory: Callable[[], ModelAdapter]
    tools_factory: Callable[[], ToolRegistry]
    cwd: str = "."
    max_steps: int | None = None


@dataclass(frozen=True, slots=True)
class RuntimeEvalRow:
    scenario: str
    condition: str
    runtime_profile: str
    wall_time_ms: float
    model_calls: int
    tool_starts: int
    tool_results: int
    progress_events: int
    runtime_events: int
    runtime_event_counts: dict[str, int]
    runtime_trace: list[str]
    assistant_messages: int
    stop_reason: str
    widened: bool
    verification_guard_triggered: bool
    completed: bool
    final_message: str


@dataclass(frozen=True, slots=True)
class ProviderFailureClassification:
    category: str
    retryable: bool
    ownership: str
    recovery_action: str


@dataclass(frozen=True, slots=True)
class ProviderDiagnostic:
    label: str
    outcome: str
    command: str
    exit_code: int
    summary: str
    stdout: str = ""
    stderr: str = ""
    risk_scope: str = "unknown"
    error_code: str = ""
    request_id: str = ""
    failure_category: str = "unknown"
    retryable: bool = False
    ownership: str = "unknown"
    recovery_action: str = ""
    readiness_status: str = ""
    repair_step_count: int = 0
    trace_artifact: str = ""
    guidance: list[str] = field(default_factory=list)


_ERROR_CODE_PATTERNS = (
    re.compile(r"\berror\s+code\s*[:=]\s*([A-Za-z0-9_.:-]+)", re.IGNORECASE),
    re.compile(r"\bcode\s*[:=]\s*([A-Za-z0-9_.:-]+)", re.IGNORECASE),
)
_REQUEST_ID_PATTERNS = (
    re.compile(r"\brequest[\s_-]*id\s*[:=]\s*([A-Za-z0-9_.:-]+)", re.IGNORECASE),
    re.compile(r"\bx-request-id\s*[:=]\s*([A-Za-z0-9_.:-]+)", re.IGNORECASE),
)


def extract_provider_error_context(*parts: str) -> dict[str, str]:
    text = "\n".join(part for part in parts if part)
    error_code = ""
    request_id = ""
    for pattern in _ERROR_CODE_PATTERNS:
        match = pattern.search(text)
        if match:
            error_code = match.group(1).strip(".,; ")
            break
    for pattern in _REQUEST_ID_PATTERNS:
        match = pattern.search(text)
        if match:
            request_id = match.group(1).strip(".,; ")
            break
    return {
        "error_code": error_code,
        "request_id": request_id,
    }


def classify_provider_failure(
    outcome: str,
    error_code: str = "",
    summary: str = "",
    risk_scope: str = "unknown",
) -> ProviderFailureClassification:
    code = str(error_code).strip().lower()
    if outcome == "answered":
        return ProviderFailureClassification(
            "none", False, "none", "No recovery action required."
        )
    if code in {"401", "403"}:
        return ProviderFailureClassification(
            "authentication",
            False,
            "local-configuration",
            "Verify the configured provider credential and endpoint.",
        )
    if code == "429":
        return ProviderFailureClassification(
            "rate-limited",
            True,
            "external-provider",
            "Honor provider retry guidance or switch to a ready fallback.",
        )
    if outcome == "provider_api_error" and code == "1010":
        return ProviderFailureClassification(
            "provider-rejected-request",
            False,
            "external-provider",
            "Inspect the provider contract, selected model, and sanitized request evidence.",
        )
    if outcome == "provider_outage" or code.startswith("5"):
        return ProviderFailureClassification(
            "provider-unavailable",
            True,
            "external-provider",
            "Retry the provider smoke or switch to a ready fallback.",
        )
    if outcome == "timeout":
        return ProviderFailureClassification(
            "timeout",
            True,
            "external-provider",
            "Retry within the bounded smoke timeout or switch fallback.",
        )
    if outcome == "provider_channel_unavailable":
        return ProviderFailureClassification(
            "configuration",
            False,
            "local-configuration",
            "Repair model-to-provider channel configuration.",
        )
    if outcome == "empty_output":
        return ProviderFailureClassification(
            "provider-response",
            True,
            "external-provider",
            "Inspect the sanitized response trace before retrying.",
        )
    return ProviderFailureClassification(
        "unknown",
        False,
        risk_scope or "unknown",
        "Inspect sanitized provider diagnostics before choosing a recovery action.",
    )


def _looks_like_terminal_fallback(message: str) -> bool:
    normalized = " ".join(message.lower().split())
    return (
        normalized.startswith("reached the maximum tool step limit")
        or normalized.startswith("model api error")
        or normalized.startswith("model api timeout")
        or normalized.startswith("network error")
        or "empty response" in normalized
    )


def _runtime_event_trace_token(event: RuntimeEvent) -> str:
    step_suffix = f"@{event.step}" if event.step is not None else ""
    if event.category == "phase":
        detail = event.phase or "unknown"
        return f"phase:{detail}{step_suffix}"
    if event.category == "compaction":
        detail = event.phase or "unknown"
        return f"compact:{detail}{step_suffix}"
    if event.category == "guard":
        detail = event.verification_focus or "guard"
        return f"guard:{detail}{step_suffix}"
    if event.category == "widening":
        detail = event.widening_reason or "widen"
        return f"widen:{detail}{step_suffix}"
    if event.category == "recovery":
        detail = event.evidence_summary or "recovery"
        return f"recover:{detail}{step_suffix}"
    if event.category == "stop":
        detail = event.stop_reason or "stop"
        return f"stop:{detail}{step_suffix}"
    return f"{event.category}{step_suffix}"


def _runtime_trace_preview(trace: list[str], max_items: int = 8) -> str:
    if len(trace) <= max_items:
        return " -> ".join(trace)
    head = trace[:max_items]
    remaining = len(trace) - max_items
    return " -> ".join(head) + f" -> ... (+{remaining} more)"


def evaluate_runtime_profiles(
    *,
    scenarios: list[RuntimeEvalScenario],
    conditions: list[RuntimeEvalCondition],
) -> list[RuntimeEvalRow]:
    rows: list[RuntimeEvalRow] = []
    for scenario in scenarios:
        for condition in conditions:
            model = scenario.model_factory()
            tools = scenario.tools_factory()
            progress_events: list[str] = []
            runtime_events: list[RuntimeEvent] = []
            assistant_messages: list[str] = []
            tool_starts = 0
            tool_results = 0

            def increment_counter(counter_name: str) -> None:
                nonlocal tool_starts, tool_results
                if counter_name == "tool_starts":
                    tool_starts += 1
                    return
                tool_results += 1

            start = time.perf_counter()
            messages = run_agent_turn(
                model=model,
                tools=tools,
                messages=list(scenario.messages),
                cwd=scenario.cwd,
                max_steps=(
                    scenario.max_steps
                    if scenario.max_steps is not None
                    else condition.max_steps
                ),
                runtime=condition.runtime,
                on_progress_message=progress_events.append,
                on_runtime_event=runtime_events.append,
                on_assistant_message=assistant_messages.append,
                on_tool_start=lambda *_args: increment_counter("tool_starts"),
                on_tool_result=lambda *_args: increment_counter("tool_results"),
            )
            wall_time_ms = (time.perf_counter() - start) * 1000.0

            final_message = ""
            if messages:
                final_message = str(messages[-1].get("content", "") or "")
            runtime_event_counts: dict[str, int] = {}
            for event in runtime_events:
                runtime_event_counts[event.category] = (
                    runtime_event_counts.get(event.category, 0) + 1
                )
            runtime_trace = [
                _runtime_event_trace_token(event)
                for event in runtime_events
            ]
            stop_reason = ""
            for event in reversed(runtime_events):
                if event.category == "stop" and event.stop_reason:
                    stop_reason = event.stop_reason
                    break
            rows.append(
                RuntimeEvalRow(
                    scenario=scenario.name,
                    condition=condition.label,
                    runtime_profile=condition.runtime_profile,
                    wall_time_ms=wall_time_ms,
                    model_calls=int(getattr(model, "calls", 0)),
                    tool_starts=tool_starts,
                    tool_results=tool_results,
                    progress_events=len(progress_events),
                    runtime_events=len(runtime_events),
                    runtime_event_counts=runtime_event_counts,
                    runtime_trace=runtime_trace,
                    assistant_messages=len(assistant_messages),
                    stop_reason=stop_reason,
                    widened=any(
                        event.category == "widening"
                        for event in runtime_events
                    ),
                    verification_guard_triggered=any(
                        event.category == "guard"
                        for event in runtime_events
                    ),
                    completed=bool(final_message) and not _looks_like_terminal_fallback(final_message),
                    final_message=final_message,
                )
            )

    return rows


def summarize_runtime_profile_eval(
    rows: list[RuntimeEvalRow],
) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for row in rows:
        bucket = summary.setdefault(
            row.condition,
            {
                "runs": 0,
                "completed_runs": 0,
                "widened_runs": 0,
                "verification_guard_runs": 0,
                "total_model_calls": 0,
                "total_tool_starts": 0,
                "total_tool_results": 0,
                "total_runtime_events": 0,
                "total_wall_time_ms": 0.0,
            },
        )
        bucket["runs"] += 1
        bucket["completed_runs"] += int(row.completed)
        bucket["widened_runs"] += int(row.widened)
        bucket["verification_guard_runs"] += int(row.verification_guard_triggered)
        bucket["total_model_calls"] += row.model_calls
        bucket["total_tool_starts"] += row.tool_starts
        bucket["total_tool_results"] += row.tool_results
        bucket["total_runtime_events"] += row.runtime_events
        bucket["total_wall_time_ms"] += row.wall_time_ms

    for bucket in summary.values():
        runs = int(bucket["runs"]) or 1
        bucket["completion_rate"] = bucket["completed_runs"] / runs
        bucket["widened_rate"] = bucket["widened_runs"] / runs
        bucket["verification_guard_rate"] = (
            bucket["verification_guard_runs"] / runs
        )
        bucket["avg_model_calls"] = bucket["total_model_calls"] / runs
        bucket["avg_tool_starts"] = bucket["total_tool_starts"] / runs
        bucket["avg_tool_results"] = bucket["total_tool_results"] / runs
        bucket["avg_runtime_events"] = bucket["total_runtime_events"] / runs
        bucket["avg_wall_time_ms"] = bucket["total_wall_time_ms"] / runs
    return summary


def runtime_profile_eval_as_dict(
    rows: list[RuntimeEvalRow],
    provider_diagnostics: list[ProviderDiagnostic] | None = None,
) -> dict[str, Any]:
    payload = {
        "rows": [asdict(row) for row in rows],
        "summary": summarize_runtime_profile_eval(rows),
    }
    if provider_diagnostics is not None:
        payload["provider_diagnostics"] = [
            asdict(item) for item in provider_diagnostics
        ]
    return payload


def runtime_profile_eval_as_markdown(
    rows: list[RuntimeEvalRow],
    provider_diagnostics: list[ProviderDiagnostic] | None = None,
) -> str:
    summary = summarize_runtime_profile_eval(rows)
    lines = ["# Runtime Profile Eval", ""]
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| condition | runs | completion_rate | widened_rate | verification_guard_rate | avg_model_calls | avg_runtime_events | avg_wall_time_ms |"
    )
    lines.append(
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    for condition, bucket in sorted(summary.items()):
        lines.append(
            "| "
            f"{condition} | {int(bucket['runs'])} | {bucket['completion_rate']:.2f} | "
            f"{bucket['widened_rate']:.2f} | {bucket['verification_guard_rate']:.2f} | "
            f"{bucket['avg_model_calls']:.2f} | {bucket['avg_runtime_events']:.2f} | "
            f"{bucket['avg_wall_time_ms']:.2f} |"
        )

    lines.append("")
    lines.append("## Scenario Rows")
    lines.append("")
    lines.append(
        "| scenario | condition | completed | stop_reason | widened | verification_guard | runtime_events | model_calls | wall_time_ms | final_message |"
    )
    lines.append(
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |"
    )
    for row in rows:
        final_message = " ".join(row.final_message.split())
        final_message = final_message[:120] + ("..." if len(final_message) > 120 else "")
        lines.append(
            "| "
            f"{row.scenario} | {row.condition} | "
            f"{'yes' if row.completed else 'no'} | "
            f"{row.stop_reason or '-'} | "
            f"{'yes' if row.widened else 'no'} | "
            f"{'yes' if row.verification_guard_triggered else 'no'} | "
            f"{row.runtime_events} | {row.model_calls} | {row.wall_time_ms:.2f} | {final_message} |"
        )

    lines.append("")
    lines.append("## Runtime Timelines")
    lines.append("")
    for row in rows:
        trace_preview = _runtime_trace_preview(row.runtime_trace) or "-"
        lines.append(
            f"- `{row.scenario}` / `{row.condition}`: {trace_preview}"
        )

    if provider_diagnostics is not None:
        lines.append("")
        lines.append("## Provider Diagnostics")
        lines.append("")
        lines.append(
            "| label | outcome | category | retryable | ownership | recovery_action | risk_scope | readiness | repair_steps | trace | error_code | request_id | exit_code | summary |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | ---: | --- |"
        )
        for item in provider_diagnostics:
            diagnostic_summary = " ".join(item.summary.split())
            diagnostic_summary = diagnostic_summary[:120] + (
                "..." if len(diagnostic_summary) > 120 else ""
            )
            lines.append(
                f"| {item.label} | {item.outcome} | {item.failure_category} | "
                f"{'yes' if item.retryable else 'no'} | {item.ownership} | "
                f"{item.recovery_action or '-'} | {item.risk_scope} | "
                f"{item.readiness_status or '-'} | {item.repair_step_count} | "
                f"{item.trace_artifact or '-'} | "
                f"{item.error_code or '-'} | {item.request_id or '-'} | "
                f"{item.exit_code} | {diagnostic_summary} |"
            )
            if item.guidance:
                lines.append("")
                lines.append(f"Guidance for `{item.label}`:")
                for guidance in item.guidance:
                    lines.append(f"- {guidance}")

    return "\n".join(lines)
