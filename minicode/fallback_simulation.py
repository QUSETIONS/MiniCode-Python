from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minicode.config import validate_provider_runtime
from minicode.model_registry import detect_provider
from minicode.product_surfaces import build_readiness_report


ALLOWED_PATCH_ROOTS = {
    "fallbackModels",
    "anthropicFallbackModels",
    "openaiFallbackModels",
    "openrouterFallbackModels",
    "customFallbackModels",
    "env",
}
ENV_RUNTIME_KEYS = {
    "ANTHROPIC_API_KEY": "apiKey",
    "ANTHROPIC_AUTH_TOKEN": "authToken",
    "ANTHROPIC_BASE_URL": "baseUrl",
    "OPENAI_API_KEY": "openaiApiKey",
    "OPENAI_BASE_URL": "openaiBaseUrl",
    "OPENROUTER_API_KEY": "openrouterApiKey",
    "OPENROUTER_BASE_URL": "openrouterBaseUrl",
    "CUSTOM_API_KEY": "customApiKey",
    "CUSTOM_API_BASE_URL": "customBaseUrl",
}
PLACEHOLDERS = {"", "[REDACTED]", "sk-...", "sk-or-..."}
_FALLBACK_ROOTS = (
    "fallbackModels",
    "anthropicFallbackModels",
    "openaiFallbackModels",
    "openrouterFallbackModels",
    "customFallbackModels",
)
_CREDENTIAL_RUNTIME_KEYS = {"apiKey", "authToken", "openaiApiKey", "openrouterApiKey", "customApiKey"}


@dataclass(frozen=True, slots=True)
class FallbackSimulation:
    status: str
    selected_label: str
    credential_state: str
    fallback_candidates: list[str] = field(default_factory=list)
    viable_fallbacks: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    effective_config: dict[str, Any] = field(default_factory=dict)
    simulation_only: bool = True
    live_provider_claim: bool = False


def select_fallback_preview(payload: Any, label: str) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(payload, dict):
        return None, "fallback preview payload is not an object"
    previews = payload.get("fallback_settings_patch_preview")
    if not isinstance(previews, list):
        return None, "fallback preview list is missing"
    matches = [item for item in previews if isinstance(item, dict) and item.get("label") == label]
    if not matches:
        return None, f"fallback preview label not found: {label}"
    if len(matches) != 1:
        return None, f"fallback preview label is ambiguous: {label}"
    return matches[0], ""


def _is_placeholder(value: Any) -> bool:
    return not isinstance(value, str) or value.strip() in PLACEHOLDERS


def _is_real_credential(value: Any) -> bool:
    return isinstance(value, str) and value.strip() not in PLACEHOLDERS


def _invalid_result(label: str, issue: str) -> FallbackSimulation:
    return FallbackSimulation(
        status="invalid",
        selected_label=label,
        credential_state="invalid",
        issues=[issue],
    )


def _patch_fallback_models(merge_patch: dict[str, Any]) -> list[str] | None:
    models: list[str] = []
    for root in _FALLBACK_ROOTS:
        if root not in merge_patch:
            continue
        value = merge_patch[root]
        if not isinstance(value, list) or any(not isinstance(model, str) for model in value):
            return None
        models.extend(model.strip() for model in value if model.strip())
    return models


def _credential_state(runtime: dict[str, Any], candidates: list[str]) -> str:
    credential_keys: set[str] = set()
    for candidate in candidates:
        provider = detect_provider(candidate, runtime).value
        if provider == "anthropic":
            credential_keys.update({"apiKey", "authToken"})
        elif provider == "openai":
            credential_keys.add("openaiApiKey")
        elif provider == "openrouter":
            credential_keys.add("openrouterApiKey")
        elif provider == "custom":
            credential_keys.add("customApiKey")

    if any(_is_real_credential(runtime.get(key)) for key in credential_keys):
        return "existing-local"
    if any(key in runtime for key in credential_keys):
        return "placeholder"
    return "missing"


