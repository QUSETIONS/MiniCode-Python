import urllib.request

import pytest

from minicode.fallback_simulation import (
    _static_provider,
    select_fallback_preview,
    simulate_fallback_patch,
)


def _openai_preview(key: str = "sk-...") -> dict:
    return {
        "label": "OpenAI fallback",
        "target_path": "/ignored/settings.json",
        "merge_patch": {
            "fallbackModels": ["gpt-4o"],
            "env": {
                "OPENAI_API_KEY": key,
                "OPENAI_BASE_URL": "https://api.openai.com",
            },
        },
        "safety": "preview-only; no settings are modified",
    }


def test_placeholder_patch_requires_credentials() -> None:
    result = simulate_fallback_patch(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
            "authToken": "primary-token",
            "baseUrl": "https://api.anthropic.com",
        },
        preview=_openai_preview(),
    )

    assert result.status == "requires-credentials"
    assert result.credential_state == "placeholder"
    assert result.fallback_candidates == ["gpt-4o"]
    assert result.viable_fallbacks == []
    assert result.live_provider_claim is False


def test_existing_real_runtime_credential_can_be_ready() -> None:
    result = simulate_fallback_patch(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
            "authToken": "primary-token",
            "baseUrl": "https://api.anthropic.com",
            "openaiApiKey": "existing-local-secret",
            "openaiBaseUrl": "https://api.openai.com",
        },
        preview=_openai_preview(key="[REDACTED]"),
    )

    assert result.status == "ready"
    assert result.credential_state == "existing-local"
    assert result.viable_fallbacks == ["gpt-4o"]


def test_vendor_prefixed_openai_fallback_uses_custom_runtime_and_is_ready() -> None:
    runtime = {
        "model": "claude-sonnet-4-20250514",
        "openaiBaseUrl": "https://provider.example.test/v1",
        "customBaseUrl": "https://custom.example.test/v1",
        "customApiKey": "existing-custom-secret",
    }
    result = simulate_fallback_patch(
        ".",
        runtime=runtime,
        preview={
            "label": "Custom fallback",
            "merge_patch": {"fallbackModels": ["openai/gpt-4o"]},
        },
    )

    assert _static_provider("openai/gpt-4o", runtime) == "custom"
    assert result.status == "ready"
    assert result.viable_fallbacks == ["openai/gpt-4o"]


def test_existing_local_openai_credential_never_probes_or_calls_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_probe(*args: object, **kwargs: object) -> tuple[str, ...]:
        raise AssertionError("fallback simulation must not probe providers")

    def fail_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("fallback simulation must not make network calls")

    monkeypatch.setattr("minicode.model_registry.probe_openai_exposed_models", fail_probe)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)
    preview = _openai_preview(key="[REDACTED]")
    preview["merge_patch"]["env"]["OPENAI_BASE_URL"] = "https://preview.example.test/v1"

    result = simulate_fallback_patch(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
            "openaiApiKey": "existing-local-secret",
        },
        preview=preview,
    )

    assert result.status == "ready"
    assert result.viable_fallbacks == ["gpt-4o"]


def test_effective_config_redacts_base_url_userinfo_and_components() -> None:
    preview = _openai_preview(key="[REDACTED]")
    preview["merge_patch"]["env"]["OPENAI_BASE_URL"] = (
        "https://preview-user:preview-password@preview.example.test:8443/v1/models"
        "?token=preview-token#fragment"
    )

    result = simulate_fallback_patch(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
            "openaiApiKey": "existing-local-secret",
        },
        preview=preview,
    )

    assert result.status == "ready"
    assert result.effective_config["base_urls"]["openai"] == "https://preview.example.test:8443"
    assert "preview-user" not in str(result.effective_config)
    assert "preview-token" not in str(result.effective_config)


def test_redacted_runtime_credential_without_preview_key_requires_credentials() -> None:
    preview = _openai_preview()
    del preview["merge_patch"]["env"]["OPENAI_API_KEY"]

    result = simulate_fallback_patch(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
            "authToken": "primary-token",
            "baseUrl": "https://api.anthropic.com",
            "openaiApiKey": "[REDACTED]",
        },
        preview=preview,
    )

    assert result.status == "requires-credentials"
    assert result.credential_state == "placeholder"
    assert result.viable_fallbacks == []


@pytest.mark.parametrize(
    "runtime_key",
    [
        "[redacted]",
        "<redacted>",
        "...",
        "***",
        "null",
        "sk-proj-...",
        "placeholder",
        "your-api-key",
    ],
)
def test_placeholder_runtime_openai_credentials_cannot_make_fallback_ready(runtime_key: str) -> None:
    result = simulate_fallback_patch(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
            "openaiApiKey": runtime_key,
        },
        preview=_openai_preview(),
    )

    assert result.status == "requires-credentials"
    assert result.credential_state == "placeholder"
    assert result.viable_fallbacks == []


def test_fallback_candidates_follow_configuration_precedence() -> None:
    preview = _openai_preview()
    preview["merge_patch"].update(
        {
            "anthropicFallbackModels": ["claude-sonnet-4-20250514"],
            "openaiFallbackModels": ["gpt-4.1"],
            "openrouterFallbackModels": ["openrouter/auto"],
            "customFallbackModels": ["custom-model"],
        }
    )

    result = simulate_fallback_patch(".", runtime={"model": "x"}, preview=preview)

    assert result.fallback_candidates == [
        "gpt-4o",
        "claude-sonnet-4-20250514",
        "gpt-4.1",
        "openrouter/auto",
        "custom-model",
    ]


def test_patch_real_credential_is_unsafe() -> None:
    result = simulate_fallback_patch(
        ".",
        runtime={"model": "claude-sonnet-4-20250514"},
        preview=_openai_preview(key="sk-real-patch-secret"),
    )

    assert result.status == "invalid"
    assert "credential" in result.issues[0].lower()


def test_unknown_patch_root_is_invalid() -> None:
    preview = _openai_preview()
    preview["merge_patch"]["mcpServers"] = {"unsafe": {"command": "sh"}}
    result = simulate_fallback_patch(".", runtime={"model": "x"}, preview=preview)

    assert result.status == "invalid"
    assert "mcpServers" in result.issues[0]


def test_preview_selection_rejects_duplicate_labels() -> None:
    payload = {"fallback_settings_patch_preview": [_openai_preview(), _openai_preview()]}

    selected, error = select_fallback_preview(payload, "OpenAI fallback")

    assert selected is None
    assert "ambiguous" in error
