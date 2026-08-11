from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ReleaseCheck:
    label: str
    command: str
    exit_code: int
    status: str
    summary: str
    stdout: str = ""
    stderr: str = ""


RELEASE_STATUS_ORDER = {
    "pass": 0,
    "warning": 1,
    "at-risk": 2,
    "blocked": 3,
}


def normalize_evidence_paths(
    value: Any,
    *,
    repo_root: Path,
    home: Path | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize_evidence_paths(item, repo_root=repo_root, home=home)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            normalize_evidence_paths(item, repo_root=repo_root, home=home)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            normalize_evidence_paths(item, repo_root=repo_root, home=home)
            for item in value
        )
    if not isinstance(value, str):
        return value

    repo_text = str(repo_root.resolve())
    home_text = str((home or Path.home()).resolve())
    normalized = value
    replaced_path = False
    repo_prefix = f"{repo_text}{os.sep}"
    if repo_prefix in normalized:
        normalized = normalized.replace(repo_prefix, "")
        replaced_path = True
    if normalized == repo_text:
        normalized = "."
        replaced_path = True
    if home_text != repo_text:
        home_prefix = f"{home_text}{os.sep}"
        if home_prefix in normalized:
            normalized = normalized.replace(home_prefix, "~/")
            replaced_path = True
        if normalized == home_text:
            normalized = "~"
            replaced_path = True
    if replaced_path and os.sep != "/":
        normalized = normalized.replace(os.sep, "/")
    return normalized


_SENSITIVE_KEY_PARTS = (
    "apikey",
    "api_key",
    "auth_token",
    "authtoken",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)
_SAFE_PLACEHOLDERS = {
    "",
    "...",
    "sk-...",
    "sk-or-...",
    "<redacted>",
    "[redacted]",
}
_SENSITIVE_STRUCTURED_KEY_NAMES = (
    "apikey",
    "password",
    "token",
    "secret",
    "authtoken",
    "authorization",
    "bearer",
)
_SECRET_TEXT_PATTERNS = (
    re.compile(r"\bsk-or-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{8,}\b", re.IGNORECASE),
    re.compile(
        r"(?P<key>[\"']?\b(?:apiKey|authToken|authorization|OPENAI_API_KEY|ANTHROPIC_API_KEY|OPENROUTER_API_KEY)\b[\"']?"
        r"[ \t]*[:=][ \t]*[\"']?)(?P<value>[A-Za-z0-9._/-]{8,})(?P<quote>[\"']?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<key>\b(?:apiKey|authToken|authorization|OPENAI_API_KEY|ANTHROPIC_API_KEY|OPENROUTER_API_KEY)\b"
        r"[ \t]+)(?P<value>[A-Za-z0-9._/-]{8,})",
        re.IGNORECASE,
    ),
)


def _looks_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    if normalized.endswith("base_url") or normalized.endswith("baseurl"):
        return False
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _is_sensitive_structured_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    return any(
        normalized == name or normalized.endswith(name)
        for name in _SENSITIVE_STRUCTURED_KEY_NAMES
    )


def _is_safe_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() in _SAFE_PLACEHOLDERS


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_nonempty_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_nonempty_string(item) for item in value)


def find_sensitive_payload_leaks(value: Any, *, limit: int = 5) -> list[str]:
    findings: list[str] = []

    def visit(item: Any, path: str) -> None:
        if len(findings) >= limit:
            return
        if isinstance(item, dict):
            for raw_key, nested in item.items():
                key = str(raw_key)
                nested_path = f"{path}.{key}" if path else key
                if _is_sensitive_structured_key(key) and not _is_safe_placeholder(nested):
                    findings.append(f"sensitive value at {nested_path}")
                    if len(findings) >= limit:
                        return
                visit(nested, nested_path)
        elif isinstance(item, (list, tuple)):
            for index, nested in enumerate(item):
                visit(nested, f"{path}[{index}]")
                if len(findings) >= limit:
                    return

    visit(value, "")
    return findings


