"""Unified model registry and routing for MiniCode.

Supports multiple LLM providers with a single configuration system:
- Anthropic (Claude) — native Messages API
- OpenAI (GPT) — Chat Completions API
- OpenRouter — unified gateway to 200+ models
- Custom OpenAI-compatible endpoints (vLLM, Ollama, LiteLLM, etc.)

Design inspired by Hermes Agent's provider/model abstraction.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any



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


class ReasoningEffort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


@dataclass
class ModelSelectionSignal:
    """Observed state for cybernetic model selection."""

    task_complexity: str = "moderate"
    budget_pressure: float = 0.0
    latency_pressure: float = 0.0
    recent_failures: int = 0
    requires_tools: bool = True
    requires_long_context: bool = False
    current_model: str = ""


@dataclass
class ModelSelectionDecision:
    """Controller output for model/routing recommendation."""

    model: str
    provider: Provider
    reasoning_effort: ReasoningEffort
    score: float
    reasons: list[str] = field(default_factory=list)
    fallback_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider.value,
            "reasoning_effort": self.reasoning_effort.value,
            "score": round(self.score, 3),
            "reasons": list(self.reasons),
            "fallback_model": self.fallback_model,
        }


class ModelSelectionController:
    """Risk/cost adaptive model recommendation controller."""

    def decide(self, signal: ModelSelectionSignal) -> ModelSelectionDecision:
        candidates = [
            info for info in list_available_models()
            if info.supports_tools or not signal.requires_tools
        ]
        if not candidates:
            info = resolve_model_info(signal.current_model or "claude-sonnet-4-20250514")
            return ModelSelectionDecision(
                model=info.name,
                provider=info.provider,
                reasoning_effort=ReasoningEffort.MEDIUM,
                score=0.0,
                reasons=["no compatible candidates"],
            )

        reasons: list[str] = []
        complexity = signal.task_complexity.lower()
        target_power = {"simple": 0.25, "moderate": 0.55, "complex": 0.85}.get(complexity, 0.55)
        if signal.recent_failures > 0:
            target_power = min(1.0, target_power + 0.10 * signal.recent_failures)
            reasons.append(f"recent failures: {signal.recent_failures}")
        if signal.requires_long_context:
            target_power = min(1.0, target_power + 0.10)
            reasons.append("long context required")
        if signal.budget_pressure >= 0.70:
            target_power = max(0.20, target_power - 0.25)
            reasons.append("high budget pressure")
        elif signal.budget_pressure <= 0.20 and complexity == "complex":
            target_power = min(1.0, target_power + 0.10)
            reasons.append("budget allows stronger model")
        if signal.latency_pressure >= 0.70:
            target_power = max(0.20, target_power - 0.15)
            reasons.append("high latency pressure")

        scored: list[tuple[float, ModelInfo, list[str]]] = []
        for info in candidates:
            power = self._model_power(info)
            cost = self._model_cost(info)
            latency = self._latency_proxy(info)
            context_fit = 1.0 if not signal.requires_long_context else min(1.0, info.context_window / 200_000)

            score = 1.0 - abs(power - target_power)
            score -= signal.budget_pressure * cost * 0.45
            score -= signal.latency_pressure * latency * 0.30
            score += context_fit * 0.15
            if signal.current_model and info.name == resolve_model_info(signal.current_model).name:
                score += 0.05
            if signal.requires_tools and not info.supports_tools:
                score -= 1.0

            candidate_reasons = [
                f"power={power:.2f}",
                f"cost={cost:.2f}",
                f"context={info.context_window // 1000}K",
            ]
            scored.append((score, info, candidate_reasons))

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best, candidate_reasons = scored[0]
        fallback = scored[1][1].name if len(scored) > 1 else None
        effort = self._reasoning_effort(target_power, signal)
        return ModelSelectionDecision(
            model=best.name,
            provider=best.provider,
            reasoning_effort=effort,
            score=max(0.0, best_score),
            reasons=reasons + candidate_reasons,
            fallback_model=fallback,
        )

    def _model_power(self, info: ModelInfo) -> float:
        name = info.name.lower()
        if "opus" in name or name == "o1" or "gemini-2.5-pro" in name:
            return 0.95
        if "sonnet" in name or "gpt-4o" in name or "o3" in name or "r1" in name:
            return 0.75
        if "mini" in name or "haiku" in name or "flash" in name or "deepseek-chat" in name:
            return 0.35
        return 0.55

    def _model_cost(self, info: ModelInfo) -> float:
        blended = (info.pricing_input + info.pricing_output) / 2
        return min(1.0, blended / 45.0)

    def _latency_proxy(self, info: ModelInfo) -> float:
        power = self._model_power(info)
        return min(1.0, 0.25 + power * 0.65)

    def _reasoning_effort(
        self,
        target_power: float,
        signal: ModelSelectionSignal,
    ) -> ReasoningEffort:
        if signal.budget_pressure >= 0.80 or signal.latency_pressure >= 0.85:
            return ReasoningEffort.LOW
        if target_power >= 0.90:
            return ReasoningEffort.XHIGH
        if target_power >= 0.75:
            return ReasoningEffort.HIGH
        if target_power >= 0.45:
            return ReasoningEffort.MEDIUM
        return ReasoningEffort.LOW


# ---------------------------------------------------------------------------
# Built-in model catalog
# ---------------------------------------------------------------------------

BUILTIN_MODELS: dict[str, ModelInfo] = {}
_OPENAI_EXPOSED_MODELS_CACHE: dict[tuple[str, str], tuple[str, ...]] = {}

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


def _normalize_openai_base_url(raw: str) -> str:
    value = str(raw or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/chat/completions"):
        return value[: -len("/chat/completions")]
    return value


def _openai_models_endpoint(base_url: str) -> str:
    normalized = _normalize_openai_base_url(base_url)
    if normalized.endswith("/v1"):
        return f"{normalized}/models"
    return f"{normalized}/v1/models"


def _coerce_model_id_list(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",")]
    if not isinstance(raw, (list, tuple, set)):
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        model_id = str(item or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        normalized.append(model_id)
    return tuple(normalized)


def _extract_model_ids(payload: Any) -> tuple[str, ...]:
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("data", [])
    if not isinstance(rows, list):
        return ()
    return _coerce_model_id_list([
        item.get("id")
        for item in rows
        if isinstance(item, dict)
    ])


def list_openai_exposed_models(
    runtime: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    runtime = runtime or {}
    preset = _coerce_model_id_list(
        runtime.get("_openaiExposedModels") or runtime.get("openaiExposedModels")
    )
    if preset:
        return preset

    base_url = (
        runtime.get("openaiBaseUrl", "")
        or os.environ.get("OPENAI_BASE_URL", "")
        or os.environ.get("OPENAI_API_BASE", "")
    )
    api_key = runtime.get("openaiApiKey", "") or os.environ.get("OPENAI_API_KEY", "")
    if not base_url or not api_key:
        return ()

    endpoint = _openai_models_endpoint(base_url)
    cache_key = (endpoint, api_key)
    if cache_key in _OPENAI_EXPOSED_MODELS_CACHE:
        models = _OPENAI_EXPOSED_MODELS_CACHE[cache_key]
        if models:
            runtime["_openaiExposedModels"] = list(models)
        return models

    return ()


def probe_openai_exposed_models(
    runtime: dict[str, Any] | None = None,
    *,
    refresh: bool = False,
) -> tuple[str, ...]:
    runtime = runtime or {}
    preset = list_openai_exposed_models(runtime)
    if preset and not refresh:
        return preset

    base_url = (
        runtime.get("openaiBaseUrl", "")
        or os.environ.get("OPENAI_BASE_URL", "")
        or os.environ.get("OPENAI_API_BASE", "")
    )
    api_key = runtime.get("openaiApiKey", "") or os.environ.get("OPENAI_API_KEY", "")
    if not base_url or not api_key:
        return preset

    try:
        req = urllib.request.Request(
            _openai_models_endpoint(base_url),
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read()
        models = _extract_model_ids(json.loads(payload))
    except (urllib.error.URLError, OSError, ValueError):
        return preset
    except Exception:
        return preset

    cache_key = (_openai_models_endpoint(base_url), api_key)
    _OPENAI_EXPOSED_MODELS_CACHE[cache_key] = models
    if models:
        runtime["_openaiExposedModels"] = list(models)
    return models


def model_is_exposed_via_openai_runtime(
    model: str,
    runtime: dict[str, Any] | None = None,
    *,
    probe_openai_models: bool = True,
) -> bool:
    model_id = str(model or "").strip()
    if not model_id:
        return False
    exposed = list_openai_exposed_models(runtime)
    if not exposed and probe_openai_models:
        exposed = probe_openai_exposed_models(runtime)
    if not exposed:
        return False
    return model_id in set(exposed)


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
_register(ModelInfo("gpt-5.5", Provider.OPENAI,
    context_window=128_000, max_output_tokens=16_384,
    pricing_input=3.0, pricing_output=15.0))
_register(ModelInfo("gpt5.5", Provider.OPENAI,
    context_window=128_000, max_output_tokens=16_384,
    pricing_input=3.0, pricing_output=15.0))
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
_register(ModelInfo("deepseek-v4-pro[1m]", Provider.ANTHROPIC,
    display_name="DeepSeek V4 Pro",
    context_window=128_000, max_output_tokens=8_192,
    pricing_input=0.10, pricing_output=0.40))
_register(ModelInfo("qwen/qwen3-235b-a22b", Provider.OPENROUTER,
    context_window=128_000, max_output_tokens=8_192,
    pricing_input=0.22, pricing_output=0.88))
_register(ModelInfo("minimax/minimax-m1", Provider.OPENROUTER,
    context_window=1_000_000, max_output_tokens=8_192,
    pricing_input=0.20, pricing_output=0.80))


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def detect_provider(
    model: str,
    runtime: dict[str, Any] | None = None,
    *,
    probe_openai_models: bool = True,
) -> Provider:
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

    if runtime and model_is_exposed_via_openai_runtime(
        model,
        runtime,
        probe_openai_models=probe_openai_models,
    ):
        return Provider.OPENAI

    if runtime and not probe_openai_models:
        # Readiness and diagnostics must remain local-only.  When the model is
        # known, its catalog provider is authoritative; for an unknown model,
        # use an explicitly configured OpenAI-compatible channel only when no
        # Anthropic credentials indicate a competing primary channel.
        normalized_model = model.casefold()
        for model_name, model_info in BUILTIN_MODELS.items():
            if model_name.casefold() == normalized_model:
                return model_info.provider
        has_openai_channel = bool(
            runtime.get("openaiApiKey")
            and runtime.get("openaiBaseUrl")
        )
        has_anthropic_channel = bool(
            runtime.get("apiKey") or runtime.get("authToken")
        )
        if has_openai_channel and not has_anthropic_channel:
            return Provider.OPENAI

    # 2. DeepSeek direct API detection
    if model_lower.startswith("deepseek") or "deepseek" in model_lower:
        if os.environ.get("DEEPSEEK_API_KEY"):
            return Provider.CUSTOM
        # If registered as CUSTOM in BUILTIN_MODELS, use that
        if model in BUILTIN_MODELS and BUILTIN_MODELS[model].provider == Provider.CUSTOM:
            return Provider.CUSTOM

    # 3. OpenAI detection
    openai_prefixes = ("gpt-5", "gpt-4", "gpt-3.5", "gpt5", "o1-", "o3-", "chatgpt-")
    openai_exact = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-5.5", "gpt5.5", "o1", "o1-mini", "o3-mini"}
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


_NON_AGENT_MODEL_MARKERS = (
    "audio",
    "embedding",
    "image",
    "moderation",
    "realtime",
    "rerank",
    "transcrib",
    "tts",
    "whisper",
)


def model_id_supports_agent_tools(model: str) -> bool:
    """Conservatively identify model IDs suitable for MiniCode tool calls.

    OpenAI-compatible ``/v1/models`` responses generally expose IDs without
    capability metadata.  Known catalog entries still use their declared
    ``supports_tools`` value; unknown IDs are filtered only when their name
    clearly identifies a non-chat modality.
    """
    normalized = str(model or "").strip().casefold()
    if not normalized:
        return False

    for model_name, info in BUILTIN_MODELS.items():
        if model_name.casefold() == normalized:
            return info.supports_tools

    compact = re.sub(r"[^a-z0-9]+", "-", normalized)
    return not any(marker in compact for marker in _NON_AGENT_MODEL_MARKERS)


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


def build_provider_config(model: str, runtime: dict[str, Any] | None = None) -> ProviderConfig:
    """Build provider configuration from model name and runtime config.

    This centralizes all the provider-specific URL/key/header logic that was
    previously scattered across main.py, headless.py, gateway.py, etc.
    """
    runtime = runtime or {}
    provider = detect_provider(model, runtime)
    resolve_model_info(model, provider)

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
            runtime.get("openaiBaseUrl", "")
            or os.environ.get("OPENAI_BASE_URL", "")
            or os.environ.get("OPENAI_API_BASE", "")
            or "https://api.openai.com"
        ).rstrip("/")
        api_key = runtime.get("openaiApiKey", "") or os.environ.get("OPENAI_API_KEY", "")
        return ProviderConfig(
            provider=Provider.OPENAI,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )

    if provider == Provider.CUSTOM:
        # Check for DeepSeek-specific env vars first
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
        base_url = (
            os.environ.get("CUSTOM_API_BASE_URL", "")
            or (deepseek_key and "https://api.deepseek.com/v1" or "")
            or runtime.get("customBaseUrl", "")
        ).rstrip("/")
        api_key = (
            os.environ.get("CUSTOM_API_KEY", "")
            or deepseek_key
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
    runtime: dict[str, Any] | None = None,
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
    enriched = dict(runtime or {})
    enriched["model"] = provider_config.model
    if "baseUrl" not in enriched:
        enriched["baseUrl"] = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    if "authToken" not in enriched and "apiKey" not in enriched:
        token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        if token:
            enriched["authToken"] = token
    # Disable extended thinking for non-standard Anthropic endpoints (DeepSeek etc.)
    if "api.anthropic.com" not in enriched.get("baseUrl", ""):
        enriched["disableThinking"] = True
    return AnthropicModelAdapter(enriched, tools)


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


def format_model_status(model: str, runtime: dict[str, Any] | None = None) -> str:
    """Format current model status."""
    provider = detect_provider(model, runtime)
    info = resolve_model_info(model, provider)
    pconfig = build_provider_config(model, runtime)
    recommendation = ModelSelectionController().decide(
        ModelSelectionSignal(
            task_complexity="moderate",
            budget_pressure=float((runtime or {}).get("budgetPressure", 0.0) or 0.0),
            latency_pressure=float((runtime or {}).get("latencyPressure", 0.0) or 0.0),
            recent_failures=int((runtime or {}).get("recentFailures", 0) or 0),
            requires_tools=True,
            current_model=model,
        )
    )

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
        "",
        "Cybernetic Recommendation",
        f"  Model:    {recommendation.model}",
        f"  Effort:   {recommendation.reasoning_effort.value}",
        f"  Score:    {recommendation.score:.2f}",
        f"  Reasons:  {', '.join(recommendation.reasons[:4])}",
    ]
    return "\n".join(lines)
