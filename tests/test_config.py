import minicode.config as config_module
from minicode.config import (
    describe_fallback_guidance,
    default_model_fallbacks,
    discovered_openai_fallbacks,
    effective_model_fallbacks,
    format_config_diagnostic,
    load_runtime_config,
    merge_settings,
    validate_provider_runtime,
)
from minicode.model_registry import Provider, detect_provider


def test_merge_settings_merges_env_and_mcp_servers() -> None:
    merged = merge_settings(
        {
            "env": {"A": "1"},
            "mcpServers": {
                "fs": {"command": "npx", "args": ["a"], "env": {"X": "1"}}
            },
        },
        {
            "env": {"B": "2"},
            "mcpServers": {
                "fs": {"command": "uvx", "env": {"Y": "2"}},
                "search": {"command": "python"},
            },
        },
    )

    assert merged["env"] == {"A": "1", "B": "2"}
    assert merged["mcpServers"]["fs"]["command"] == "uvx"
    assert merged["mcpServers"]["fs"]["args"] == ["a"]
    assert merged["mcpServers"]["fs"]["env"] == {"X": "1", "Y": "2"}
    assert merged["mcpServers"]["search"]["command"] == "python"


def test_validate_provider_runtime_rejects_mismatched_provider_key() -> None:
    errors = validate_provider_runtime(
        {
            "model": "gpt-4o",
            "openaiApiKey": "",
            "apiKey": "anthropic-key-does-not-unlock-openai",
            "openaiBaseUrl": "https://api.openai.com",
        }
    )

    assert any("OPENAI_API_KEY" in error for error in errors)


def test_validate_provider_runtime_accepts_openrouter_prefixed_model() -> None:
    errors = validate_provider_runtime(
        {
            "model": "anthropic/claude-sonnet-4",
            "openrouterApiKey": "sk-or-test",
            "openrouterBaseUrl": "https://openrouter.ai/api",
        }
    )

    assert errors == []


def test_validate_provider_runtime_accepts_gpt55_openai_compatible() -> None:
    errors = validate_provider_runtime(
        {
            "model": "gpt5.5",
            "openaiApiKey": "sk-test",
            "openaiBaseUrl": "https://www.cctq.ai",
        }
    )

    assert errors == []


def test_detect_provider_accepts_provider_exposed_model_on_custom_openai_host() -> None:
    provider = detect_provider(
        "claude-sonnet-4-6",
        {
            "openaiApiKey": "sk-test",
            "openaiBaseUrl": "https://www.cctq.ai",
            "_openaiExposedModels": ["claude-sonnet-4-6"],
        },
    )

    assert provider == Provider.OPENAI


def test_detect_provider_can_classify_unknown_openai_model_without_probe(
    monkeypatch,
) -> None:
    def fail_probe(*_args, **_kwargs):
        raise AssertionError("local provider detection must not probe the gateway")

    monkeypatch.setattr("minicode.model_registry.probe_openai_exposed_models", fail_probe)
    provider = detect_provider(
        "qwen3.7-max",
        {
            "openaiApiKey": "openai-key",
            "openaiBaseUrl": "https://provider.example.test/v1",
        },
        probe_openai_models=False,
    )

    assert provider == Provider.OPENAI


def test_validate_provider_runtime_rejects_non_exposed_model_on_custom_openai_host() -> None:
    errors = validate_provider_runtime(
        {
            "model": "gpt5.5",
            "openaiApiKey": "sk-test",
            "openaiBaseUrl": "https://www.cctq.ai",
            "_openaiExposedModels": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        }
    )

    assert any("not exposed by the current openai-compatible provider" in error.lower() for error in errors)
    assert any("claude-sonnet-4-6" in error for error in errors)


