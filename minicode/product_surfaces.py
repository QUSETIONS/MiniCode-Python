from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from minicode.background_tasks import get_slot_stats, list_background_tasks
from minicode.config import (
    MINI_CODE_EXTENSIONS_DIR,
    MINI_CODE_MANAGED_POLICY_PATH,
    MINI_CODE_SETTINGS_PATH,
    MINI_CODE_USER_PROFILE_PATH,
    configured_model_fallbacks,
    describe_fallback_guidance,
    describe_provider_channel,
    discovered_openai_fallbacks,
    default_model_fallbacks,
    load_runtime_config,
    project_extensions_dir,
    project_managed_policy_path,
    project_user_profile_path,
    validate_provider_runtime,
)
from minicode.hooks import get_hook_manager
from minicode.model_registry import detect_provider


@dataclass(frozen=True, slots=True)
class InstructionLayer:
    name: str
    scope: str
    kind: str
    path: str
    exists: bool
    preview: str = ""
    content: str = ""


@dataclass(frozen=True, slots=True)
class ExtensionManifest:
    name: str
    scope: str
    path: str
    version: str = ""
    description: str = ""
    enabled: bool = True
    entrypoint: str = ""


@dataclass(frozen=True, slots=True)
class HookStatus:
    total_hooks: int
    enabled_hooks: int
    total_calls: int
    total_duration_ms: int
    summary: str


