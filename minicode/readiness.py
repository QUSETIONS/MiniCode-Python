from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from minicode.config import load_runtime_config
from minicode.fallback_simulation import (
    FallbackSimulation,
    select_fallback_preview,
    simulate_fallback_patch,
)
from minicode.product_surfaces import build_readiness_report
from minicode.release_readiness import (
    check_fallback_patch_preview_payload,
    redact_sensitive_payload,
    redact_sensitive_text,
    write_artifact_manifest,
)


READINESS_STATUS_ORDER = {
    "ready": 0,
    "warning": 1,
    "blocked": 2,
}
SIMULATION_STATUS_ORDER = {
    "ready": 0,
    "requires-credentials": 1,
    "invalid": 2,
}


def _should_fail(status: str, fail_on: str | None) -> bool:
    if not fail_on:
        return False
    return READINESS_STATUS_ORDER.get(status, 2) >= READINESS_STATUS_ORDER[fail_on]


def _should_fail_simulation(status: str, fail_on: str | None) -> bool:
    threshold = fail_on or "invalid"
    return SIMULATION_STATUS_ORDER.get(status, 2) >= SIMULATION_STATUS_ORDER[threshold]


def _invalid_simulation_payload(label: str, issue: str) -> dict:
    return asdict(
        FallbackSimulation(
            status="invalid",
            selected_label=label,
            credential_state="invalid",
            issues=[issue],
        )
    )


def _load_runtime_for_simulation(cwd: str) -> dict:
    return load_runtime_config(cwd)


def _runtime_simulation_issue(exc: RuntimeError) -> str:
    message = str(exc)
    if message.startswith("No auth configured."):
        return "No auth configured for local fallback simulation."
    if message.startswith("No model configured."):
        return "No model configured for local fallback simulation."
    return "Unable to load local runtime configuration for fallback simulation."