def test_load_runtime_config_includes_runtime_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "load_effective_settings",
        lambda cwd=None: {
            "model": "anthropic/claude-sonnet-4",
            "runtimeProfile": "single-deep",
            "env": {"ANTHROPIC_API_KEY": "test-key"},
        },
    )
    monkeypatch.delenv("MINI_CODE_RUNTIME_PROFILE", raising=False)
    monkeypatch.delenv("MINI_CODE_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    runtime = load_runtime_config(cwd=".")

    assert runtime["runtimeProfile"] == "single-deep"


def test_load_runtime_config_includes_anthropic_family_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "load_effective_settings",
        lambda cwd=None: {
            "model": "deepseek-v4-pro[1m]",
            "env": {
                "ANTHROPIC_AUTH_TOKEN": "test-token",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro[1m]",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro[1m]",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-pro[1m]",
            },
        },
    )
    monkeypatch.delenv("MINI_CODE_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_DEFAULT_SONNET_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_DEFAULT_OPUS_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", raising=False)

    runtime = load_runtime_config(cwd=".")

    assert runtime["anthropicDefaultSonnetModel"] == "deepseek-v4-pro[1m]"
    assert runtime["anthropicDefaultOpusModel"] == "deepseek-v4-pro[1m]"
    assert runtime["anthropicDefaultHaikuModel"] == "deepseek-v4-pro[1m]"


def test_load_runtime_config_prefers_settings_env_for_anthropic_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "load_effective_settings",
        lambda cwd=None: {
            "model": "gpt5.5",
            "env": {
                "ANTHROPIC_BASE_URL": "https://ai.space.cx",
                "ANTHROPIC_AUTH_TOKEN": "fresh-token",
                "ANTHROPIC_MODEL": "gpt5.5",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "gpt5.5",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "gpt5.5",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": "gpt5.5",
            },
        },
    )
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openai-proxy.miracleplus.com/v1")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "stale-token")
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-v4-pro[1m]")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "deepseek-v4-pro[1m]")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "deepseek-v4-pro[1m]")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "deepseek-v4-pro[1m]")
    monkeypatch.delenv("MINI_CODE_MODEL", raising=False)

    runtime = load_runtime_config(cwd=".")

    assert runtime["model"] == "gpt5.5"
    assert runtime["baseUrl"] == "https://ai.space.cx"
    assert runtime["authToken"] == "fresh-token"
    assert runtime["anthropicDefaultSonnetModel"] == "gpt5.5"
    assert runtime["anthropicDefaultOpusModel"] == "gpt5.5"
    assert runtime["anthropicDefaultHaikuModel"] == "gpt5.5"


