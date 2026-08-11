from __future__ import annotations

import sys
import subprocess
from pathlib import Path
from unittest.mock import patch
import json

from benchmarks.release_readiness import (
    _check_artifact_manifest,
    _check_artifact_redaction,
    _check_fallback_evidence,
    _check_fallback_patch_preview,
    _check_fallback_simulation,
    _check_fallback_switch_smoke,
    _check_headless_trace,
    _check_readiness_bundle,
    _check_readiness_artifacts,
    _check_structure_compliance_artifact,
    _prepare_saved_session,
    _readiness_snapshot,
    _run_command,
    _normalize_evidence_paths,
    main as release_readiness_main,
)
from minicode.product_surfaces import ReadinessReport
from minicode.release_readiness import ReleaseCheck
from minicode.session import list_sessions


def test_release_readiness_command_preserves_repo_import_path(tmp_path: Path) -> None:
    check = _run_command(
        "import-minicode",
        [sys.executable, "-c", "import minicode; print('OK')"],
        cwd=tmp_path,
        timeout=30,
    )

    assert check.status == "passed"
    assert check.exit_code == 0
    assert check.stdout == "OK"


def test_release_evidence_paths_are_portable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    payload = {
        "path": str(repo / ".temp" / "trace.json"),
        "command": f"python {repo / 'benchmarks' / 'release_readiness.py'}",
        "home_path": str(home / ".mini-code" / "settings.json"),
        "nested": [str(repo), 7, False, None],
        "similar_prefix": f"{repo}-archive",
    }

    normalized = _normalize_evidence_paths(payload, repo_root=repo, home=home)

    assert normalized == {
        "path": ".temp/trace.json",
        "command": "python benchmarks/release_readiness.py",
        "home_path": "~/.mini-code/settings.json",
        "nested": [".", 7, False, None],
        "similar_prefix": f"{repo}-archive",
    }


def test_release_readiness_command_summarizes_readiness_json(tmp_path: Path) -> None:
    check = _run_command(
        "readiness-threshold",
        [
            sys.executable,
            "-c",
            "import json; print(json.dumps({'status':'warning','risk_scope':'fallback-gap'}))",
        ],
        cwd=tmp_path,
        timeout=30,
    )

    assert check.status == "passed"
    assert check.summary == "readiness warning (fallback-gap)"


def test_release_pytest_command_does_not_inherit_live_provider_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "live-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ai.space.cx")
    monkeypatch.setenv("MINI_CODE_MODEL", "qwen3.7-max")
    monkeypatch.setenv("OPENAI_MODEL_FALLBACKS", "kimi-k2.7-code")
    captured: dict[str, str] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="pytest ok\n",
            stderr="",
        )

    monkeypatch.setattr("benchmarks.release_readiness.subprocess.run", fake_run)

    check = _run_command(
        "pytest-q",
        [sys.executable, "-m", "pytest", "-q"],
        cwd=tmp_path,
        timeout=30,
    )

    assert check.status == "passed"
    assert "OPENAI_API_KEY" not in captured
    assert "OPENAI_BASE_URL" not in captured
    assert "MINI_CODE_MODEL" not in captured
    assert "OPENAI_MODEL_FALLBACKS" not in captured


def test_release_runtime_profile_command_is_offline_even_with_global_provider_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "live-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("MINICODE_LIVE_PROVIDER_SMOKE", "1")
    captured: dict[str, str] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="runtime profile ok\n",
            stderr="",
        )

    monkeypatch.setattr("benchmarks.release_readiness.subprocess.run", fake_run)

    check = _run_command(
        "runtime-profile-eval",
        [sys.executable, "benchmarks/runtime_profile_eval.py"],
        cwd=tmp_path,
        timeout=30,
    )

    assert check.status == "passed"
    assert "OPENAI_API_KEY" not in captured
    assert "OPENAI_BASE_URL" not in captured
    assert "MINICODE_LIVE_PROVIDER_SMOKE" not in captured
    assert captured["HOME"] != str(Path.home())


