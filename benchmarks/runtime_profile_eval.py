from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minicode.release_readiness import (
    classify_provider_outcome,
    normalize_evidence_paths,
    redact_sensitive_payload,
    redact_sensitive_text,
)
from minicode.runtime_profile_eval import (
    ProviderDiagnostic,
    RuntimeEvalCondition,
    RuntimeEvalScenario,
    classify_provider_failure,
    evaluate_runtime_profiles,
    extract_provider_error_context,
    runtime_profile_eval_as_dict,
    runtime_profile_eval_as_markdown,
)
from minicode.tooling import ToolRegistry
from minicode.types import AgentStep, ChatMessage, ModelAdapter

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_PROVIDER_SMOKE_ENV = "MINICODE_LIVE_PROVIDER_SMOKE"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _clear_provider_environment(env: dict[str, str]) -> None:
    """Make the non-live runtime profile subprocess unable to use credentials."""
    for key in list(env):
        if key.startswith((
            "MINI_CODE_",
            "OPENAI_",
            "ANTHROPIC_",
            "OPENROUTER_",
            "CUSTOM_",
            "DEEPSEEK_",
        )):
            env.pop(key, None)
    env.pop(LIVE_PROVIDER_SMOKE_ENV, None)


def _portable_provider_diagnostic(
    diagnostic: ProviderDiagnostic,
    *,
    repo_root: Path = REPO_ROOT,
    home: Path | None = None,
) -> ProviderDiagnostic:
    payload = normalize_evidence_paths(
        asdict(diagnostic),
        repo_root=repo_root,
        home=home,
    )
    return ProviderDiagnostic(**payload)


class ScriptedModel(ModelAdapter):
    def __init__(self, steps: list[AgentStep]) -> None:
        self._steps = steps
        self.calls = 0

    def next(self, messages: list[ChatMessage], on_stream_chunk=None) -> AgentStep:
        step = self._steps[self.calls]
        self.calls += 1
        return step


def build_demo_scenarios() -> list[RuntimeEvalScenario]:
    return [
        RuntimeEvalScenario(
            name="depth-budget-floor",
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "repair the runtime policy"},
            ],
            model_factory=lambda: ScriptedModel(
                [
                    AgentStep(
                        type="assistant",
                        content="scanning the relevant files",
                        kind="progress",
                    ),
                    AgentStep(type="assistant", content="done"),
                ]
            ),
            tools_factory=lambda: ToolRegistry([]),
            max_steps=1,
        ),
        RuntimeEvalScenario(
            name="widening-escalation",
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "repair the runtime policy"},
            ],
            model_factory=lambda: ScriptedModel(
                [
                    AgentStep(type="assistant", content="still exploring", kind="progress"),
                    AgentStep(type="assistant", content="still exploring", kind="progress"),
                    AgentStep(type="assistant", content="still exploring", kind="progress"),
                    AgentStep(type="assistant", content="still exploring", kind="progress"),
                    AgentStep(type="assistant", content="still exploring", kind="progress"),
                    AgentStep(type="assistant", content=""),
                    AgentStep(type="assistant", content=""),
                    AgentStep(type="assistant", content=""),
                    AgentStep(type="assistant", content=""),
                    AgentStep(type="assistant", content="done with a broader plan"),
                ]
            ),
            tools_factory=lambda: ToolRegistry([]),
        ),
    ]


def build_demo_conditions() -> list[RuntimeEvalCondition]:
    return [
        RuntimeEvalCondition(
            label="single",
            runtime={"runtimeProfile": "single"},
            max_steps=1,
        ),
        RuntimeEvalCondition(
            label="single-deep",
            runtime={"runtimeProfile": "single-deep"},
            max_steps=1,
        ),
    ]


