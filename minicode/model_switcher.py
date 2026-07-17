"""Model Switcher for dynamic model changes at runtime.

Handles the lifecycle of switching between LLM models during a session,
including adapter recreation, context preservation, and state updates.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from minicode.config import configured_model_fallbacks, default_model_fallbacks
from minicode.logging_config import get_logger
from minicode.model_registry import (
    ModelSelectionController,
    ModelSelectionSignal,
    BUILTIN_MODELS,
    build_provider_config,
    create_model_adapter,
    detect_provider,
    list_available_models,
    list_openai_exposed_models,
    model_id_supports_agent_tools,
    probe_openai_exposed_models,
    resolve_model_info,
)

logger = get_logger("model_switcher")


_ANTHROPIC_RUNTIME_FAMILY_DEFAULTS = {
    "claude-sonnet-4-20250514": "anthropicDefaultSonnetModel",
    "claude-opus-4-20250514": "anthropicDefaultOpusModel",
    "claude-haiku-3-20240307": "anthropicDefaultHaikuModel",
}


@dataclass
class SwitchResult:
    """Result of a model switch operation."""
    success: bool
    old_model: str
    new_model: str
    old_provider: str
    new_provider: str
    reason: str
    adapter: Any | None = None
    errors: list[str] = field(default_factory=list)

    def to_log(self) -> str:
        status = "OK" if self.success else "FAILED"
        msg = f"Switch [{status}]: {self.old_model} ({self.old_provider}) -> {self.new_model} ({self.new_provider})"
        if self.errors:
            msg += f" Errors: {'; '.join(self.errors)}"
        return msg


class ModelSwitcher:
    """Manages runtime model switching with adapter lifecycle."""

    def __init__(
        self,
        current_model: str,
        current_runtime: dict[str, Any],
        current_tools: Any,
        available_models: dict[str, Any] | None = None,
    ):
        self._current_model = current_model
        self._runtime = current_runtime
        self._tools = current_tools
        self._available_models = available_models or BUILTIN_MODELS
        inferred_default_model = ""
        try:
            if (
                detect_provider_name(current_model, current_runtime) == "anthropic"
                and current_model
                and not current_model.startswith("claude-")
            ):
                inferred_default_model = current_model
        except Exception:
            inferred_default_model = ""
        self._runtime_family_defaults = {
            key: str((current_runtime or {}).get(key, "") or inferred_default_model).strip()
            for key in _ANTHROPIC_RUNTIME_FAMILY_DEFAULTS.values()
        }
        self._switch_history: list[SwitchResult] = []
        self._current_adapter: Any = None
        self._failed_models: set[str] = set()

    @property
    def current_model(self) -> str:
        return self._current_model

    @property
    def switch_count(self) -> int:
        return len(self._switch_history)

    def sync_current_model(self, model_name: str | None, adapter: Any | None = None) -> None:
        """Synchronize switcher state with the active runtime model."""
        normalized = (model_name or "").strip()
        if normalized:
            self._current_model = normalized
            self._runtime["model"] = normalized
            self._maybe_seed_runtime_family_defaults(normalized)
        if adapter is not None:
            self._current_adapter = adapter

    def record_runtime_failure(self, model_name: str | None = None) -> None:
        """Mark a model as failed for the current runtime fallback window."""
        normalized = (model_name or self._current_model or "").strip()
        if normalized:
            self._failed_models.add(normalized)

    def clear_runtime_failures(self) -> None:
        """Clear transient runtime failures after a successful model response."""
        self._failed_models.clear()

    def switch_to(self, target_model: str, reason: str = "user_request") -> SwitchResult:
        """Switch to a new model."""
        if not target_model:
            return self.switch_to_fallback(reason=reason)

        if target_model == self._current_model:
            return SwitchResult(
                success=False,
                old_model=self._current_model,
                new_model=target_model,
                old_provider=detect_provider_name(self._current_model, self._runtime),
                new_provider=detect_provider_name(target_model, self._runtime),
                reason=reason,
                errors=["Target model is already active"],
            )

        old_model = self._current_model
        old_provider = detect_provider_name(old_model, self._runtime)
        new_provider = detect_provider_name(target_model, self._runtime)

        try:
            new_adapter = create_model_adapter(
                model=target_model,
                tools=self._tools,
                runtime=self._runtime,
            )

            self._current_model = target_model
            self._current_adapter = new_adapter
            self._runtime["model"] = target_model

            result = SwitchResult(
                success=True,
                old_model=old_model,
                new_model=target_model,
                old_provider=old_provider,
                new_provider=new_provider,
                reason=reason,
                adapter=new_adapter,
            )

            self._switch_history.append(result)
            logger.info(result.to_log())
            return result

        except Exception as e:
            result = SwitchResult(
                success=False,
                old_model=old_model,
                new_model=target_model,
                old_provider=old_provider,
                new_provider=new_provider,
                reason=reason,
                errors=[str(e)],
            )
            self._switch_history.append(result)
            logger.error("Model switch failed: %s", result.to_log())
            return result

    def switch_to_fallback(self, reason: str = "fallback") -> SwitchResult:
        """Switch to the first viable fallback candidate."""
        old_model = self._current_model
        old_provider = detect_provider_name(old_model, self._runtime)
        errors: list[str] = []
        candidates = self._fallback_candidates()

        logger.debug(
            "Fallback resolution: current=%s failed=%s snapshot_defaults=%s live_defaults=%s candidates=%s",
            self._current_model,
            sorted(self._failed_models),
            self._runtime_family_defaults,
            {
                key: str(self._runtime.get(key, "") or "").strip()
                for key in _ANTHROPIC_RUNTIME_FAMILY_DEFAULTS.values()
            },
            candidates,
        )

        for candidate in candidates:
            result = self.switch_to(candidate, reason=reason)
            if result.success:
                return result
            if result.errors:
                errors.extend(result.errors)

        result = SwitchResult(
            success=False,
            old_model=old_model,
            new_model="",
            old_provider=old_provider,
            new_provider="unknown",
            reason=reason,
            errors=errors or ["No viable fallback models were available"],
        )
        self._switch_history.append(result)
        logger.error("Model fallback failed: %s", result.to_log())
        return result

    def _fallback_candidates(self) -> list[str]:
        current_provider = detect_provider_name(self._current_model, self._runtime)
        provider_env = f"{current_provider.upper()}_MODEL_FALLBACKS"
        explicit_candidates: list[str] = []
        candidates: list[str] = []
        bounded_family_fallbacks = False

        runtime_candidates = configured_model_fallbacks(self._runtime, current_provider)
        explicit_candidates.extend(runtime_candidates)
        candidates.extend(runtime_candidates)
        candidates.extend(
            default_model_fallbacks(
                self._runtime,
                current_provider,
                current_model=self._current_model,
            )
        )
        if current_provider == "openai" and self._uses_custom_openai_compatible_host():
            candidates.extend(
                model
                for model in probe_openai_exposed_models(self._runtime)
                if model_id_supports_agent_tools(model)
            )

        for env_var in ("MINI_CODE_MODEL_FALLBACKS", provider_env):
            parsed = _parse_model_list(os.environ.get(env_var, ""))
            explicit_candidates.extend(parsed)
            candidates.extend(parsed)

        bounded_family_fallbacks = self._should_bound_provider_family_fallbacks(explicit_candidates)
        if not bounded_family_fallbacks:
            current_info = resolve_model_info(self._current_model)
            candidates.extend(
                info.name
                for info in list_available_models(current_info.provider)
            )

        if not bounded_family_fallbacks:
            try:
                decision = ModelSelectionController().decide(
                    ModelSelectionSignal(
                        task_complexity=str(self._runtime.get("taskComplexity", "moderate") or "moderate"),
                        budget_pressure=float(self._runtime.get("budgetPressure", 0.0) or 0.0),
                        latency_pressure=float(self._runtime.get("latencyPressure", 0.0) or 0.0),
                        recent_failures=int(self._runtime.get("recentFailures", 0) or 0),
                        current_model=self._current_model,
                    )
                )
                if decision.fallback_model:
                    candidates.append(decision.fallback_model)
                candidates.append(decision.model)
            except Exception:
                pass

        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in candidates:
            if candidate in explicit_candidates:
                normalized = candidate.strip()
            else:
                normalized = self._resolve_runtime_model_override(candidate)
            if (
                not normalized
                or normalized == self._current_model
                or normalized in self._failed_models
                or normalized in seen
                or not self._can_attempt_model(normalized)
            ):
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _should_bound_provider_family_fallbacks(self, explicit_candidates: list[str]) -> bool:
        try:
            current_provider = detect_provider_name(self._current_model, self._runtime)
        except Exception:
            return False
        if current_provider == "anthropic":
            if not self._current_model or self._current_model.startswith("claude-"):
                return False
            if explicit_candidates:
                return True
            return any(self._runtime_family_defaults.values())
        if current_provider == "openai":
            return self._uses_custom_openai_compatible_host()
        return False

    def _uses_custom_openai_compatible_host(self) -> bool:
        if detect_provider_name(self._current_model, self._runtime) != "openai":
            return False
        try:
            provider_config = build_provider_config(self._current_model, self._runtime)
        except Exception:
            return False
        base_url = str(
            getattr(provider_config, "base_url", "")
            or getattr(provider_config, "api_base_url", "")
            or ""
        ).strip()
        if not base_url:
            return False
        normalized = _normalize_openai_base_url(base_url)
        return normalized not in {
            "https://api.openai.com",
            "https://api.openai.com/v1",
        }

    def _resolve_runtime_model_override(self, candidate: str) -> str:
        normalized = candidate.strip()
        if not normalized:
            return ""
        override_key = _ANTHROPIC_RUNTIME_FAMILY_DEFAULTS.get(normalized)
        if not override_key:
            return normalized
        override_model = self._runtime_family_defaults.get(override_key, "")
        if not override_model:
            override_model = str(self._runtime.get(override_key, "") or "").strip()
        return override_model or normalized

    def _maybe_seed_runtime_family_defaults(self, model_name: str) -> None:
        try:
            if detect_provider_name(model_name, self._runtime) != "anthropic" or model_name.startswith("claude-"):
                return
        except Exception:
            return
        if any(self._runtime_family_defaults.values()):
            return
        for key in _ANTHROPIC_RUNTIME_FAMILY_DEFAULTS.values():
            self._runtime_family_defaults[key] = model_name

    def _can_attempt_model(self, model_name: str) -> bool:
        if not model_id_supports_agent_tools(model_name):
            return False
        try:
            provider_config = build_provider_config(model_name, self._runtime)
        except Exception:
            return False
        if self._uses_custom_openai_compatible_host():
            exposed = list_openai_exposed_models(self._runtime)
            exposed_set = set(exposed)
            if exposed_set and model_name not in exposed_set:
                return False
        return bool(provider_config.api_key)

    def get_switch_history(self) -> list[dict[str, Any]]:
        """Get human-readable switch history."""
        return [
            {
                "old": s.old_model,
                "new": s.new_model,
                "reason": s.reason,
                "success": s.success,
                "errors": s.errors,
            }
            for s in self._switch_history
        ]

    def get_current_adapter(self) -> Any | None:
        """Get the current model adapter."""
        return self._current_adapter


def detect_provider_name(model: str, runtime: dict[str, Any] | None = None) -> str:
    """Get provider name string for a model.

    Uses the lightweight ``detect_provider`` helper so that runtime-aware
    routing (e.g. custom OpenAI-compatible hosts) is respected without having
    to construct a full provider config just to read a name. This also keeps
    the function compatible with test doubles that only stub part of the
    provider config surface.
    """
    provider = detect_provider(model, runtime)
    return provider.value


def _parse_model_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _normalize_openai_base_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = (parsed.path or "").rstrip("/")
    if path == "/v1/messages":
        path = "/v1"
    return f"{scheme}://{netloc}{path}"