def test_release_readiness_snapshot_preserves_local_preflight() -> None:
    report = ReadinessReport(
        status="warning",
        provider="anthropic",
        provider_ready=True,
        fallback_ready=False,
        repair_plan=[
            {
                "step": "verify-local-readiness",
                "status": "verify",
                "command": "minicode-readiness --json --fail-on blocked",
            }
        ],
        preflight_checks=[
            {
                "label": "live-smoke-readiness",
                "status": "not-run",
                "summary": "local-only",
                "action": "run release readiness",
            }
        ],
        summary="readiness: warning",
    )

    snapshot = _readiness_snapshot(report)

    assert snapshot["preflight_checks"] == report.preflight_checks
    assert snapshot["repair_plan"] == report.repair_plan


def test_release_readiness_main_can_fail_on_configured_threshold(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr("benchmarks.release_readiness._prepare_saved_session", lambda workspace: None)

    def _fake_run_command(label, command, *, cwd, timeout=1800):
        calls.setdefault("commands", []).append((label, command))
        return ReleaseCheck(
            label=label,
            command=" ".join(command),
            exit_code=0,
            status="passed",
            summary=f"{label} passed",
        )

    monkeypatch.setattr(
        "benchmarks.release_readiness._run_command",
        _fake_run_command,
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_readiness_artifacts",
        lambda *, examples_path, doctor_path, repair_plan_path, patch_preview_path: ReleaseCheck(
            label="readiness-artifacts",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_artifact_redaction",
        lambda paths: ReleaseCheck(
            label="artifact-redaction",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_headless_trace",
        lambda path: ReleaseCheck(
            label="headless-trace",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_artifact_manifest",
        lambda manifest: ReleaseCheck(
            label="artifact-manifest",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_structure_compliance_artifact",
        lambda path: ReleaseCheck(
            label="structure-compliance-artifact",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_readiness_bundle",
        lambda directory: ReleaseCheck(
            label="readiness-bundle",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_fallback_evidence",
        lambda payload: ReleaseCheck(
            label="fallback-evidence",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_fallback_patch_preview",
        lambda path: ReleaseCheck(
            label="fallback-patch-preview",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_fallback_simulation",
        lambda path: ReleaseCheck(
            label="fallback-simulation",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness._check_fallback_switch_smoke",
        lambda: ReleaseCheck(
            label="fallback-switch-smoke",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    def _fake_manifest(artifacts):
        calls["manifest_artifacts"] = artifacts
        return [
            {
                "label": "runtime-json",
                "path": "runtime.json",
                "exists": True,
                "size_bytes": 1,
                "sha256": "0" * 64,
            }
        ]

    monkeypatch.setattr("benchmarks.release_readiness.build_artifact_manifest", _fake_manifest)
    monkeypatch.setattr(
        "benchmarks.release_readiness.build_readiness_report",
        lambda root: ReadinessReport(
            status="warning",
            provider="anthropic",
            provider_ready=True,
            fallback_ready=False,
            summary="readiness: warning",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness.summarize_release_status",
        lambda **kwargs: "at-risk",
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness.check_release_report",
        lambda path: ReleaseCheck(
            label="release-report",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )
    monkeypatch.setattr(
        "benchmarks.release_readiness.check_release_markdown",
        lambda path, *, release_json=None: ReleaseCheck(
            label="release-markdown",
            command="validate",
            exit_code=0,
            status="passed",
            summary="valid",
        ),
    )

    def _fake_write_text(self, text, encoding=None):
        calls[str(self)] = text
        return None

    monkeypatch.setattr(Path, "write_text", _fake_write_text)
    monkeypatch.setattr(Path, "exists", lambda self: False)

    assert release_readiness_main([]) == 0
    assert release_readiness_main(["--fail-on", "blocked"]) == 0
    assert release_readiness_main(["--fail-on", "at-risk"]) == 1
    structure_commands = [
        command
        for label, command in calls["commands"]
        if label == "structure-compliance"
    ]
    assert structure_commands
    assert all("--check-material-inventory" in command for command in structure_commands)
    release_payload = json.loads(
        calls[str(Path("benchmarks/release_readiness_results.json").resolve())]
    )
    assert "fallback_simulations_json" in release_payload["readiness_artifacts"]
    assert any(
        item["label"] == "fallback-simulation"
        for item in release_payload["smoke_checks"]
    )
    assert "fallback_simulations_json" in calls["manifest_artifacts"]


def test_release_readiness_command_summarizes_readiness_cli_before_config_examples(tmp_path: Path) -> None:
    check = _run_command(
        "readiness-cli",
        [
            sys.executable,
            "-c",
            (
                "print('Readiness surface:')\n"
                "print('readiness: warning (anthropic) [fallback missing]')\n"
                "print('Config examples:')\n"
                "print('- OpenAI fallback: {...}')"
            ),
        ],
        cwd=tmp_path,
        timeout=30,
    )

    assert check.status == "passed"
    assert check.summary == "readiness: warning (anthropic) [fallback missing]"


def test_release_readiness_command_summarizes_readiness_examples(tmp_path: Path) -> None:
    check = _run_command(
        "readiness-examples",
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "print(json.dumps({'risk_scope':'no-fallback-configured',"
                "'fallback_config_examples':[{}, {}]}))"
            ),
        ],
        cwd=tmp_path,
        timeout=30,
    )

    assert check.status == "passed"
    assert check.summary == "fallback examples 2 (no-fallback-configured)"


def test_release_readiness_command_summarizes_readiness_repair_plan(tmp_path: Path) -> None:
    check = _run_command(
        "readiness-repair-plan",
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "print(json.dumps({'risk_scope':'no-fallback-configured',"
                "'repair_plan':[{}, {}, {}]}))"
            ),
        ],
        cwd=tmp_path,
        timeout=30,
    )

    assert check.status == "passed"
    assert check.summary == "repair plan 3 (no-fallback-configured)"


def test_release_readiness_command_summarizes_readiness_patch_preview(tmp_path: Path) -> None:
    check = _run_command(
        "readiness-patch-preview",
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "print(json.dumps({'risk_scope':'no-fallback-configured',"
                "'fallback_settings_patch_preview':[{}, {}]}))"
            ),
        ],
        cwd=tmp_path,
        timeout=30,
    )

    assert check.status == "passed"
    assert check.summary == "patch preview 2 (no-fallback-configured)"


def test_release_readiness_command_summarizes_readiness_doctor(tmp_path: Path) -> None:
    check = _run_command(
        "readiness-doctor",
        [
            sys.executable,
            "-c",
            (
                "print('# MiniCode Readiness Doctor')\n"
                "print('- Status: warning')\n"
                "print('- Risk scope: no-fallback-configured')"
            ),
        ],
        cwd=tmp_path,
        timeout=30,
    )

    assert check.status == "passed"
    assert check.summary == "doctor warning (no-fallback-configured)"


def test_release_readiness_artifact_check_passes_for_doctor_and_examples(tmp_path: Path) -> None:
    examples_path = tmp_path / "readiness-fallback-examples.json"
    doctor_path = tmp_path / "readiness-doctor.md"
    repair_plan_path = tmp_path / "readiness-repair-plan.json"
    patch_preview_path = tmp_path / "readiness-fallback-patch-preview.json"
    examples_path.write_text(
        json.dumps({"fallback_config_examples": [{}, {}]}),
        encoding="utf-8",
    )
    doctor_path.write_text(
        "\n".join(
            [
                "# MiniCode Readiness Doctor",
                "",
                "## Local Preflight",
                "",
                "- `primary-provider-config`: pass",
                "",
                "## Safety",
                "",
                "- This report is read-only.",
                "- It does not modify MiniCode settings.",
            ]
        ),
        encoding="utf-8",
    )
    repair_plan_path.write_text(
        json.dumps(
            {
                "summary": "readiness: warning",
                "status": "warning",
                "risk_scope": "no-fallback-configured",
                "repair_plan": [{"step": "verify-local-readiness"}],
            }
        ),
        encoding="utf-8",
    )
    patch_preview_path.write_text(
        json.dumps(
            {
                "summary": "readiness: warning",
                "status": "warning",
                "risk_scope": "no-fallback-configured",
                "fallback_settings_patch_preview": [{"label": "OpenAI fallback"}],
            }
        ),
        encoding="utf-8",
    )

    check = _check_readiness_artifacts(
        examples_path=examples_path,
        doctor_path=doctor_path,
        repair_plan_path=repair_plan_path,
        patch_preview_path=patch_preview_path,
    )

    assert check.status == "passed"
    assert check.summary == (
        "readiness artifacts valid: "
        "2 fallback example(s), 1 repair step(s), 1 patch preview(s)"
    )


def test_release_readiness_artifact_redaction_check_passes_for_placeholders(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text(
        json.dumps({"OPENAI_API_KEY": "sk-...", "status": "warning"}),
        encoding="utf-8",
    )

    check = _check_artifact_redaction([artifact])

    assert check.status == "passed"
    assert check.summary == "artifact redaction valid: 1 artifact(s)"


def test_release_readiness_artifact_redaction_check_fails_on_real_secret(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text(
        json.dumps({"OPENAI_API_KEY": "sk-real-secret-1234567890"}),
        encoding="utf-8",
    )

    check = _check_artifact_redaction([artifact])

    assert check.status == "failed"
    assert check.exit_code == 1
    assert "sensitive token" in check.summary


def test_release_readiness_headless_trace_check_passes(tmp_path: Path) -> None:
    trace_path = tmp_path / "headless-trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "exit_code": 1,
                "readiness_report": {
                    "status": "warning",
                    "summary": "readiness: warning",
                },
                "repair_plan": [{"step": "verify-local-readiness"}],
            }
        ),
        encoding="utf-8",
    )

    check = _check_headless_trace(trace_path)

    assert check.status == "passed"
    assert check.summary == "headless trace valid: exit_code=1 readiness=warning repair_steps=1"


def test_release_readiness_artifact_manifest_check_passes(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("evidence\n", encoding="utf-8")
    from benchmarks.release_readiness import build_artifact_manifest

    manifest = build_artifact_manifest({"artifact": artifact})
    check = _check_artifact_manifest(manifest)

    assert check.status == "passed"
    assert check.summary == "artifact manifest valid: 1 artifact(s)"


def test_release_readiness_structure_compliance_artifact_check_passes(tmp_path: Path) -> None:
    artifact = tmp_path / "structure-compliance.json"
    artifact.write_text(
        json.dumps(
            {
                "cliPassed": True,
                "qualityGatePassed": True,
                "qualityGateFindings": [],
                "materialInventory": {
                    "passed": True,
                    "findings": [],
                    "summary": {
                        "focused_gate_count": 16,
                        "material_count": 9,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    check = _check_structure_compliance_artifact(artifact)

    assert check.status == "passed"
    assert check.label == "structure-compliance-artifact"


def test_release_readiness_fallback_switch_smoke_delegates_to_utility() -> None:
    check = _check_fallback_switch_smoke()

    assert check.status == "passed"
    assert check.label == "fallback-switch-smoke"


def test_release_readiness_bundle_check_delegates_to_utility(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "readiness-bundle"
    check = _check_readiness_bundle(bundle_dir)

    assert check.status == "failed"
    assert check.label == "readiness-bundle"
    assert "readiness bundle missing" in check.summary


def test_release_readiness_fallback_evidence_check_delegates_to_utility(tmp_path: Path) -> None:
    examples_path = tmp_path / "examples.json"
    doctor_path = tmp_path / "doctor.md"
    repair_path = tmp_path / "repair.json"
    patch_preview_path = tmp_path / "patch-preview.json"
    bundle_dir = tmp_path / "bundle"
    bundle_manifest_path = bundle_dir / "manifest.json"
    bundle_dir.mkdir()
    examples_path.write_text('{"fallback_config_examples": []}\n', encoding="utf-8")
    doctor_path.write_text("# MiniCode Readiness Doctor\n", encoding="utf-8")
    repair_path.write_text('{"repair_plan": []}\n', encoding="utf-8")
    patch_preview_path.write_text('{"fallback_settings_patch_preview": []}\n', encoding="utf-8")
    bundle_manifest_path.write_text("[]\n", encoding="utf-8")
    check = _check_fallback_evidence(
        {
            "provider_status": "at-risk",
            "provider_diagnostics": [{"label": "headless-smoke", "outcome": "provider_api_error"}],
            "readiness_artifacts": {
                "fallback_examples_json": str(examples_path),
                "doctor_markdown": str(doctor_path),
                "repair_plan_json": str(repair_path),
                "patch_preview_json": str(patch_preview_path),
                "bundle_directory": str(bundle_dir),
                "bundle_manifest_json": str(bundle_manifest_path),
            },
            "readiness_report": {
                "fallback_ready": False,
                "risk_scope": "no-fallback-configured",
                "fallback_config_examples": [{"label": "OpenAI fallback"}],
                "preflight_checks": [
                    {"label": "fallback-coverage"},
                    {"label": "live-smoke-readiness"},
                ],
                "repair_plan": [
                    {"step": "diagnose-local-readiness"},
                    {"step": "choose-fallback-provider"},
                    {"step": "verify-local-readiness"},
                    {"step": "verify-release-readiness"},
                ],
            },
        }
    )

    assert check.status == "passed"
    assert check.label == "fallback-evidence"


def test_release_readiness_fallback_patch_preview_check_delegates_to_utility(tmp_path: Path) -> None:
    preview_path = tmp_path / "patch-preview.json"
    preview_path.write_text(
        json.dumps(
            {
                "summary": "readiness: warning",
                "status": "warning",
                "risk_scope": "no-fallback-configured",
                "fallback_settings_patch_preview": [
                    {
                        "label": "OpenAI fallback",
                        "target_path": str(tmp_path / "settings.json"),
                        "merge_patch": {"fallbackModels": ["gpt-4o"]},
                        "safety": "preview-only; no settings are modified",
                        "apply_notes": [
                            "Review the selected provider patch before applying it.",
                            "Replace placeholder credentials locally.",
                            "Merge only one selected patch into the target settings file.",
                            "Run minicode-readiness --json --fail-on blocked after applying.",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    check = _check_fallback_patch_preview(preview_path)

    assert check.status == "passed"
    assert check.label == "fallback-patch-preview"


def test_release_readiness_artifact_check_fails_on_missing_files(tmp_path: Path) -> None:
    check = _check_readiness_artifacts(
        examples_path=tmp_path / "missing-examples.json",
        doctor_path=tmp_path / "missing-doctor.md",
        repair_plan_path=tmp_path / "missing-repair-plan.json",
        patch_preview_path=tmp_path / "missing-patch-preview.json",
    )

    assert check.status == "failed"
    assert check.exit_code == 1
    assert "missing examples artifact" in check.summary


def test_release_readiness_prepares_one_workspace_session(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    workspace = tmp_path / "release_smoke_workspace"

    with patch("minicode.session.SESSIONS_DIR", sessions_dir), patch(
        "minicode.session.MINI_CODE_DIR",
        tmp_path,
    ):
        _prepare_saved_session(workspace)
        _prepare_saved_session(workspace)

        sessions = list_sessions(workspace=str(workspace))

    assert len(sessions) == 1
    assert sessions[0].workspace == str(workspace)