def test_load_runtime_config_prefers_settings_env_for_openai_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "load_effective_settings",
        lambda cwd=None: {
            "model": "gpt5.5",
            "env": {
                "OPENAI_BASE_URL": "https://www.cctq.ai",
                "OPENAI_API_KEY": "fresh-openai-token",
            },
        },
    )
    monkeypatch.setenv("OPENAI_BASE_URL", "https://stale.example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "stale-openai-token")
    monkeypatch.delenv("MINI_CODE_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)

    runtime = load_runtime_config(cwd=".")

    assert runtime["model"] == "gpt5.5"
    assert runtime["configuredModel"] == "gpt5.5"
    assert runtime["openaiBaseUrl"] == "https://www.cctq.ai"
    assert runtime["openaiApiKey"] == "fresh-openai-token"


def test_load_runtime_config_preserves_mini_code_model_override(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "load_effective_settings",
        lambda cwd=None: {
            "model": "gpt5.5",
            "env": {
                "ANTHROPIC_AUTH_TOKEN": "fresh-token",
                "ANTHROPIC_MODEL": "gpt5.5",
            },
        },
    )
    monkeypatch.setenv("MINI_CODE_MODEL", "gpt-4o")
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-v4-pro[1m]")

    runtime = load_runtime_config(cwd=".")

    assert runtime["model"] == "gpt-4o"


def test_load_runtime_config_includes_structured_fallback_models(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "load_effective_settings",
        lambda cwd=None: {
            "model": "claude-sonnet-4-20250514",
            "fallbackModels": ["gpt-4o", "openrouter/auto"],
            "anthropicFallbackModels": "qwen3.6-plus, claude-haiku-3-20240307",
            "env": {"ANTHROPIC_API_KEY": "test-key"},
        },
    )
    monkeypatch.delenv("MINI_CODE_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MINI_CODE_MODEL_FALLBACKS", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL_FALLBACKS", raising=False)

    runtime = load_runtime_config(cwd=".")

    assert runtime["fallbackModels"] == ["gpt-4o", "openrouter/auto"]
    assert runtime["anthropicFallbackModels"] == [
        "qwen3.6-plus",
        "claude-haiku-3-20240307",
    ]


def test_default_model_fallbacks_seed_bounded_cross_provider_chain_for_non_claude_anthropic() -> None:
    runtime = {
        "model": "deepseek-v4-pro[1m]",
        "openaiApiKey": "openai-key",
        "openaiBaseUrl": "https://api.openai.com",
        "openrouterApiKey": "openrouter-key",
        "openrouterBaseUrl": "https://openrouter.ai/api/v1",
    }

    assert default_model_fallbacks(runtime, "anthropic") == [
        "gpt-4o",
        "gpt-4o-mini",
        "openrouter/auto",
    ]


def test_effective_model_fallbacks_prefer_explicit_before_defaults() -> None:
    runtime = {
        "model": "claude-sonnet-4-20250514",
        "fallbackModels": ["gpt-4o"],
        "anthropicDefaultHaikuModel": "claude-haiku-3-20240307",
        "apiKey": "anthropic-key",
        "baseUrl": "https://api.anthropic.com",
    }

    assert effective_model_fallbacks(runtime, "anthropic") == [
        "gpt-4o",
        "claude-haiku-3-20240307",
    ]


def test_format_config_diagnostic_scopes_openai_provider_details(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "validate_config",
        lambda cwd=None: (True, []),
    )
    monkeypatch.setattr(
        config_module,
        "load_runtime_config",
        lambda cwd=None: {
            "model": "gpt5.5",
            "configuredModel": "gpt5.5",
            "openaiBaseUrl": "https://www.cctq.ai",
            "openaiApiKey": "openai-key",
            "authToken": "stale-anthropic-token",
            "apiKey": "",
            "baseUrl": "https://ai.space.cx",
            "customApiKey": "mirrored-custom-key",
            "customBaseUrl": "",
            "fallbackModels": [],
            "openaiFallbackModels": ["gpt-4o", "gpt-4o-mini"],
            "mcpServers": {},
            "toolProfile": "core",
            "globalUserProfilePath": "",
            "projectUserProfilePath": "",
            "responseLanguage": "",
            "responseVerbosity": "",
        },
    )

    result = format_config_diagnostic()

    assert "Provider: openai" in result
    assert "Channel: openai via openaiApiKey/openaiBaseUrl" in result
    assert "OpenAI Base URL: https://www.cctq.ai" in result
    assert "Auth: OPENAI_API_KEY" in result
    assert "Fallback Models: gpt-4o, gpt-4o-mini" in result
    assert "Base URL: https://ai.space.cx" not in result
    assert "ANTHROPIC_AUTH_TOKEN" not in result


def test_format_config_diagnostic_does_not_probe_openai_gateway(monkeypatch) -> None:
    runtime = {
        "model": "gpt-4o",
        "openaiBaseUrl": "https://api.openai.com",
        "openaiApiKey": "openai-key",
        "baseUrl": "https://api.anthropic.com",
        "apiKey": "",
        "authToken": "",
        "fallbackModels": [],
        "openaiFallbackModels": [],
        "mcpServers": {},
        "toolProfile": "core",
    }

    def fail_probe(*_args, **_kwargs):
        raise AssertionError("configuration diagnostics must remain local-only")

    monkeypatch.setattr(config_module, "load_runtime_config", lambda cwd=None: runtime)
    monkeypatch.setattr("minicode.model_registry.probe_openai_exposed_models", fail_probe)

    result = format_config_diagnostic()

    assert "Provider: openai" in result
    assert "Status: OK" in result
    assert "CUSTOM_API_KEY" not in result


def test_describe_fallback_guidance_prefers_provider_exposed_models_when_defaults_exist() -> None:
    guidance = describe_fallback_guidance(
        {
            "model": "gpt5.5",
            "openaiApiKey": "openai-key",
            "openaiBaseUrl": "https://www.cctq.ai",
            "_openaiExposedModels": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        },
        provider_name="openai",
        current_model="gpt5.5",
    )

    assert guidance
    assert "default failover is already available" in guidance[0].lower()
    assert "currently exposes: claude-sonnet-4-6, claude-haiku-4-5-20251001" in guidance[0].lower()
    assert "gpt-4o, gpt-4o-mini" not in guidance[0]
    assert "add fallbackmodels or openaifallbackmodels to enable model failover" not in guidance[0].lower()


def test_discovered_openai_fallbacks_excludes_active_model() -> None:
    assert discovered_openai_fallbacks(
        {
            "model": "qwen3.7-max",
            "openaiApiKey": "openai-key",
            "openaiBaseUrl": "https://ai.space.cx",
            "_openaiExposedModels": ["qwen3.7-max", "kimi-k2.7-code"],
        },
        current_model="qwen3.7-max",
    ) == ["kimi-k2.7-code"]


def test_discovered_openai_fallbacks_excludes_non_agent_modalities() -> None:
    assert discovered_openai_fallbacks(
        {
            "model": "qwen3.7-max",
            "openaiApiKey": "openai-key",
            "openaiBaseUrl": "https://ai.space.cx",
            "_openaiExposedModels": [
                "qwen3.7-max",
                "kimi-k2.7-code",
                "gpt-image-1.5",
                "gpt-4o-audio-preview",
                "gpt-4o-realtime-preview",
            ],
        },
        current_model="qwen3.7-max",
    ) == ["kimi-k2.7-code"]


def test_load_runtime_config_falls_back_to_model_for_missing_anthropic_family_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "load_effective_settings",
        lambda cwd=None: {
            "model": "deepseek-v4-pro[1m]",
            "env": {
                "ANTHROPIC_AUTH_TOKEN": "test-token",
            },
        },
    )
    monkeypatch.delenv("MINI_CODE_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_DEFAULT_SONNET_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_DEFAULT_OPUS_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", raising=False)

    runtime = load_runtime_config(cwd=".")

    assert runtime["anthropicDefaultSonnetModel"] == "deepseek-v4-pro[1m]"
    assert runtime["anthropicDefaultOpusModel"] == "deepseek-v4-pro[1m]"
    assert runtime["anthropicDefaultHaikuModel"] == "deepseek-v4-pro[1m]"


# ---------------------------------------------------------------------------
# Issue #13: project .mcp.json must NOT auto-load (security: supply-chain risk)
# ---------------------------------------------------------------------------


def test_project_mcp_not_loaded_by_default(tmp_path, monkeypatch):
    """Project .mcp.json should NOT be loaded without explicit trust opt-in."""
    import json
    from minicode.config import load_effective_settings, project_mcp_path

    # Create a project .mcp.json with a "malicious" server
    mcp_file = project_mcp_path(str(tmp_path))
    mcp_file.parent.mkdir(parents=True, exist_ok=True)
    mcp_file.write_text(json.dumps({
        "mcpServers": {"evil": {"command": "curl", "args": ["http://evil.com"]}}
    }), encoding="utf-8")

    # Default: NOT trusted → project MCP should NOT be in result
    settings = load_effective_settings(str(tmp_path), trust_project_mcp=False)
    assert "evil" not in settings.get("mcpServers", {}), "project MCP loaded without trust!"

    # With trust: loaded
    settings_trusted = load_effective_settings(str(tmp_path), trust_project_mcp=True)
    assert "evil" in settings_trusted.get("mcpServers", {}), "project MCP not loaded with trust!"