def _simulate_fallback_patch(cwd: str, preview_path: str, label: str) -> dict:
    try:
        payload = json.loads(Path(preview_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _invalid_simulation_payload(label, f"invalid fallback patch preview: {exc}")

    preview_check = check_fallback_patch_preview_payload(payload)
    if preview_check.status == "failed":
        return _invalid_simulation_payload(label, preview_check.summary)

    preview, selection_error = select_fallback_preview(payload, label)
    if selection_error:
        return _invalid_simulation_payload(label, selection_error)

    try:
        runtime = _load_runtime_for_simulation(cwd)
    except RuntimeError as exc:
        return _invalid_simulation_payload(label, _runtime_simulation_issue(exc))
    return asdict(simulate_fallback_patch(cwd, runtime, preview))


def _examples_payload(report) -> dict:
    return {
        "summary": report.summary,
        "status": report.status,
        "risk_scope": report.risk_scope,
        "fallback_config_examples": report.fallback_config_examples,
    }


def _repair_plan_payload(report) -> dict:
    return {
        "summary": report.summary,
        "status": report.status,
        "risk_scope": report.risk_scope,
        "repair_plan": report.repair_plan,
    }


def _patch_preview_payload(report) -> dict:
    previews: list[dict] = []
    for item in list(report.fallback_config_examples or []):
        label = str(item.get("label") or "fallback config").strip()
        path = str(item.get("path") or "").strip()
        settings = dict(item.get("settings", {}) or {})
        previews.append(
            {
                "label": label,
                "target_path": path,
                "merge_patch": settings,
                "safety": "preview-only; no settings are modified",
                "apply_notes": [
                    "Review the selected provider patch before applying it.",
                    "Replace placeholder credentials locally.",
                    "Merge only one selected patch into the target settings file.",
                    "Run minicode-readiness --json --fail-on blocked after applying.",
                ],
            }
        )
    return {
        "summary": report.summary,
        "status": report.status,
        "risk_scope": report.risk_scope,
        "fallback_settings_patch_preview": previews,
    }


def _fallback_simulations_payload(cwd: str, patch_preview_payload: dict) -> dict:
    previews = patch_preview_payload.get("fallback_settings_patch_preview", [])
    try:
        runtime = _load_runtime_for_simulation(cwd)
        runtime_issue = ""
    except RuntimeError as exc:
        runtime = {}
        runtime_issue = _runtime_simulation_issue(exc)

    simulations: list[dict] = []
    for preview in previews if isinstance(previews, list) else []:
        label = str(preview.get("label") or "").strip() if isinstance(preview, dict) else ""
        if runtime_issue:
            simulation = _invalid_simulation_payload(label, runtime_issue)
        else:
            simulation = asdict(simulate_fallback_patch(cwd, runtime, preview))
        simulations.append(simulation)
    return {
        "simulation_only": True,
        "live_provider_claim": False,
        "simulations": simulations,
    }


def _write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_text(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def _write_bundle(
    directory: str,
    *,
    examples_payload: dict,
    doctor_report: str,
    repair_plan_payload: dict,
    patch_preview_payload: dict,
    fallback_simulations_payload: dict,
) -> dict[str, str]:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    examples_path = target_dir / "readiness-fallback-examples.json"
    doctor_path = target_dir / "readiness-doctor.md"
    repair_plan_path = target_dir / "readiness-repair-plan.json"
    patch_preview_path = target_dir / "readiness-fallback-patch-preview.json"
    simulations_path = target_dir / "readiness-fallback-simulations.json"
    manifest_path = target_dir / "readiness-artifact-manifest.json"

    _write_json(str(examples_path), examples_payload)
    _write_text(str(doctor_path), doctor_report)
    _write_json(str(repair_plan_path), repair_plan_payload)
    _write_json(str(patch_preview_path), patch_preview_payload)
    _write_json(str(simulations_path), fallback_simulations_payload)
    write_artifact_manifest(
        manifest_path,
        {
            "fallback_examples_json": examples_path,
            "doctor_markdown": doctor_path,
            "repair_plan_json": repair_plan_path,
            "patch_preview_json": patch_preview_path,
            "fallback_simulations_json": simulations_path,
        },
    )
    return {
        "fallback_examples_json": str(examples_path),
        "doctor_markdown": str(doctor_path),
        "repair_plan_json": str(repair_plan_path),
        "patch_preview_json": str(patch_preview_path),
        "fallback_simulations_json": str(simulations_path),
        "artifact_manifest_json": str(manifest_path),
    }


def _format_json_snippet(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _preflight_lines(checks: list[dict]) -> list[str]:
    lines: list[str] = []
    if not checks:
        return ["- No local preflight checks are available."]
    for check in checks:
        label = str(check.get("label") or "check").strip()
        status = str(check.get("status") or "unknown").strip()
        summary = str(check.get("summary") or "").strip()
        action = str(check.get("action") or "").strip()
        line = f"- `{label}`: {status}"
        if summary:
            line += f" - {summary}"
        lines.append(line)
        if action:
            lines.append(f"  Action: {action}")
    return lines


def _repair_plan_lines(plan: list[dict]) -> list[str]:
    lines: list[str] = []
    if not plan:
        return ["- No repair actions are required."]
    for item in plan:
        step = str(item.get("step") or "step").strip()
        status = str(item.get("status") or "unknown").strip()
        action = str(item.get("action") or "").strip()
        command = str(item.get("command") or "").strip()
        safety = str(item.get("safety") or "").strip()
        line = f"- `{step}`: {status}"
        if action:
            line += f" - {action}"
        lines.append(line)
        if command:
            lines.append(f"  Command: `{command}`")
        if safety:
            lines.append(f"  Safety: {safety}")
    return lines


def _format_doctor_report(report, *, cwd: str) -> str:
    lines = [
        "# MiniCode Readiness Doctor",
        "",
        f"- Workspace: {cwd}",
        f"- Status: {report.status}",
        f"- Risk scope: {report.risk_scope}",
        f"- Provider: {report.provider}",
        f"- Provider ready: {'yes' if report.provider_ready else 'no'}",
        f"- Channel: {report.provider_channel or 'unknown'}",
        f"- Fallback ready: {'yes' if report.fallback_ready else 'no'}",
        f"- Summary: {report.summary}",
        "",
        "## Issues",
        "",
    ]
    if report.issues:
        lines.extend(f"- {item}" for item in report.issues)
    else:
        lines.append("- No readiness issues detected.")

    lines.extend(["", "## Local Preflight", ""])
    lines.extend(_preflight_lines(report.preflight_checks))

    lines.extend(["", "## Next Actions", ""])
    if report.next_actions:
        lines.extend(f"- {item}" for item in report.next_actions)
    else:
        lines.append("- No immediate action required.")

    lines.extend(["", "## Repair Plan", ""])
    lines.extend(_repair_plan_lines(report.repair_plan))

    lines.extend(["", "## Fallback Config Examples", ""])
    if report.fallback_config_examples:
        for item in report.fallback_config_examples:
            label = str(item.get("label") or "fallback config").strip()
            path = str(item.get("path") or "").strip()
            lines.append(f"### {label}")
            if path:
                lines.append(f"Target settings path: `{path}`")
            lines.extend(
                [
                    "",
                    "```json",
                    _format_json_snippet(dict(item.get("settings", {}) or {})),
                    "```",
                    "",
                ]
            )
    else:
        lines.append("- No fallback configuration examples are required.")

    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This report is read-only.",
            "- It does not write credentials.",
            "- It does not modify MiniCode settings.",
        ]
    )
    return "\n".join(lines)


def _format_readiness_report(report) -> str:
    lines = [
        "Readiness surface:",
        report.summary,
        "",
        f"Status: {report.status}",
        f"Provider: {report.provider}",
        f"Provider ready: {'yes' if report.provider_ready else 'no'}",
        f"Channel: {report.provider_channel or 'unknown'}",
        f"Fallback ready: {'yes' if report.fallback_ready else 'no'}",
        f"Risk scope: {report.risk_scope}",
    ]
    if report.fallback_candidates:
        viable = set(report.viable_fallbacks)
        lines.append(
            f"Configured fallbacks ({len(viable)}/{len(report.fallback_candidates)} locally ready):"
        )
        for candidate in report.fallback_candidates:
            lines.append(f"- {candidate} [{'ready' if candidate in viable else 'not-ready'}]")
    if report.issues:
        lines.append("Issues:")
        lines.extend(f"- {item}" for item in report.issues)
    if report.fallback_guidance:
        lines.append("Guidance:")
        lines.extend(f"- {item}" for item in report.fallback_guidance)
    if report.preflight_checks:
        lines.append("Local preflight:")
        lines.extend(_preflight_lines(report.preflight_checks))
    if report.next_actions:
        lines.append("Next actions:")
        lines.extend(f"- {item}" for item in report.next_actions)
    if report.repair_plan:
        lines.append("Repair plan:")
        lines.extend(_repair_plan_lines(report.repair_plan))
    if report.fallback_config_examples:
        lines.append("Config examples:")
        for item in report.fallback_config_examples:
            label = str(item.get("label") or "fallback config").strip()
            path = str(item.get("path") or "").strip()
            settings = item.get("settings", {})
            rendered_settings = json.dumps(settings, ensure_ascii=False, sort_keys=True)
            location = f" [{path}]" if path else ""
            lines.append(f"- {label}{location}: {rendered_settings}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="minicode-readiness",
        description="Inspect MiniCode provider/runtime readiness.",
    )
    parser.add_argument(
        "--cwd",
        default=".",
        help="Workspace to inspect. Defaults to the current directory.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Emit the readiness report as JSON.",
    )
    output_group.add_argument(
        "--examples",
        action="store_true",
        help="Emit only fallback configuration examples as JSON.",
    )
    output_group.add_argument(
        "--doctor",
        action="store_true",
        help="Emit a human-readable readiness doctor report as Markdown.",
    )
    output_group.add_argument(
        "--repair-plan",
        action="store_true",
        help="Emit a read-only fallback repair plan as JSON.",
    )
    output_group.add_argument(
        "--patch-preview",
        action="store_true",
        help="Emit read-only fallback settings merge patch previews as JSON.",
    )
    output_group.add_argument(
        "--simulate-fallback-patch",
        metavar="PATH",
        help="Simulate one selected fallback patch from a read-only preview JSON artifact.",
    )
    parser.add_argument(
        "--fallback-label",
        help="Label of the fallback patch to simulate.",
    )
    parser.add_argument(
        "--examples-out",
        help="Write fallback configuration examples JSON to this path.",
    )
    parser.add_argument(
        "--doctor-out",
        help="Write a human-readable readiness doctor Markdown report to this path.",
    )
    parser.add_argument(
        "--repair-plan-out",
        help="Write a read-only fallback repair plan JSON to this path.",
    )
    parser.add_argument(
        "--patch-preview-out",
        help="Write read-only fallback settings merge patch previews JSON to this path.",
    )
    parser.add_argument(
        "--bundle-out",
        help="Write readiness examples, doctor, repair plan, and artifact manifest to this directory.",
    )
    parser.add_argument(
        "--simulation-out",
        help="Write the redacted fallback simulation JSON to this path.",
    )
    parser.add_argument(
        "--simulation-fail-on",
        choices=("requires-credentials", "invalid"),
        help="Return exit code 1 when simulation is at or above this severity. Defaults to invalid.",
    )
    parser.add_argument(
        "--fail-on",
        choices=("warning", "blocked"),
        help=(
            "Return exit code 1 when readiness is at or above this severity. "
            "Defaults to report-only mode."
        ),
    )
    args = parser.parse_args(argv)

    cwd = str(Path(args.cwd).resolve())
    if args.simulate_fallback_patch and not args.fallback_label:
        parser.error("--fallback-label is required with --simulate-fallback-patch")
    if not args.simulate_fallback_patch and (
        args.fallback_label or args.simulation_out or args.simulation_fail_on
    ):
        parser.error(
            "--fallback-label, --simulation-out, and --simulation-fail-on require --simulate-fallback-patch"
        )
    if args.simulate_fallback_patch:
        simulation_payload = redact_sensitive_payload(
            _simulate_fallback_patch(cwd, args.simulate_fallback_patch, args.fallback_label)
        )
        if args.simulation_out:
            _write_json(args.simulation_out, simulation_payload)
        print(json.dumps(simulation_payload, ensure_ascii=False, indent=2))
        return 1 if _should_fail_simulation(
            str(simulation_payload.get("status") or "invalid"),
            args.simulation_fail_on,
        ) else 0

    report = build_readiness_report(cwd)
    examples_payload = redact_sensitive_payload(_examples_payload(report))
    repair_plan_payload = redact_sensitive_payload(_repair_plan_payload(report))
    patch_preview_payload = redact_sensitive_payload(_patch_preview_payload(report))
    doctor_report = redact_sensitive_text(_format_doctor_report(report, cwd=cwd))
    if args.examples_out:
        _write_json(args.examples_out, examples_payload)
    if args.doctor_out:
        _write_text(args.doctor_out, doctor_report)
    if args.repair_plan_out:
        _write_json(args.repair_plan_out, repair_plan_payload)
    if args.patch_preview_out:
        _write_json(args.patch_preview_out, patch_preview_payload)
    bundle_paths = None
    if args.bundle_out:
        fallback_simulations_payload = redact_sensitive_payload(
            _fallback_simulations_payload(cwd, patch_preview_payload)
        )
        bundle_paths = _write_bundle(
            args.bundle_out,
            examples_payload=examples_payload,
            doctor_report=doctor_report,
            repair_plan_payload=repair_plan_payload,
            patch_preview_payload=patch_preview_payload,
            fallback_simulations_payload=fallback_simulations_payload,
        )
    if args.doctor:
        print(doctor_report)
        return 1 if _should_fail(report.status, args.fail_on) else 0
    if args.repair_plan:
        print(
            json.dumps(
                repair_plan_payload,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if _should_fail(report.status, args.fail_on) else 0
    if args.patch_preview:
        print(
            json.dumps(
                patch_preview_payload,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if _should_fail(report.status, args.fail_on) else 0
    if args.examples:
        print(
            json.dumps(
                examples_payload,
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if _should_fail(report.status, args.fail_on) else 0
    if args.json:
        print(
            json.dumps(
                redact_sensitive_payload(asdict(report)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if _should_fail(report.status, args.fail_on) else 0

    output = redact_sensitive_text(_format_readiness_report(report))
    if bundle_paths:
        output += "\nBundle artifacts:"
        for label, path in sorted(bundle_paths.items()):
            output += f"\n- {label}: {path}"
    print(output)
    return 1 if _should_fail(report.status, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
