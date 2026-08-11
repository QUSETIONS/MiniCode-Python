import json

from minicode.release_readiness import (
    ReleaseCheck,
    build_artifact_manifest,
    check_artifact_manifest,
    check_fallback_evidence,
    check_fallback_evidence_payload,
    check_fallback_patch_preview,
    check_fallback_patch_preview_payload,
    check_fallback_switch_smoke,
    check_headless_trace,
    check_readiness_bundle,
    check_release_markdown,
    check_release_report,
    check_structure_compliance_artifact,
    classify_provider_outcome,
    find_sensitive_payload_leaks,
    find_sensitive_text_leaks,
    main as release_readiness_utility_main,
    release_readiness_as_dict,
    release_readiness_as_markdown,
    release_status_reasons,
    redact_sensitive_payload,
    redact_sensitive_text,
    should_fail_release_status,
    summarize_local_gate_status,
    summarize_provider_status,
    summarize_release_status,
)
import minicode.release_readiness as release_readiness


def _check(label: str, *, status: str = "passed", exit_code: int = 0, summary: str | None = None) -> ReleaseCheck:
    return ReleaseCheck(
        label=label,
        command=f"python -m {label}",
        exit_code=exit_code,
        status=status,
        summary=summary or f"{label} completed.",
    )


def test_evidence_path_normalizer_is_shared_and_boundary_safe(tmp_path) -> None:
    repo = tmp_path / "repo"
    home = tmp_path / "home"

    normalized = release_readiness.normalize_evidence_paths(
        {
            "repo": str(repo / ".temp" / "trace.json"),
            "home": str(home / ".mini-code" / "settings.json"),
            "similar": f"{repo}-archive",
        },
        repo_root=repo,
        home=home,
    )

    assert normalized == {
        "repo": ".temp/trace.json",
        "home": "~/.mini-code/settings.json",
        "similar": f"{repo}-archive",
    }


def _fallback_simulations_payload(label: str = "OpenAI fallback") -> dict:
    return {
        "simulation_only": True,
        "live_provider_claim": False,
        "simulations": [
            {
                "status": "requires-credentials",
                "selected_label": label,
                "credential_state": "placeholder",
                "fallback_candidates": ["gpt-4o"],
                "viable_fallbacks": [],
                "issues": ["Fallback credentials are required."],
                "next_actions": ["Configure the fallback credential locally."],
                "effective_config": {"credential_present": {"openai": False}},
                "simulation_only": True,
                "live_provider_claim": False,
            }
        ],
    }


def test_classify_provider_outcome_detects_answered_and_provider_outage() -> None:
    answered = classify_provider_outcome(exit_code=0, stdout="OK", stderr="")
    outage = classify_provider_outcome(
        exit_code=1,
        stdout="",
        stderr="Provider availability failure: all viable fallback models were unavailable.",
    )
    api_error = classify_provider_outcome(
        exit_code=1,
        stdout="Model API error (RuntimeError): error code: 1010",
        stderr="",
    )

    assert answered == ("answered", "OK")
    assert outage == ("provider_outage", "Provider availability failure: all viable fallback models were unavailable.")
    assert api_error == ("provider_api_error", "Model API error (RuntimeError): error code: 1010")


def test_classify_provider_outcome_keeps_local_channel_failures_local() -> None:
    for message in (
        "No available channel for model.",
        "No model configured.",
        "No auth configured.",
    ):
        outcome, summary = classify_provider_outcome(
            exit_code=1,
            stdout="",
            stderr=message,
        )

        assert outcome == "provider_channel_unavailable"
        assert summary == message


def test_summarize_release_status_treats_provider_outage_as_warning() -> None:
    status = summarize_release_status(
        compile_check=_check("compileall"),
        test_check=_check("pytest-q"),
        runtime_eval_check=_check("runtime-profile-eval"),
        smoke_checks=[_check("inspect-session"), _check("replay-session")],
        provider_outcomes=["provider_outage"],
        readiness_report={"fallback_ready": True},
    )

    assert status == "warning"


def test_summarize_release_status_escalates_provider_outage_without_fallbacks() -> None:
    status = summarize_release_status(
        compile_check=_check("compileall"),
        test_check=_check("pytest-q"),
        runtime_eval_check=_check("runtime-profile-eval"),
        smoke_checks=[_check("inspect-session"), _check("replay-session")],
        provider_outcomes=["provider_outage"],
        readiness_report={"fallback_ready": False},
    )

    assert status == "at-risk"


def test_summarize_release_status_treats_empty_or_api_error_as_at_risk() -> None:
    for outcome in ("empty_output", "provider_api_error", "timeout"):
        status = summarize_release_status(
            compile_check=_check("compileall"),
            test_check=_check("pytest-q"),
            runtime_eval_check=_check("runtime-profile-eval"),
            smoke_checks=[_check("inspect-session"), _check("replay-session")],
            provider_outcomes=[outcome],
            readiness_report={"fallback_ready": True},
        )

        assert status == "at-risk"


def test_summarize_release_status_treats_missing_provider_evidence_as_at_risk() -> None:
    status = summarize_release_status(
        compile_check=_check("compileall"),
        test_check=_check("pytest-q"),
        runtime_eval_check=_check("runtime-profile-eval"),
        smoke_checks=[_check("inspect-session"), _check("replay-session")],
        provider_outcomes=[],
        readiness_report={"fallback_ready": True},
    )

    assert summarize_provider_status(provider_outcomes=[], readiness_report={"fallback_ready": True}) == "at-risk"
    assert status == "at-risk"


def test_release_status_reasons_explain_local_provider_and_fallback_state() -> None:
    reasons = release_status_reasons(
        local_gate_status="pass",
        provider_status="at-risk",
        provider_diagnostics=[
            {
                "outcome": "provider_api_error",
                "error_code": "1010",
            }
        ],
        readiness_report={
            "fallback_ready": False,
            "risk_scope": "no-fallback-configured",
        },
    )

    assert "Local gates passed." in reasons
    assert "Live provider status is at-risk: provider_api_error." in reasons
    assert "Provider error code(s): 1010." in reasons
    assert "Fallback coverage is not locally ready (no-fallback-configured)." in reasons