def redact_sensitive_text(text: str) -> str:
    redacted = str(text)
    for pattern in _SECRET_TEXT_PATTERNS:
        if "value" in pattern.groupindex and "quote" in pattern.groupindex:
            redacted = pattern.sub(r"\g<key>[REDACTED]\g<quote>", redacted)
        elif "value" in pattern.groupindex:
            redacted = pattern.sub(r"\g<key>[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def find_sensitive_text_leaks(text: str, *, limit: int = 5) -> list[str]:
    findings: list[str] = []
    for pattern in _SECRET_TEXT_PATTERNS:
        for match in pattern.finditer(str(text)):
            value = (
                match.group("value")
                if "value" in pattern.groupindex
                else match.group(0)
            )
            if str(value).strip() in _SAFE_PLACEHOLDERS:
                continue
            findings.append(f"sensitive token near offset {match.start()}")
            if len(findings) >= limit:
                return findings
    return findings


def redact_sensitive_payload(value: Any, *, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            item_key: redact_sensitive_payload(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive_payload(item) for item in value]
    if isinstance(value, str):
        if _looks_sensitive_key(key) and value.strip() not in _SAFE_PLACEHOLDERS:
            return "[REDACTED]"
        return redact_sensitive_text(value)
    return value


def check_artifact_redaction(paths: list[str | Path]) -> ReleaseCheck:
    errors: list[str] = []
    checked = 0
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            errors.append(f"missing artifact for redaction check: {path}")
            continue
        try:
            findings = find_sensitive_text_leaks(path.read_text(encoding="utf-8"))
        except OSError as exc:
            errors.append(f"invalid artifact for redaction check: {path}: {exc}")
            continue
        checked += 1
        if findings:
            errors.append(f"{path}: {findings[0]}")
    if errors:
        return ReleaseCheck(
            label="artifact-redaction",
            command="validate artifact redaction",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="artifact-redaction",
        command="validate artifact redaction",
        exit_code=0,
        status="passed",
        summary=f"artifact redaction valid: {checked} artifact(s)",
    )


def check_headless_trace(path: str | Path) -> ReleaseCheck:
    trace_path = Path(path)
    errors: list[str] = []
    payload: dict[str, Any] = {}
    if not trace_path.exists():
        errors.append(f"missing headless trace artifact: {trace_path}")
    else:
        try:
            loaded = json.loads(trace_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
            else:
                errors.append("headless trace payload is not a JSON object")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid headless trace artifact: {exc}")

    if payload:
        if "exit_code" not in payload or not isinstance(payload.get("exit_code"), int):
            errors.append("headless trace missing integer exit_code")
        readiness_report = payload.get("readiness_report")
        if not isinstance(readiness_report, dict):
            errors.append("headless trace missing readiness_report object")
            readiness_status = ""
        else:
            readiness_status = str(readiness_report.get("status") or "").strip()
            if readiness_status not in {"ready", "warning", "blocked", "unknown"}:
                errors.append(f"headless trace has invalid readiness status: {readiness_status}")
            if "summary" not in readiness_report:
                errors.append("headless trace readiness_report missing summary")
        repair_plan = payload.get("repair_plan")
        if not isinstance(repair_plan, list):
            errors.append("headless trace missing repair_plan list")
            repair_step_count = 0
        else:
            repair_step_count = len(repair_plan)
            if repair_step_count == 0:
                errors.append("headless trace repair_plan has no steps")
    else:
        readiness_status = ""
        repair_step_count = 0

    if errors:
        return ReleaseCheck(
            label="headless-trace",
            command="validate headless trace",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="headless-trace",
        command="validate headless trace",
        exit_code=0,
        status="passed",
        summary=(
            "headless trace valid: "
            f"exit_code={payload.get('exit_code')} "
            f"readiness={readiness_status} "
            f"repair_steps={repair_step_count}"
        ),
    )


def build_artifact_manifest(artifacts: dict[str, str | Path]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for label, raw_path in sorted(artifacts.items()):
        path = Path(raw_path)
        entry: dict[str, Any] = {
            "label": str(label),
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": 0,
            "sha256": "",
        }
        if path.exists() and path.is_file():
            try:
                data = path.read_bytes()
                entry["size_bytes"] = len(data)
                entry["sha256"] = hashlib.sha256(data).hexdigest()
            except OSError as exc:
                entry["error"] = str(exc)
        manifest.append(entry)
    return manifest


def check_artifact_manifest(manifest: list[dict[str, Any]]) -> ReleaseCheck:
    errors: list[str] = []
    if not isinstance(manifest, list) or not manifest:
        errors.append("artifact manifest is empty")
        manifest = []
    for entry in manifest:
        if not isinstance(entry, dict):
            errors.append("artifact manifest entry is not an object")
            continue
        label = str(entry.get("label") or "artifact")
        if not entry.get("exists"):
            errors.append(f"artifact missing: {label}")
            continue
        if int(entry.get("size_bytes") or 0) <= 0:
            errors.append(f"artifact is empty: {label}")
        sha256 = str(entry.get("sha256") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", sha256):
            errors.append(f"artifact sha256 invalid: {label}")
        if entry.get("error"):
            errors.append(f"artifact unreadable: {label}: {entry.get('error')}")
    if errors:
        return ReleaseCheck(
            label="artifact-manifest",
            command="validate artifact manifest",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="artifact-manifest",
        command="validate artifact manifest",
        exit_code=0,
        status="passed",
        summary=f"artifact manifest valid: {len(manifest)} artifact(s)",
    )


def check_structure_compliance_artifact(path: str | Path) -> ReleaseCheck:
    artifact_path = Path(path)
    errors: list[str] = []
    payload: dict[str, Any] = {}
    material_summary: dict[str, Any] = {}
    try:
        loaded = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"structure compliance artifact unreadable: {exc}")
    else:
        if isinstance(loaded, dict):
            payload = loaded
        else:
            errors.append("structure compliance artifact payload is not an object")

    if payload:
        if payload.get("cliPassed") is not True:
            errors.append("structure compliance artifact cliPassed is not true")
        if payload.get("qualityGatePassed") is not True:
            errors.append("structure compliance artifact qualityGatePassed is not true")
        quality_findings = payload.get("qualityGateFindings")
        if not isinstance(quality_findings, list):
            errors.append("structure compliance artifact qualityGateFindings is not a list")
        elif quality_findings:
            errors.append("structure compliance artifact has quality gate findings")

        material_inventory = payload.get("materialInventory")
        if not isinstance(material_inventory, dict):
            errors.append("structure compliance artifact missing materialInventory")
        else:
            if material_inventory.get("passed") is not True:
                errors.append("structure compliance materialInventory did not pass")
            material_findings = material_inventory.get("findings")
            if not isinstance(material_findings, list):
                errors.append("structure compliance materialInventory findings is not a list")
            elif material_findings:
                errors.append("structure compliance materialInventory has findings")
            material_summary = material_inventory.get("summary", {})
            if not isinstance(material_summary, dict):
                errors.append("structure compliance materialInventory summary is not an object")
                material_summary = {}
            if int(material_summary.get("focused_gate_count") or 0) <= 0:
                errors.append("structure compliance materialInventory has no focused gates")
            if int(material_summary.get("material_count") or 0) <= 0:
                errors.append("structure compliance materialInventory has no materials")

    if errors:
        return ReleaseCheck(
            label="structure-compliance-artifact",
            command="validate structure compliance artifact",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="structure-compliance-artifact",
        command="validate structure compliance artifact",
        exit_code=0,
        status="passed",
        summary=(
            "structure compliance artifact valid: "
            f"focused_gates={material_summary.get('focused_gate_count')} "
            f"materials={material_summary.get('material_count')}"
        ),
    )


def check_fallback_switch_smoke() -> ReleaseCheck:
    """Validate the local model fallback switch path without calling providers."""
    from types import SimpleNamespace

    from minicode import model_switcher as model_switcher_module
    from minicode.model_switcher import ModelSwitcher
    from minicode.tooling import ToolRegistry

    runtime = {
        "model": "claude-sonnet-4-20250514",
        "fallbackModels": ["gpt-4o"],
    }
    created_models: list[str] = []
    original_build_provider_config = model_switcher_module.build_provider_config
    original_create_model_adapter = model_switcher_module.create_model_adapter

    def _fake_build_provider_config(model: str, runtime: dict[str, Any] | None = None):
        return SimpleNamespace(api_key="test-key" if model == "gpt-4o" else "")

    def _fake_create_model_adapter(
        model: str,
        tools: Any,
        runtime: dict[str, Any] | None = None,
        force_mock: bool = False,
    ):
        created_models.append(model)
        return SimpleNamespace(model_id=model)

    try:
        model_switcher_module.build_provider_config = _fake_build_provider_config
        model_switcher_module.create_model_adapter = _fake_create_model_adapter
        switcher = ModelSwitcher(
            current_model="claude-sonnet-4-20250514",
            current_runtime=runtime,
            current_tools=ToolRegistry([]),
        )
        result = switcher.switch_to_fallback(reason="release_smoke")
    except Exception as exc:
        return ReleaseCheck(
            label="fallback-switch-smoke",
            command="validate local fallback switch",
            exit_code=1,
            status="failed",
            summary=f"fallback switch smoke failed: {exc}",
            stderr=str(exc),
        )
    finally:
        model_switcher_module.build_provider_config = original_build_provider_config
        model_switcher_module.create_model_adapter = original_create_model_adapter

    errors: list[str] = []
    if not result.success:
        errors.append("; ".join(result.errors) or "fallback switch did not succeed")
    if result.new_model != "gpt-4o":
        errors.append(f"fallback switch selected unexpected model: {result.new_model}")
    if switcher.current_model != "gpt-4o":
        errors.append(f"switcher current model did not update: {switcher.current_model}")
    if created_models != ["gpt-4o"]:
        errors.append(f"fallback adapter creation drifted: {created_models}")
    if errors:
        return ReleaseCheck(
            label="fallback-switch-smoke",
            command="validate local fallback switch",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="fallback-switch-smoke",
        command="validate local fallback switch",
        exit_code=0,
        status="passed",
        summary="fallback switch smoke valid: claude-sonnet-4-20250514 -> gpt-4o",
    )


def parse_artifact_specs(specs: list[str]) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    for spec in specs:
        label, separator, raw_path = str(spec).partition("=")
        if not separator or not label.strip() or not raw_path.strip():
            raise ValueError(
                f"Invalid artifact spec '{spec}'. Expected label=path."
            )
        artifacts[label.strip()] = Path(raw_path.strip())
    return artifacts


def write_artifact_manifest(path: str | Path, artifacts: dict[str, str | Path]) -> list[dict[str, Any]]:
    manifest = build_artifact_manifest(artifacts)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _check_mapping_fields(
    *,
    value: Any,
    label: str,
    required: tuple[str, ...],
    errors: list[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} is not an object")
        return {}
    for field in required:
        if field not in value:
            errors.append(f"{label} missing {field}")
    return value


def _release_check_from_mapping(value: Any, *, default_label: str) -> ReleaseCheck:
    payload = value if isinstance(value, dict) else {}
    try:
        exit_code = int(payload.get("exit_code", 1))
    except (TypeError, ValueError):
        exit_code = 1
    return ReleaseCheck(
        label=str(payload.get("label") or default_label),
        command=str(payload.get("command") or ""),
        exit_code=exit_code,
        status=str(payload.get("status") or "failed"),
        summary=str(payload.get("summary") or ""),
        stdout=str(payload.get("stdout") or ""),
        stderr=str(payload.get("stderr") or ""),
    )


def check_release_report_payload(payload: Any) -> ReleaseCheck:
    errors: list[str] = []
    report = _check_mapping_fields(
        value=payload,
        label="release report",
        required=(
            "generated_at",
            "status",
            "local_gate_status",
            "provider_status",
            "status_reasons",
            "compile_check",
            "test_check",
            "runtime_eval_check",
            "smoke_checks",
            "provider_diagnostics",
            "runtime_profile_artifacts",
            "readiness_artifacts",
            "artifact_manifest",
            "readiness_report",
        ),
        errors=errors,
    )
    if not report:
        return ReleaseCheck(
            label="release-report",
            command="validate release report",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )

    if report.get("status") not in {"pass", "warning", "at-risk", "blocked"}:
        errors.append(f"release report has invalid status: {report.get('status')}")
    if report.get("local_gate_status") not in {"pass", "blocked"}:
        errors.append(f"release report has invalid local_gate_status: {report.get('local_gate_status')}")
    if report.get("provider_status") not in {"pass", "warning", "at-risk"}:
        errors.append(f"release report has invalid provider_status: {report.get('provider_status')}")
    if not isinstance(report.get("status_reasons"), list) or not report.get("status_reasons"):
        errors.append("release report status_reasons is empty")

    for label in ("compile_check", "test_check", "runtime_eval_check"):
        check = _check_mapping_fields(
            value=report.get(label),
            label=label,
            required=("label", "status", "exit_code", "summary"),
            errors=errors,
        )
        if check and check.get("status") not in {"passed", "failed"}:
            errors.append(f"{label} has invalid status: {check.get('status')}")

    structure_check = report.get("structure_check")
    if structure_check is not None:
        check = _check_mapping_fields(
            value=structure_check,
            label="structure_check",
            required=("label", "status", "exit_code", "summary"),
            errors=errors,
        )
        if check and check.get("status") not in {"passed", "failed"}:
            errors.append(f"structure_check has invalid status: {check.get('status')}")
        if check and "--check-material-inventory" not in str(check.get("command") or ""):
            errors.append("structure_check command missing --check-material-inventory")

    smoke_checks = report.get("smoke_checks")
    if not isinstance(smoke_checks, list) or not smoke_checks:
        errors.append("release report smoke_checks is empty")
        smoke_checks = []
    for index, smoke_check in enumerate(smoke_checks):
        check = _check_mapping_fields(
            value=smoke_check,
            label=f"smoke_checks[{index}]",
            required=("label", "status", "exit_code", "summary"),
            errors=errors,
        )
        if check and check.get("status") not in {"passed", "failed"}:
            errors.append(f"smoke_checks[{index}] has invalid status: {check.get('status')}")
    for required_label in (
        "readiness-artifacts",
        "readiness-bundle",
        "fallback-simulation",
        "fallback-evidence",
        "fallback-patch-preview",
        "headless-trace",
        "artifact-redaction",
        "fallback-switch-smoke",
        "structure-compliance-artifact",
        "artifact-manifest",
    ):
        matching_smokes = [
            item for item in smoke_checks
            if isinstance(item, dict) and str(item.get("label") or "") == required_label
        ]
        if not matching_smokes:
            errors.append(f"release report smoke_checks missing {required_label}")
        elif matching_smokes[0].get("status") != "passed":
            errors.append(f"release report smoke_check failed: {required_label}")

    local_gate_checks = [
        report.get("compile_check"),
        report.get("test_check"),
        report.get("runtime_eval_check"),
        report.get("structure_check"),
        *smoke_checks,
    ]
    has_failed_local_gate = any(
        isinstance(item, dict) and item.get("status") == "failed"
        for item in local_gate_checks
    )
    if report.get("local_gate_status") == "pass" and has_failed_local_gate:
        errors.append("release report local_gate_status pass contradicts failed local gate")

    provider_diagnostics = report.get("provider_diagnostics")
    if not isinstance(provider_diagnostics, list) or not provider_diagnostics:
        errors.append("release report provider_diagnostics is empty")
    else:
        for index, diagnostic in enumerate(provider_diagnostics):
            checked_diagnostic = _check_mapping_fields(
                value=diagnostic,
                label=f"provider_diagnostics[{index}]",
                required=("label", "outcome", "exit_code", "summary"),
                errors=errors,
            )
            if checked_diagnostic and checked_diagnostic.get("outcome") != "answered":
                for field in ("failure_category", "ownership", "recovery_action"):
                    if not _is_nonempty_string(checked_diagnostic.get(field)):
                        errors.append(f"provider_diagnostics[{index}] missing {field}")
                if not isinstance(checked_diagnostic.get("retryable"), bool):
                    errors.append(f"provider_diagnostics[{index}] retryable is not a boolean")

    runtime_artifacts = _check_mapping_fields(
        value=report.get("runtime_profile_artifacts"),
        label="runtime_profile_artifacts",
        required=("json", "markdown", "headless_trace"),
        errors=errors,
    )
    readiness_artifacts = _check_mapping_fields(
        value=report.get("readiness_artifacts"),
        label="readiness_artifacts",
        required=(
            "fallback_examples_json",
            "doctor_markdown",
            "repair_plan_json",
            "patch_preview_json",
            "fallback_simulations_json",
            "bundle_directory",
            "bundle_manifest_json",
        ),
        errors=errors,
    )
    if runtime_artifacts or readiness_artifacts:
        pass

    trace_payload: dict[str, Any] = {}
    trace_path = Path(str(runtime_artifacts.get("headless_trace") or "")) if runtime_artifacts else Path()
    if runtime_artifacts:
        try:
            loaded_trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"release report headless_trace unreadable: {exc}")
        else:
            if isinstance(loaded_trace, dict):
                trace_payload = loaded_trace
            else:
                errors.append("release report headless_trace payload is not an object")

    if isinstance(provider_diagnostics, list) and trace_payload:
        for index, diagnostic in enumerate(provider_diagnostics):
            if not isinstance(diagnostic, dict):
                continue
            trace_artifact = str(diagnostic.get("trace_artifact") or "").strip()
            if not trace_artifact:
                continue
            if Path(trace_artifact).resolve() != trace_path.resolve():
                errors.append(f"provider_diagnostics[{index}] trace_artifact does not match runtime headless_trace")
            trace_exit_code = trace_payload.get("exit_code")
            if isinstance(trace_exit_code, int) and diagnostic.get("exit_code") != trace_exit_code:
                errors.append(f"provider_diagnostics[{index}] exit_code does not match headless_trace")
            trace_readiness_report = trace_payload.get("readiness_report", {})
            if isinstance(trace_readiness_report, dict):
                trace_readiness_status = str(trace_readiness_report.get("status") or "").strip()
                diagnostic_readiness_status = str(diagnostic.get("readiness_status") or "").strip()
                if diagnostic_readiness_status and diagnostic_readiness_status != trace_readiness_status:
                    errors.append(f"provider_diagnostics[{index}] readiness_status does not match headless_trace")
            trace_repair_plan = trace_payload.get("repair_plan", [])
            if isinstance(trace_repair_plan, list):
                diagnostic_repair_count = diagnostic.get("repair_step_count")
                if isinstance(diagnostic_repair_count, int) and diagnostic_repair_count != len(trace_repair_plan):
                    errors.append(f"provider_diagnostics[{index}] repair_step_count does not match headless_trace")

    manifest_check = check_artifact_manifest(report.get("artifact_manifest", []))
    if manifest_check.status == "failed":
        errors.append(manifest_check.summary)
    manifest_entries = report.get("artifact_manifest", [])
    structure_compliance_path = ""
    if isinstance(manifest_entries, list):
        manifest_paths = {
            str(Path(str(entry.get("path") or "")).resolve())
            for entry in manifest_entries
            if isinstance(entry, dict) and str(entry.get("path") or "").strip()
        }
        declared_artifacts: dict[str, str] = {}
        for source in (runtime_artifacts, readiness_artifacts):
            if not isinstance(source, dict):
                continue
            for label, raw_path in source.items():
                if label == "bundle_directory":
                    continue
                path_text = str(raw_path or "").strip()
                if path_text:
                    declared_artifacts[str(label)] = path_text
        for label, raw_path in sorted(declared_artifacts.items()):
            if str(Path(raw_path).resolve()) not in manifest_paths:
                errors.append(f"release report artifact_manifest missing declared artifact: {label}")
        for entry in manifest_entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("label") or "") == "structure_compliance":
                structure_compliance_path = str(entry.get("path") or "").strip()
                break
    if not structure_compliance_path:
        errors.append("release report artifact_manifest missing structure_compliance")
    else:
        structure_artifact_check = check_structure_compliance_artifact(structure_compliance_path)
        if structure_artifact_check.status == "failed":
            errors.append(structure_artifact_check.summary)

    readiness_report = _check_mapping_fields(
        value=report.get("readiness_report"),
        label="readiness_report",
        required=("status", "provider", "risk_scope", "preflight_checks", "repair_plan", "summary"),
        errors=errors,
    )
    if readiness_report:
        if readiness_report.get("status") not in {"ready", "warning", "blocked"}:
            errors.append(f"readiness_report has invalid status: {readiness_report.get('status')}")
        if not isinstance(readiness_report.get("preflight_checks"), list) or not readiness_report.get("preflight_checks"):
            errors.append("readiness_report preflight_checks is empty")
        if not isinstance(readiness_report.get("repair_plan"), list) or not readiness_report.get("repair_plan"):
            errors.append("readiness_report repair_plan is empty")

    fallback_evidence_check = check_fallback_evidence_payload(report)
    if fallback_evidence_check.status == "failed":
        errors.append(fallback_evidence_check.summary)

    if isinstance(smoke_checks, list):
        compile_check_obj = _release_check_from_mapping(
            report.get("compile_check"),
            default_label="compileall",
        )
        test_check_obj = _release_check_from_mapping(
            report.get("test_check"),
            default_label="pytest-q",
        )
        runtime_eval_check_obj = _release_check_from_mapping(
            report.get("runtime_eval_check"),
            default_label="runtime-profile-eval",
        )
        structure_check_obj = (
            _release_check_from_mapping(
                report.get("structure_check"),
                default_label="structure-compliance",
            )
            if isinstance(report.get("structure_check"), dict)
            else None
        )
        smoke_check_objs = [
            _release_check_from_mapping(item, default_label=f"smoke-{index}")
            for index, item in enumerate(smoke_checks)
            if isinstance(item, dict)
        ]
        expected_local_status = summarize_local_gate_status(
            compile_check=compile_check_obj,
            test_check=test_check_obj,
            runtime_eval_check=runtime_eval_check_obj,
            structure_check=structure_check_obj,
            smoke_checks=smoke_check_objs,
        )
        expected_provider_status = summarize_provider_status(
            provider_outcomes=_provider_outcomes(provider_diagnostics if isinstance(provider_diagnostics, list) else []),
            readiness_report=readiness_report,
        )
        expected_status = summarize_release_status(
            compile_check=compile_check_obj,
            test_check=test_check_obj,
            runtime_eval_check=runtime_eval_check_obj,
            structure_check=structure_check_obj,
            smoke_checks=smoke_check_objs,
            provider_outcomes=_provider_outcomes(provider_diagnostics if isinstance(provider_diagnostics, list) else []),
            readiness_report=readiness_report,
        )
        expected_reasons = release_status_reasons(
            local_gate_status=expected_local_status,
            provider_status=expected_provider_status,
            provider_diagnostics=provider_diagnostics if isinstance(provider_diagnostics, list) else [],
            readiness_report=readiness_report,
        )
        if report.get("local_gate_status") != expected_local_status:
            errors.append("release report local_gate_status does not match recomputed local gates")
        if report.get("provider_status") != expected_provider_status:
            errors.append("release report provider_status does not match recomputed provider status")
        if report.get("status") != expected_status:
            errors.append("release report status does not match recomputed status")
        if report.get("status_reasons") != expected_reasons:
            errors.append("release report status_reasons do not match recomputed reasons")

    if errors:
        return ReleaseCheck(
            label="release-report",
            command="validate release report",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="release-report",
        command="validate release report",
        exit_code=0,
        status="passed",
        summary=(
            "release report valid: "
            f"status={report.get('status')} "
            f"local={report.get('local_gate_status')} "
            f"provider={report.get('provider_status')} "
            f"smokes={len(smoke_checks)}"
        ),
    )


def check_release_report(path: str | Path) -> ReleaseCheck:
    report_path = Path(path)
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ReleaseCheck(
            label="release-report",
            command="validate release report",
            exit_code=1,
            status="failed",
            summary=f"invalid release report: {exc}",
            stderr=str(exc),
        )
    return check_release_report_payload(payload)


def _require_markdown_fragments(
    *,
    markdown: str,
    fragments: list[str],
    label: str,
    errors: list[str],
) -> None:
    for fragment in fragments:
        if fragment not in markdown:
            errors.append(f"release markdown missing {label}: {fragment}")


def check_release_markdown(path: str | Path, *, release_json: str | Path | None = None) -> ReleaseCheck:
    markdown_path = Path(path)
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        return ReleaseCheck(
            label="release-markdown",
            command="validate release markdown",
            exit_code=1,
            status="failed",
            summary=f"invalid release markdown: {exc}",
            stderr=str(exc),
        )

    errors: list[str] = []
    required_sections = [
        "# MiniCode Release Readiness",
        "## Status Reasons",
        "## Core Gate",
        "## Product Smokes",
        "## Provider Diagnostics",
        "## Runtime Profile Artifacts",
    ]
    _require_markdown_fragments(
        markdown=markdown,
        fragments=required_sections,
        label="section",
        errors=errors,
    )

    report: dict[str, Any] | None = None
    if release_json is not None:
        report_path = Path(release_json)
        try:
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"paired release report invalid: {exc}")
            loaded = None
        if loaded is not None:
            report_check = check_release_report_payload(loaded)
            if report_check.status == "failed":
                errors.append(f"paired release report invalid: {report_check.summary}")
            if isinstance(loaded, dict):
                report = loaded
            else:
                errors.append("paired release report is not an object")

    if report:
        _require_markdown_fragments(
            markdown=markdown,
            fragments=[
                f"Status: {report.get('status')}",
                f"Local gates: {report.get('local_gate_status')}",
                f"Provider status: {report.get('provider_status')}",
            ],
            label="status",
            errors=errors,
        )
        status_reasons = report.get("status_reasons", [])
        if isinstance(status_reasons, list):
            _require_markdown_fragments(
                markdown=markdown,
                fragments=[str(reason) for reason in status_reasons if str(reason).strip()],
                label="status reason",
                errors=errors,
            )
        else:
            errors.append("paired release report status_reasons is not a list")

        for field in ("compile_check", "test_check", "runtime_eval_check", "structure_check"):
            check = report.get(field)
            if isinstance(check, dict):
                label = str(check.get("label") or "").strip()
                if label:
                    _require_markdown_fragments(
                        markdown=markdown,
                        fragments=[label],
                        label="core gate",
                        errors=errors,
                    )

        smoke_checks = report.get("smoke_checks", [])
        if isinstance(smoke_checks, list):
            smoke_labels = [
                str(item.get("label") or "").strip()
                for item in smoke_checks
                if isinstance(item, dict) and str(item.get("label") or "").strip()
            ]
            _require_markdown_fragments(
                markdown=markdown,
                fragments=smoke_labels,
                label="smoke",
                errors=errors,
            )
        else:
            errors.append("paired release report smoke_checks is not a list")

        provider_diagnostics = report.get("provider_diagnostics", [])
        if isinstance(provider_diagnostics, list):
            diagnostic_fragments: list[str] = []
            for diagnostic in provider_diagnostics:
                if not isinstance(diagnostic, dict):
                    continue
                for key in (
                    "label",
                    "outcome",
                    "risk_scope",
                    "error_code",
                    "request_id",
                    "failure_category",
                    "ownership",
                    "recovery_action",
                ):
                    value = str(diagnostic.get(key) or "").strip()
                    if value:
                        diagnostic_fragments.append(value)
            _require_markdown_fragments(
                markdown=markdown,
                fragments=diagnostic_fragments,
                label="provider diagnostic",
                errors=errors,
            )
        else:
            errors.append("paired release report provider_diagnostics is not a list")

        readiness_report = report.get("readiness_report")
        if isinstance(readiness_report, dict) and readiness_report:
            fallback_fragments = [
                "## Provider Fallback Coverage",
                f"Provider: {readiness_report.get('provider', 'unknown')}",
                f"Fallback ready: {'yes' if readiness_report.get('fallback_ready') else 'no'}",
                f"Risk scope: {readiness_report.get('risk_scope', 'unknown')}",
            ]
            preflight_checks = readiness_report.get("preflight_checks", [])
            if isinstance(preflight_checks, list) and preflight_checks:
                fallback_fragments.append("### Local Preflight")
                fallback_fragments.extend(
                    str(item.get("label") or "").strip()
                    for item in preflight_checks
                    if isinstance(item, dict) and str(item.get("label") or "").strip()
                )
            repair_plan = readiness_report.get("repair_plan", [])
            if isinstance(repair_plan, list):
                fallback_fragments.extend(
                    str(item.get("step") or "").strip()
                    for item in repair_plan
                    if isinstance(item, dict) and str(item.get("step") or "").strip()
                )
            _require_markdown_fragments(
                markdown=markdown,
                fragments=fallback_fragments,
                label="fallback coverage",
                errors=errors,
            )

        runtime_artifacts = report.get("runtime_profile_artifacts")
        if isinstance(runtime_artifacts, dict):
            _require_markdown_fragments(
                markdown=markdown,
                fragments=[
                    str(path)
                    for path in runtime_artifacts.values()
                    if str(path).strip()
                ],
                label="runtime artifact",
                errors=errors,
            )

        readiness_artifacts = report.get("readiness_artifacts")
        if isinstance(readiness_artifacts, dict) and readiness_artifacts:
            artifact_fragments = ["## Readiness Artifacts"]
            for label, raw_path in sorted(readiness_artifacts.items()):
                if str(raw_path).strip():
                    artifact_fragments.extend([str(label), str(raw_path)])
            _require_markdown_fragments(
                markdown=markdown,
                fragments=artifact_fragments,
                label="readiness artifact",
                errors=errors,
            )

        artifact_manifest = report.get("artifact_manifest", [])
        if isinstance(artifact_manifest, list) and artifact_manifest:
            manifest_fragments = ["## Artifact Manifest"]
            for entry in artifact_manifest:
                if not isinstance(entry, dict):
                    continue
                for key in ("label", "path"):
                    value = str(entry.get(key) or "").strip()
                    if value:
                        manifest_fragments.append(value)
            _require_markdown_fragments(
                markdown=markdown,
                fragments=manifest_fragments,
                label="artifact manifest",
                errors=errors,
            )

    leaks = find_sensitive_text_leaks(markdown)
    if leaks:
        errors.append(f"release markdown contains sensitive token: {leaks[0]}")

    if errors:
        return ReleaseCheck(
            label="release-markdown",
            command="validate release markdown",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    summary = "release markdown valid"
    if report:
        smoke_count = len(report.get("smoke_checks", [])) if isinstance(report.get("smoke_checks"), list) else 0
        summary = (
            "release markdown valid: "
            f"status={report.get('status')} "
            f"smokes={smoke_count}"
        )
    return ReleaseCheck(
        label="release-markdown",
        command="validate release markdown",
        exit_code=0,
        status="passed",
        summary=summary,
    )


def check_fallback_patch_preview_payload(payload: Any) -> ReleaseCheck:
    errors: list[str] = []
    if not isinstance(payload, dict):
        errors.append("fallback patch preview payload is not an object")
        payload = {}

    status = str(payload.get("status") or "").strip()
    risk_scope = str(payload.get("risk_scope") or "").strip()
    previews = payload.get("fallback_settings_patch_preview")
    if status not in {"ready", "warning", "blocked"}:
        errors.append(f"fallback patch preview has invalid status: {status}")
    if not risk_scope:
        errors.append("fallback patch preview missing risk_scope")
    if not isinstance(previews, list):
        errors.append("fallback patch preview missing fallback_settings_patch_preview list")
        previews = []
    elif status != "ready" and risk_scope != "none" and not previews:
        errors.append("fallback patch preview has no actionable preview")

    required_note_fragments = (
        "Review the selected provider patch",
        "Replace placeholder credentials locally",
        "Merge only one selected patch",
        "Run minicode-readiness --json --fail-on blocked",
    )
    for index, preview in enumerate(previews):
        if not isinstance(preview, dict):
            errors.append(f"fallback patch preview[{index}] is not an object")
            continue
        label = str(preview.get("label") or "").strip()
        target_path = str(preview.get("target_path") or "").strip()
        safety = str(preview.get("safety") or "").strip()
        merge_patch = preview.get("merge_patch")
        apply_notes = preview.get("apply_notes")
        if not label:
            errors.append(f"fallback patch preview[{index}] missing label")
        if not target_path:
            errors.append(f"fallback patch preview[{index}] missing target_path")
        if safety != "preview-only; no settings are modified":
            errors.append(f"fallback patch preview[{index}] has invalid safety")
        if not isinstance(merge_patch, dict) or not merge_patch:
            errors.append(f"fallback patch preview[{index}] missing non-empty merge_patch")
        if not isinstance(apply_notes, list) or not apply_notes:
            errors.append(f"fallback patch preview[{index}] missing apply_notes")
        else:
            joined_notes = "\n".join(str(item) for item in apply_notes)
            for fragment in required_note_fragments:
                if fragment not in joined_notes:
                    errors.append(f"fallback patch preview[{index}] missing apply note: {fragment}")

    redaction_findings = find_sensitive_text_leaks(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    if redaction_findings:
        errors.append(redaction_findings[0])

    if errors:
        return ReleaseCheck(
            label="fallback-patch-preview",
            command="validate fallback patch preview",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="fallback-patch-preview",
        command="validate fallback patch preview",
        exit_code=0,
        status="passed",
        summary=(
            "fallback patch preview valid: "
            f"{len(previews)} preview(s) ({risk_scope or 'unknown'})"
        ),
    )


def check_fallback_patch_preview(path: str | Path) -> ReleaseCheck:
    preview_path = Path(path)
    try:
        text = preview_path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        return ReleaseCheck(
            label="fallback-patch-preview",
            command="validate fallback patch preview",
            exit_code=1,
            status="failed",
            summary=f"invalid fallback patch preview: {exc}",
            stderr=str(exc),
        )
    redaction_findings = find_sensitive_text_leaks(text)
    if redaction_findings:
        return ReleaseCheck(
            label="fallback-patch-preview",
            command="validate fallback patch preview",
            exit_code=1,
            status="failed",
            summary=redaction_findings[0],
            stderr="\n".join(redaction_findings),
        )
    return check_fallback_patch_preview_payload(payload)


def _check_single_fallback_simulation_payload(payload: Any) -> ReleaseCheck:
    errors: list[str] = []
    if not isinstance(payload, dict):
        errors.append("fallback simulation payload is not an object")
        payload = {}

    status = str(payload.get("status") or "").strip()
    selected_label = payload.get("selected_label")
    credential_state = str(payload.get("credential_state") or "").strip()
    if status not in {"ready", "requires-credentials", "invalid"}:
        errors.append(f"fallback simulation has invalid status: {status}")
    if not _is_nonempty_string(selected_label):
        errors.append("fallback simulation missing selected_label")
    if credential_state not in {"existing-local", "placeholder", "missing", "invalid"}:
        errors.append(f"fallback simulation has invalid credential_state: {credential_state}")
    if payload.get("simulation_only") is not True:
        errors.append("fallback simulation must be simulation_only")
    if payload.get("live_provider_claim") is not False:
        errors.append("fallback simulation must not claim a live provider result")

    for field in ("issues", "next_actions"):
        values = payload.get(field)
        if not isinstance(values, list):
            errors.append(f"fallback simulation missing {field} list")
        elif not _is_nonempty_string_list(values):
            errors.append(f"fallback simulation has invalid {field} entries")

    fallback_candidates = payload.get("fallback_candidates")
    viable_fallbacks = payload.get("viable_fallbacks")
    fallback_candidates_valid = _is_nonempty_string_list(fallback_candidates)
    viable_fallbacks_valid = _is_nonempty_string_list(viable_fallbacks)
    for field, values in (
        ("fallback_candidates", fallback_candidates),
        ("viable_fallbacks", viable_fallbacks),
    ):
        if not isinstance(values, list):
            errors.append(f"fallback simulation missing {field} list")
        elif not _is_nonempty_string_list(values):
            errors.append(f"fallback simulation has invalid {field} entries")

    if fallback_candidates_valid and viable_fallbacks_valid:
        if not set(viable_fallbacks).issubset(fallback_candidates):
            errors.append("fallback simulation has viable fallbacks outside fallback_candidates")

    if status == "ready" and (
        credential_state != "existing-local"
        or not isinstance(fallback_candidates, list)
        or not fallback_candidates
        or not isinstance(viable_fallbacks, list)
        or not viable_fallbacks
    ):
        errors.append("ready fallback simulation requires existing-local credentials and fallback coverage")

    redaction_findings = find_sensitive_text_leaks(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    if redaction_findings:
        errors.append(redaction_findings[0])
    structured_findings = find_sensitive_payload_leaks(payload)
    if structured_findings:
        errors.append(structured_findings[0])

    if errors:
        return ReleaseCheck(
            label="fallback-simulation",
            command="validate fallback simulation",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="fallback-simulation",
        command="validate fallback simulation",
        exit_code=0,
        status="passed",
        summary=f"fallback simulation valid: {status} ({selected_label})",
    )


def check_fallback_simulation_payload(payload: Any) -> ReleaseCheck:
    if not isinstance(payload, dict) or "simulations" not in payload:
        return _check_single_fallback_simulation_payload(payload)

    errors: list[str] = []
    if payload.get("simulation_only") is not True:
        errors.append("fallback simulations bundle must be simulation_only")
    if payload.get("live_provider_claim") is not False:
        errors.append("fallback simulations bundle must not claim a live provider result")
    simulations = payload.get("simulations")
    if not isinstance(simulations, list):
        errors.append("fallback simulations bundle missing simulations list")
        simulations = []
    for index, simulation in enumerate(simulations):
        check = _check_single_fallback_simulation_payload(simulation)
        if check.status == "failed":
            details = check.stderr or check.summary
            errors.extend(f"simulations[{index}]: {line}" for line in details.splitlines())

    structured_findings = find_sensitive_payload_leaks(payload)
    if structured_findings:
        errors.append(structured_findings[0])
    if errors:
        return ReleaseCheck(
            label="fallback-simulation",
            command="validate fallback simulations",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="fallback-simulation",
        command="validate fallback simulations",
        exit_code=0,
        status="passed",
        summary=f"fallback simulations valid: {len(simulations)} simulation(s)",
    )


def check_fallback_simulation(path: str | Path) -> ReleaseCheck:
    simulation_path = Path(path)
    try:
        text = simulation_path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        return ReleaseCheck(
            label="fallback-simulation",
            command="validate fallback simulation",
            exit_code=1,
            status="failed",
            summary=f"invalid fallback simulation: {exc}",
            stderr=str(exc),
        )
    redaction_findings = find_sensitive_text_leaks(text)
    if redaction_findings:
        return ReleaseCheck(
            label="fallback-simulation",
            command="validate fallback simulation",
            exit_code=1,
            status="failed",
            summary=redaction_findings[0],
            stderr="\n".join(redaction_findings),
        )
    return check_fallback_simulation_payload(payload)


def check_readiness_bundle(directory: str | Path) -> ReleaseCheck:
    bundle_dir = Path(directory)
    paths = {
        "fallback_examples_json": bundle_dir / "readiness-fallback-examples.json",
        "doctor_markdown": bundle_dir / "readiness-doctor.md",
        "repair_plan_json": bundle_dir / "readiness-repair-plan.json",
        "patch_preview_json": bundle_dir / "readiness-fallback-patch-preview.json",
        "fallback_simulations_json": bundle_dir / "readiness-fallback-simulations.json",
        "artifact_manifest_json": bundle_dir / "readiness-artifact-manifest.json",
    }
    errors: list[str] = []
    for label, path in paths.items():
        if not path.exists():
            errors.append(f"readiness bundle missing {label}: {path}")

    if not errors:
        examples_payload: dict[str, Any] = {}
        patch_preview_payload: dict[str, Any] = {}
        simulations_payload: dict[str, Any] = {}
        try:
            loaded_examples = json.loads(paths["fallback_examples_json"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid fallback examples JSON: {exc}")
        else:
            if not isinstance(loaded_examples, dict):
                errors.append("fallback examples payload is not an object")
            else:
                examples_payload = loaded_examples
                if not isinstance(examples_payload.get("fallback_config_examples"), list):
                    errors.append("fallback examples missing fallback_config_examples list")

        try:
            repair_payload = json.loads(paths["repair_plan_json"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid repair plan JSON: {exc}")
        else:
            if not isinstance(repair_payload, dict):
                errors.append("repair plan payload is not an object")
            elif not isinstance(repair_payload.get("repair_plan"), list) or not repair_payload.get("repair_plan"):
                errors.append("repair plan missing non-empty repair_plan list")

        try:
            loaded_patch_preview = json.loads(paths["patch_preview_json"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid fallback patch preview JSON: {exc}")
        else:
            if isinstance(loaded_patch_preview, dict):
                patch_preview_payload = loaded_patch_preview
            patch_preview_check = check_fallback_patch_preview_payload(loaded_patch_preview)
            if patch_preview_check.status == "failed":
                errors.append(patch_preview_check.summary)

        try:
            loaded_simulations = json.loads(
                paths["fallback_simulations_json"].read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid fallback simulations JSON: {exc}")
        else:
            if isinstance(loaded_simulations, dict):
                simulations_payload = loaded_simulations
            simulation_check = check_fallback_simulation_payload(loaded_simulations)
            if simulation_check.status == "failed":
                errors.append(simulation_check.summary)

        if patch_preview_payload and simulations_payload:
            previews = patch_preview_payload.get("fallback_settings_patch_preview", [])
            simulations = simulations_payload.get("simulations", [])
            if isinstance(previews, list) and isinstance(simulations, list):
                preview_labels = [
                    str(item.get("label") or "").strip()
                    for item in previews
                    if isinstance(item, dict)
                ]
                simulation_labels = [
                    str(item.get("selected_label") or "").strip()
                    for item in simulations
                    if isinstance(item, dict)
                ]
                if simulation_labels != preview_labels:
                    errors.append(
                        "readiness bundle fallback simulations do not match preview order"
                    )

        if examples_payload and patch_preview_payload:
            example_items = examples_payload.get("fallback_config_examples", [])
            preview_items = patch_preview_payload.get("fallback_settings_patch_preview", [])
            if isinstance(example_items, list) and isinstance(preview_items, list):
                example_map = {
                    (
                        str(item.get("label") or "").strip(),
                        str(item.get("path") or "").strip(),
                    ): item.get("settings")
                    for item in example_items
                    if isinstance(item, dict)
                }
                preview_map = {
                    (
                        str(item.get("label") or "").strip(),
                        str(item.get("target_path") or "").strip(),
                    ): item.get("merge_patch")
                    for item in preview_items
                    if isinstance(item, dict)
                }
                if set(example_map) != set(preview_map):
                    errors.append("readiness bundle fallback examples and patch previews differ")
                else:
                    for key, settings in example_map.items():
                        if settings != preview_map.get(key):
                            label = key[0] or "fallback"
                            errors.append(f"readiness bundle patch preview differs from example: {label}")
                            break

        try:
            doctor = paths["doctor_markdown"].read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"invalid readiness doctor Markdown: {exc}")
        else:
            for required in (
                "# MiniCode Readiness Doctor",
                "## Local Preflight",
                "## Repair Plan",
                "## Safety",
            ):
                if required not in doctor:
                    errors.append(f"readiness doctor missing: {required}")

        try:
            loaded_manifest = json.loads(paths["artifact_manifest_json"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid readiness bundle manifest JSON: {exc}")
        else:
            manifest_check = check_artifact_manifest(loaded_manifest)
            if manifest_check.status == "failed":
                errors.append(manifest_check.summary)
            expected_manifest = build_artifact_manifest(
                {
                    "fallback_examples_json": paths["fallback_examples_json"],
                    "doctor_markdown": paths["doctor_markdown"],
                    "repair_plan_json": paths["repair_plan_json"],
                    "patch_preview_json": paths["patch_preview_json"],
                    "fallback_simulations_json": paths["fallback_simulations_json"],
                }
            )
            if isinstance(loaded_manifest, list):
                actual_by_label = {
                    str(item.get("label") or ""): item
                    for item in loaded_manifest
                    if isinstance(item, dict)
                }
                expected_by_label = {
                    str(item.get("label") or ""): item
                    for item in expected_manifest
                }
                if set(actual_by_label) != set(expected_by_label):
                    errors.append("readiness bundle manifest labels differ from bundle artifacts")
                else:
                    for label, expected in expected_by_label.items():
                        actual = actual_by_label[label]
                        actual_path = str(actual.get("path") or "")
                        expected_path = str(expected.get("path") or "")
                        if Path(actual_path).resolve() != Path(expected_path).resolve():
                            errors.append(
                                f"readiness bundle manifest drift for {label}: path"
                            )
                            break
                        for field in ("exists", "size_bytes", "sha256"):
                            if actual.get(field) != expected.get(field):
                                errors.append(
                                    f"readiness bundle manifest drift for {label}: {field}"
                                )
                                break
                        if errors and errors[-1].startswith("readiness bundle manifest drift"):
                            break

        redaction_check = check_artifact_redaction(list(paths.values()))
        if redaction_check.status == "failed":
            errors.append(redaction_check.summary)

    if errors:
        return ReleaseCheck(
            label="readiness-bundle",
            command="validate readiness bundle",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    return ReleaseCheck(
        label="readiness-bundle",
        command="validate readiness bundle",
        exit_code=0,
        status="passed",
        summary=f"readiness bundle valid: {len(paths)} artifact(s)",
    )


def _list_labels(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    labels: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            if label:
                labels.add(label)
    return labels


def _list_steps(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    steps: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            step = str(item.get("step") or "").strip()
            if step:
                steps.add(step)
    return steps


def check_fallback_evidence_payload(payload: Any) -> ReleaseCheck:
    errors: list[str] = []
    if not isinstance(payload, dict):
        errors.append("fallback evidence payload is not an object")
        payload = {}

    readiness_report = payload.get("readiness_report")
    if not isinstance(readiness_report, dict):
        errors.append("fallback evidence missing readiness_report object")
        readiness_report = {}

    provider_diagnostics = payload.get("provider_diagnostics")
    if not isinstance(provider_diagnostics, list) or not provider_diagnostics:
        errors.append("fallback evidence missing provider diagnostics")
        provider_diagnostics = []

    provider_status = str(payload.get("provider_status") or "").strip()
    if not provider_status:
        provider_status = summarize_provider_status(
            provider_outcomes=_provider_outcomes(provider_diagnostics),
            readiness_report=readiness_report,
        )

    fallback_ready = bool(readiness_report.get("fallback_ready"))
    fallback_candidates = list(readiness_report.get("fallback_candidates", []) or [])
    viable_fallbacks = list(readiness_report.get("viable_fallbacks", []) or [])
    preflight_labels = _list_labels(readiness_report.get("preflight_checks"))
    repair_steps = _list_steps(readiness_report.get("repair_plan"))

    if provider_status not in {"pass", "warning", "at-risk"}:
        errors.append(f"fallback evidence has invalid provider_status: {provider_status}")
    if "fallback-coverage" not in preflight_labels:
        errors.append("fallback evidence missing fallback-coverage preflight")
    if "live-smoke-readiness" not in preflight_labels:
        errors.append("fallback evidence missing live-smoke-readiness preflight")
    if not repair_steps:
        errors.append("fallback evidence missing repair plan")

    if fallback_ready:
        if not fallback_candidates:
            errors.append("fallback evidence reports ready without fallback candidates")
        if not viable_fallbacks:
            errors.append("fallback evidence reports ready without viable fallbacks")
        if "keep-fallback-gate" not in repair_steps:
            errors.append("fallback evidence missing keep-fallback-gate repair step")
    else:
        risk_scope = str(readiness_report.get("risk_scope") or "").strip()
        if risk_scope in {"", "none"}:
            errors.append("fallback evidence not ready but risk_scope is not actionable")
        examples = readiness_report.get("fallback_config_examples")
        if not isinstance(examples, list) or not examples:
            errors.append("fallback evidence missing fallback configuration examples")
        required_steps = {
            "diagnose-local-readiness",
            "verify-local-readiness",
            "verify-release-readiness",
        }
        missing_steps = sorted(required_steps - repair_steps)
        if missing_steps:
            errors.append(f"fallback evidence missing repair step(s): {', '.join(missing_steps)}")
        if not ({"choose-fallback-provider", "define-fallback-channel"} & repair_steps):
            errors.append("fallback evidence missing fallback selection repair step")

    if provider_status != "pass":
        readiness_artifacts = payload.get("readiness_artifacts")
        if not isinstance(readiness_artifacts, dict):
            errors.append("fallback evidence missing readiness_artifacts object")
            readiness_artifacts = {}
        for required in (
            "fallback_examples_json",
            "doctor_markdown",
            "repair_plan_json",
            "patch_preview_json",
            "bundle_directory",
            "bundle_manifest_json",
        ):
            artifact_path = str(readiness_artifacts.get(required) or "").strip()
            if not artifact_path:
                errors.append(f"fallback evidence missing readiness artifact: {required}")
                continue
            path = Path(artifact_path)
            if required == "bundle_directory":
                if not path.is_dir():
                    errors.append(f"fallback evidence artifact is not a directory: {required}")
            elif not path.is_file():
                errors.append(f"fallback evidence artifact is missing: {required}")
            else:
                try:
                    if path.stat().st_size <= 0:
                        errors.append(f"fallback evidence artifact is empty: {required}")
                except OSError as exc:
                    errors.append(f"fallback evidence artifact is unreadable: {required}: {exc}")

    if errors:
        return ReleaseCheck(
            label="fallback-evidence",
            command="validate fallback evidence",
            exit_code=1,
            status="failed",
            summary=errors[0],
            stderr="\n".join(errors),
        )
    summary = (
        f"fallback evidence valid: provider={provider_status} "
        f"fallback={'ready' if fallback_ready else 'not-ready'} "
        f"repair_steps={len(repair_steps)}"
    )
    return ReleaseCheck(
        label="fallback-evidence",
        command="validate fallback evidence",
        exit_code=0,
        status="passed",
        summary=summary,
    )


def check_fallback_evidence(path: str | Path) -> ReleaseCheck:
    report_path = Path(path)
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ReleaseCheck(
            label="fallback-evidence",
            command="validate fallback evidence",
            exit_code=1,
            status="failed",
            summary=f"invalid fallback evidence report: {exc}",
            stderr=str(exc),
        )
    return check_fallback_evidence_payload(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m minicode.release_readiness",
        description="Release readiness utility checks.",
    )
    parser.add_argument(
        "--check-artifact-redaction",
        nargs="+",
        metavar="PATH",
        help="Validate that generated artifacts do not contain real secret tokens.",
    )
    parser.add_argument(
        "--check-headless-trace",
        metavar="PATH",
        help="Validate that a headless trace artifact contains readiness and repair evidence.",
    )
    parser.add_argument(
        "--check-structure-compliance-artifact",
        metavar="PATH",
        help="Validate that a structure compliance artifact includes passing material inventory evidence.",
    )
    parser.add_argument(
        "--check-fallback-switch-smoke",
        action="store_true",
        help="Validate the local model fallback switch path without calling providers.",
    )
    parser.add_argument(
        "--check-artifact-manifest",
        metavar="PATH",
        help="Validate an artifact manifest JSON file or release readiness JSON containing artifact_manifest.",
    )
    parser.add_argument(
        "--check-release-report",
        metavar="PATH",
        help="Validate a release readiness JSON report schema and evidence links.",
    )
    parser.add_argument(
        "--check-release-markdown",
        metavar="PATH",
        help="Validate a release readiness Markdown report and optional JSON alignment.",
    )
    parser.add_argument(
        "--release-json",
        metavar="PATH",
        help="Release readiness JSON used with --check-release-markdown for alignment checks.",
    )
    parser.add_argument(
        "--check-readiness-bundle",
        metavar="DIR",
        help="Validate a readiness bundle directory generated by minicode-readiness --bundle-out.",
    )
    parser.add_argument(
        "--check-fallback-evidence",
        metavar="PATH",
        help="Validate release JSON fallback evidence for provider risk and repair coverage.",
    )
    parser.add_argument(
        "--check-fallback-patch-preview",
        metavar="PATH",
        help="Validate a read-only fallback settings patch preview artifact.",
    )
    parser.add_argument(
        "--check-fallback-simulation",
        metavar="PATH",
        help="Validate a redacted local fallback simulation artifact.",
    )
    parser.add_argument(
        "--write-artifact-manifest",
        metavar="PATH",
        help="Write an artifact manifest JSON file for --artifact label=path entries.",
    )
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="Artifact entry used with --write-artifact-manifest. May be repeated.",
    )
    args = parser.parse_args(argv)

    if args.check_readiness_bundle:
        check = check_readiness_bundle(args.check_readiness_bundle)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_fallback_evidence:
        check = check_fallback_evidence(args.check_fallback_evidence)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_fallback_patch_preview:
        check = check_fallback_patch_preview(args.check_fallback_patch_preview)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_fallback_simulation:
        check = check_fallback_simulation(args.check_fallback_simulation)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_structure_compliance_artifact:
        check = check_structure_compliance_artifact(args.check_structure_compliance_artifact)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_fallback_switch_smoke:
        check = check_fallback_switch_smoke()
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_release_report:
        check = check_release_report(args.check_release_report)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_release_markdown:
        check = check_release_markdown(args.check_release_markdown, release_json=args.release_json)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.write_artifact_manifest:
        try:
            artifacts = parse_artifact_specs(args.artifact)
            if not artifacts:
                raise ValueError("--write-artifact-manifest requires at least one --artifact label=path entry.")
            manifest = write_artifact_manifest(args.write_artifact_manifest, artifacts)
        except (OSError, ValueError) as exc:
            print(f"artifact manifest write failed: {exc}")
            return 1
        check = check_artifact_manifest(manifest)
        print(f"artifact manifest written: {args.write_artifact_manifest}")
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_artifact_manifest:
        try:
            loaded = json.loads(Path(args.check_artifact_manifest).read_text(encoding="utf-8"))
            manifest = loaded.get("artifact_manifest", loaded) if isinstance(loaded, dict) else loaded
        except (OSError, json.JSONDecodeError) as exc:
            manifest = []
            check = ReleaseCheck(
                label="artifact-manifest",
                command="validate artifact manifest",
                exit_code=1,
                status="failed",
                summary=f"invalid artifact manifest: {exc}",
                stderr=str(exc),
            )
        else:
            check = check_artifact_manifest(manifest)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_headless_trace:
        check = check_headless_trace(args.check_headless_trace)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    if args.check_artifact_redaction:
        check = check_artifact_redaction(args.check_artifact_redaction)
        print(check.summary)
        if check.stderr:
            print(check.stderr)
        return check.exit_code

    parser.print_help()
    return 0


def should_fail_release_status(status: str, fail_on: str | None) -> bool:
    if not fail_on:
        return False
    return RELEASE_STATUS_ORDER.get(status, 3) >= RELEASE_STATUS_ORDER[fail_on]


def classify_provider_outcome(*, exit_code: int, stdout: str, stderr: str) -> tuple[str, str]:
    stripped_stdout = (stdout or "").strip()
    stripped_stderr = (stderr or "").strip()
    combined = " ".join(f"{stripped_stdout}\n{stripped_stderr}".lower().split())
    summary_source = stripped_stdout or stripped_stderr
    summary = summary_source.splitlines()[0].strip() if summary_source else ""

    if exit_code == 0 and stripped_stdout == "OK":
        return "answered", summary or "Headless provider smoke returned OK."
    if any(
        marker in combined
        for marker in (
            "no available channel",
            "no model configured",
            "no auth configured",
        )
    ):
        return "provider_channel_unavailable", summary or "Provider channel unavailable."
    if (
        "provider availability failure" in combined
        or "all viable fallback models were unavailable" in combined
    ):
        return "provider_outage", summary or "Provider availability failure."
    if "model api error" in combined:
        return "provider_api_error", summary or "Provider API error."
    if "empty response" in combined:
        return "empty_output", summary or "Provider smoke returned an empty response."
    if exit_code == 124:
        return "timeout", summary or "Provider smoke timed out."
    return "error", summary or f"Provider smoke failed with exit code {exit_code}."


def summarize_local_gate_status(
    *,
    compile_check: ReleaseCheck,
    test_check: ReleaseCheck,
    runtime_eval_check: ReleaseCheck,
    smoke_checks: list[ReleaseCheck],
    structure_check: ReleaseCheck | None = None,
) -> str:
    gate_checks = [compile_check, test_check, runtime_eval_check, *smoke_checks]
    if structure_check is not None:
        gate_checks.append(structure_check)
    if any(check.status == "failed" for check in gate_checks):
        return "blocked"
    return "pass"


def summarize_provider_status(
    *,
    provider_outcomes: list[str],
    readiness_report: dict[str, Any] | None = None,
) -> str:
    if not provider_outcomes:
        return "at-risk"
    if any(outcome in {"empty_output", "timeout", "provider_api_error"} for outcome in provider_outcomes):
        return "at-risk"
    if any(outcome != "answered" and outcome != "provider_outage" for outcome in provider_outcomes):
        return "at-risk"
    if any(outcome == "provider_outage" for outcome in provider_outcomes):
        report = dict(readiness_report or {})
        if not report.get("fallback_ready"):
            return "at-risk"
        return "warning"
    return "pass"


def summarize_release_status(
    *,
    compile_check: ReleaseCheck,
    test_check: ReleaseCheck,
    runtime_eval_check: ReleaseCheck,
    smoke_checks: list[ReleaseCheck],
    provider_outcomes: list[str],
    structure_check: ReleaseCheck | None = None,
    readiness_report: dict[str, Any] | None = None,
) -> str:
    local_status = summarize_local_gate_status(
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        smoke_checks=smoke_checks,
        structure_check=structure_check,
    )
    if local_status == "blocked":
        return "blocked"
    return summarize_provider_status(
        provider_outcomes=provider_outcomes,
        readiness_report=readiness_report,
    )


def _provider_outcomes(provider_diagnostics: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("outcome", "error")) for item in provider_diagnostics]


def release_status_reasons(
    *,
    local_gate_status: str,
    provider_status: str,
    provider_diagnostics: list[dict[str, Any]],
    readiness_report: dict[str, Any] | None = None,
) -> list[str]:
    report = dict(readiness_report or {})
    reasons: list[str] = []
    if local_gate_status == "pass":
        reasons.append("Local gates passed.")
    else:
        reasons.append("Local gates are blocked; inspect failed core or product smoke checks.")

    if not provider_diagnostics:
        reasons.append("Live provider diagnostics are missing.")
    elif provider_status == "pass":
        reasons.append("Live provider smoke answered successfully.")
    else:
        outcomes = sorted(
            {
                str(diagnostic.get("outcome") or "unknown")
                for diagnostic in provider_diagnostics
            }
        )
        reasons.append(
            f"Live provider status is {provider_status}: {', '.join(outcomes)}."
        )
        error_codes = sorted(
            {
                str(diagnostic.get("error_code") or "").strip()
                for diagnostic in provider_diagnostics
                if str(diagnostic.get("error_code") or "").strip()
            }
        )
        if error_codes:
            reasons.append(f"Provider error code(s): {', '.join(error_codes)}.")

    if report:
        risk_scope = str(report.get("risk_scope") or "unknown")
        if report.get("fallback_ready"):
            reasons.append("Fallback coverage is locally ready.")
        else:
            reasons.append(f"Fallback coverage is not locally ready ({risk_scope}).")
    return reasons


def release_readiness_as_dict(
    *,
    generated_at: str,
    status: str,
    compile_check: ReleaseCheck,
    test_check: ReleaseCheck,
    runtime_eval_check: ReleaseCheck,
    smoke_checks: list[ReleaseCheck],
    provider_diagnostics: list[dict[str, Any]],
    runtime_profile_artifacts: dict[str, str],
    readiness_artifacts: dict[str, str] | None = None,
    artifact_manifest: list[dict[str, Any]] | None = None,
    structure_check: ReleaseCheck | None = None,
    readiness_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_gate_status = summarize_local_gate_status(
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        smoke_checks=smoke_checks,
        structure_check=structure_check,
    )
    provider_status = summarize_provider_status(
        provider_outcomes=_provider_outcomes(provider_diagnostics),
        readiness_report=readiness_report,
    )
    status_reasons = release_status_reasons(
        local_gate_status=local_gate_status,
        provider_status=provider_status,
        provider_diagnostics=provider_diagnostics,
        readiness_report=readiness_report,
    )
    payload = {
        "generated_at": generated_at,
        "status": status,
        "local_gate_status": local_gate_status,
        "provider_status": provider_status,
        "status_reasons": status_reasons,
        "compile_check": asdict(compile_check),
        "test_check": asdict(test_check),
        "runtime_eval_check": asdict(runtime_eval_check),
        "structure_check": asdict(structure_check) if structure_check else None,
        "smoke_checks": [asdict(item) for item in smoke_checks],
        "provider_diagnostics": provider_diagnostics,
        "runtime_profile_artifacts": runtime_profile_artifacts,
        "readiness_artifacts": dict(readiness_artifacts or {}),
        "artifact_manifest": list(artifact_manifest or []),
        "readiness_report": dict(readiness_report or {}),
    }
    return redact_sensitive_payload(payload)


def release_readiness_as_markdown(
    *,
    generated_at: str,
    status: str,
    compile_check: ReleaseCheck,
    test_check: ReleaseCheck,
    runtime_eval_check: ReleaseCheck,
    smoke_checks: list[ReleaseCheck],
    provider_diagnostics: list[dict[str, Any]],
    runtime_profile_artifacts: dict[str, str],
    readiness_artifacts: dict[str, str] | None = None,
    artifact_manifest: list[dict[str, Any]] | None = None,
    structure_check: ReleaseCheck | None = None,
    readiness_report: dict[str, Any] | None = None,
) -> str:
    report = dict(readiness_report or {})
    local_gate_status = summarize_local_gate_status(
        compile_check=compile_check,
        test_check=test_check,
        runtime_eval_check=runtime_eval_check,
        smoke_checks=smoke_checks,
        structure_check=structure_check,
    )
    provider_status = summarize_provider_status(
        provider_outcomes=_provider_outcomes(provider_diagnostics),
        readiness_report=readiness_report,
    )
    status_reasons = release_status_reasons(
        local_gate_status=local_gate_status,
        provider_status=provider_status,
        provider_diagnostics=provider_diagnostics,
        readiness_report=readiness_report,
    )
    lines = [
        "# MiniCode Release Readiness",
        "",
        f"- Generated at: {generated_at}",
        f"- Status: {status}",
        f"- Local gates: {local_gate_status}",
        f"- Provider status: {provider_status}",
        "",
        "## Status Reasons",
        "",
        *[f"- {reason}" for reason in status_reasons],
        "",
        "## Core Gate",
        "",
        "| check | status | exit_code | summary |",
        "| --- | --- | ---: | --- |",
    ]
    core_checks = [compile_check, test_check, runtime_eval_check]
    if structure_check is not None:
        core_checks.append(structure_check)
    for core_check in core_checks:
        lines.append(
            f"| {core_check.label} | {core_check.status} | "
            f"{core_check.exit_code} | {core_check.summary} |"
        )

    lines.extend(
        [
            "",
            "## Product Smokes",
            "",
            "| check | status | exit_code | summary |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for item in smoke_checks:
        lines.append(
            f"| {item.label} | {item.status} | {item.exit_code} | {item.summary} |"
        )

    lines.extend(
        [
            "",
            "## Provider Diagnostics",
            "",
            "| label | outcome | failure_category | retryable | ownership | recovery_action | risk_scope | error_code | request_id | exit_code | summary |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    provider_action_items: list[tuple[str, str]] = []
    if not provider_diagnostics:
        lines.append(
            "| provider-smoke | missing | unknown | false | unknown | Run provider smoke. | unknown | - | - | 0 | "
            "No provider diagnostics were collected. |"
        )
        provider_action_items.append(
            (
                "provider-smoke",
                "Run runtime profile eval or headless provider smoke before release.",
            )
        )
    for diagnostic in provider_diagnostics:
        lines.append(
            f"| {diagnostic.get('label', '-')} | {diagnostic.get('outcome', '-')} | "
            f"{diagnostic.get('failure_category') or '-'} | "
            f"{str(diagnostic.get('retryable', False)).lower()} | "
            f"{diagnostic.get('ownership') or '-'} | "
            f"{diagnostic.get('recovery_action') or '-'} | "
            f"{diagnostic.get('risk_scope', 'unknown')} | "
            f"{diagnostic.get('error_code') or '-'} | "
            f"{diagnostic.get('request_id') or '-'} | "
            f"{diagnostic.get('exit_code', 0)} | "
            f"{diagnostic.get('summary', '')} |"
        )
        for guidance in list(diagnostic.get("guidance", []) or []):
            guidance_text = str(guidance).strip()
            if guidance_text:
                provider_action_items.append(
                    (str(diagnostic.get("label", "provider")), guidance_text)
                )

    if provider_action_items:
        lines.extend(["", "## Provider Action Items", ""])
        for label, guidance in provider_action_items:
            lines.append(f"- `{label}`: {guidance}")

    if report:
        fallback_candidates = [
            str(candidate)
            for candidate in list(report.get("fallback_candidates", []) or [])
        ]
        viable_fallbacks = {
            str(candidate)
            for candidate in list(report.get("viable_fallbacks", []) or [])
        }
        lines.extend(
            [
                "",
                "## Provider Fallback Coverage",
                "",
                f"- Provider: {report.get('provider', 'unknown')}",
                f"- Provider ready: {'yes' if report.get('provider_ready') else 'no'}",
                f"- Channel: {report.get('provider_channel', 'unknown')}",
                f"- Fallback ready: {'yes' if report.get('fallback_ready') else 'no'}",
                f"- Risk scope: {report.get('risk_scope', 'unknown')}",
                f"- Summary: {report.get('summary', '')}",
            ]
        )
        guidance = [
            str(item)
            for item in list(report.get("fallback_guidance", []) or [])
            if str(item).strip()
        ]
        if guidance:
            lines.append("- Guidance:")
            for guidance_item in guidance:
                lines.append(f"  - {guidance_item}")
        next_actions = [
            str(item)
            for item in list(report.get("next_actions", []) or [])
            if str(item).strip()
        ]
        if next_actions:
            lines.append("- Next actions:")
            for action_item in next_actions:
                lines.append(f"  - {action_item}")
        repair_plan = [
            dict(item)
            for item in list(report.get("repair_plan", []) or [])
            if isinstance(item, dict)
        ]
        if repair_plan:
            lines.append("- Repair plan:")
            for repair_item in repair_plan:
                step = str(repair_item.get("step") or "step").strip()
                status = str(repair_item.get("status") or "unknown").strip()
                action = str(repair_item.get("action") or "").strip()
                command = str(repair_item.get("command") or "").strip()
                detail = f"  - {step} [{status}]"
                if action:
                    detail += f": {action}"
                lines.append(detail)
                if command:
                    lines.append(f"    command: `{command}`")
        config_examples = [
            dict(item)
            for item in list(report.get("fallback_config_examples", []) or [])
            if isinstance(item, dict)
        ]
        if config_examples:
            lines.append("- Config examples:")
            for config_example in config_examples:
                label = str(config_example.get("label") or "fallback config").strip()
                path = str(config_example.get("path") or "").strip()
                settings = config_example.get("settings", {})
                rendered_settings = json.dumps(settings, ensure_ascii=False, sort_keys=True)
                location = f" ({path})" if path else ""
                lines.append(f"  - {label}{location}: `{rendered_settings}`")
        preflight_checks = [
            dict(item)
            for item in list(report.get("preflight_checks", []) or [])
            if isinstance(item, dict)
        ]
        if preflight_checks:
            lines.extend(["", "### Local Preflight", ""])
            lines.append("| check | status | summary | action |")
            lines.append("| --- | --- | --- | --- |")
            for check in preflight_checks:
                lines.append(
                    f"| {check.get('label', '-')} | {check.get('status', 'unknown')} | "
                    f"{check.get('summary', '')} | {check.get('action', '')} |"
                )
        if fallback_candidates:
            lines.append("")
            lines.append("| fallback | locally ready |")
            lines.append("| --- | --- |")
            for candidate in fallback_candidates:
                lines.append(
                    f"| {candidate} | {'yes' if candidate in viable_fallbacks else 'no'} |"
                )

    lines.extend(
        [
            "",
            "## Runtime Profile Artifacts",
            "",
            f"- JSON: {runtime_profile_artifacts.get('json', '-')}",
            f"- Markdown: {runtime_profile_artifacts.get('markdown', '-')}",
        ]
    )
    for label, path in sorted(runtime_profile_artifacts.items()):
        if label in {"json", "markdown"}:
            continue
        lines.append(f"- {label}: {path}")
    if readiness_artifacts:
        lines.extend(["", "## Readiness Artifacts", ""])
        for label, path in sorted(readiness_artifacts.items()):
            lines.append(f"- {label}: {path}")
    if artifact_manifest:
        lines.extend(["", "## Artifact Manifest", ""])
        lines.append("| label | exists | size_bytes | sha256 | path |")
        lines.append("| --- | --- | ---: | --- | --- |")
        for entry in artifact_manifest:
            sha256 = str(entry.get("sha256") or "")
            short_hash = sha256[:12] if sha256 else "-"
            lines.append(
                f"| {entry.get('label', '-')} | "
                f"{'yes' if entry.get('exists') else 'no'} | "
                f"{entry.get('size_bytes', 0)} | {short_hash} | "
                f"{entry.get('path', '-')} |"
            )
    return redact_sensitive_text("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
