from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from minicode.model_registry import BUILTIN_MODELS, Provider


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
_PLACEHOLDER_MARKERS = {"null", "none", "redacted", "masked", "placeholder", "changeme"}
_MIN_CREDENTIAL_LENGTH = 16
_FALLBACK_ROOTS = (
    "fallbackModels",
    "anthropicFallbackModels",
    "openaiFallbackModels",
    "openrouterFallbackModels",
    "customFallbackModels",
)
_CREDENTIAL_RUNTIME_KEYS = {"apiKey", "authToken", "openaiApiKey", "openrouterApiKey", "customApiKey"}
_OPENAI_PREFIXES = ("gpt-5", "gpt-4", "gpt-3.5", "gpt5", "o1-", "o3-", "chatgpt-")
_OPENAI_EXACT_MODELS = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-5.5", "gpt5.5", "o1", "o1-mini", "o3-mini"}
_OPENROUTER_PREFIXES = (
    "openrouter/",
    "anthropic/",
    "openai/",
    "google/",
    "meta-llama/",
    "deepseek/",
    "qwen/",
    "minimax/",
    "mistralai/",
)
_VENDOR_PREFIXES = _OPENROUTER_PREFIXES[1:]


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


def _normalize_credential_marker(value: Any) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def _is_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return True

    marker = _normalize_credential_marker(value)
    compact_marker = "".join(character for character in marker if character.isalnum())
    if not marker or compact_marker in _PLACEHOLDER_MARKERS:
        return True
    if "redacted" in marker or "placeholder" in marker:
        return True
    if not any(character.isalnum() for character in marker):
        return True
    if marker.endswith("..."):
        return True
    return len(marker) < _MIN_CREDENTIAL_LENGTH


def _is_real_credential(value: Any) -> bool:
    return isinstance(value, str) and not _is_placeholder(value)


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


def _static_provider(model: str, runtime: dict[str, Any] | None = None) -> str:
    normalized = model.strip()
    normalized_lower = normalized.lower()
    if normalized_lower.startswith(_VENDOR_PREFIXES):
        if runtime and runtime.get("openaiBaseUrl"):
            return Provider.CUSTOM.value
        return Provider.OPENROUTER.value

    model_info = BUILTIN_MODELS.get(normalized)
    if model_info is not None:
        return model_info.provider.value

    for known_model, known_info in BUILTIN_MODELS.items():
        if known_model.lower() == normalized_lower:
            return known_info.provider.value
    if normalized_lower.startswith(_OPENROUTER_PREFIXES):
        return Provider.OPENROUTER.value
    if normalized_lower in _OPENAI_EXACT_MODELS or normalized_lower.startswith(_OPENAI_PREFIXES):
        return Provider.OPENAI.value
    if normalized_lower.startswith("claude-"):
        return Provider.ANTHROPIC.value
    return Provider.CUSTOM.value


def _is_valid_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value.strip())
        _ = parsed.port
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def _safe_origin(value: Any) -> str:
    if not _is_valid_http_url(value):
        return ""
    parsed = urlsplit(str(value).strip())
    hostname = parsed.hostname
    if not hostname:
        return ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    port = parsed.port
    suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme.lower()}://{host}{suffix}"


def _candidate_validation_errors(runtime: dict[str, Any], candidate: str) -> list[str]:
    provider = _static_provider(candidate, runtime)
    provider_requirements = {
        Provider.ANTHROPIC.value: (("apiKey", "authToken"), "baseUrl"),
        Provider.OPENAI.value: (("openaiApiKey",), "openaiBaseUrl"),
        Provider.OPENROUTER.value: (("openrouterApiKey",), "openrouterBaseUrl"),
        Provider.CUSTOM.value: (("customApiKey",), "customBaseUrl"),
    }
    requirements = provider_requirements.get(provider)
    if requirements is None:
        return [f"Fallback '{candidate}' uses unsupported provider '{provider}'."]

    credential_keys, base_url_key = requirements
    errors: list[str] = []
    if not any(_is_real_credential(runtime.get(key)) for key in credential_keys):
        errors.append("credential")
    if not _is_valid_http_url(runtime.get(base_url_key)):
        errors.append("base URL")
    return errors


def _credential_state(runtime: dict[str, Any], candidates: list[str]) -> str:
    credential_keys: set[str] = set()
    for candidate in candidates:
        provider = _static_provider(candidate, runtime)
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
        "primary_provider": _static_provider(str(runtime.get("model", "")), runtime),
        "fallback_candidates": list(candidates),
        "base_urls": {
            "anthropic": _safe_origin(runtime.get("baseUrl")),
            "openai": _safe_origin(runtime.get("openaiBaseUrl")),
            "openrouter": _safe_origin(runtime.get("openrouterBaseUrl")),
            "custom": _safe_origin(runtime.get("customBaseUrl")),
        },
        "credential_present": {
            "anthropic": any(_is_real_credential(runtime.get(key)) for key in ("apiKey", "authToken")),
            "openai": _is_real_credential(runtime.get("openaiApiKey")),
            "openrouter": _is_real_credential(runtime.get("openrouterApiKey")),
            "custom": _is_real_credential(runtime.get("customApiKey")),
        },
    }


def _next_actions(status: str) -> list[str]:
    if status == "ready":
        return ["Keep fallback coverage in release readiness checks."]
    if status == "requires-credentials":
        return ["Configure a real local credential for the selected fallback provider."]
    return ["Review the selected fallback model and provider configuration."]


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

    candidate_errors = {
        candidate: _candidate_validation_errors(effective_runtime, candidate)
        for candidate in candidates
    }
    viable_fallbacks = [candidate for candidate in candidates if not candidate_errors[candidate]]
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
            next_actions=_next_actions("ready"),
            effective_config=effective_config,
        )

    if credential_state in {"missing", "placeholder"} and all(
        errors == ["credential"] for errors in candidate_errors.values()
    ):
        return FallbackSimulation(
            status="requires-credentials",
            selected_label=label,
            credential_state=credential_state,
            fallback_candidates=candidates,
            issues=[],
            next_actions=_next_actions("requires-credentials"),
            effective_config=effective_config,
        )

    return FallbackSimulation(
        status="invalid",
        selected_label=label,
        credential_state=credential_state,
        fallback_candidates=candidates,
        issues=["Selected fallback models are not locally viable."],
        next_actions=_next_actions("invalid"),
        effective_config=effective_config,
    )