def test_release_redaction_preserves_placeholders_but_removes_real_secrets() -> None:
    payload = {
        "apiKey": "sk-real-secret-1234567890",
        "authToken": "token-secret-1234567890",
        "example": "sk-...",
        "nested": {
            "OPENAI_API_KEY": "sk-another-secret-1234567890",
            "OPENAI_BASE_URL": "https://api.openai.com",
        },
    }
    text = (
        "Authorization: Bearer token-secret-1234567890\n"
        "OPENAI_API_KEY=sk-another-secret-1234567890\n"
        "Channel: anthropic-compatible via baseUrl/authToken\n"
        "Fallback ready: no\n"
        "placeholder sk-..."
    )

    redacted = redact_sensitive_payload(payload)

    assert redacted["apiKey"] == "[REDACTED]"
    assert redacted["authToken"] == "[REDACTED]"
    assert redacted["example"] == "sk-..."
    assert redacted["nested"]["OPENAI_API_KEY"] == "[REDACTED]"
    assert redacted["nested"]["OPENAI_BASE_URL"] == "https://api.openai.com"
    assert "token-secret" not in redact_sensitive_text(text)
    assert "sk-another-secret" not in redact_sensitive_text(text)
    assert "Fallback ready: no" in redact_sensitive_text(text)
    assert "sk-..." in redact_sensitive_text(text)
    assert find_sensitive_text_leaks('{"OPENROUTER_API_KEY": "sk-or-..."}') == []
    assert find_sensitive_text_leaks('{"OPENROUTER_API_KEY": "sk-or-real-secret-1234567890"}')


def test_release_redaction_detects_nested_authorization_and_bearer_secrets() -> None:
    payload = {
        "headers": {
            "authorization": "opaque-authorization-value",
            "bearer": "opaque-bearer-value",
        }
    }

    redacted = redact_sensitive_payload(payload)

    assert redacted == {
        "headers": {
            "authorization": "[REDACTED]",
            "bearer": "[REDACTED]",
        }
    }
    assert find_sensitive_payload_leaks(payload) == [
        "sensitive value at headers.authorization",
        "sensitive value at headers.bearer",
    ]


def test_release_readiness_artifact_redaction_cli(tmp_path, capsys) -> None:
    clean = tmp_path / "clean.json"
    dirty = tmp_path / "dirty.json"
    clean.write_text('{"OPENAI_API_KEY":"sk-..."}', encoding="utf-8")
    dirty.write_text('{"OPENAI_API_KEY":"sk-real-secret-1234567890"}', encoding="utf-8")

    assert release_readiness_utility_main(["--check-artifact-redaction", str(clean)]) == 0
    assert "artifact redaction valid: 1 artifact(s)" in capsys.readouterr().out

    assert release_readiness_utility_main(["--check-artifact-redaction", str(dirty)]) == 1
    output = capsys.readouterr().out
    assert "sensitive token" in output


def test_release_readiness_fallback_switch_smoke_cli(capsys) -> None:
    check = check_fallback_switch_smoke()

    assert check.status == "passed"
    assert check.summary == "fallback switch smoke valid: claude-sonnet-4-20250514 -> gpt-4o"
    assert release_readiness_utility_main(["--check-fallback-switch-smoke"]) == 0
    assert "fallback switch smoke valid" in capsys.readouterr().out