def _effective_config(runtime: dict[str, Any], candidates: list[str]) -> dict[str, Any]:
    return {
        "primary_provider": detect_provider(str(runtime.get("model", "")), runtime).value,
        "fallback_candidates": list(candidates),
        "base_urls": {
            "anthropic": str(runtime.get("baseUrl", "")),
            "openai": str(runtime.get("openaiBaseUrl", "")),
            "openrouter": str(runtime.get("openrouterBaseUrl", "")),
            "custom": str(runtime.get("customBaseUrl", "")),
        },
        "credential_present": {
            "anthropic": any(_is_real_credential(runtime.get(key)) for key in ("apiKey", "authToken")),
            "openai": _is_real_credential(runtime.get("openaiApiKey")),
            "openrouter": _is_real_credential(runtime.get("openrouterApiKey")),
            "custom": _is_real_credential(runtime.get("customApiKey")),
        },
    }


def _credentials_are_the_only_blockers(runtime: dict[str, Any], candidates: list[str]) -> bool:
    for candidate in candidates:
        candidate_runtime = dict(runtime)
        candidate_runtime["model"] = candidate
        errors = validate_provider_runtime(candidate_runtime)
        if not errors or any("API_KEY" not in error and "AUTH_TOKEN" not in error for error in errors):
            return False
    return bool(candidates)


def simulate_fallback_patch(
    cwd: str,
    runtime: dict[str, Any],
    preview: Any,
) -> FallbackSimulation:
    if not isinstance(preview, dict):
        return _invalid_result("", "fallback preview is not an object")

    label = str(preview.get("label") or "").strip()
    merge_patch = preview.get("merge_patch")
    if not label or not isinstance(merge_patch, dict):
        return _invalid_result(label, "fallback preview is missing a label or merge patch")

    for root in merge_patch:
        if root not in ALLOWED_PATCH_ROOTS:
            return _invalid_result(label, f"fallback preview contains disallowed patch root: {root}")

    candidates = _patch_fallback_models(merge_patch)
    if candidates is None:
        return _invalid_result(label, "fallback model patches must contain lists of model names")
    if not candidates:
        return _invalid_result(label, "fallback preview does not configure any fallback models")

    effective_runtime = dict(runtime)
    for root in _FALLBACK_ROOTS:
        if root in merge_patch:
            effective_runtime[root] = list(merge_patch[root])

    env = merge_patch.get("env", {})
    if not isinstance(env, dict):
        return _invalid_result(label, "fallback preview env patch is not an object")
    for env_key, value in env.items():
        runtime_key = ENV_RUNTIME_KEYS.get(env_key)
        if runtime_key is None:
            return _invalid_result(label, f"fallback preview contains disallowed env key: {env_key}")
        if runtime_key in _CREDENTIAL_RUNTIME_KEYS:
            if _is_real_credential(value):
                return _invalid_result(label, "fallback preview credentials must be placeholders or redacted values")
            if not _is_real_credential(effective_runtime.get(runtime_key)):
                effective_runtime[runtime_key] = ""
        else:
            effective_runtime[runtime_key] = value

    # Preview credentials are never usable. Retain only actual local runtime credentials.
    for runtime_key in _CREDENTIAL_RUNTIME_KEYS:
        if not _is_real_credential(effective_runtime.get(runtime_key)):
            effective_runtime[runtime_key] = ""

    report = build_readiness_report(cwd, runtime=effective_runtime)
    viable_fallbacks = [
        candidate for candidate in candidates if candidate in report.viable_fallbacks
    ]
    credential_state = _credential_state(effective_runtime, candidates)
    effective_config = _effective_config(effective_runtime, candidates)

    if viable_fallbacks:
        return FallbackSimulation(
            status="ready",
            selected_label=label,
            credential_state=credential_state,
            fallback_candidates=candidates,
            viable_fallbacks=viable_fallbacks,
            issues=[],
            next_actions=report.next_actions,
            effective_config=effective_config,
        )

    if credential_state in {"missing", "placeholder"} and _credentials_are_the_only_blockers(
        effective_runtime, candidates
    ):
        return FallbackSimulation(
            status="requires-credentials",
            selected_label=label,
            credential_state=credential_state,
            fallback_candidates=candidates,
            issues=[],
            next_actions=["Configure a real local credential for the selected fallback provider."],
            effective_config=effective_config,
        )

    return FallbackSimulation(
        status="invalid",
        selected_label=label,
        credential_state=credential_state,
        fallback_candidates=candidates,
        issues=["Selected fallback models are not locally viable."],
        next_actions=report.next_actions,
        effective_config=effective_config,
    )
