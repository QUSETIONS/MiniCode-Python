from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minicode.product_surfaces import build_readiness_report
from minicode.release_readiness import (
    ReleaseCheck,
    build_artifact_manifest,
    check_artifact_manifest,
    check_artifact_redaction,
    check_fallback_evidence_payload,
    check_fallback_patch_preview,
    check_fallback_simulation,
    check_fallback_switch_smoke,
    check_headless_trace,
    check_readiness_bundle,
    check_release_markdown,
    check_release_report,
    check_structure_compliance_artifact,
    classify_provider_outcome,
    normalize_evidence_paths,
    release_readiness_as_dict,
    release_readiness_as_markdown,
    should_fail_release_status,
    summarize_release_status,
)
from minicode.runtime_profile_eval import (
    classify_provider_failure,
    extract_provider_error_context,
)
from minicode.session import (
    create_file_checkpoint,
    create_new_session,
    delete_session,
    list_sessions,
    save_session,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"


def _clear_test_provider_environment(env: dict[str, str]) -> None:
    """Remove provider credentials and live-smoke gates from child checks."""
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
    env.pop("MINICODE_LIVE_PROVIDER_SMOKE", None)


def _normalize_evidence_paths(
    value: object,
    *,
    repo_root: Path = REPO_ROOT,
    home: Path | None = None,
) -> object:
    return normalize_evidence_paths(value, repo_root=repo_root, home=home)


def _run_command(label: str, command: list[str], *, cwd: Path, timeout: int = 1800) -> ReleaseCheck:
    env = dict(os.environ)
    _clear_test_provider_environment(env)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(REPO_ROOT)
        if not existing_pythonpath
        else f"{REPO_ROOT}{os.pathsep}{existing_pythonpath}"
    )
    try:
        # Config is read at import time from Path.home().  An empty temporary
        # home keeps release checks offline even when ~/.mini-code/settings.json
        # contains valid provider credentials.
        with tempfile.TemporaryDirectory(prefix="minicode-release-home-") as isolated_home:
            env["HOME"] = isolated_home
            env["USERPROFILE"] = isolated_home
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        summary_source = stdout or stderr
        summary = summary_source.splitlines()[-1].strip() if summary_source else f"{label} completed."
        if label == "readiness-cli" and stdout:
            for line in stdout.splitlines():
                normalized = line.strip()
                if normalized.startswith("readiness: "):
                    summary = normalized
                    break
        if label == "readiness-examples" and stdout:
            try:
                examples_payload = json.loads(stdout)
                summary = (
                    "fallback examples "
                    f"{len(examples_payload.get('fallback_config_examples', []) or [])} "
                    f"({examples_payload.get('risk_scope', 'unknown')})"
                )
            except json.JSONDecodeError:
                pass
        if label == "readiness-repair-plan" and stdout:
            try:
                repair_payload = json.loads(stdout)
                summary = (
                    "repair plan "
                    f"{len(repair_payload.get('repair_plan', []) or [])} "
                    f"({repair_payload.get('risk_scope', 'unknown')})"
                )
            except json.JSONDecodeError:
                pass
        if label == "readiness-patch-preview" and stdout:
            try:
                patch_payload = json.loads(stdout)
                summary = (
                    "patch preview "
                    f"{len(patch_payload.get('fallback_settings_patch_preview', []) or [])} "
                    f"({patch_payload.get('risk_scope', 'unknown')})"
                )
            except json.JSONDecodeError:
                pass
        if label == "readiness-doctor" and stdout:
            status = "unknown"
            risk_scope = "unknown"
            for line in stdout.splitlines():
                normalized = line.strip()
                if normalized.startswith("- Status:"):
                    status = normalized.split(":", 1)[1].strip()
                if normalized.startswith("- Risk scope:"):
                    risk_scope = normalized.split(":", 1)[1].strip()
            summary = f"doctor {status} ({risk_scope})"
        if label in {"readiness-json", "readiness-script-json", "readiness-threshold"} and stdout:
            try:
                readiness_payload = json.loads(stdout)
                summary = (
                    f"readiness {readiness_payload.get('status', 'unknown')} "
                    f"({readiness_payload.get('risk_scope', 'unknown')})"
                )
            except json.JSONDecodeError:
                pass
        status = "passed" if completed.returncode == 0 else "failed"
        return ReleaseCheck(
            label=label,
            command=" ".join(command),
            exit_code=completed.returncode,
            status=status,
            summary=summary,
            stdout=stdout,
            stderr=stderr,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return ReleaseCheck(
            label=label,
            command=" ".join(command),
            exit_code=124,
            status="failed",
            summary=f"{label} timed out.",
            stdout=stdout if isinstance(stdout, str) else "",
            stderr=stderr if isinstance(stderr, str) else "",
        )


def _check_readiness_artifacts(
    *,
    examples_path: Path,
    doctor_path: Path,
    repair_plan_path: Path,
    patch_preview_path: Path,
) -> ReleaseCheck:
    errors: list[str] = []
    example_count = 0
    repair_step_count = 0
    patch_preview_count = 0

    if not examples_path.exists():
        errors.append(f"missing examples artifact: {examples_path}")
    else:
        try:
            payload = json.loads(examples_path.read_text(encoding="utf-8"))
            examples = payload.get("fallback_config_examples", [])
            if not isinstance(examples, list):
                errors.append("examples artifact fallback_config_examples is not a list")
            else:
                example_count = len(examples)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid examples artifact: {exc}")

    if not doctor_path.exists():
        errors.append(f"missing doctor artifact: {doctor_path}")
    else:
        try:
            doctor = doctor_path.read_text(encoding="utf-8")
            for required in (
                "# MiniCode Readiness Doctor",
                "## Local Preflight",
                "## Safety",
                "This report is read-only.",
                "It does not modify MiniCode settings.",
            ):
                if required not in doctor:
                    errors.append(f"doctor artifact missing: {required}")
        except OSError as exc:
            errors.append(f"invalid doctor artifact: {exc}")

    if not repair_plan_path.exists():
        errors.append(f"missing repair plan artifact: {repair_plan_path}")
    else:
        try:
            payload = json.loads(repair_plan_path.read_text(encoding="utf-8"))
            repair_plan = payload.get("repair_plan", [])
            if not isinstance(repair_plan, list):
                errors.append("repair plan artifact repair_plan is not a list")
            else:
                repair_step_count = len(repair_plan)
                for required in ("summary", "status", "risk_scope"):
                    if required not in payload:
                        errors.append(f"repair plan artifact missing: {required}")
                if repair_step_count == 0:
                    errors.append("repair plan artifact has no steps")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid repair plan artifact: {exc}")

    if not patch_preview_path.exists():
        errors.append(f"missing patch preview artifact: {patch_preview_path}")
    else:
        try:
            payload = json.loads(patch_preview_path.read_text(encoding="utf-8"))
            patch_previews = payload.get("fallback_settings_patch_preview", [])
            if not isinstance(patch_previews, list):
                errors.append("patch preview artifact fallback_settings_patch_preview is not a list")
            else:
                patch_preview_count = len(patch_previews)
            for required in ("summary", "status", "risk_scope"):
                if required not in payload:
                    errors.append(f"patch preview artifact missing: {required}")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid patch preview artifact: {exc}")

    if errors:
        return ReleaseCheck(
            label="readiness-artifacts",
            command="validate readiness artifacts",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="readiness-artifacts",
        command="validate readiness artifacts",
        exit_code=0,
        status="passed",
        summary=(
            "readiness artifacts valid: "
            f"{example_count} fallback example(s), "
            f"{repair_step_count} repair step(s), "
            f"{patch_preview_count} patch preview(s)"
        ),
    )


def _check_artifact_redaction(paths: list[Path]) -> ReleaseCheck:
    return check_artifact_redaction(paths)


def _check_headless_trace(path: Path) -> ReleaseCheck:
    return check_headless_trace(path)


def _check_artifact_manifest(manifest: list[dict[str, object]]) -> ReleaseCheck:
    return check_artifact_manifest(manifest)


def _check_structure_compliance_artifact(path: Path) -> ReleaseCheck:
    return check_structure_compliance_artifact(path)


def _check_readiness_bundle(directory: Path) -> ReleaseCheck:
    return check_readiness_bundle(directory)


def _check_fallback_evidence(payload: dict[str, object]) -> ReleaseCheck:
    return check_fallback_evidence_payload(payload)


def _check_fallback_patch_preview(path: Path) -> ReleaseCheck:
    return check_fallback_patch_preview(path)


def _check_fallback_simulation(path: Path) -> ReleaseCheck:
    return check_fallback_simulation(path)


def _check_fallback_switch_smoke() -> ReleaseCheck:
    return check_fallback_switch_smoke()


def _readiness_snapshot(readiness_report) -> dict[str, object]:
    return {
        "status": readiness_report.status,
        "provider": readiness_report.provider,
        "provider_ready": readiness_report.provider_ready,
        "provider_channel": readiness_report.provider_channel,
        "fallback_ready": readiness_report.fallback_ready,
        "fallback_candidates": readiness_report.fallback_candidates,
        "viable_fallbacks": readiness_report.viable_fallbacks,
        "fallback_guidance": readiness_report.fallback_guidance,
        "risk_scope": readiness_report.risk_scope,
        "next_actions": readiness_report.next_actions,
        "fallback_config_examples": readiness_report.fallback_config_examples,
        "repair_plan": readiness_report.repair_plan,
        "preflight_checks": readiness_report.preflight_checks,
        "issues": readiness_report.issues,
        "summary": readiness_report.summary,
    }


def _prepare_saved_session(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    workspace_key = str(workspace)
    for meta in list_sessions(workspace=workspace_key):
        delete_session(meta.session_id)
    target = workspace / "demo.txt"
    target.write_text("after", encoding="utf-8")
    extension_dir = workspace / ".mini-code" / "extensions" / "git-helpers"
    extension_dir.mkdir(parents=True, exist_ok=True)
    (extension_dir / "extension.json").write_text(
        json.dumps(
            {
                "name": "git-helpers",
                "version": "1.0.0",
                "description": "Local helper bundle",
                "enabled": True,
                "entrypoint": "bundle.py",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (extension_dir / "bundle.py").write_text("print('ok')\n", encoding="utf-8")

    session = create_new_session(workspace=str(workspace))
    session.history = ["continue with runtime trace"]
    session.transcript_entries = [
        {
            "id": 1,
            "kind": "progress",
            "category": "runtime",
            "runtimeKind": "phase",
            "runtimeStep": 2,
            "runtimePhase": "verify",
            "body": "Runtime phase: verify.",
        },
        {
            "id": 2,
            "kind": "tool",
            "toolName": "edit_file",
            "status": "success",
            "body": "Patched demo.txt",
        },
    ]
    session.instruction_layers = [
        {
            "name": "project-managed",
            "scope": "project",
            "kind": "managed",
            "path": str(workspace / ".mini-code" / "MANAGED.md"),
            "exists": True,
            "preview": "Prefer verification-first delivery.",
        }
    ]
    session.hook_status = {
        "total_hooks": 1,
        "enabled_hooks": 1,
        "total_calls": 1,
        "total_duration_ms": 8,
        "failure_count": 0,
        "last_status": "success",
    }
    session.delegated_tasks = [{"label": "lint-worker", "status": "running"}]
    session.delegation_status = {
        "running_tasks": 1,
        "total_tracked": 1,
        "max_slots": 4,
        "available_slots": 3,
        "active_labels": ["lint-worker"],
    }
    session.extension_manifests = [
        {
            "name": "git-helpers",
            "scope": "project",
            "enabled": True,
            "version": "1.0.0",
            "description": "Local helper bundle",
            "entrypoint": "bundle.py",
        }
    ]
    session.readiness_report = {
        "status": "ready",
        "provider": "anthropic-compatible",
        "provider_ready": True,
        "issues": [],
    }
    create_file_checkpoint(
        session,
        file_path=str(target),
        existed=True,
        previous_content="before",
    )
    save_session(session)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="release_readiness",
        description="Run MiniCode release readiness checks and refresh reports.",
    )
    parser.add_argument(
        "--fail-on",
        choices=("warning", "at-risk", "blocked"),
        help=(
            "Return exit code 1 when the release status is at or above this "
            "severity. Defaults to report-only mode."
        ),
    )
    args = parser.parse_args(argv)

    generated_at = datetime.now(UTC).isoformat()
    workspace = REPO_ROOT / "outputs" / "release_smoke_workspace"
    _prepare_saved_session(workspace)
    readiness_examples_path = REPO_ROOT / ".temp" / "readiness-fallback-examples.json"
    readiness_doctor_path = REPO_ROOT / ".temp" / "readiness-doctor.md"
    readiness_repair_plan_path = REPO_ROOT / ".temp" / "readiness-repair-plan.json"
    readiness_patch_preview_path = REPO_ROOT / ".temp" / "readiness-fallback-patch-preview.json"
    readiness_bundle_dir = REPO_ROOT / ".temp" / "readiness-bundle"
    readiness_simulations_path = (
        readiness_bundle_dir / "readiness-fallback-simulations.json"
    )

    compile_check = _run_command(
        "compileall",
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "minicode",
            "tests",
            "benchmarks",
            "Main",
            "Package",
        ],
        cwd=REPO_ROOT,
        timeout=600,
    )
    test_check = _run_command(
        "pytest-q",
        [sys.executable, "-m", "pytest", "-q"],
        cwd=REPO_ROOT,
        timeout=2400,
    )
    runtime_eval_check = _run_command(
        "runtime-profile-eval",
        [sys.executable, "benchmarks/runtime_profile_eval.py"],
        cwd=REPO_ROOT,
        timeout=600,
    )
    structure_check = _run_command(
        "structure-compliance",
        [
            sys.executable,
            "-m",
            "minicode.structure_check",
            "--root",
            ".",
            "--hotspots",
            "5",
            "--max-dependency-upstream",
            "4",
            "--check-material-inventory",
            "--report",
            ".temp/structure-compliance.json",
        ],
        cwd=REPO_ROOT,
        timeout=600,
    )

    smoke_checks = [
        _run_command(
            "list-workspace-sessions",
            [sys.executable, "-m", "minicode.main", "--list-workspace-sessions"],
            cwd=workspace,
            timeout=120,
        ),
        _run_command(
            "inspect-session",
            [sys.executable, "-m", "minicode.main", "--inspect-session", "latest"],
            cwd=workspace,
            timeout=120,
        ),
        _run_command(
            "replay-session",
            [sys.executable, "-m", "minicode.main", "--replay-session", "latest"],
            cwd=workspace,
            timeout=120,
        ),
        _run_command(
            "preview-rewind",
            [sys.executable, "-m", "minicode.main", "--preview-rewind", "latest"],
            cwd=workspace,
            timeout=120,
        ),
        _run_command(
            "readiness-cli",
            [sys.executable, "-m", "minicode.main", "--readiness"],
            cwd=workspace,
            timeout=120,
        ),
        _run_command(
            "readiness-json",
            [sys.executable, "-m", "minicode.main", "--readiness-json"],
            cwd=workspace,
            timeout=120,
        ),
        _run_command(
            "readiness-script-json",
            [sys.executable, "-m", "minicode.readiness", "--cwd", str(workspace), "--json"],
            cwd=REPO_ROOT,
            timeout=120,
        ),
        _run_command(
            "readiness-threshold",
            [
                sys.executable,
                "-m",
                "minicode.readiness",
                "--cwd",
                str(workspace),
                "--json",
                "--fail-on",
                "blocked",
            ],
            cwd=REPO_ROOT,
            timeout=120,
        ),
        _run_command(
            "readiness-examples",
            [
                sys.executable,
                "-m",
                "minicode.readiness",
                "--cwd",
                str(workspace),
                "--examples",
                "--examples-out",
                str(readiness_examples_path),
                "--fail-on",
                "blocked",
            ],
            cwd=REPO_ROOT,
            timeout=120,
        ),
        _run_command(
            "readiness-doctor",
            [
                sys.executable,
                "-m",
                "minicode.readiness",
                "--cwd",
                str(workspace),
                "--doctor",
                "--doctor-out",
                str(readiness_doctor_path),
                "--fail-on",
                "blocked",
            ],
            cwd=REPO_ROOT,
            timeout=120,
        ),
        _run_command(
            "readiness-repair-plan",
            [
                sys.executable,
                "-m",
                "minicode.readiness",
                "--cwd",
                str(workspace),
                "--repair-plan",
                "--repair-plan-out",
                str(readiness_repair_plan_path),
                "--fail-on",
                "blocked",
            ],
            cwd=REPO_ROOT,
            timeout=120,
        ),
        _run_command(
            "readiness-patch-preview",
            [
                sys.executable,
                "-m",
                "minicode.readiness",
                "--cwd",
                str(workspace),
                "--patch-preview",
                "--patch-preview-out",
                str(readiness_patch_preview_path),
                "--fail-on",
                "blocked",
            ],
            cwd=REPO_ROOT,
            timeout=120,
        ),
        _run_command(
            "readiness-bundle-generate",
            [
                sys.executable,
                "-m",
                "minicode.readiness",
                "--cwd",
                str(workspace),
                "--bundle-out",
                str(readiness_bundle_dir),
                "--fail-on",
                "blocked",
            ],
            cwd=REPO_ROOT,
            timeout=120,
        ),
    ]
    smoke_checks.append(
        _check_readiness_artifacts(
            examples_path=readiness_examples_path,
            doctor_path=readiness_doctor_path,
            repair_plan_path=readiness_repair_plan_path,
            patch_preview_path=readiness_patch_preview_path,
        )
    )
    smoke_checks.append(_check_fallback_patch_preview(readiness_patch_preview_path))
    smoke_checks.append(_check_fallback_simulation(readiness_simulations_path))
    smoke_checks.append(_check_fallback_switch_smoke())
    smoke_checks.append(_check_readiness_bundle(readiness_bundle_dir))
    smoke_checks.append(
        _check_headless_trace(REPO_ROOT / ".temp" / "headless-provider-smoke-trace.json")
    )
    smoke_checks.append(
        _check_artifact_redaction(
            [
                readiness_examples_path,
                readiness_doctor_path,
                readiness_repair_plan_path,
                readiness_patch_preview_path,
                REPO_ROOT / ".temp" / "headless-provider-smoke-trace.json",
                BENCHMARKS_DIR / "runtime_profile_eval_results.json",
                BENCHMARKS_DIR / "runtime_profile_eval_results.md",
            ]
        )
    )

    runtime_profile_json = BENCHMARKS_DIR / "runtime_profile_eval_results.json"
    provider_diagnostics: list[dict[str, object]] = []
    if runtime_profile_json.exists():
        payload = json.loads(runtime_profile_json.read_text(encoding="utf-8"))
        provider_diagnostics = list(payload.get("provider_diagnostics", []) or [])

    if not provider_diagnostics:
        fallback_check = _run_command(
            "headless-provider-smoke",
            [sys.executable, "-m", "minicode.headless", "Reply with exactly OK."],
            cwd=REPO_ROOT,
            timeout=180,
        )
        outcome, summary = classify_provider_outcome(
            exit_code=fallback_check.exit_code,
            stdout=fallback_check.stdout,
            stderr=fallback_check.stderr,
        )
        error_context = extract_provider_error_context(
            fallback_check.stdout,
            fallback_check.stderr,
            summary,
        )
        classification = classify_provider_failure(
            outcome,
            error_context["error_code"],
            summary,
        )
        provider_diagnostics = [
            {
                "label": fallback_check.label,
                "outcome": outcome,
                "command": fallback_check.command,
                "exit_code": fallback_check.exit_code,
                "summary": summary,
                **error_context,
                "failure_category": classification.category,
                "retryable": classification.retryable,
                "ownership": classification.ownership,
                "recovery_action": classification.recovery_action,
                "stdout": fallback_check.stdout,
                "stderr": fallback_check.stderr,
            }
        ]

    readiness_report = build_readiness_report(REPO_ROOT)

    readiness_snapshot = _readiness_snapshot(readiness_report)
    runtime_profile_artifacts = {
        "json": str(runtime_profile_json),
        "markdown": str(BENCHMARKS_DIR / "runtime_profile_eval_results.md"),
        "headless_trace": str(REPO_ROOT / ".temp" / "headless-provider-smoke-trace.json"),
    }
    readiness_artifacts = {
        "fallback_examples_json": str(readiness_examples_path),
        "doctor_markdown": str(readiness_doctor_path),
        "repair_plan_json": str(readiness_repair_plan_path),
        "patch_preview_json": str(readiness_patch_preview_path),
        "fallback_simulations_json": str(readiness_simulations_path),
        "bundle_directory": str(readiness_bundle_dir),
        "bundle_manifest_json": str(readiness_bundle_dir / "readiness-artifact-manifest.json"),
    }
    smoke_checks.append(
        _check_fallback_evidence(
            {
                "provider_status": "",
                "provider_diagnostics": provider_diagnostics,
                "readiness_report": readiness_snapshot,
                "readiness_artifacts": readiness_artifacts,
            }
        )
    )
    artifact_manifest = build_artifact_manifest(
        {
            "structure_compliance": REPO_ROOT / ".temp" / "structure-compliance.json",
            **runtime_profile_artifacts,
            "fallback_examples_json": readiness_examples_path,
            "doctor_markdown": readiness_doctor_path,
            "repair_plan_json": readiness_repair_plan_path,
            "patch_preview_json": readiness_patch_preview_path,
            "fallback_simulations_json": readiness_simulations_path,
            "bundle_manifest_json": readiness_bundle_dir / "readiness-artifact-manifest.json",
        }
    )
    smoke_checks.append(
        _check_structure_compliance_artifact(
            REPO_ROOT / ".temp" / "structure-compliance.json"
        )
    )
    smoke_checks.append(_check_artifact_manifest(artifact_manifest))

    status = summarize_release_status(
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        smoke_checks=smoke_checks,
        provider_outcomes=[str(item.get("outcome", "error")) for item in provider_diagnostics],
        structure_check=structure_check,
        readiness_report=readiness_snapshot,
    )

    payload = release_readiness_as_dict(
        generated_at=generated_at,
        status=status,
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        structure_check=structure_check,
        smoke_checks=smoke_checks,
        provider_diagnostics=provider_diagnostics,
        runtime_profile_artifacts=runtime_profile_artifacts,
        readiness_artifacts=readiness_artifacts,
        artifact_manifest=artifact_manifest,
        readiness_report=readiness_snapshot,
    )
    markdown = release_readiness_as_markdown(
        generated_at=generated_at,
        status=status,
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        structure_check=structure_check,
        smoke_checks=smoke_checks,
        provider_diagnostics=provider_diagnostics,
        runtime_profile_artifacts=runtime_profile_artifacts,
        readiness_artifacts=readiness_artifacts,
        artifact_manifest=artifact_manifest,
        readiness_report=readiness_snapshot,
    )
    payload = _normalize_evidence_paths(payload)
    markdown = _normalize_evidence_paths(markdown)

    json_path = BENCHMARKS_DIR / "release_readiness_results.json"
    markdown_path = BENCHMARKS_DIR / "release_readiness_results.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    report_check = check_release_report(json_path)
    markdown_check = check_release_markdown(markdown_path, release_json=json_path)
    print(json_path)
    print(markdown_path)
    for final_check in (report_check, markdown_check):
        if final_check.status != "failed":
            continue
        print(final_check.summary)
        if final_check.stderr:
            print(final_check.stderr)
        return 1
    return 1 if should_fail_release_status(status, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
