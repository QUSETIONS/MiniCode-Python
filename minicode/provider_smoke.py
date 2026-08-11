"""Explicit, bounded, and redacted provider smoke checks.

The normal readiness surface is intentionally local-only.  This module is the
separate opt-in path for one minimal end-to-end provider request.  A live run
requires both the CLI flag and ``MINICODE_LIVE_PROVIDER_SMOKE=1`` so a copied
command or an inherited environment cannot silently spend provider quota.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from minicode.config import load_runtime_config, validate_provider_runtime
from minicode.model_registry import detect_provider
from minicode.product_surfaces import build_readiness_report
from minicode.release_readiness import (
    classify_provider_outcome,
    redact_sensitive_payload,
    redact_sensitive_text,
)
from minicode.runtime_profile_eval import (
    classify_provider_failure,
    extract_provider_error_context,
)

LIVE_PROVIDER_SMOKE_ENV = "MINICODE_LIVE_PROVIDER_SMOKE"
SMOKE_PROMPT = "Reply with exactly OK."
DEFAULT_TIMEOUT_SECONDS = 45
MAX_TIMEOUT_SECONDS = 300
REPO_ROOT = Path(__file__).resolve().parents[1]

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _bounded_timeout(value: int | str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_TIMEOUT_SECONDS
    return max(1, min(parsed, MAX_TIMEOUT_SECONDS))


def _safe_summary(value: object, *, fallback: str) -> str:
    summary = " ".join(_text(value).split())
    if not summary:
        summary = fallback
    return redact_sensitive_text(summary)[:500]


def _provider_risk_scope(outcome: str) -> str:
    if outcome == "answered":
        return "none"
    if outcome in {
        "provider_channel_unavailable",
        "provider_api_error",
    }:
        return "provider-config" if outcome == "provider_channel_unavailable" else "external-provider"
    if outcome in {"provider_outage", "timeout"}:
        return "external-provider"
    return "provider-response"


def _read_trace(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _readiness_snapshot(report: object) -> dict[str, Any]:
    if is_dataclass(report):
        payload = asdict(report)
    elif isinstance(report, dict):
        payload = report
    else:
        return {}
    fallback_candidates = payload.get("fallback_candidates", [])
    viable_fallbacks = payload.get("viable_fallbacks", [])
    return {
        "status": str(payload.get("status") or "unknown"),
        "fallback_ready": bool(payload.get("fallback_ready")),
        "fallback_candidates": len(fallback_candidates) if isinstance(fallback_candidates, list) else 0,
        "viable_fallbacks": len(viable_fallbacks) if isinstance(viable_fallbacks, list) else 0,
        "risk_scope": str(payload.get("risk_scope") or "unknown"),
    }


def _base_result(*, timeout: int, summary: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "skipped",
        "outcome": "skipped",
        "live_provider_claim": False,
        "attempted": False,
        "prompt": SMOKE_PROMPT,
        "timeout_seconds": timeout,
        "provider": "",
        "model": "",
        "summary": summary,
        "failure_category": "not-run",
        "retryable": False,
        "ownership": "local-control",
        "recovery_action": "",
        "error_code": "",
        "request_id": "",
        "latency_ms": 0.0,
        "readiness": {},
        "trace": {
            "available": False,
            "readiness_status": "",
            "repair_step_count": 0,
        },
    }


def run_provider_smoke(
    cwd: str | Path | None = None,
    *,
    run_live: bool = False,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Run one provider smoke, returning only safe structured evidence.

    ``run_live`` is the CLI/API gate.  The process environment gate is checked
    separately, and runtime configuration is validated before a subprocess is
    started.  The default path performs no config read and no subprocess call.
    """

    timeout_seconds = _bounded_timeout(timeout)
    result = _base_result(
        timeout=timeout_seconds,
        summary=(
            "Live provider smoke skipped. Pass --run-live and set "
            f"{LIVE_PROVIDER_SMOKE_ENV}=1."
        ),
    )
    if not run_live:
        return redact_sensitive_payload(result)
    if not _truthy(os.environ.get(LIVE_PROVIDER_SMOKE_ENV)):
        result.update(
            {
                "status": "blocked",
                "outcome": "blocked",
                "summary": (
                    f"Live provider smoke is blocked until {LIVE_PROVIDER_SMOKE_ENV}=1 "
                    "is set explicitly."
                ),
                "recovery_action": f"Set {LIVE_PROVIDER_SMOKE_ENV}=1 for this one run.",
            }
        )
        return redact_sensitive_payload(result)

    project_root = Path(cwd or Path.cwd()).resolve()
    runtime: dict[str, Any]
    try:
        runtime = load_runtime_config(project_root)
    except Exception as exc:  # noqa: BLE001
        result.update(
            {
                "status": "blocked",
                "outcome": "blocked",
                "summary": _safe_summary(
                    exc,
                    fallback="Provider runtime configuration could not be loaded.",
                ),
                "recovery_action": "Configure a model and provider credentials before running the live smoke.",
            }
        )
        return redact_sensitive_payload(result)

    model = str(runtime.get("model") or "").strip()
    try:
        provider = detect_provider(
            model,
            runtime,
            probe_openai_models=False,
        ).value
    except Exception:  # noqa: BLE001
        provider = "unknown"
    result.update({"provider": provider, "model": model})

    try:
        validation_errors = validate_provider_runtime(
            runtime,
            probe_openai_models=False,
        )
    except Exception as exc:  # noqa: BLE001
        validation_errors = [_safe_summary(exc, fallback="Provider runtime validation failed.")]
    try:
        readiness = build_readiness_report(project_root, runtime=runtime)
    except Exception:  # noqa: BLE001
        readiness = None
    result["readiness"] = _readiness_snapshot(readiness)
    if validation_errors:
        result.update(
            {
                "status": "blocked",
                "outcome": "blocked",
                "summary": _safe_summary(
                    validation_errors[0],
                    fallback="Provider runtime configuration is not ready.",
                ),
                "failure_category": "configuration",
                "ownership": "local-configuration",
                "recovery_action": "Repair the provider model, endpoint, or credential configuration.",
            }
        )
        return redact_sensitive_payload(result)

    command = [sys.executable, "-m", "minicode.headless", SMOKE_PROMPT]
    with tempfile.TemporaryDirectory(prefix="minicode-provider-smoke-") as temp_dir:
        trace_path = Path(temp_dir) / "headless-trace.json"
        env = dict(os.environ)
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(REPO_ROOT)
            if not existing_pythonpath
            else f"{REPO_ROOT}{os.pathsep}{existing_pythonpath}"
        )
        # A smoke request must not inherit non-interactive edit approval,
        # project MCP trust, or mock mode from the caller.
        for key in (
            "MINI_CODE_ALLOW_EDITS",
            "MINI_CODE_TRUST_PROJECT_MCP",
            "MINI_CODE_MODEL_MODE",
        ):
            env.pop(key, None)
        env["MINI_CODE_HEADLESS_MESSAGES_OUT"] = str(trace_path)
        env["MINICODE_MODEL_TIMEOUT"] = str(timeout_seconds)
        started = time.perf_counter()
        result["attempted"] = True
        result["live_provider_claim"] = True
        try:
            completed = runner(
                command,
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
            stdout = _text(completed.stdout)
            stderr = _text(completed.stderr)
            outcome, summary = classify_provider_outcome(
                exit_code=int(completed.returncode),
                stdout=stdout,
                stderr=stderr,
            )
            error_context = extract_provider_error_context(stdout, stderr, summary)
            risk_scope = _provider_risk_scope(outcome)
            failure = classify_provider_failure(
                outcome,
                error_context["error_code"],
                summary,
                risk_scope,
            )
            trace_payload = _read_trace(trace_path)
            trace_readiness = trace_payload.get("readiness_report", {})
            repair_plan = trace_payload.get("repair_plan", [])
            result.update(
                {
                    "status": "passed" if outcome == "answered" else "failed",
                    "outcome": outcome,
                    "summary": _safe_summary(summary, fallback="Provider smoke completed."),
                    "failure_category": failure.category,
                    "retryable": failure.retryable,
                    "ownership": failure.ownership,
                    "recovery_action": failure.recovery_action,
                    "error_code": error_context["error_code"],
                    "request_id": error_context["request_id"],
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "trace": {
                        "available": bool(trace_payload),
                        "readiness_status": (
                            str(trace_readiness.get("status") or "")
                            if isinstance(trace_readiness, dict)
                            else ""
                        ),
                        "repair_step_count": len(repair_plan) if isinstance(repair_plan, list) else 0,
                    },
                }
            )
        except subprocess.TimeoutExpired:
            trace_payload = _read_trace(trace_path)
            repair_plan = trace_payload.get("repair_plan", [])
            failure = classify_provider_failure(
                "timeout",
                risk_scope="external-provider",
            )
            result.update(
                {
                    "status": "failed",
                    "outcome": "timeout",
                    "summary": "Provider smoke timed out within the bounded timeout.",
                    "failure_category": failure.category,
                    "retryable": failure.retryable,
                    "ownership": failure.ownership,
                    "recovery_action": failure.recovery_action,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "trace": {
                        "available": bool(trace_payload),
                        "readiness_status": "",
                        "repair_step_count": len(repair_plan) if isinstance(repair_plan, list) else 0,
                    },
                }
            )
        except OSError as exc:
            failure = classify_provider_failure(
                "error",
                summary=str(exc),
                risk_scope="local-runtime",
            )
            result.update(
                {
                    "status": "failed",
                    "outcome": "error",
                    "summary": _safe_summary(exc, fallback="Provider smoke process could not start."),
                    "failure_category": failure.category,
                    "retryable": failure.retryable,
                    "ownership": failure.ownership,
                    "recovery_action": failure.recovery_action,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
    return redact_sensitive_payload(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="minicode-provider-smoke",
        description="Run one explicitly authorized, bounded provider smoke request.",
    )
    parser.add_argument("--cwd", default=".", help="Project directory used for runtime configuration.")
    parser.add_argument(
        "--run-live",
        action="store_true",
        help=f"Allow a live request; also requires {LIVE_PROVIDER_SMOKE_ENV}=1.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Bounded request timeout in seconds (1-{MAX_TIMEOUT_SECONDS}; default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument("--json-out", help="Optional path for the redacted JSON result.")
    args = parser.parse_args(argv)
    result = run_provider_smoke(
        args.cwd,
        run_live=args.run_live,
        timeout=args.timeout,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.json_out:
        output_path = Path(args.json_out).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    return 0 if result.get("status") in {"skipped", "passed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