def test_release_readiness_headless_trace_check_cli(tmp_path, capsys) -> None:
    valid = tmp_path / "trace.json"
    invalid = tmp_path / "invalid.json"
    valid.write_text(
        (
            "{\n"
            '  "exit_code": 1,\n'
            '  "readiness_report": {"status": "warning", "summary": "readiness: warning"},\n'
            '  "repair_plan": [{"step": "verify-local-readiness"}]\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    invalid.write_text('{"exit_code": "1"}', encoding="utf-8")

    assert check_headless_trace(valid).status == "passed"
    assert release_readiness_utility_main(["--check-headless-trace", str(valid)]) == 0
    assert "headless trace valid: exit_code=1 readiness=warning repair_steps=1" in capsys.readouterr().out

    assert release_readiness_utility_main(["--check-headless-trace", str(invalid)]) == 1
    output = capsys.readouterr().out
    assert "headless trace missing integer exit_code" in output


def test_release_readiness_artifact_manifest_check_cli(tmp_path, capsys) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("stable evidence\n", encoding="utf-8")
    missing = tmp_path / "missing.txt"
    manifest = build_artifact_manifest(
        {
            "artifact": artifact,
            "missing": missing,
        }
    )
    manifest_path = tmp_path / "manifest.json"
    release_payload_path = tmp_path / "release.json"
    valid_manifest = [item for item in manifest if item["label"] == "artifact"]
    manifest_path.write_text(json.dumps(valid_manifest), encoding="utf-8")
    release_payload_path.write_text(
        json.dumps({"artifact_manifest": valid_manifest}),
        encoding="utf-8",
    )

    assert manifest[0]["exists"] is True
    assert manifest[0]["size_bytes"] > 0
    assert len(manifest[0]["sha256"]) == 64
    assert manifest[1]["exists"] is False
    assert check_artifact_manifest(valid_manifest).status == "passed"

    assert release_readiness_utility_main(["--check-artifact-manifest", str(manifest_path)]) == 0
    assert "artifact manifest valid: 1 artifact(s)" in capsys.readouterr().out

    assert release_readiness_utility_main(["--check-artifact-manifest", str(release_payload_path)]) == 0
    assert "artifact manifest valid: 1 artifact(s)" in capsys.readouterr().out

    missing_manifest_path = tmp_path / "missing-manifest.json"
    missing_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert release_readiness_utility_main(["--check-artifact-manifest", str(missing_manifest_path)]) == 1
    assert "artifact missing: missing" in capsys.readouterr().out


def test_release_readiness_artifact_manifest_write_cli(tmp_path, capsys) -> None:
    artifact = tmp_path / "artifact.txt"
    manifest_path = tmp_path / "out" / "manifest.json"
    artifact.write_text("release evidence\n", encoding="utf-8")

    assert release_readiness_utility_main(
        [
            "--write-artifact-manifest",
            str(manifest_path),
            "--artifact",
            f"evidence={artifact}",
        ]
    ) == 0
    output = capsys.readouterr().out
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "artifact manifest written:" in output
    assert "artifact manifest valid: 1 artifact(s)" in output
    assert manifest[0]["label"] == "evidence"
    assert manifest[0]["exists"] is True
    assert manifest[0]["size_bytes"] == artifact.stat().st_size
    assert len(manifest[0]["sha256"]) == 64

    assert release_readiness_utility_main(
        [
            "--write-artifact-manifest",
            str(manifest_path),
        ]
    ) == 1
    assert "requires at least one --artifact" in capsys.readouterr().out


def test_release_readiness_bundle_check_cli(tmp_path, capsys) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    examples_path = bundle_dir / "readiness-fallback-examples.json"
    doctor_path = bundle_dir / "readiness-doctor.md"
    repair_path = bundle_dir / "readiness-repair-plan.json"
    patch_preview_path = bundle_dir / "readiness-fallback-patch-preview.json"
    simulations_path = bundle_dir / "readiness-fallback-simulations.json"
    manifest_path = bundle_dir / "readiness-artifact-manifest.json"
    fallback_settings = {"fallbackModels": ["gpt-4o"]}
    settings_path = str(tmp_path / "settings.json")
    examples_path.write_text(
        json.dumps(
            {
                "fallback_config_examples": [
                    {
                        "label": "OpenAI fallback",
                        "path": settings_path,
                        "settings": fallback_settings,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doctor_path.write_text(
        "\n".join(
            [
                "# MiniCode Readiness Doctor",
                "",
                "## Local Preflight",
                "",
                "## Repair Plan",
                "",
                "## Safety",
            ]
        ),
        encoding="utf-8",
    )
    repair_path.write_text(
        json.dumps({"repair_plan": [{"step": "verify-local-readiness"}]}),
        encoding="utf-8",
    )
    patch_preview_path.write_text(
        json.dumps(
            {
                "summary": "readiness: warning",
                "status": "warning",
                "risk_scope": "no-fallback-configured",
                "fallback_settings_patch_preview": [
                    {
                        "label": "OpenAI fallback",
                        "target_path": settings_path,
                        "merge_patch": fallback_settings,
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
    simulations_path.write_text(
        json.dumps(_fallback_simulations_payload()),
        encoding="utf-8",
    )
    manifest = build_artifact_manifest(
        {
            "fallback_examples_json": examples_path,
            "doctor_markdown": doctor_path,
            "repair_plan_json": repair_path,
            "patch_preview_json": patch_preview_path,
            "fallback_simulations_json": simulations_path,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert check_readiness_bundle(bundle_dir).status == "passed"
    assert release_readiness_utility_main(["--check-readiness-bundle", str(bundle_dir)]) == 0
    assert "readiness bundle valid: 6 artifact(s)" in capsys.readouterr().out

    repair_path.unlink()
    assert release_readiness_utility_main(["--check-readiness-bundle", str(bundle_dir)]) == 1
    assert "readiness bundle missing repair_plan_json" in capsys.readouterr().out


def test_release_readiness_bundle_check_fails_when_patch_preview_drifts(tmp_path, capsys) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    examples_path = bundle_dir / "readiness-fallback-examples.json"
    doctor_path = bundle_dir / "readiness-doctor.md"
    repair_path = bundle_dir / "readiness-repair-plan.json"
    patch_preview_path = bundle_dir / "readiness-fallback-patch-preview.json"
    simulations_path = bundle_dir / "readiness-fallback-simulations.json"
    manifest_path = bundle_dir / "readiness-artifact-manifest.json"
    settings_path = str(tmp_path / "settings.json")
    examples_path.write_text(
        json.dumps(
            {
                "fallback_config_examples": [
                    {
                        "label": "OpenAI fallback",
                        "path": settings_path,
                        "settings": {"fallbackModels": ["gpt-4o"]},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doctor_path.write_text(
        "# MiniCode Readiness Doctor\n\n## Local Preflight\n\n## Repair Plan\n\n## Safety\n",
        encoding="utf-8",
    )
    repair_path.write_text(
        json.dumps({"repair_plan": [{"step": "verify-local-readiness"}]}),
        encoding="utf-8",
    )
    patch_preview_path.write_text(
        json.dumps(
            {
                "summary": "readiness: warning",
                "status": "warning",
                "risk_scope": "no-fallback-configured",
                "fallback_settings_patch_preview": [
                    {
                        "label": "OpenAI fallback",
                        "target_path": settings_path,
                        "merge_patch": {"fallbackModels": ["gpt-4o-mini"]},
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
    simulations_path.write_text(
        json.dumps(_fallback_simulations_payload()),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            build_artifact_manifest(
                {
                    "fallback_examples_json": examples_path,
                    "doctor_markdown": doctor_path,
                    "repair_plan_json": repair_path,
                    "patch_preview_json": patch_preview_path,
                    "fallback_simulations_json": simulations_path,
                }
            )
        ),
        encoding="utf-8",
    )

    assert release_readiness_utility_main(["--check-readiness-bundle", str(bundle_dir)]) == 1
    assert "readiness bundle patch preview differs from example" in capsys.readouterr().out


def test_release_readiness_bundle_check_fails_when_manifest_drifts(tmp_path, capsys) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    examples_path = bundle_dir / "readiness-fallback-examples.json"
    doctor_path = bundle_dir / "readiness-doctor.md"
    repair_path = bundle_dir / "readiness-repair-plan.json"
    patch_preview_path = bundle_dir / "readiness-fallback-patch-preview.json"
    simulations_path = bundle_dir / "readiness-fallback-simulations.json"
    manifest_path = bundle_dir / "readiness-artifact-manifest.json"
    settings_path = str(tmp_path / "settings.json")
    fallback_settings = {"fallbackModels": ["gpt-4o"]}
    examples_path.write_text(
        json.dumps(
            {
                "fallback_config_examples": [
                    {
                        "label": "OpenAI fallback",
                        "path": settings_path,
                        "settings": fallback_settings,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    doctor_path.write_text(
        "# MiniCode Readiness Doctor\n\n## Local Preflight\n\n## Repair Plan\n\n## Safety\n",
        encoding="utf-8",
    )
    repair_path.write_text(
        json.dumps({"repair_plan": [{"step": "verify-local-readiness"}]}),
        encoding="utf-8",
    )
    patch_preview_path.write_text(
        json.dumps(
            {
                "summary": "readiness: warning",
                "status": "warning",
                "risk_scope": "no-fallback-configured",
                "fallback_settings_patch_preview": [
                    {
                        "label": "OpenAI fallback",
                        "target_path": settings_path,
                        "merge_patch": fallback_settings,
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
    simulations_path.write_text(
        json.dumps(_fallback_simulations_payload()),
        encoding="utf-8",
    )
    manifest = build_artifact_manifest(
        {
            "fallback_examples_json": examples_path,
            "doctor_markdown": doctor_path,
            "repair_plan_json": repair_path,
            "patch_preview_json": patch_preview_path,
            "fallback_simulations_json": simulations_path,
        }
    )
    manifest[0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert release_readiness_utility_main(["--check-readiness-bundle", str(bundle_dir)]) == 1
    assert "readiness bundle manifest drift" in capsys.readouterr().out


def test_release_readiness_fallback_patch_preview_check_cli(tmp_path, capsys) -> None:
    preview_path = tmp_path / "readiness-fallback-patch-preview.json"
    payload = {
        "summary": "readiness: warning",
        "status": "warning",
        "risk_scope": "no-fallback-configured",
        "fallback_settings_patch_preview": [
            {
                "label": "OpenAI fallback",
                "target_path": str(tmp_path / "settings.json"),
                "merge_patch": {
                    "fallbackModels": ["gpt-4o"],
                    "env": {"OPENAI_API_KEY": "sk-..."},
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
    preview_path.write_text(json.dumps(payload), encoding="utf-8")

    assert check_fallback_patch_preview_payload(payload).status == "passed"
    assert check_fallback_patch_preview(preview_path).status == "passed"
    assert release_readiness_utility_main(["--check-fallback-patch-preview", str(preview_path)]) == 0
    assert "fallback patch preview valid: 1 preview(s)" in capsys.readouterr().out

    broken = dict(payload)
    broken["fallback_settings_patch_preview"] = [
        {
            **payload["fallback_settings_patch_preview"][0],
            "safety": "manual",
        }
    ]
    broken_path = tmp_path / "broken-patch-preview.json"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")

    assert release_readiness_utility_main(["--check-fallback-patch-preview", str(broken_path)]) == 1
    assert "has invalid safety" in capsys.readouterr().out

    dirty = dict(payload)
    dirty["fallback_settings_patch_preview"] = [
        {
            **payload["fallback_settings_patch_preview"][0],
            "merge_patch": {"env": {"OPENAI_API_KEY": "sk-real-secret-1234567890"}},
        }
    ]
    dirty_path = tmp_path / "dirty-patch-preview.json"
    dirty_path.write_text(json.dumps(dirty), encoding="utf-8")

    assert release_readiness_utility_main(["--check-fallback-patch-preview", str(dirty_path)]) == 1
    assert "sensitive token" in capsys.readouterr().out


def test_release_readiness_fallback_simulation_validator_rejects_unsafe_payloads(tmp_path) -> None:
    payload = {
        "status": "ready",
        "selected_label": "OpenAI fallback",
        "credential_state": "existing-local",
        "fallback_candidates": ["gpt-4o"],
        "viable_fallbacks": ["gpt-4o"],
        "issues": [],
        "next_actions": ["Keep fallback coverage in release readiness checks."],
        "effective_config": {"credential_present": {"openai": True}},
        "simulation_only": True,
        "live_provider_claim": False,
    }
    path = tmp_path / "simulation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert release_readiness.check_fallback_simulation_payload(payload).status == "passed"
    assert release_readiness.check_fallback_simulation(path).status == "passed"

    placeholder_ready = {**payload, "credential_state": "placeholder"}
    live_claim = {**payload, "live_provider_claim": True}
    missing_label = {**payload, "selected_label": ""}
    leaked_secret = {
        **payload,
        "effective_config": {"OPENAI_API_KEY": "sk-real-secret-1234567890"},
    }
    unprefixed_structured_secret = {
        **payload,
        "effective_config": {"api_key": "long-unprefixed-secret-value"},
    }
    none_candidates = {**payload, "fallback_candidates": None}
    object_viable_fallbacks = {**payload, "viable_fallbacks": {"gpt-4o": True}}
    empty_candidate = {**payload, "fallback_candidates": [""]}
    missing_candidate = {**payload, "viable_fallbacks": ["gpt-4o-mini"]}

    assert release_readiness.check_fallback_simulation_payload(placeholder_ready).status == "failed"
    assert release_readiness.check_fallback_simulation_payload(live_claim).status == "failed"
    assert release_readiness.check_fallback_simulation_payload(missing_label).status == "failed"
    assert release_readiness.check_fallback_simulation_payload(leaked_secret).status == "failed"
    assert release_readiness.check_fallback_simulation_payload(unprefixed_structured_secret).status == "failed"
    assert release_readiness.check_fallback_simulation_payload(none_candidates).status == "failed"
    assert release_readiness.check_fallback_simulation_payload(object_viable_fallbacks).status == "failed"
    assert release_readiness.check_fallback_simulation_payload(empty_candidate).status == "failed"
    assert release_readiness.check_fallback_simulation_payload(missing_candidate).status == "failed"


def test_release_readiness_fallback_simulation_validator_checks_every_bundled_result(tmp_path) -> None:
    payload = _fallback_simulations_payload()
    payload["simulations"].append(
        {
            **payload["simulations"][0],
            "selected_label": "OpenRouter fallback",
            "fallback_candidates": ["openrouter/auto"],
            "effective_config": {"credential_present": {"openrouter": False}},
        }
    )
    path = tmp_path / "readiness-fallback-simulations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    check = release_readiness.check_fallback_simulation(path)

    assert check.status == "passed"
    assert "2 simulation(s)" in check.summary

    payload["simulations"][1]["live_provider_claim"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    check = release_readiness.check_fallback_simulation(path)

    assert check.status == "failed"
    assert "simulations[1]" in check.stderr


def test_release_readiness_fallback_simulation_validator_allows_no_explicit_previews() -> None:
    check = release_readiness.check_fallback_simulation_payload(
        {
            "simulation_only": True,
            "live_provider_claim": False,
            "simulations": [],
        }
    )

    assert check.status == "passed"
    assert "0 simulation(s)" in check.summary


def test_release_readiness_fallback_simulation_requires_native_nonempty_selected_label() -> None:
    payload = {
        "status": "ready",
        "selected_label": "OpenAI fallback",
        "credential_state": "existing-local",
        "fallback_candidates": ["gpt-4o"],
        "viable_fallbacks": ["gpt-4o"],
        "issues": [],
        "next_actions": [],
        "simulation_only": True,
        "live_provider_claim": False,
    }

    for selected_label in (None, 42, {"label": "OpenAI fallback"}):
        check = release_readiness.check_fallback_simulation_payload(
            {**payload, "selected_label": selected_label}
        )

        assert check.status == "failed"


def test_release_readiness_fallback_simulation_requires_nonempty_string_issue_entries() -> None:
    payload = {
        "status": "ready",
        "selected_label": "OpenAI fallback",
        "credential_state": "existing-local",
        "fallback_candidates": ["gpt-4o"],
        "viable_fallbacks": ["gpt-4o"],
        "issues": [],
        "next_actions": [],
        "simulation_only": True,
        "live_provider_claim": False,
    }

    for issues in ([None], [""], [42]):
        check = release_readiness.check_fallback_simulation_payload(
            {**payload, "issues": issues}
        )

        assert check.status == "failed"


def test_release_readiness_fallback_simulation_requires_nonempty_string_next_action_entries() -> None:
    payload = {
        "status": "ready",
        "selected_label": "OpenAI fallback",
        "credential_state": "existing-local",
        "fallback_candidates": ["gpt-4o"],
        "viable_fallbacks": ["gpt-4o"],
        "issues": [],
        "next_actions": [],
        "simulation_only": True,
        "live_provider_claim": False,
    }

    for next_actions in ([""], [42]):
        check = release_readiness.check_fallback_simulation_payload(
            {**payload, "next_actions": next_actions}
        )

        assert check.status == "failed"


def test_release_readiness_fallback_simulation_requires_viable_subset_for_nonready_statuses() -> None:
    payload = {
        "selected_label": "OpenAI fallback",
        "fallback_candidates": ["gpt-4o"],
        "viable_fallbacks": ["gpt-4o-mini"],
        "issues": [],
        "next_actions": [],
        "simulation_only": True,
        "live_provider_claim": False,
    }

    for status, credential_state in (
        ("requires-credentials", "placeholder"),
        ("invalid", "invalid"),
    ):
        check = release_readiness.check_fallback_simulation_payload(
            {
                **payload,
                "status": status,
                "credential_state": credential_state,
            }
        )

        assert check.status == "failed"
        assert "viable fallbacks outside fallback_candidates" in check.stderr


def test_release_readiness_release_report_check_cli_allows_provider_at_risk(tmp_path, capsys) -> None:
    artifact = tmp_path / "runtime.json"
    artifact.write_text('{"ok": true}\n', encoding="utf-8")
    trace_artifact = tmp_path / "headless-trace.json"
    trace_artifact.write_text(
        json.dumps(
            {
                "exit_code": 1,
                "readiness_report": {
                    "status": "warning",
                    "summary": "readiness: warning",
                },
                "repair_plan": [{"step": "diagnose"}, {"step": "verify"}],
            }
        ),
        encoding="utf-8",
    )
    structure_artifact = tmp_path / "structure-compliance.json"
    structure_artifact.write_text(
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
                        "finding_count": 0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = build_artifact_manifest(
        {
            "runtime_json": artifact,
            "headless_trace": trace_artifact,
            "structure_compliance": structure_artifact,
        }
    )
    report_path = tmp_path / "release.json"
    report = {
        "generated_at": "2026-06-30T00:00:00+00:00",
        "status": "at-risk",
        "local_gate_status": "pass",
        "provider_status": "at-risk",
        "status_reasons": [
            "Local gates passed.",
            "Live provider status is at-risk: provider_api_error.",
            "Provider error code(s): 1010.",
            "Fallback coverage is not locally ready (no-fallback-configured).",
        ],
        "compile_check": {
            "label": "compileall",
            "status": "passed",
            "exit_code": 0,
            "summary": "compileall passed",
        },
        "test_check": {
            "label": "pytest-q",
            "status": "passed",
            "exit_code": 0,
            "summary": "pytest passed",
        },
        "runtime_eval_check": {
            "label": "runtime-profile-eval",
            "status": "passed",
            "exit_code": 0,
            "summary": "runtime eval passed",
        },
        "structure_check": {
            "label": "structure-compliance",
            "command": "python -m minicode.structure_check --root . --check-material-inventory --report .temp/structure-compliance.json",
            "status": "passed",
            "exit_code": 0,
            "summary": "quality gate findings: 0",
        },
        "smoke_checks": [
            {"label": "readiness-artifacts", "status": "passed", "exit_code": 0, "summary": "valid"},
            {"label": "readiness-bundle", "status": "passed", "exit_code": 0, "summary": "valid"},
            {"label": "fallback-simulation", "status": "passed", "exit_code": 0, "summary": "valid"},
            {"label": "fallback-evidence", "status": "passed", "exit_code": 0, "summary": "valid"},
            {"label": "fallback-patch-preview", "status": "passed", "exit_code": 0, "summary": "valid"},
            {"label": "fallback-switch-smoke", "status": "passed", "exit_code": 0, "summary": "valid"},
            {"label": "headless-trace", "status": "passed", "exit_code": 0, "summary": "valid"},
            {"label": "artifact-redaction", "status": "passed", "exit_code": 0, "summary": "valid"},
            {"label": "structure-compliance-artifact", "status": "passed", "exit_code": 0, "summary": "valid"},
            {"label": "artifact-manifest", "status": "passed", "exit_code": 0, "summary": "valid"},
        ],
        "provider_diagnostics": [
            {
                "label": "headless-smoke",
                "outcome": "provider_api_error",
                "exit_code": 1,
                "summary": "Model API error",
                "error_code": "1010",
                "failure_category": "provider-rejected-request",
                "retryable": False,
                "ownership": "external-provider",
                "recovery_action": "Inspect the provider contract, selected model, and sanitized request evidence.",
                "trace_artifact": str(trace_artifact),
                "readiness_status": "warning",
                "repair_step_count": 2,
            }
        ],
        "runtime_profile_artifacts": {
            "json": str(artifact),
            "markdown": str(artifact),
            "headless_trace": str(trace_artifact),
        },
        "readiness_artifacts": {
            "fallback_examples_json": str(artifact),
            "doctor_markdown": str(artifact),
            "repair_plan_json": str(artifact),
            "patch_preview_json": str(artifact),
            "fallback_simulations_json": str(artifact),
            "bundle_directory": str(tmp_path),
            "bundle_manifest_json": str(artifact),
        },
        "artifact_manifest": manifest,
        "readiness_report": {
            "status": "warning",
            "provider": "anthropic",
            "fallback_ready": False,
            "fallback_candidates": [],
            "viable_fallbacks": [],
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
            "summary": "readiness: warning",
        },
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert check_structure_compliance_artifact(structure_artifact).status == "passed"
    assert release_readiness_utility_main(
        ["--check-structure-compliance-artifact", str(structure_artifact)]
    ) == 0
    assert "structure compliance artifact valid: focused_gates=16 materials=9" in capsys.readouterr().out
    assert check_release_report(report_path).status == "passed"
    assert release_readiness_utility_main(["--check-release-report", str(report_path)]) == 0
    output = capsys.readouterr().out
    assert "release report valid: status=at-risk local=pass provider=at-risk smokes=10" in output

    markdown_path = tmp_path / "release.md"
    markdown = release_readiness_as_markdown(
        generated_at=report["generated_at"],
        status=report["status"],
        compile_check=_check("compileall", summary="compileall passed"),
        test_check=_check("pytest-q", summary="pytest passed"),
        runtime_eval_check=_check("runtime-profile-eval", summary="runtime eval passed"),
        smoke_checks=[
            _check(item["label"], summary=item["summary"])
            for item in report["smoke_checks"]
        ],
        provider_diagnostics=report["provider_diagnostics"],
        runtime_profile_artifacts=report["runtime_profile_artifacts"],
        readiness_artifacts=report["readiness_artifacts"],
        artifact_manifest=report["artifact_manifest"],
        readiness_report=report["readiness_report"],
    )
    markdown_path.write_text(markdown, encoding="utf-8")

    assert check_release_markdown(markdown_path, release_json=report_path).status == "passed"
    assert release_readiness_utility_main(
        [
            "--check-release-markdown",
            str(markdown_path),
            "--release-json",
            str(report_path),
        ]
    ) == 0
    assert "release markdown valid: status=at-risk smokes=10" in capsys.readouterr().out

    for field in ("failure_category", "ownership", "recovery_action"):
        missing_evidence_path = tmp_path / f"missing-{field}-release.json"
        missing_evidence = json.loads(json.dumps(report))
        del missing_evidence["provider_diagnostics"][0][field]
        missing_evidence_path.write_text(json.dumps(missing_evidence), encoding="utf-8")

        assert release_readiness_utility_main(
            ["--check-release-report", str(missing_evidence_path)]
        ) == 1
        assert field in capsys.readouterr().out

    invalid_retryable_path = tmp_path / "invalid-retryable-release.json"
    invalid_retryable = json.loads(json.dumps(report))
    invalid_retryable["provider_diagnostics"][0]["retryable"] = "false"
    invalid_retryable_path.write_text(json.dumps(invalid_retryable), encoding="utf-8")

    assert release_readiness_utility_main(
        ["--check-release-report", str(invalid_retryable_path)]
    ) == 1
    assert "retryable" in capsys.readouterr().out

    broken_markdown_path = tmp_path / "broken-release.md"
    broken_markdown_path.write_text(markdown.replace("fallback-evidence", "fallback evidence"), encoding="utf-8")
    assert release_readiness_utility_main(
        [
            "--check-release-markdown",
            str(broken_markdown_path),
            "--release-json",
            str(report_path),
        ]
    ) == 1
    assert "release markdown missing smoke: fallback-evidence" in capsys.readouterr().out

    broken_path = tmp_path / "broken-release.json"
    broken = dict(report)
    broken["smoke_checks"] = []
    broken_path.write_text(json.dumps(broken), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(broken_path)]) == 1
    assert "release report smoke_checks is empty" in capsys.readouterr().out

    missing_bundle_path = tmp_path / "missing-bundle-release.json"
    missing_bundle = dict(report)
    missing_bundle["smoke_checks"] = [
        item for item in report["smoke_checks"] if item["label"] != "readiness-bundle"
    ]
    missing_bundle_path.write_text(json.dumps(missing_bundle), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(missing_bundle_path)]) == 1
    assert "release report smoke_checks missing readiness-bundle" in capsys.readouterr().out

    missing_fallback_evidence_path = tmp_path / "missing-fallback-evidence-release.json"
    missing_fallback_evidence = dict(report)
    missing_fallback_evidence["smoke_checks"] = [
        item for item in report["smoke_checks"] if item["label"] != "fallback-evidence"
    ]
    missing_fallback_evidence_path.write_text(json.dumps(missing_fallback_evidence), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(missing_fallback_evidence_path)]) == 1
    assert "release report smoke_checks missing fallback-evidence" in capsys.readouterr().out

    failed_smoke_path = tmp_path / "failed-smoke-release.json"
    failed_smoke = dict(report)
    failed_smoke["smoke_checks"] = [
        {
            **item,
            "status": "failed",
            "exit_code": 1,
            "summary": "fallback evidence failed",
        }
        if item["label"] == "fallback-evidence"
        else item
        for item in report["smoke_checks"]
    ]
    failed_smoke_path.write_text(json.dumps(failed_smoke), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(failed_smoke_path)]) == 1
    assert "release report smoke_check failed: fallback-evidence" in capsys.readouterr().out

    contradictory_local_path = tmp_path / "contradictory-local-release.json"
    contradictory_local = dict(report)
    contradictory_local["smoke_checks"] = [
        *report["smoke_checks"],
        {
            "label": "extra-local-smoke",
            "status": "failed",
            "exit_code": 1,
            "summary": "extra smoke failed",
        },
    ]
    contradictory_local_path.write_text(json.dumps(contradictory_local), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(contradictory_local_path)]) == 1
    assert "local_gate_status pass contradicts failed local gate" in capsys.readouterr().out

    stale_trace_metadata_path = tmp_path / "stale-trace-metadata-release.json"
    stale_trace_metadata = dict(report)
    stale_trace_metadata["provider_diagnostics"] = [
        {
            **report["provider_diagnostics"][0],
            "readiness_status": "ready",
        }
    ]
    stale_trace_metadata_path.write_text(json.dumps(stale_trace_metadata), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(stale_trace_metadata_path)]) == 1
    assert "readiness_status does not match headless_trace" in capsys.readouterr().out

    stale_status_path = tmp_path / "stale-status-release.json"
    stale_status = dict(report)
    stale_status["status"] = "warning"
    stale_status_path.write_text(json.dumps(stale_status), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(stale_status_path)]) == 1
    assert "release report status does not match recomputed status" in capsys.readouterr().out

    stale_provider_status_path = tmp_path / "stale-provider-status-release.json"
    stale_provider_status = dict(report)
    stale_provider_status["provider_status"] = "pass"
    stale_provider_status_path.write_text(json.dumps(stale_provider_status), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(stale_provider_status_path)]) == 1
    assert "release report provider_status does not match recomputed provider status" in capsys.readouterr().out

    stale_reasons_path = tmp_path / "stale-reasons-release.json"
    stale_reasons = dict(report)
    stale_reasons["status_reasons"] = ["Local gates passed."]
    stale_reasons_path.write_text(json.dumps(stale_reasons), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(stale_reasons_path)]) == 1
    assert "release report status_reasons do not match recomputed reasons" in capsys.readouterr().out

    missing_manifest_artifact_path = tmp_path / "missing-manifest-artifact-release.json"
    missing_manifest_artifact = dict(report)
    extra_artifact = tmp_path / "extra-runtime.json"
    extra_artifact.write_text('{"extra": true}\n', encoding="utf-8")
    missing_manifest_artifact["runtime_profile_artifacts"] = {
        **report["runtime_profile_artifacts"],
        "json": str(extra_artifact),
    }
    missing_manifest_artifact_path.write_text(json.dumps(missing_manifest_artifact), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(missing_manifest_artifact_path)]) == 1
    assert "artifact_manifest missing declared artifact: json" in capsys.readouterr().out

    missing_structure_artifact_path = tmp_path / "missing-structure-artifact-release.json"
    missing_structure_artifact = dict(report)
    missing_structure_artifact["artifact_manifest"] = [
        item for item in report["artifact_manifest"] if item["label"] != "structure_compliance"
    ]
    missing_structure_artifact_path.write_text(json.dumps(missing_structure_artifact), encoding="utf-8")

    assert release_readiness_utility_main(["--check-release-report", str(missing_structure_artifact_path)]) == 1
    assert "artifact_manifest missing structure_compliance" in capsys.readouterr().out

    stale_structure_artifact = tmp_path / "stale-structure-compliance.json"
    stale_structure_artifact.write_text(
        json.dumps(
            {
                "cliPassed": True,
                "qualityGatePassed": True,
                "qualityGateFindings": [],
            }
        ),
        encoding="utf-8",
    )
    stale_structure_report_path = tmp_path / "stale-structure-release.json"
    stale_structure_report = dict(report)
    stale_structure_report["artifact_manifest"] = [
        {
            **item,
            "path": str(stale_structure_artifact),
            "size_bytes": stale_structure_artifact.stat().st_size,
            "sha256": "0" * 64,
        }
        if item["label"] == "structure_compliance"
        else item
        for item in report["artifact_manifest"]
    ]
    stale_structure_report_path.write_text(json.dumps(stale_structure_report), encoding="utf-8")

    assert release_readiness_utility_main(
        ["--check-structure-compliance-artifact", str(stale_structure_artifact)]
    ) == 1
    assert "structure compliance artifact missing materialInventory" in capsys.readouterr().out

    assert release_readiness_utility_main(["--check-release-report", str(stale_structure_report_path)]) == 1
    assert "structure compliance artifact missing materialInventory" in capsys.readouterr().out


def test_release_readiness_fallback_evidence_check_cli(tmp_path, capsys) -> None:
    report_path = tmp_path / "release.json"
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
    payload = {
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
            "status": "warning",
            "provider": "anthropic",
            "fallback_ready": False,
            "fallback_candidates": [],
            "viable_fallbacks": [],
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
            "summary": "readiness: warning",
        },
    }
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    assert check_fallback_evidence_payload(payload).status == "passed"
    assert check_fallback_evidence(report_path).status == "passed"
    assert release_readiness_utility_main(["--check-fallback-evidence", str(report_path)]) == 0
    assert "fallback evidence valid: provider=at-risk fallback=not-ready" in capsys.readouterr().out

    broken = dict(payload)
    broken["readiness_report"] = {
        **payload["readiness_report"],
        "repair_plan": [{"step": "diagnose-local-readiness"}],
    }
    broken_path = tmp_path / "broken-release.json"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")

    assert release_readiness_utility_main(["--check-fallback-evidence", str(broken_path)]) == 1
    assert "fallback evidence missing repair step" in capsys.readouterr().out

    missing_artifact = dict(payload)
    missing_artifact["readiness_artifacts"] = {
        **payload["readiness_artifacts"],
        "repair_plan_json": str(tmp_path / "missing-repair.json"),
    }
    missing_artifact_path = tmp_path / "missing-artifact-release.json"
    missing_artifact_path.write_text(json.dumps(missing_artifact), encoding="utf-8")

    assert release_readiness_utility_main(["--check-fallback-evidence", str(missing_artifact_path)]) == 1
    assert "fallback evidence artifact is missing: repair_plan_json" in capsys.readouterr().out


def test_should_fail_release_status_respects_thresholds() -> None:
    assert should_fail_release_status("at-risk", None) is False
    assert should_fail_release_status("at-risk", "blocked") is False
    assert should_fail_release_status("at-risk", "at-risk") is True
    assert should_fail_release_status("warning", "at-risk") is False
    assert should_fail_release_status("blocked", "warning") is True


def test_summarize_release_status_blocks_on_structure_gate_failure() -> None:
    status = summarize_release_status(
        compile_check=_check("compileall"),
        test_check=_check("pytest-q"),
        runtime_eval_check=_check("runtime-profile-eval"),
        structure_check=_check(
            "structure-compliance",
            status="failed",
            exit_code=1,
            summary="quality gate findings: 1",
        ),
        smoke_checks=[_check("inspect-session"), _check("replay-session")],
        provider_outcomes=["answered"],
        readiness_report={"fallback_ready": True},
    )

    assert status == "blocked"


def test_release_readiness_separates_local_gates_from_provider_status() -> None:
    local_status = summarize_local_gate_status(
        compile_check=_check("compileall"),
        test_check=_check("pytest-q"),
        runtime_eval_check=_check("runtime-profile-eval"),
        structure_check=_check("structure-compliance"),
        smoke_checks=[_check("inspect-session"), _check("replay-session")],
    )
    provider_status = summarize_provider_status(
        provider_outcomes=["provider_outage"],
        readiness_report={"fallback_ready": False},
    )
    release_status = summarize_release_status(
        compile_check=_check("compileall"),
        test_check=_check("pytest-q"),
        runtime_eval_check=_check("runtime-profile-eval"),
        structure_check=_check("structure-compliance"),
        smoke_checks=[_check("inspect-session"), _check("replay-session")],
        provider_outcomes=["provider_outage"],
        readiness_report={"fallback_ready": False},
    )

    assert local_status == "pass"
    assert provider_status == "at-risk"
    assert release_status == "at-risk"


def test_release_readiness_outputs_include_provider_diagnostics_and_artifacts() -> None:
    compile_check = _check("compileall")
    test_check = _check("pytest-q")
    runtime_eval_check = _check("runtime-profile-eval", summary="runtime eval completed.")
    structure_check = _check(
        "structure-compliance",
        summary="AGENTS structure compliance: passed",
    )
    smoke_checks = [
        _check("list-sessions", summary="2 sessions listed."),
        _check("preview-rewind", summary="rewind preview completed."),
    ]
    diagnostics = [
        {
            "label": "headless-provider-smoke",
            "outcome": "provider_outage",
            "command": "python -m minicode.headless \"Reply with exactly OK.\"",
            "exit_code": 1,
            "summary": "Provider availability failure.",
            "stdout": "",
            "stderr": "Provider availability failure.",
            "risk_scope": "external-provider",
            "error_code": "503",
            "request_id": "req-release-1",
            "failure_category": "provider-unavailable",
            "retryable": True,
            "ownership": "external-provider",
            "recovery_action": "Retry the provider smoke or switch to a ready fallback.",
            "guidance": ["Configure fallbackModels before release."],
        }
    ]
    artifacts = {
        "json": "benchmarks/runtime_profile_eval_results.json",
        "markdown": "benchmarks/runtime_profile_eval_results.md",
    }
    readiness_artifacts = {
        "doctor_markdown": ".temp/readiness-doctor.md",
        "fallback_examples_json": ".temp/readiness-fallback-examples.json",
        "repair_plan_json": ".temp/readiness-repair-plan.json",
        "patch_preview_json": ".temp/readiness-fallback-patch-preview.json",
        "fallback_simulations_json": ".temp/readiness-bundle/readiness-fallback-simulations.json",
        "bundle_directory": ".temp/readiness-bundle",
        "bundle_manifest_json": ".temp/readiness-bundle/readiness-artifact-manifest.json",
    }

    payload = release_readiness_as_dict(
        generated_at="2026-06-05T00:00:00+00:00",
        status="warning",
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        structure_check=structure_check,
        smoke_checks=smoke_checks,
        provider_diagnostics=diagnostics,
        runtime_profile_artifacts=artifacts,
        readiness_artifacts=readiness_artifacts,
        readiness_report={
            "provider": "anthropic",
            "provider_ready": True,
            "provider_channel": "anthropic-compatible via baseUrl/authToken",
            "fallback_ready": True,
            "fallback_candidates": ["gpt-4o"],
            "viable_fallbacks": ["gpt-4o"],
            "fallback_guidance": [
                "Primary runtime is using a single anthropic-compatible channel from baseUrl/authToken.",
                "Add fallbackModels or anthropicFallbackModels to enable model failover.",
            ],
            "risk_scope": "none",
            "next_actions": ["Keep fallback coverage in release readiness checks."],
            "fallback_config_examples": [
                {
                    "label": "OpenAI fallback",
                    "path": "/home/user/.mini-code/settings.json",
                    "settings": {
                        "fallbackModels": ["gpt-4o"],
                        "env": {"OPENAI_API_KEY": "sk-..."},
                    },
                }
            ],
            "preflight_checks": [
                {
                    "label": "primary-provider-config",
                    "status": "pass",
                    "summary": "anthropic-compatible via baseUrl/authToken",
                    "action": "Run a live provider smoke before release.",
                },
                {
                    "label": "fallback-coverage",
                    "status": "pass",
                    "summary": "1/1 fallback model(s) locally ready",
                    "action": "Keep fallback coverage in release readiness checks.",
                },
            ],
            "summary": "readiness: ready (anthropic) [fallbacks 1/1 locally ready]",
        },
    )
    rendered = release_readiness_as_markdown(
        generated_at="2026-06-05T00:00:00+00:00",
        status="warning",
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        structure_check=structure_check,
        smoke_checks=smoke_checks,
        provider_diagnostics=diagnostics,
        runtime_profile_artifacts=artifacts,
        readiness_artifacts=readiness_artifacts,
        readiness_report={
            "provider": "anthropic",
            "provider_ready": True,
            "provider_channel": "anthropic-compatible via baseUrl/authToken",
            "fallback_ready": True,
            "fallback_candidates": ["gpt-4o"],
            "viable_fallbacks": ["gpt-4o"],
            "fallback_guidance": [
                "Primary runtime is using a single anthropic-compatible channel from baseUrl/authToken.",
                "Add fallbackModels or anthropicFallbackModels to enable model failover.",
            ],
            "risk_scope": "none",
            "next_actions": ["Keep fallback coverage in release readiness checks."],
            "fallback_config_examples": [
                {
                    "label": "OpenAI fallback",
                    "path": "/home/user/.mini-code/settings.json",
                    "settings": {
                        "fallbackModels": ["gpt-4o"],
                        "env": {"OPENAI_API_KEY": "sk-..."},
                    },
                }
            ],
            "preflight_checks": [
                {
                    "label": "primary-provider-config",
                    "status": "pass",
                    "summary": "anthropic-compatible via baseUrl/authToken",
                    "action": "Run a live provider smoke before release.",
                },
                {
                    "label": "fallback-coverage",
                    "status": "pass",
                    "summary": "1/1 fallback model(s) locally ready",
                    "action": "Keep fallback coverage in release readiness checks.",
                },
            ],
            "summary": "readiness: ready (anthropic) [fallbacks 1/1 locally ready]",
        },
    )

    assert payload["status"] == "warning"
    assert payload["local_gate_status"] == "pass"
    assert payload["provider_status"] == "warning"
    assert "Local gates passed." in payload["status_reasons"]
    assert payload["provider_diagnostics"][0]["outcome"] == "provider_outage"
    assert payload["provider_diagnostics"][0]["risk_scope"] == "external-provider"
    assert payload["provider_diagnostics"][0]["error_code"] == "503"
    assert payload["provider_diagnostics"][0]["request_id"] == "req-release-1"
    assert payload["readiness_report"]["fallback_ready"] is True
    assert payload["readiness_report"]["risk_scope"] == "none"
    assert payload["readiness_report"]["preflight_checks"][0]["label"] == "primary-provider-config"
    assert payload["readiness_report"]["next_actions"] == [
        "Keep fallback coverage in release readiness checks."
    ]
    assert payload["readiness_report"]["provider_channel"] == "anthropic-compatible via baseUrl/authToken"
    assert payload["structure_check"]["label"] == "structure-compliance"
    assert payload["structure_check"]["status"] == "passed"
    assert payload["runtime_profile_artifacts"]["json"].endswith("runtime_profile_eval_results.json")
    assert payload["readiness_artifacts"] == readiness_artifacts
    assert "## Core Gate" in rendered
    assert "## Status Reasons" in rendered
    assert "Local gates passed." in rendered
    assert "Local gates: pass" in rendered
    assert "Provider status: warning" in rendered
    assert "structure-compliance" in rendered
    assert "## Product Smokes" in rendered
    assert "## Provider Diagnostics" in rendered
    assert "external-provider" in rendered
    assert "req-release-1" in rendered
    assert "provider-unavailable" in rendered
    assert "Retry the provider smoke or switch to a ready fallback." in rendered
    assert "## Provider Action Items" in rendered
    assert "Configure fallbackModels before release." in rendered
    assert "## Provider Fallback Coverage" in rendered
    assert "Risk scope: none" in rendered
    assert "Next actions:" in rendered
    assert "Keep fallback coverage in release readiness checks." in rendered
    assert "Config examples:" in rendered
    assert "OPENAI_API_KEY" in rendered
    assert "### Local Preflight" in rendered
    assert "primary-provider-config" in rendered
    assert "headless-provider-smoke" in rendered
    assert "Channel: anthropic-compatible via baseUrl/authToken" in rendered
    assert "Guidance:" in rendered
    assert "gpt-4o" in rendered
    assert "runtime_profile_eval_results.md" in rendered
    assert "## Readiness Artifacts" in rendered
    assert ".temp/readiness-doctor.md" in rendered


def test_release_readiness_outputs_missing_provider_diagnostic_evidence() -> None:
    compile_check = _check("compileall")
    test_check = _check("pytest-q")
    runtime_eval_check = _check("runtime-profile-eval")
    smoke_checks = [_check("inspect-session")]

    payload = release_readiness_as_dict(
        generated_at="2026-06-05T00:00:00+00:00",
        status="at-risk",
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        smoke_checks=smoke_checks,
        provider_diagnostics=[],
        runtime_profile_artifacts={},
        readiness_report={"fallback_ready": True},
    )
    rendered = release_readiness_as_markdown(
        generated_at="2026-06-05T00:00:00+00:00",
        status="at-risk",
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        smoke_checks=smoke_checks,
        provider_diagnostics=[],
        runtime_profile_artifacts={},
        readiness_report={"fallback_ready": True},
    )

    assert payload["provider_status"] == "at-risk"
    assert "Live provider diagnostics are missing." in payload["status_reasons"]
    assert "No provider diagnostics were collected." in rendered
    assert "Live provider diagnostics are missing." in rendered
    assert "Run runtime profile eval or headless provider smoke before release." in rendered
