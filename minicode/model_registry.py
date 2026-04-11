"""Unified model registry and routing for MiniCode.

Supports multiple LLM providers with a single configuration system:
- Anthropic (Claude) — native Messages API
- OpenAI (GPT) — Chat Completions API
- OpenRouter — unified gateway to 200+ models
- Custom OpenAI-compatible endpoints (vLLM, Ollama, LiteLLM, etc.)

Design inspired by Hermes Agent's provider/model abstraction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from minicode.types import AgentStep


# ---------------------------------------------------------------------------
# Provider types
# ---------------------------------------------------------------------------

class Provider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    CUSTOM = "custom"
    MOCK = "mock"


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------

@dataclass
class ModelInfo:
    """Static metadata about a model."""
    name: str                          # Canonical model ID
    provider: Provider                 # Which provider to use
    display_name: str = ""             # Human-readable name
    context_window: int = 128_000      # Token limit
    max_output_tokens: int | None = None
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_vision: bool = False
    pricing_input: float = 3.0        # USD per 1M input tokens
    pricing_output: float = 15.0      # USD per 1M output tokens

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name


# ---------------------------------------------------------------------------
# Built-in model catalog
# ---------------------------------------------------------------------------

BUILTIN_MODELS: dict[str, ModelInfo] = {}

def _register(info: ModelInfo) -> None:
    BUILTIN_MODELS[info.name] = info
    # Also register under common aliases
    for alias in _aliases(info.name):
        if alias not in BUILTIN_MODELS:
            BUILTIN_MODELS[alias] = info


def _aliases(name: str) -> list[str]:
    """Generate common aliases for a model name."""
    result: list[str] = []
    # e.g. "claude-sonnet-4-20250514" -> "claude-sonnet-4", "sonnet-4"
    parts = name.split("-")
    if "claude" in parts:
        idx = parts.index("claude")
        family = "-".join(parts[idx:idx + 2])  # claude-sonnet-4
        if family != name:
            result.append(family)
    if "gpt" in parts:
        idx = parts.index("gpt")
        family = "-".join(parts[idx:idx + 2])  # gpt-4o
        if family != name:
            result.append(family)
    return result


# --- Anthropic models ---
_register(ModelInfo("claude-sonnet-4-20250514", Provider.ANTHROPIC,
    context_window=200_000, max_output_tokens=16_384,
    pricing_input=3.0, pricing_output=15.0))
_register(ModelInfo("claude-opus-4-20250514", Provider.ANTHROPIC,
    context_window=200_000, max_output_tokens=16_384,
    pricing_input=15.0, pricing_output=75.0))
_register(ModelInfo("claude-haiku-3-20240307", Provider.ANTHROPIC,
    context_window=100_000, max_output_tokens=4_096,
    pricing_input=0.25, pricing_output=1.25))

# --- OpenAI models ---
_register(ModelInfo("gpt-4o", Provider.OPENAI,
    context_window=128_000, max_output_tokens=16_384,
    pricing_input=2.50, pricing_output=10.0))
_register(ModelInfo("gpt-4o-mini", Provider.OPENAI,
    context_window=128_000, max_output_tokens=16_384,
    pricing_input=0.15, pricing_output=0.60))
_register(ModelInfo("gpt-4-turbo", Provider.OPENAI,
    context_window=128_000, max_output_tokens=4_096,
    pricing_input=10.0, pricing_output=30.0))
_register(ModelInfo("o1", Provider.OPENAI,
    context_window=200_000, max_output_tokens=100_000,
    pricing_input=15.0, pricing_output=60.0, supports_tools=False))
_register(ModelInfo("o1-mini", Provider.OPENAI,
    context_window=128_000, max_output_tokens=65_536,
    pricing_input=3.0, pricing_output=12.0, supports_tools=False))
_register(ModelInfo("o3-mini", Provider.OPENAI,
    context_window=200_000, max_output_tokens=100_000,
    pricing_input=1.10, pricing_output=4.40))

# --- OpenRouter popular models ---
_register(ModelInfo("openrouter/auto", Provider.OPENROUTER,
    display_name="OpenRouter Auto", context_window=200_000,
    pricing_input=3.0, pricing_output=15.0))
_register(ModelInfo("anthropic/claude-sonnet-4", Provider.OPENROUTER,
    context_window=200_000, max_output_tokens=16_384,
    pricing_input=3.0, pricing_output=15.0))
_register(ModelInfo("anthropic/claude-opus-4", Provider.OPENROUTER,
    context_window=200_000, max_output_tokens=16_384,
    pricing_input=15.0, pricing_output=75.0))
_register(ModelInfo("openai/gpt-4o", Provider.OPENROUTER,
    context_window=128_000, max_output_tokens=16_384,
    pricing_input=2.50, pricing_output=10.0))
_register(ModelInfo("openai/gpt-4o-mini", Provider.OPENROUTER,
    context_window=128_000, max_output_tokens=16_384,
    pricing_input=0.15, pricing_output=0.60))
_register(ModelInfo("google/gemini-2.5-pro", Provider.OPENROUTER,
    context_window=1_000_000, max_output_tokens=8_192,
    pricing_input=1.25, pricing_output=10.0, supports_vision=True))
_register(ModelInfo("google/gemini-2.5-flash", Provider.OPENROUTER,
    context_window=1_000_000, max_output_tokens=8_192,
    pricing_input=0.15, pricing_output=0.60, supports_vision=True))
_register(ModelInfo("meta-llama/llama-4-maverick", Provider.OPENROUTER,
    context_window=1_000_000, max_output_tokens=8_192,
    pricing_input=0.20, pricing_output=0.60))
_register(ModelInfo("deepseek/deepseek-r1", Provider.OPENROUTER,
    context_window=128_000, max_output_tokens=8_192,
    pricing_input=0.55, pricing_output=2.19))
_register(ModelInfo("deepseek/deepseek-chat", Provider.OPENROUTER,
    context_window=128_000, max_output_tokens=8_192,
    pricing_input=0.14, pricing_output=0.28))
_register(ModelInfo("qwen/qwen3-235b-a22b", Provider.OPENROUTER,
    context_window=128_000, max_output_tokens=8_192,
    pricing_input=0.22, pricing_output=0.88))
_register(ModelInfo("minimax/minimax-m1", Provider.OPENROUTER,
    context_window=1_000_000, max_output_tokens=8_192,
    pricing_input=0.20, pricing_output=0.80))


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def detect_provider(model: str, runtime: dict | None = None) -> Provider:
    """Auto-detect which provider to use based on model name and config.

    Priority:
    1. OpenRouter — if OPENROUTER_API_KEY set or model starts with "openrouter/"
    2. OpenAI — if model matches OpenAI patterns or OPENAI_API_KEY set
    3. Custom — if CUSTOM_API_BASE_URL set
    4. Anthropic — default
    """
    model_lower = model.lower()

    # 1. OpenRouter detection
    if os.environ.get("OPENROUTER_API_KEY") or model_lower.startswith("openrouter/"):
        return Provider.OPENROUTER
    # Also check provider prefix patterns like "anthropic/", "openai/", "google/"
    for prefix in ("anthropic/", "openai/", "google/", "meta-llama/", "deepseek/",
                   "qwen/", "minimax/", "mistralai/"):
        if model_lower.startswith(prefix):
            if os.environ.get("OPENROUTER_API_KEY"):
                return Provider.OPENROUTER
            # Could also be a custom endpoint with this naming
            if runtime and runtime.get("openaiBaseUrl"):
                return Provider.CUSTOM
            # Default to OpenRouter for vendor-prefixed models
            return Provider.OPENROUTER

    # 2. OpenAI detection
    openai_prefixes = ("gpt-4", "gpt-3.5", "o1-", "o3-", "chatgpt-")
    openai_exact = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini", "o3-mini"}
    if model_lower in openai_exact or any(model_lower.startswith(p) for p in openai_prefixes):
        return Provider.OPENAI
    if os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
        return Provider.OPENAI

    # 3. Custom endpoint detection
    custom_base = (
        os.environ.get("CUSTOM_API_BASE_URL", "")
        or (runtime or {}).get("customBaseUrl", "")
    )
    if custom_base:
        return Provider.CUSTOM

    # 4. Default: Anthropic
    return Provider.ANTHROPIC


def resolve_model_info(model: str, provider: Provider | None = None) -> ModelInfo:
    """Resolve a model name to ModelInfo, with fallback for unknown models."""
    # Check built-in catalog first
    if model in BUILTIN_MODELS:
        return BUILTIN_MODELS[model]

    # Try case-insensitive lookup
    for key, info in BUILTIN_MODELS.items():
        if key.lower() == model.lower():
            return info

    # Unknown model: generate a best-effort ModelInfo
    resolved_provider = provider or detect_provider(model)
    return ModelInfo(
        name=model,
        provider=resolved_provider,
        context_window=128_000,
        pricing_input=3.0,
        pricing_output=15.0,
    )


# ---------------------------------------------------------------------------
# Provider configuration builder
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """Resolved provider configuration for a model."""
    provider: Provider
    model: str
    base_url: str
    api_key: str
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_params: dict[str, Any] = field(default_factory=dict)

    @property
    def is_openai_compatible(self) -> bool:
        """Whether this provider uses OpenAI Chat Completions API format."""
        return self.provider in (Provider.OPENAI, Provider.OPENROUTER, Provider.CUSTOM)


def build_provider_config(model: str, runtime: dict | None = None) -> ProviderConfig:
    """Build provider configuration from model name and runtime config.

    This centralizes all the provider-specific URL/key/header logic that was
    previously scattered across main.py, headless.py, gateway.py, etc.
    """
    runtime = runtime or {}
    provider = detect_provider(model, runtime)
    info = resolve_model_info(model, provider)

    if provider == Provider.OPENROUTER:
        return ProviderConfig(
            provider=Provider.OPENROUTER,
            model=model,
            base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api").rstrip("/"),
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            extra_headers={
                "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", "https://github.com/minicode-py"),
                "X-Title": os.environ.get("OPENROUTER_TITLE", "MiniCode Python"),
            },
            extra_params={
                # OpenRouter supports provider-specific routing
                "transforms": os.environ.get("OPENROUTER_TRANSFORMS", "").split(",")
                if os.environ.get("OPENROUTER_TRANSFORMS") else None,
            },
        )

    if provider == Provider.OPENAI:
        base_url = (
            os.environ.get("OPENAI_BASE_URL", "")
            or os.environ.get("OPENAI_API_BASE", "")
            or runtime.get("openaiBaseUrl", "")
            or "https://api.openai.com"
        ).rstrip("/")
        api_key = os.environ.get("OPENAI_API_KEY", "") or runtime.get("openaiApiKey", "")
        return ProviderConfig(
            provider=Provider.OPENAI,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )

    if provider == Provider.CUSTOM:
        base_url = (
            os.environ.get("CUSTOM_API_BASE_URL", "")
            or runtime.get("customBaseUrl", "")
        ).rstrip("/")
        api_key = (
            os.environ.get("CUSTOM_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", "")
            or runtime.get("customApiKey", "")
        )
        return ProviderConfig(
            provider=Provider.CUSTOM,
            model=model,
            base_url=base_url,
            api_key=api_key,
            extra_headers=_parse_extra_headers("CUSTOM_API_EXTRA_HEADERS"),
        )

    # Default: Anthropic
    base_url = (
        os.environ.get("ANTHROPIC_BASE_URL", "")
        or runtime.get("baseUrl", "")
        or "https://api.anthropic.com"
    ).rstrip("/")
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY", "")
        or runtime.get("apiKey", "")
    )
    auth_token = (
        os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        or runtime.get("authToken", "")
    )
    # Anthropic uses x-api-key header, but we keep it in api_key for simplicity
    # The adapter will handle the difference
    return ProviderConfig(
        provider=Provider.ANTHROPIC,
        model=model,
        base_url=base_url,
        api_key=api_key or auth_token,
        extra_params={"auth_token": auth_token} if auth_token else {},
    )


def _parse_extra_headers(env_var: str) -> dict[str, str]:
    """Parse 'Key1:Val1,Key2:Val2' from env var into dict."""
    raw = os.environ.get(env_var, "")
    if not raw:
        return {}
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            headers[k.strip()] = v.strip()
    return headers


# ---------------------------------------------------------------------------
# Model adapter factory (centralized replacement for scattered if/elif)
# ---------------------------------------------------------------------------

def create_model_adapter(
    model: str,
    tools: Any,
    runtime: dict | None = None,
    force_mock: bool = False,
) -> Any:
    """Create the appropriate ModelAdapter for the given model.

    This replaces the duplicated model-selection logic in main.py,
    headless.py, gateway.py, etc. with a single call.

    Args:
        model: Model name (e.g., "claude-sonnet-4-20250514", "openai/gpt-4o")
        tools: Tool registry instance
        runtime: Runtime configuration dict
        force_mock: Force mock mode (for testing or no API key)

    Returns:
        A ModelAdapter instance (AnthropicModelAdapter, OpenAIModelAdapter, or MockModelAdapter)
    """
    if force_mock or os.environ.get("MINI_CODE_MODEL_MODE") == "mock":
        from minicode.mock_model import MockModelAdapter
        return MockModelAdapter()

    provider_config = build_provider_config(model, runtime)

    # OpenRouter / Custom / OpenAI all use OpenAI-compatible API
    if provider_config.is_openai_compatible:
        from minicode.openai_adapter import OpenAIModelAdapter
        # Inject provider config into runtime so the adapter can use it
        enriched_runtime = dict(runtime or {})
        enriched_runtime["model"] = provider_config.model
        if provider_config.provider == Provider.OPENROUTER:
            enriched_runtime["openaiBaseUrl"] = provider_config.base_url
            enriched_runtime["openaiApiKey"] = provider_config.api_key
            enriched_runtime["_openrouter_headers"] = provider_config.extra_headers
            enriched_runtime["_openrouter_params"] = provider_config.extra_params
        elif provider_config.provider == Provider.CUSTOM:
            enriched_runtime["openaiBaseUrl"] = provider_config.base_url
            enriched_runtime["openaiApiKey"] = provider_config.api_key
            enriched_runtime["_custom_headers"] = provider_config.extra_headers
        elif provider_config.provider == Provider.OPENAI:
            enriched_runtime["openaiBaseUrl"] = provider_config.base_url
            enriched_runtime["openaiApiKey"] = provider_config.api_key
        return OpenAIModelAdapter(enriched_runtime, tools)

    # Anthropic
    from minicode.anthropic_adapter import AnthropicModelAdapter
    return AnthropicModelAdapter(runtime or {}, tools)


# ---------------------------------------------------------------------------
# Runtime model switching
# ---------------------------------------------------------------------------

@dataclass
class ModelSwitch:
    """Result of a model switch operation."""
    success: bool
    old_model: str
    new_model: str
    provider: Provider
    message: str


def list_available_models(provider: Provider | None = None) -> list[ModelInfo]:
    """List all available models, optionally filtered by provider."""
    models = list(BUILTIN_MODELS.values())
    # Deduplicate (aliases point to same ModelInfo)
    seen: set[str] = set()
    unique: list[ModelInfo] = []
    for m in models:
        if m.name not in seen:
            seen.add(m.name)
            unique.append(m)
    if provider:
        unique = [m for m in unique if m.provider == provider]
    return sorted(unique, key=lambda m: (m.provider.value, m.pricing_input))


def format_model_list(provider: Provider | None = None) -> str:
    """Format available models as a readable table."""
    models = list_available_models(provider)
    if not models:
        return "No models available."

    lines = ["Available Models", "=" * 70, ""]

    current_provider: Provider | None = None
    for m in models:
        if m.provider != current_provider:
            current_provider = m.provider
            lines.append(f"  [{current_provider.value.upper()}]")
            lines.append(f"  {'-' * 50}")

        pricing = f"${m.pricing_input:.2f}/${m.pricing_output:.2f}"
        ctx = f"{m.context_window // 1000}K"
        tools_flag = "tools" if m.supports_tools else "no-tools"
        lines.append(f"    {m.name:<45} {pricing:<14} {ctx:<8} {tools_flag}")

    lines.append("")
    lines.append("  Pricing: input/output per 1M tokens | Context: token limit")
    lines.append("")
    lines.append("  Usage:")
    lines.append("    /model <name>          — Switch to a specific model")
    lines.append("    /model anthropic       — List Anthropic models")
    lines.append("    /model openrouter      — List OpenRouter models")
    lines.append("    /model status          — Show current model info")
    return "\n".join(lines)


def format_model_status(model: str, runtime: dict | None = None) -> str:
    """Format current model status."""
    provider = detect_provider(model, runtime)
    info = resolve_model_info(model, provider)
    pconfig = build_provider_config(model, runtime)

    lines = [
        "Current Model",
        "=" * 50,
        f"  Model:    {info.display_name}",
        f"  Provider: {info.provider.value}",
        f"  Base URL: {pconfig.base_url}",
        f"  Context:  {info.context_window:,} tokens",
        f"  Pricing:  ${info.pricing_input:.2f} / ${info.pricing_output:.2f} (in/out per 1M)",
        f"  Tools:    {'Yes' if info.supports_tools else 'No'}",
        f"  Vision:   {'Yes' if info.supports_vision else 'No'}",
        f"  API Key:  {'*' * 8}{pconfig.api_key[-4:]}" if len(pconfig.api_key) > 4 else "  API Key:  not set",
    ]
    return "\n".join(lines)
