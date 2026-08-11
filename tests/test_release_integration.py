from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from minicode.agent_loop import run_agent_turn
from minicode.memory import MemoryManager
from minicode.permissions import PermissionManager
from minicode.product_surfaces import ReadinessReport
from minicode.prompt import build_system_prompt
from minicode.tooling import ToolRegistry
from minicode.tools import create_default_tool_registry
from minicode.tui.event_flow import _handle_event
from minicode.tui.input_handler import _handle_input
from minicode.tui.input_parser import KeyEvent
from minicode.tui.state import ScreenState, TtyAppArgs
from minicode.types import AgentStep


REPO_ROOT = Path(__file__).resolve().parent.parent


def _release_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT)
            + os.pathsep
            + env.get("PYTHONPATH", ""),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "MINI_CODE_MODEL": "gpt-4o",
            "MINI_CODE_MODEL_MODE": "mock",
            "MINI_CODE_TOOL_PROFILE": "core",
            "MINI_CODE_SHOW_GUIDE": "0",
            "OPENAI_API_KEY": "test-openai-key",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "OPENROUTER_API_KEY": "",
            "CUSTOM_API_KEY": "",
            "CUSTOM_API_BASE_URL": "",
        }
    )
    return env


def test_release_cli_valid_config_runs_as_black_box(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    completed = subprocess.run(
        [sys.executable, "-m", "minicode.main", "valid-config"],
        cwd=workspace,
        env=_release_env(tmp_path),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Configuration Diagnostics" in completed.stdout
    assert "Status: OK" in completed.stdout
    assert "Provider: openai" in completed.stdout
    assert "Tool Profile: core" in completed.stdout
    assert "UnicodeEncodeError" not in completed.stderr


def test_release_cli_lists_only_current_workspace_sessions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    env = _release_env(tmp_path)

    seed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from minicode.session import create_new_session, save_session\n"
                f"s1=create_new_session(workspace={str(workspace)!r})\n"
                "s1.messages=[{'role':'user','content':'current workspace task'}]\n"
                "save_session(s1)\n"
                f"s2=create_new_session(workspace={str(other_workspace)!r})\n"
                "s2.messages=[{'role':'user','content':'other workspace task'}]\n"
                "save_session(s2)\n"
            ),
        ],
        cwd=workspace,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert seed.returncode == 0, seed.stderr

    completed = subprocess.run(
        [sys.executable, "-m", "minicode.main", "--list-workspace-sessions"],
        cwd=workspace,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "current workspace task" in completed.stdout
    assert "other workspace task" not in completed.stdout
    assert "Total: 1 session(s)" in completed.stdout


def test_release_cli_readiness_entrypoints_run_as_black_box(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = _release_env(tmp_path)

    text = subprocess.run(
        [sys.executable, "-m", "minicode.main", "--readiness"],
        cwd=workspace,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert text.returncode == 0, text.stderr
    assert "Readiness surface:" in text.stdout
    assert "Risk scope:" in text.stdout
    assert "Next actions:" in text.stdout

    as_json = subprocess.run(
        [sys.executable, "-m", "minicode.main", "--readiness-json"],
        cwd=workspace,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert as_json.returncode == 0, as_json.stderr
    payload = json.loads(as_json.stdout)
    assert payload["provider"] == "openai"
    assert "risk_scope" in payload
    assert "next_actions" in payload


def test_release_readiness_script_runs_as_black_box(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = _release_env(tmp_path)

    text = subprocess.run(
        [sys.executable, "-m", "minicode.readiness", "--cwd", str(workspace)],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert text.returncode == 0, text.stderr
    assert "Readiness surface:" in text.stdout
    assert "Risk scope:" in text.stdout
    assert "Local preflight:" in text.stdout

    as_json = subprocess.run(
        [sys.executable, "-m", "minicode.readiness", "--cwd", str(workspace), "--json"],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert as_json.returncode == 0, as_json.stderr
    payload = json.loads(as_json.stdout)
    assert payload["provider"] == "openai"
    assert "risk_scope" in payload
    assert payload["preflight_checks"]
    assert payload["preflight_checks"][-1]["label"] == "live-smoke-readiness"


def test_release_readiness_script_exports_fallback_examples_as_black_box(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    examples_path = tmp_path / "artifacts" / "fallback-examples.json"
    env = _release_env(tmp_path)
    env.update(
        {
            "MINI_CODE_MODEL": "deepseek-v4-pro[1m]",
            "MINI_CODE_MODEL_MODE": "",
            "ANTHROPIC_AUTH_TOKEN": "proxy-token",
            "ANTHROPIC_BASE_URL": "https://example.invalid",
            "OPENAI_API_KEY": "",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "minicode.readiness",
            "--cwd",
            str(workspace),
            "--examples",
            "--examples-out",
            str(examples_path),
            "--fail-on",
            "blocked",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    saved_payload = json.loads(examples_path.read_text(encoding="utf-8"))
    assert payload == saved_payload
    assert payload["risk_scope"] == "no-fallback-configured"
    assert payload["fallback_config_examples"]
    assert payload["fallback_config_examples"][0]["settings"]["env"]["OPENAI_API_KEY"] == "sk-..."


def test_release_readiness_script_exports_doctor_report_as_black_box(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    doctor_path = tmp_path / "artifacts" / "readiness-doctor.md"
    env = _release_env(tmp_path)
    env.update(
        {
            "MINI_CODE_MODEL": "deepseek-v4-pro[1m]",
            "MINI_CODE_MODEL_MODE": "",
            "ANTHROPIC_AUTH_TOKEN": "proxy-token",
            "ANTHROPIC_BASE_URL": "https://example.invalid",
            "OPENAI_API_KEY": "",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "minicode.readiness",
            "--cwd",
            str(workspace),
            "--doctor",
            "--doctor-out",
            str(doctor_path),
            "--fail-on",
            "blocked",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    saved = doctor_path.read_text(encoding="utf-8")
    assert completed.stdout == saved
    assert "# MiniCode Readiness Doctor" in saved
    assert "- Status: warning" in saved
    assert "- Risk scope: no-fallback-configured" in saved
    assert "## Local Preflight" in saved
    assert "## Repair Plan" in saved
    assert "primary-provider-config" in saved
    assert "live-smoke-readiness" in saved
    assert "OPENAI_API_KEY" in saved
    assert "This report is read-only." in saved


def test_release_readiness_script_exports_repair_plan_as_black_box(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repair_path = tmp_path / "artifacts" / "readiness-repair-plan.json"
    env = _release_env(tmp_path)
    env.update(
        {
            "MINI_CODE_MODEL": "deepseek-v4-pro[1m]",
            "MINI_CODE_MODEL_MODE": "",
            "ANTHROPIC_AUTH_TOKEN": "proxy-token",
            "ANTHROPIC_BASE_URL": "https://example.invalid",
            "OPENAI_API_KEY": "",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "minicode.readiness",
            "--cwd",
            str(workspace),
            "--repair-plan",
            "--repair-plan-out",
            str(repair_path),
            "--fail-on",
            "blocked",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    saved_payload = json.loads(repair_path.read_text(encoding="utf-8"))
    assert payload == saved_payload
    assert payload["risk_scope"] == "no-fallback-configured"
    assert payload["repair_plan"]
    assert any(item["step"] == "choose-fallback-provider" for item in payload["repair_plan"])
    assert any(item.get("safety") == "preview-only; no settings are modified" for item in payload["repair_plan"])


def test_release_readiness_script_exports_patch_preview_as_black_box(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    patch_preview_path = tmp_path / "artifacts" / "readiness-fallback-patch-preview.json"
    env = _release_env(tmp_path)
    env.update(
        {
            "MINI_CODE_MODEL": "deepseek-v4-pro[1m]",
            "MINI_CODE_MODEL_MODE": "",
            "ANTHROPIC_AUTH_TOKEN": "proxy-token",
            "ANTHROPIC_BASE_URL": "https://example.invalid",
            "OPENAI_API_KEY": "",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "minicode.readiness",
            "--cwd",
            str(workspace),
            "--patch-preview",
            "--patch-preview-out",
            str(patch_preview_path),
            "--fail-on",
            "blocked",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    saved_payload = json.loads(patch_preview_path.read_text(encoding="utf-8"))
    assert payload == saved_payload
    assert payload["risk_scope"] == "no-fallback-configured"
    assert payload["fallback_settings_patch_preview"]
    assert payload["fallback_settings_patch_preview"][0]["merge_patch"]["env"]["OPENAI_API_KEY"] == "sk-..."
    assert payload["fallback_settings_patch_preview"][0]["safety"] == "preview-only; no settings are modified"


def test_readiness_simulates_selected_patch_without_writing_settings(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    preview_path = tmp_path / "preview.json"
    output_path = tmp_path / "simulation.json"
    target_path = tmp_path / "must" / "not" / "be" / "written.json"
    preview_path.write_text(
        json.dumps(
            {
                "status": "warning",
                "risk_scope": "no-fallback-configured",
                "fallback_settings_patch_preview": [
                    {
                        "label": "OpenAI fallback",
                        "target_path": str(target_path),
                        "merge_patch": {
                            "fallbackModels": ["gpt-4o"],
                            "env": {
                                "OPENAI_API_KEY": "sk-...",
                                "OPENAI_BASE_URL": "https://api.openai.com",
                            },
                        },
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
    env = _release_env(tmp_path)
    env.update(
        {
            "MINI_CODE_MODEL": "claude-sonnet-4-20250514",
            "ANTHROPIC_AUTH_TOKEN": "primary-auth-token",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "OPENAI_API_KEY": "",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "minicode.readiness",
            "--cwd",
            str(workspace),
            "--simulate-fallback-patch",
            str(preview_path),
            "--fallback-label",
            "OpenAI fallback",
            "--simulation-out",
            str(output_path),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    assert payload["status"] == "requires-credentials"
    assert payload["simulation_only"] is True
    assert payload["live_provider_claim"] is False
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
    assert not target_path.exists()


def test_readiness_simulation_no_model_emits_redacted_invalid_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    preview_path = tmp_path / "preview.json"
    output_path = tmp_path / "simulation.json"
    preview_path.write_text(
        json.dumps(
            {
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
    env = _release_env(tmp_path)
    env.update(
        {
            "MINI_CODE_MODEL": "",
            "OPENAI_API_KEY": "sk-real-secret-1234567890",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "minicode.readiness",
            "--cwd",
            str(workspace),
            "--simulate-fallback-patch",
            str(preview_path),
            "--fallback-label",
            "OpenAI fallback",
            "--simulation-out",
            str(output_path),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert payload["status"] == "invalid"
    assert payload["simulation_only"] is True
    assert payload["live_provider_claim"] is False
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
    assert "Traceback" not in completed.stderr
    assert "sk-real-secret" not in completed.stdout
    assert "sk-real-secret" not in completed.stderr


def test_readiness_simulation_threshold_and_missing_label_are_deterministic(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    preview_path = tmp_path / "preview.json"
    preview_path.write_text(
        json.dumps(
            {
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
    env = _release_env(tmp_path)
    env["OPENAI_API_KEY"] = ""
    env["ANTHROPIC_AUTH_TOKEN"] = "primary-auth-token"
    command = [
        sys.executable,
        "-m",
        "minicode.readiness",
        "--cwd",
        str(workspace),
        "--simulate-fallback-patch",
        str(preview_path),
    ]

    missing_label = subprocess.run(
        command,
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert missing_label.returncode == 2
    assert "--fallback-label is required with --simulate-fallback-patch" in missing_label.stderr

    threshold = subprocess.run(
        [
            *command,
            "--fallback-label",
            "OpenAI fallback",
            "--simulation-fail-on",
            "requires-credentials",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert threshold.returncode == 1
    assert threshold.stdout, threshold.stderr
    assert json.loads(threshold.stdout)["status"] == "requires-credentials"


def test_release_readiness_script_exports_bundle_as_black_box(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bundle_dir = tmp_path / "artifacts" / "readiness-bundle"
    env = _release_env(tmp_path)
    env.update(
        {
            "MINI_CODE_MODEL": "deepseek-v4-pro[1m]",
            "MINI_CODE_MODEL_MODE": "",
            "ANTHROPIC_AUTH_TOKEN": "proxy-token",
            "ANTHROPIC_BASE_URL": "https://example.invalid",
            "OPENAI_API_KEY": "",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "minicode.readiness",
            "--cwd",
            str(workspace),
            "--bundle-out",
            str(bundle_dir),
            "--fail-on",
            "blocked",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Bundle artifacts:" in completed.stdout
    examples_path = bundle_dir / "readiness-fallback-examples.json"
    doctor_path = bundle_dir / "readiness-doctor.md"
    repair_path = bundle_dir / "readiness-repair-plan.json"
    patch_preview_path = bundle_dir / "readiness-fallback-patch-preview.json"
    simulations_path = bundle_dir / "readiness-fallback-simulations.json"
    manifest_path = bundle_dir / "readiness-artifact-manifest.json"
    examples = json.loads(examples_path.read_text(encoding="utf-8"))
    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    patch_preview = json.loads(patch_preview_path.read_text(encoding="utf-8"))
    simulations = json.loads(simulations_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert examples["risk_scope"] == "no-fallback-configured"
    assert "## Repair Plan" in doctor_path.read_text(encoding="utf-8")
    assert repair["repair_plan"]
    assert patch_preview["fallback_settings_patch_preview"]
    preview_labels = [
        item["label"] for item in patch_preview["fallback_settings_patch_preview"]
    ]
    assert simulations["simulation_only"] is True
    assert simulations["live_provider_claim"] is False
    assert [item["selected_label"] for item in simulations["simulations"]] == preview_labels
    assert len(simulations["simulations"]) == len(preview_labels)
    assert "proxy-token" not in simulations_path.read_text(encoding="utf-8")
    assert {item["label"] for item in manifest} == {
        "doctor_markdown",
        "fallback_examples_json",
        "fallback_simulations_json",
        "patch_preview_json",
        "repair_plan_json",
    }
    assert all(item["exists"] and item["size_bytes"] > 0 and len(item["sha256"]) == 64 for item in manifest)


def test_readiness_non_bundle_outputs_skip_fallback_simulation(monkeypatch, tmp_path: Path, capsys) -> None:
    import minicode.readiness

    report = ReadinessReport(
        status="ready",
        provider="openai",
        provider_ready=True,
        provider_channel="openai via OPENAI_API_KEY",
        risk_scope="none",
        summary="readiness: ready (openai)",
    )
    monkeypatch.setattr(minicode.readiness, "build_readiness_report", lambda cwd: report)

    def fail_if_called(cwd: str, patch_preview_payload: dict) -> dict:
        raise AssertionError("fallback simulations should only run for --bundle-out")

    monkeypatch.setattr(minicode.readiness, "_fallback_simulations_payload", fail_if_called)

    for output_args in (
        ["--doctor"],
        ["--repair-plan"],
        ["--patch-preview"],
        ["--examples"],
        ["--json"],
    ):
        assert minicode.readiness.main(["--cwd", str(tmp_path), *output_args]) == 0
        capsys.readouterr()


def test_readiness_outputs_redact_real_secrets(monkeypatch, tmp_path: Path, capsys) -> None:
    import minicode.readiness

    report = ReadinessReport(
        status="warning",
        provider="openai",
        provider_ready=True,
        provider_channel="openai via OPENAI_API_KEY",
        fallback_ready=False,
        fallback_config_examples=[
            {
                "label": "real fallback",
                "path": str(tmp_path / "settings.json"),
                "settings": {
                    "fallbackModels": ["gpt-4o"],
                    "env": {
                        "OPENAI_API_KEY": "sk-real-secret-1234567890",
                        "OPENAI_BASE_URL": "https://api.openai.com",
                    },
                },
            }
        ],
        issues=["OPENAI_API_KEY=sk-real-secret-1234567890"],
        next_actions=["Use authToken token-secret-1234567890"],
        repair_plan=[
            {
                "step": "preview-secret-fallback",
                "status": "preview",
                "settings_preview": {
                    "env": {"OPENAI_API_KEY": "sk-real-secret-1234567890"}
                },
            }
        ],
        summary="readiness: warning [Bearer token-secret-1234567890]",
    )
    monkeypatch.setattr(minicode.readiness, "build_readiness_report", lambda cwd: report)

    examples_path = tmp_path / "examples.json"
    doctor_path = tmp_path / "doctor.md"
    repair_path = tmp_path / "repair.json"
    patch_preview_path = tmp_path / "patch-preview.json"

    assert minicode.readiness.main(["--cwd", str(tmp_path), "--json"]) == 0
    json_stdout = capsys.readouterr().out
    assert "sk-real-secret" not in json_stdout
    assert "token-secret" not in json_stdout
    assert "[REDACTED]" in json_stdout

    assert minicode.readiness.main(
        [
            "--cwd",
            str(tmp_path),
            "--examples",
            "--examples-out",
            str(examples_path),
        ]
    ) == 0
    examples_stdout = capsys.readouterr().out
    examples_saved = examples_path.read_text(encoding="utf-8")
    assert "sk-real-secret" not in examples_stdout
    assert "sk-real-secret" not in examples_saved
    assert json.loads(examples_saved)["fallback_config_examples"][0]["settings"]["env"]["OPENAI_API_KEY"] == "[REDACTED]"

    assert minicode.readiness.main(
        [
            "--cwd",
            str(tmp_path),
            "--repair-plan",
            "--repair-plan-out",
            str(repair_path),
        ]
    ) == 0
    repair_stdout = capsys.readouterr().out
    repair_saved = repair_path.read_text(encoding="utf-8")
    assert "sk-real-secret" not in repair_stdout
    assert "sk-real-secret" not in repair_saved
    assert json.loads(repair_saved)["repair_plan"][0]["settings_preview"]["env"]["OPENAI_API_KEY"] == "[REDACTED]"

    assert minicode.readiness.main(
        [
            "--cwd",
            str(tmp_path),
            "--patch-preview",
            "--patch-preview-out",
            str(patch_preview_path),
        ]
    ) == 0
    patch_preview_stdout = capsys.readouterr().out
    patch_preview_saved = patch_preview_path.read_text(encoding="utf-8")
    assert "sk-real-secret" not in patch_preview_stdout
    assert "sk-real-secret" not in patch_preview_saved
    assert json.loads(patch_preview_saved)["fallback_settings_patch_preview"][0]["merge_patch"]["env"]["OPENAI_API_KEY"] == "[REDACTED]"

    assert minicode.readiness.main(
        [
            "--cwd",
            str(tmp_path),
            "--doctor",
            "--doctor-out",
            str(doctor_path),
        ]
    ) == 0
    doctor_stdout = capsys.readouterr().out
    doctor_saved = doctor_path.read_text(encoding="utf-8")
    assert "sk-real-secret" not in doctor_stdout
    assert "token-secret" not in doctor_stdout
    assert "sk-real-secret" not in doctor_saved
    assert "token-secret" not in doctor_saved


def test_release_readiness_script_can_fail_on_threshold(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = _release_env(tmp_path)
    env.update(
        {
            "MINI_CODE_MODEL": "deepseek-v4-pro[1m]",
            "MINI_CODE_MODEL_MODE": "",
            "ANTHROPIC_AUTH_TOKEN": "proxy-token",
            "ANTHROPIC_BASE_URL": "https://example.invalid",
            "OPENAI_API_KEY": "",
        }
    )

    warning_gate = subprocess.run(
        [
            sys.executable,
            "-m",
            "minicode.readiness",
            "--cwd",
            str(workspace),
            "--json",
            "--fail-on",
            "warning",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert warning_gate.returncode == 1
    warning_payload = json.loads(warning_gate.stdout)
    assert warning_payload["status"] == "warning"
    assert warning_payload["risk_scope"] == "no-fallback-configured"

    blocked_gate = subprocess.run(
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
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert blocked_gate.returncode == 0, blocked_gate.stderr
    assert json.loads(blocked_gate.stdout)["status"] == "warning"


def test_release_non_tty_main_handles_memory_and_local_commands(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    completed = subprocess.run(
        [sys.executable, "-m", "minicode.main"],
        cwd=workspace,
        env=_release_env(tmp_path),
        input="# Prefer pytest before release\n/memory\n/tools\n/exit\n",
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Saved memory (project): Prefer pytest before release" in completed.stdout
    assert "Memory System Status" in completed.stdout
    assert "read_file:" in completed.stdout
    assert "base64_encode:" not in completed.stdout

    memory_file = workspace / ".mini-code-memory" / "MEMORY.md"
    assert memory_file.exists()
    assert "Prefer pytest before release" in memory_file.read_text(encoding="utf-8")


class ReadFileReleaseModel:
    def __init__(self) -> None:
        self.calls = 0

    def next(self, messages, on_stream_chunk=None):
        self.calls += 1
        if self.calls == 1:
            return AgentStep(
                type="tool_calls",
                calls=[
                    {
                        "id": "release-read",
                        "toolName": "read_file",
                        "input": {"path": "README.md"},
                    }
                ],
            )
        tool_result = next(
            message for message in reversed(messages) if message["role"] == "tool_result"
        )
        return AgentStep(
            type="assistant",
            content=f"release final saw: {tool_result['content'][:80]}",
        )


def test_release_agent_loop_executes_real_tool_chain(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Release Fixture\n", encoding="utf-8")

    tools = create_default_tool_registry(str(workspace), runtime={"toolProfile": "core"})
    permissions = PermissionManager(
        str(workspace),
        prompt=lambda _request: {"decision": "allow_once"},
    )

    messages = run_agent_turn(
        model=ReadFileReleaseModel(),
        tools=tools,
        messages=[
            {"role": "system", "content": "release integration system"},
            {"role": "user", "content": "read the release fixture"},
        ],
        cwd=str(workspace),
        permissions=permissions,
        max_steps=5,
    )

    assert any(message["role"] == "assistant_tool_call" for message in messages)
    assert any(
        message["role"] == "tool_result" and "# Release Fixture" in message["content"]
        for message in messages
    )
    assert messages[-1]["role"] == "assistant"
    assert "Release Fixtur" in messages[-1]["content"]


def test_release_openai_protocol_fallback_completes_tool_turn(tmp_path: Path, monkeypatch) -> None:
    """Exercise provider failure, automatic fallback, and tool continuation locally."""
    primary_model = "qwen3.7-max"
    fallback_model = "kimi-k2.7-code"
    requests: list[dict] = []

    class FallbackProtocolHandler(BaseHTTPRequestHandler):
        server_version = "MiniCodeFallbackFixture/1.0"

        def log_message(self, _format: str, *_args) -> None:
            return

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/v1/models":
                self._send_json(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {"id": primary_model, "object": "model"},
                            {"id": fallback_model, "object": "model"},
                        ],
                    },
                )
                return
            self._send_json(404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append(payload)
            model = payload.get("model")
            messages = payload.get("messages", [])

            if model == primary_model:
                self._send_json(
                    503,
                    {
                        "error": {
                            "message": f"No available channel for model {primary_model}",
                            "type": "server_error",
                        }
                    },
                )
                return

            if model != fallback_model:
                self._send_json(
                    400,
                    {"error": {"message": f"unexpected model: {model}"}},
                )
                return

            if any(message.get("role") == "tool" for message in messages):
                response = "fallback succeeded after tool execution"
                self._send_json(
                    200,
                    {
                        "id": "chatcmpl-fallback-final",
                        "object": "chat.completion",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": response},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    },
                )
                return

            self._send_json(
                200,
                {
                    "id": "chatcmpl-fallback-tool",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-read-marker",
                                        "type": "function",
                                        "function": {
                                            "name": "read_marker",
                                            "arguments": json.dumps({"path": "README.md"}),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("# fallback fixture\n", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), FallbackProtocolHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        from minicode.model_registry import create_model_adapter
        from minicode.tooling import ToolDefinition, ToolResult

        def run_read_marker(input_data: dict, _context) -> ToolResult:
            return ToolResult(ok=True, output=f"marker:{input_data['path']}")

        tools = ToolRegistry(
            [
                ToolDefinition(
                    name="read_marker",
                    description="Read the deterministic release marker.",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                    validator=lambda value: value,
                    run=run_read_marker,
                )
            ]
        )
        runtime = {
            "model": primary_model,
            "configuredModel": primary_model,
            "openaiApiKey": "local-test-key",
            "openaiBaseUrl": f"http://127.0.0.1:{server.server_port}",
            "openaiFallbackModels": [fallback_model],
            "_openaiExposedModels": [primary_model, fallback_model],
            "maxOutputTokens": 128,
        }
        model = create_model_adapter(primary_model, tools, runtime=runtime)
        monkeypatch.setenv("MINICODE_MODEL_TIMEOUT", "5")

        messages = run_agent_turn(
            model=model,
            tools=tools,
            messages=[
                {"role": "system", "content": "Use the available tool, then report the result."},
                {"role": "user", "content": "Read the marker and finish the task."},
            ],
            cwd=str(workspace),
            permissions=PermissionManager(
                str(workspace),
                prompt=lambda _request: {"decision": "allow_once"},
            ),
            runtime=runtime,
            max_steps=5,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    assert [request.get("model") for request in requests] == [primary_model, fallback_model, fallback_model]
    assert any(
        message["role"] == "assistant_tool_call" and message["toolName"] == "read_marker"
        for message in messages
    )
    assert any(
        message["role"] == "tool_result" and "marker:README.md" in message["content"]
        for message in messages
    )
    assert messages[-1]["role"] == "assistant"
    assert "fallback succeeded" in messages[-1]["content"]
    assert runtime["model"] == fallback_model


class PromptCapturingModel:
    def __init__(self) -> None:
        self.system_prompt = ""

    def next(self, messages, on_stream_chunk=None):
        self.system_prompt = messages[0]["content"]
        return AgentStep(type="assistant", content="ok")


def test_release_memory_is_injected_into_next_agent_turn(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = MemoryManager(workspace)
    assert memory.handle_user_memory_input("# Prefer pytest before release")

    model = PromptCapturingModel()
    messages = [
        {
            "role": "system",
            "content": build_system_prompt(
                str(workspace),
                [],
                {
                    "skills": [],
                    "mcpServers": [],
                    "memory_context": memory.get_relevant_context(query="release tests"),
                },
            ),
        },
        {"role": "user", "content": "How should I verify release tests?"},
    ]

    run_agent_turn(
        model=model,
        tools=ToolRegistry([]),
        messages=messages,
        cwd=str(workspace),
        max_steps=1,
    )

    assert "Project Memory & Context" in model.system_prompt
    assert "Prefer pytest before release" in model.system_prompt


def test_release_tty_return_routes_memory_without_agent_turn(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = MemoryManager(workspace)
    state = ScreenState(input="# Prefer pytest before release", cursor_offset=30)
    args = TtyAppArgs(
        runtime=None,
        tools=ToolRegistry([]),
        model=None,
        messages=[{"role": "system", "content": "sys"}],
        cwd=str(workspace),
        permissions=PermissionManager(str(workspace)),
        memory_manager=memory,
    )
    renders: list[bool] = []

    _handle_event(
        args,
        state,
        KeyEvent(name="return", ctrl=False, meta=False),
        lambda: renders.append(True),
        threading.Event(),
        {},
        _handle_input,
    )

    assert renders
    assert state.is_busy is False
    assert len(state.transcript) == 2
    assert state.transcript[0].kind == "user"
    assert state.transcript[1].kind == "assistant"
    assert "Saved memory" in state.transcript[1].body
    assert any("pytest" in entry.content for entry in memory.search("pytest"))
