from minicode.fallback_simulation import (
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