def _classify_provider_diagnostic(
    *,
    label: str,
    command: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    trace_artifact: Path | None = None,
    trace_payload: dict | None = None,
) -> ProviderDiagnostic:
    outcome, summary_line = classify_provider_outcome(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )
    provider_context = extract_provider_error_context(
        summary_line,
        stdout,
        stderr,
    )
    risk_scope = "unknown"
    guidance: list[str] = []
    if outcome == "answered":
        risk_scope = "none"
    elif outcome == "provider_outage":
        risk_scope = "external-provider"
        guidance = [
            "Check upstream provider availability and retry the headless provider smoke.",
            "Configure fallbackModels or provider-specific fallback models before relying on live-provider release evidence.",
        ]
    elif outcome == "provider_channel_unavailable":
        risk_scope = "provider-config"
        guidance = [
            "Verify the selected model group and provider channel configuration.",
            "Add a viable fallback provider/model or credentials for the configured channel.",
        ]
    elif outcome == "provider_api_error":
        risk_scope = "external-provider"
        guidance = [
            "Inspect the provider error code and request id in stderr/stdout.",
            "Retry with a known available fallback model before marking live-provider readiness as stable.",
        ]
    elif outcome == "empty_output":
        risk_scope = "provider-response"
        guidance = [
            "Retry the headless provider smoke and inspect provider response logs.",
            "Keep local gates separate from live-provider readiness until a non-empty answer is observed.",
        ]
    else:
        outcome = "error"
        guidance = [
            "Inspect stdout/stderr for the provider smoke command.",
            "Confirm whether the failure is local configuration, provider availability, or response parsing.",
        ]
    readiness_status = ""
    repair_step_count = 0
    if trace_payload:
        readiness_report = trace_payload.get("readiness_report", {})
        if isinstance(readiness_report, dict):
            readiness_status = str(readiness_report.get("status") or "").strip()
        repair_plan = trace_payload.get("repair_plan", [])
        if isinstance(repair_plan, list):
            repair_step_count = len(repair_plan)
    if trace_artifact is not None:
        guidance.append(f"Inspect headless trace artifact: {trace_artifact}")
    failure = classify_provider_failure(
        outcome=outcome,
        error_code=provider_context["error_code"],
        summary=summary_line,
        risk_scope=risk_scope,
    )
    return ProviderDiagnostic(
        label=label,
        outcome=outcome,
        command=command,
        exit_code=exit_code,
        summary=summary_line or f"{label}: {outcome}",
        stdout=stdout,
        stderr=stderr,
        risk_scope=risk_scope,
        error_code=provider_context["error_code"],
        request_id=provider_context["request_id"],
        failure_category=failure.category,
        retryable=failure.retryable,
        ownership=failure.ownership,
        recovery_action=failure.recovery_action,
        readiness_status=readiness_status,
        repair_step_count=repair_step_count,
        trace_artifact=str(trace_artifact) if trace_artifact is not None else "",
        guidance=guidance,
    )


def collect_provider_diagnostics(*, allow_live: bool = False) -> list[ProviderDiagnostic]:
    command = [sys.executable, "-m", "minicode.headless", "Reply with exactly OK."]
    trace_artifact = REPO_ROOT / ".temp" / "headless-provider-smoke-trace.json"
    trace_artifact.parent.mkdir(parents=True, exist_ok=True)
    try:
        trace_artifact.unlink()
    except FileNotFoundError:
        pass
    env = dict(os.environ)
    live_enabled = allow_live and _truthy(env.get(LIVE_PROVIDER_SMOKE_ENV))
    isolated_home: tempfile.TemporaryDirectory[str] | None = None
    if not live_enabled:
        _clear_provider_environment(env)
        isolated_home = tempfile.TemporaryDirectory(prefix="minicode-runtime-profile-home-")
        env["HOME"] = isolated_home.name
        env["USERPROFILE"] = isolated_home.name
    env["MINI_CODE_HEADLESS_MESSAGES_OUT"] = str(trace_artifact)
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
        trace_payload = {}
        if trace_artifact.exists():
            try:
                trace_payload = json.loads(trace_artifact.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                trace_payload = {}
        return [
            _classify_provider_diagnostic(
                label="headless-smoke",
                command=" ".join(command),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                trace_artifact=trace_artifact if trace_artifact.exists() else None,
                trace_payload=trace_payload,
            )
        ]
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        failure = classify_provider_failure(
            outcome="timeout",
            risk_scope="external-provider",
        )
        return [
            ProviderDiagnostic(
                label="headless-smoke",
                outcome="timeout",
                command=" ".join(command),
                exit_code=124,
                summary="Headless provider smoke timed out.",
                stdout=stdout if isinstance(stdout, str) else "",
                stderr=stderr if isinstance(stderr, str) else "",
                risk_scope="external-provider",
                failure_category=failure.category,
                retryable=failure.retryable,
                ownership=failure.ownership,
                recovery_action=failure.recovery_action,
            )
        ]
    finally:
        if isolated_home is not None:
            isolated_home.cleanup()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate runtime profiles and optionally run an explicit live provider smoke."
    )
    parser.add_argument(
        "--live-provider-smoke",
        action="store_true",
        help=f"Allow a live smoke only when {LIVE_PROVIDER_SMOKE_ENV}=1 is also set.",
    )
    args = parser.parse_args(argv)
    rows = evaluate_runtime_profiles(
        scenarios=build_demo_scenarios(),
        conditions=build_demo_conditions(),
    )
    provider_diagnostics = [
        _portable_provider_diagnostic(diagnostic)
        for diagnostic in collect_provider_diagnostics(
            allow_live=args.live_provider_smoke,
        )
    ]
    payload = redact_sensitive_payload(
        runtime_profile_eval_as_dict(rows, provider_diagnostics)
    )
    payload = normalize_evidence_paths(payload, repo_root=REPO_ROOT)
    markdown = normalize_evidence_paths(
        redact_sensitive_text(
            runtime_profile_eval_as_markdown(rows, provider_diagnostics)
        ),
        repo_root=REPO_ROOT,
    )
    output_path = Path("benchmarks") / "runtime_profile_eval_results.json"
    markdown_path = Path("benchmarks") / "runtime_profile_eval_results.md"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    print(output_path)
    print(markdown_path)


if __name__ == "__main__":
    main()