@dataclass(frozen=True, slots=True)
class DelegationStatus:
    running_tasks: int
    total_tracked: int
    max_slots: int
    available_slots: int
    active_labels: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    status: str
    provider: str
    provider_ready: bool
    provider_channel: str = ""
    fallback_ready: bool = False
    fallback_candidates: list[str] = field(default_factory=list)
    viable_fallbacks: list[str] = field(default_factory=list)
    fallback_guidance: list[str] = field(default_factory=list)
    risk_scope: str = "unknown"
    next_actions: list[str] = field(default_factory=list)
    fallback_config_examples: list[dict[str, Any]] = field(default_factory=list)
    repair_plan: list[dict[str, Any]] = field(default_factory=list)
    preflight_checks: list[dict[str, str]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass(frozen=True, slots=True)
class PromptBundle:
    prompt: str
    instruction_layers: list[InstructionLayer]
    instruction_summary: str
    hook_status: HookStatus
    delegation_status: DelegationStatus
    extension_manifests: list[ExtensionManifest]
    extension_summary: str
    readiness_report: ReadinessReport
    readiness_summary: str
    product_snapshot: dict[str, Any]


def _maybe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _preview_text(content: str, limit: int = 100) -> str:
    normalized = " ".join(content.split())
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _surface_value(item: Any, field_name: str, default: Any = None) -> Any:
    if hasattr(item, field_name):
        return getattr(item, field_name)
    if isinstance(item, dict):
        return item.get(field_name, default)
    return default


def collect_instruction_layers(cwd: str | Path) -> list[InstructionLayer]:
    cwd_path = Path(cwd)
    candidates = [
        ("global-claude", "global", "claude", Path.home() / ".claude" / "CLAUDE.md"),
        ("global-user", "global", "user", MINI_CODE_USER_PROFILE_PATH),
        ("global-managed", "global", "managed", MINI_CODE_MANAGED_POLICY_PATH),
        ("project-claude", "project", "claude", cwd_path / "CLAUDE.md"),
        ("project-user", "project", "user", project_user_profile_path(cwd_path)),
        ("project-managed", "project", "managed", project_managed_policy_path(cwd_path)),
    ]
    layers: list[InstructionLayer] = []
    for name, scope, kind, path in candidates:
        content = _maybe_read_text(path) if path.exists() else ""
        layers.append(
            InstructionLayer(
                name=name,
                scope=scope,
                kind=kind,
                path=str(path),
                exists=path.exists(),
                preview=_preview_text(content),
                content=content,
            )
        )
    return layers


def format_instruction_summary(layers: list[dict[str, Any]] | list[InstructionLayer]) -> str:
    usable = [layer for layer in layers if bool(_surface_value(layer, "exists", False))]
    if not usable:
        return "instructions: no active layers"
    tokens = [
        f"{_surface_value(layer, 'scope', 'unknown')}:{_surface_value(layer, 'kind', 'unknown')}"
        for layer in usable
    ]
    return f"instructions: {len(usable)} active layer(s) [{', '.join(tokens)}]"


def collect_extension_manifests(cwd: str | Path) -> list[ExtensionManifest]:
    manifests: list[ExtensionManifest] = []
    search_roots = extension_search_roots(cwd)
    for scope, root in search_roots:
        if not root.exists():
            continue
        for manifest_path in sorted(root.glob("*/extension.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            manifests.append(
                ExtensionManifest(
                    name=str(payload.get("name") or manifest_path.parent.name),
                    scope=scope,
                    path=str(manifest_path),
                    version=str(payload.get("version", "") or ""),
                    description=str(payload.get("description", "") or ""),
                    enabled=bool(payload.get("enabled", True)),
                    entrypoint=str(payload.get("entrypoint", "") or ""),
                )
            )
    return manifests


def extension_search_roots(cwd: str | Path) -> list[tuple[str, Path]]:
    return [
        ("global", MINI_CODE_EXTENSIONS_DIR),
        ("project", project_extensions_dir(cwd)),
    ]


def resolve_extension_manifest(
    cwd: str | Path,
    identifier: str,
) -> ExtensionManifest:
    requested = str(identifier or "").strip()
    if not requested:
        raise ValueError("Extension name is required.")

    scope_filter = ""
    name_filter = requested
    if ":" in requested:
        maybe_scope, remainder = requested.split(":", 1)
        maybe_scope = maybe_scope.strip().lower()
        if maybe_scope in {"global", "project"}:
            scope_filter = maybe_scope
            name_filter = remainder.strip()
    if not name_filter:
        raise ValueError("Extension name is required.")

    matches = [
        manifest
        for manifest in collect_extension_manifests(cwd)
        if (
            (not scope_filter or manifest.scope == scope_filter)
            and manifest.name == name_filter
        )
    ]
    if not matches:
        raise ValueError(f"No extension named '{requested}' was found.")
    if len(matches) > 1:
        options = ", ".join(
            f"{manifest.scope}:{manifest.name}"
            for manifest in matches
        )
        raise ValueError(
            f"Multiple extensions matched '{requested}'. Use one of: {options}"
        )
    return matches[0]


def extension_manifest_payload(manifest: ExtensionManifest) -> dict[str, Any]:
    manifest_path = Path(manifest.path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Failed to read extension manifest '{manifest.path}': {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Extension manifest '{manifest.path}' is not a JSON object.")
    return payload


def set_extension_enabled(
    cwd: str | Path,
    identifier: str,
    enabled: bool,
) -> ExtensionManifest:
    manifest = resolve_extension_manifest(cwd, identifier)
    payload = extension_manifest_payload(manifest)
    payload["enabled"] = bool(enabled)
    manifest_path = Path(manifest.path)
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return resolve_extension_manifest(cwd, f"{manifest.scope}:{manifest.name}")


def format_extension_summary(
    manifests: list[dict[str, Any]] | list[ExtensionManifest],
) -> str:
    if not manifests:
        return "extensions: none discovered"
    enabled = [
        manifest for manifest in manifests
        if bool(_surface_value(manifest, "enabled", False))
    ]
    project_count = sum(
        1 for manifest in manifests
        if str(_surface_value(manifest, "scope", "")) == "project"
    )
    return (
        f"extensions: {len(enabled)}/{len(manifests)} enabled "
        f"({project_count} project, {len(manifests) - project_count} global)"
    )


def build_hook_status() -> HookStatus:
    stats = get_hook_manager().get_hook_stats()
    total_hooks = int(stats.get("total_hooks", 0))
    enabled_hooks = int(stats.get("enabled_hooks", 0))
    total_calls = int(stats.get("total_calls", 0))
    total_duration_ms = int(stats.get("total_duration_ms", 0))
    if total_hooks == 0:
        summary = "hooks: none registered"
    else:
        summary = (
            f"hooks: {enabled_hooks}/{total_hooks} enabled, "
            f"{total_calls} call(s), {total_duration_ms}ms total"
        )
    return HookStatus(
        total_hooks=total_hooks,
        enabled_hooks=enabled_hooks,
        total_calls=total_calls,
        total_duration_ms=total_duration_ms,
        summary=summary,
    )


def build_delegation_status() -> DelegationStatus:
    stats = get_slot_stats()
    tasks = list_background_tasks()
    running = [task for task in tasks if task.get("status") == "running"]
    labels = [
        str(task.get("label") or task.get("command") or task.get("taskId") or "task")
        for task in running[:3]
    ]
    summary = (
        f"delegation: {len(running)} running, "
        f"{int(stats.get('available_slots', 0))}/{int(stats.get('max_slots', 0))} slots free"
    )
    if labels:
        summary += f" [{', '.join(labels)}]"
    return DelegationStatus(
        running_tasks=len(running),
        total_tracked=int(stats.get("total_tracked", 0)),
        max_slots=int(stats.get("max_slots", 0)),
        available_slots=int(stats.get("available_slots", 0)),
        active_labels=labels,
        summary=summary,
    )


def _classify_fallbacks(
    runtime: dict[str, Any],
    provider: str,
    *,
    probe_openai_models: bool = True,
) -> tuple[list[str], list[str], list[str]]:
    current_model = str(runtime.get("model", "")).strip()
    configured = configured_model_fallbacks(runtime, provider)
    discovered = (
        discovered_openai_fallbacks(
            runtime,
            current_model=current_model,
            probe_openai_models=probe_openai_models,
        )
        if provider == "openai"
        else []
    )
    defaults = discovered or default_model_fallbacks(
        runtime,
        provider,
        current_model=current_model,
    )
    fallback_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in [*configured, *defaults]:
        normalized = str(candidate or "").strip()
        if not normalized or normalized == current_model or normalized in seen:
            continue
        seen.add(normalized)
        fallback_candidates.append(normalized)
    viable: list[str] = []
    issues: list[str] = []
    for candidate in fallback_candidates:
        candidate_runtime = dict(runtime)
        candidate_runtime["model"] = candidate
        candidate_issues = validate_provider_runtime(
            candidate_runtime,
            probe_openai_models=probe_openai_models,
        )
        if candidate_issues:
            issues.append(f"Fallback '{candidate}' is not locally ready: {candidate_issues[0]}")
            continue
        viable.append(candidate)
    return fallback_candidates, viable, issues


def _readiness_risk_scope(
    *,
    provider_ready: bool,
    fallback_ready: bool,
    fallback_candidates: list[str],
) -> str:
    if provider_ready and fallback_ready:
        return "none"
    if provider_ready:
        return "fallback-gap" if fallback_candidates else "no-fallback-configured"
    if fallback_ready:
        return "degraded-fallback"
    return "provider-config"


def _readiness_next_actions(
    *,
    provider_ready: bool,
    fallback_ready: bool,
    fallback_guidance: list[str],
    issues: list[str],
) -> list[str]:
    actions: list[str] = []
    if not provider_ready:
        actions.append("Fix the primary provider channel or credentials.")
    if not fallback_ready:
        actions.append("Configure at least one locally ready fallback model.")
    if provider_ready and fallback_ready:
        actions.append("Keep fallback coverage in release readiness checks.")
    for item in [*fallback_guidance, *issues]:
        text = str(item).strip()
        if text and text not in actions:
            actions.append(text)
    return actions


def _readiness_fallback_config_examples(
    *,
    runtime: dict[str, Any],
    provider: str,
    fallback_ready: bool,
) -> list[dict[str, Any]]:
    if fallback_ready:
        return []
    settings_path = str(MINI_CODE_SETTINGS_PATH)
    examples: list[dict[str, Any]] = []

    if not runtime.get("openaiApiKey"):
        examples.append(
            {
                "label": "OpenAI fallback",
                "path": settings_path,
                "settings": {
                    "fallbackModels": ["gpt-4o", "gpt-4o-mini"],
                    "env": {
                        "OPENAI_API_KEY": "sk-...",
                        "OPENAI_BASE_URL": "https://api.openai.com",
                    },
                },
            }
        )
    elif provider != "openai":
        examples.append(
            {
                "label": "Use configured OpenAI credentials as fallback",
                "path": settings_path,
                "settings": {"fallbackModels": ["gpt-4o", "gpt-4o-mini"]},
            }
        )

    if not runtime.get("openrouterApiKey"):
        examples.append(
            {
                "label": "OpenRouter fallback",
                "path": settings_path,
                "settings": {
                    "fallbackModels": ["openrouter/auto"],
                    "env": {
                        "OPENROUTER_API_KEY": "sk-or-...",
                        "OPENROUTER_BASE_URL": "https://openrouter.ai/api",
                    },
                },
            }
        )

    return examples[:2]


def _repair_step_id(label: str) -> str:
    normalized = "".join(
        char.lower() if char.isalnum() else "-"
        for char in str(label).strip()
    )
    return "-".join(part for part in normalized.split("-") if part) or "fallback"


def _readiness_repair_plan(
    *,
    provider_ready: bool,
    fallback_ready: bool,
    risk_scope: str,
    fallback_config_examples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = [
        {
            "step": "diagnose-local-readiness",
            "status": "ready" if provider_ready else "blocked",
            "action": "Inspect local provider and fallback readiness without calling the model provider.",
            "command": "minicode-readiness --json --fail-on blocked",
            "safety": "read-only",
        }
    ]
    if fallback_ready:
        plan.append(
            {
                "step": "keep-fallback-gate",
                "status": "ready",
                "action": "Keep fallback coverage in release readiness checks.",
                "command": "python benchmarks/release_readiness.py --fail-on at-risk",
                "safety": "read-only",
            }
        )
        return plan

    if fallback_config_examples:
        target_paths = sorted(
            {
                str(item.get("path") or "").strip()
                for item in fallback_config_examples
                if str(item.get("path") or "").strip()
            }
        )
        plan.append(
            {
                "step": "choose-fallback-provider",
                "status": "manual",
                "action": (
                    "Choose one fallback provider, replace placeholder credentials locally, "
                    "and merge only the selected settings into the target settings file."
                ),
                "target_paths": target_paths,
                "risk_scope": risk_scope,
                "safety": "preview-only; no settings are modified",
            }
        )
        for item in fallback_config_examples:
            label = str(item.get("label") or "fallback").strip()
            settings = dict(item.get("settings", {}) or {})
            plan.append(
                {
                    "step": f"preview-{_repair_step_id(label)}",
                    "status": "preview",
                    "action": f"Preview settings for {label}.",
                    "target_path": str(item.get("path") or "").strip(),
                    "settings_preview": settings,
                    "safety": "contains placeholders only; do not commit real credentials",
                }
            )
    else:
        plan.append(
            {
                "step": "define-fallback-channel",
                "status": "manual",
                "action": "Add explicit fallbackModels and matching provider credentials to MiniCode settings.",
                "risk_scope": risk_scope,
                "safety": "manual configuration required",
            }
        )

    plan.extend(
        [
            {
                "step": "verify-local-readiness",
                "status": "verify",
                "action": "Verify that local provider config and fallback coverage are no longer blocked.",
                "command": "minicode-readiness --json --fail-on blocked",
                "safety": "read-only",
            },
            {
                "step": "verify-release-readiness",
                "status": "verify",
                "action": "Run the release smoke after local readiness is configured.",
                "command": "MINICODE_LIVE_PROVIDER_SMOKE=1 minicode-provider-smoke --run-live",
                "safety": "may call the live provider; explicit opt-in required",
            },
        ]
    )
    return plan


def _readiness_preflight_checks(
    *,
    provider_ready: bool,
    fallback_ready: bool,
    provider_channel: str,
    configured_fallbacks: list[str],
    default_fallbacks: list[str],
    fallback_candidates: list[str],
    viable_fallbacks: list[str],
    issues: list[str],
) -> list[dict[str, str]]:
    issue_preview = issues[0] if issues else "No local provider configuration issues detected."
    checks = [
        {
            "label": "primary-provider-config",
            "status": "pass" if provider_ready else "blocked",
            "summary": provider_channel or issue_preview,
            "action": "Run a live provider smoke before release.",
        },
        {
            "label": "fallback-coverage",
            "status": "pass" if fallback_ready else "warning",
            "summary": (
                f"{len(viable_fallbacks)}/{len(fallback_candidates)} fallback model(s) locally ready"
                if fallback_candidates
                else "No configured or default fallback models are available."
            ),
            "action": (
                "Keep fallback coverage in release readiness checks."
                if fallback_ready
                else "Configure at least one locally ready fallback model."
            ),
        },
        {
            "label": "configured-fallbacks",
            "status": "pass" if configured_fallbacks else "warning",
            "summary": (
                f"{len(configured_fallbacks)} configured fallback model(s)"
                if configured_fallbacks
                else "No explicit fallbackModels are configured."
            ),
            "action": "Add fallbackModels for deterministic release behavior.",
        },
        {
            "label": "default-fallbacks",
            "status": "pass" if default_fallbacks else "warning",
            "summary": (
                f"{len(default_fallbacks)} default fallback model(s) inferred"
                if default_fallbacks
                else "No default fallback model is locally viable for this provider."
            ),
            "action": "Use explicit fallbackModels when defaults are unavailable.",
        },
        {
            "label": "live-smoke-readiness",
            "status": "not-run",
            "summary": "Readiness preflight is local-only and does not call the model provider.",
            "action": "Run the explicit provider smoke with --run-live and MINICODE_LIVE_PROVIDER_SMOKE=1.",
        },
    ]
    if not provider_ready and fallback_ready:
        checks[0]["action"] = "Fix primary credentials while using the ready fallback path."
    if not provider_ready and not fallback_ready:
        checks[1]["status"] = "blocked"
    return checks


def build_readiness_report(
    cwd: str | Path,
    runtime: dict[str, Any] | None = None,
) -> ReadinessReport:
    try:
        effective_runtime = runtime or load_runtime_config(cwd)
        issues = validate_provider_runtime(
            effective_runtime,
            probe_openai_models=False,
        )
        provider = detect_provider(
            str(effective_runtime.get("model", "")).strip(),
            effective_runtime,
            probe_openai_models=False,
        ).value
        provider_ready = not issues
        configured_fallbacks = configured_model_fallbacks(effective_runtime, provider)
        discovered_fallbacks = (
            discovered_openai_fallbacks(
                effective_runtime,
                current_model=str(effective_runtime.get("model", "")).strip(),
                probe_openai_models=False,
            )
            if provider == "openai"
            else []
        )
        default_fallbacks = [
            candidate
            for candidate in (
                discovered_fallbacks
                or default_model_fallbacks(
                    effective_runtime,
                    provider,
                    current_model=str(effective_runtime.get("model", "")).strip(),
                )
            )
            if candidate not in configured_fallbacks
        ]
        fallback_candidates, viable_fallbacks, fallback_issues = _classify_fallbacks(
            effective_runtime,
            provider,
            probe_openai_models=False,
        )
        provider_channel = describe_provider_channel(effective_runtime, provider)
        fallback_guidance = describe_fallback_guidance(
            effective_runtime,
            provider_name=provider,
            current_model=str(effective_runtime.get("model", "")).strip(),
        )
        issues.extend(fallback_issues)
    except Exception as exc:
        effective_runtime = runtime or {}
        issues = [str(exc)]
        provider = detect_provider(
            str(effective_runtime.get("model", "")).strip(),
            effective_runtime,
        ).value if effective_runtime else "unknown"
        provider_ready = False
        configured_fallbacks = []
        default_fallbacks = []
        fallback_candidates = []
        viable_fallbacks = []
        provider_channel = describe_provider_channel(effective_runtime, provider)
        fallback_guidance = describe_fallback_guidance(
            effective_runtime,
            provider_name=provider,
            current_model=str(effective_runtime.get("model", "")).strip(),
        )
    fallback_ready = bool(viable_fallbacks)
    if provider_ready and fallback_ready:
        status = "ready"
    elif provider_ready:
        status = "warning"
        if fallback_candidates:
            if configured_fallbacks and default_fallbacks:
                issues.append("Primary provider is ready, but no configured or default fallback model is locally ready.")
            elif configured_fallbacks:
                issues.append("Primary provider is ready, but no configured fallback model is locally ready.")
            else:
                issues.append("Primary provider is ready, but no default fallback model is locally ready.")
        else:
            issues.append("Primary provider is ready, but no configured or default fallback models are available.")
    elif fallback_ready:
        status = "warning"
        if configured_fallbacks and default_fallbacks:
            issues.insert(0, "Primary provider is blocked, but at least one configured or default fallback model is locally ready.")
        elif configured_fallbacks:
            issues.insert(0, "Primary provider is blocked, but at least one configured fallback model is locally ready.")
        else:
            issues.insert(0, "Primary provider is blocked, but at least one default fallback model is locally ready.")
    else:
        status = "blocked"
    summary = f"readiness: {status} ({provider})"
    if fallback_candidates:
        summary += f" [fallbacks {len(viable_fallbacks)}/{len(fallback_candidates)} locally ready]"
    if issues:
        summary += f" [{issues[0]}]"
    risk_scope = _readiness_risk_scope(
        provider_ready=provider_ready,
        fallback_ready=fallback_ready,
        fallback_candidates=fallback_candidates,
    )
    next_actions = _readiness_next_actions(
        provider_ready=provider_ready,
        fallback_ready=fallback_ready,
        fallback_guidance=fallback_guidance,
        issues=issues,
    )
    fallback_config_examples = _readiness_fallback_config_examples(
        runtime=effective_runtime,
        provider=provider,
        fallback_ready=fallback_ready,
    )
    repair_plan = _readiness_repair_plan(
        provider_ready=provider_ready,
        fallback_ready=fallback_ready,
        risk_scope=risk_scope,
        fallback_config_examples=fallback_config_examples,
    )
    preflight_checks = _readiness_preflight_checks(
        provider_ready=provider_ready,
        fallback_ready=fallback_ready,
        provider_channel=provider_channel,
        configured_fallbacks=configured_fallbacks,
        default_fallbacks=default_fallbacks,
        fallback_candidates=fallback_candidates,
        viable_fallbacks=viable_fallbacks,
        issues=issues,
    )
    return ReadinessReport(
        status=status,
        provider=provider,
        provider_ready=provider_ready,
        provider_channel=provider_channel,
        fallback_ready=fallback_ready,
        fallback_candidates=fallback_candidates,
        viable_fallbacks=viable_fallbacks,
        fallback_guidance=fallback_guidance,
        risk_scope=risk_scope,
        next_actions=next_actions,
        fallback_config_examples=fallback_config_examples,
        repair_plan=repair_plan,
        preflight_checks=preflight_checks,
        issues=issues,
        summary=summary,
    )


def build_product_snapshot(
    cwd: str | Path,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    instruction_layers = collect_instruction_layers(cwd)
    hook_status = build_hook_status()
    delegation_status = build_delegation_status()
    extension_manifests = collect_extension_manifests(cwd)
    readiness_report = build_readiness_report(cwd, runtime=runtime)
    return {
        "instruction_layers": [asdict(layer) for layer in instruction_layers],
        "instruction_summary": format_instruction_summary(instruction_layers),
        "hook_status": asdict(hook_status),
        "hook_summary": hook_status.summary,
        "delegated_tasks": list_background_tasks(),
        "delegation_status": asdict(delegation_status),
        "delegation_summary": delegation_status.summary,
        "extension_manifests": [asdict(manifest) for manifest in extension_manifests],
        "extension_summary": format_extension_summary(extension_manifests),
        "readiness_report": asdict(readiness_report),
        "readiness_summary": readiness_report.summary,
    }
