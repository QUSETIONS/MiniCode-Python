"""Smart Routing Engine - combines router, switcher, and feedback learning.

Central orchestration layer that:
1. Routes each task to optimal model via AgentRouter
2. Switches models at runtime via ModelSwitcher  
3. Learns from task outcomes to improve future routing
"""

from __future__ import annotations

import functools
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minicode.agent_router import AgentRouter, RoutingDecision, extract_task_profile
from minicode.logging_config import get_logger
from minicode.model_registry import resolve_model_info
from minicode.model_switcher import ModelSwitcher, SwitchResult

logger = get_logger("smart_router")


@dataclass
class TaskOutcome:
    """Record of how a task performed after routing."""
    task_text: str
    assigned_model: str
    success: bool
    duration_ms: float
    cost_usd: float
    tool_errors: int
    model_switches: int
    timestamp: float = field(default_factory=time.time)
    user_satisfaction: float | None = None


class FeedbackLearner:
    """Learns from task outcomes to improve routing decisions.
    
    Uses batched async writes to avoid disk I/O on every outcome.
    """

    def __init__(self, storage_path: Path | None = None):
        self._storage = storage_path
        self._outcomes: list[TaskOutcome] = []
        self._model_performance: dict[str, dict[str, float]] = {}
        self._dirty = False
        self._save_lock = threading.Lock()
        self._batch_size = 10  # Save every N outcomes
        self._load()

    def record_outcome(self, outcome: TaskOutcome) -> None:
        """Record a task outcome for learning.
        
        Updates are batched: disk write only occurs every _batch_size records
        or when explicitly flushed.
        """
        self._outcomes.append(outcome)
        
        model = outcome.assigned_model
        if model not in self._model_performance:
            self._model_performance[model] = {
                "total_tasks": 0,
                "successful_tasks": 0,
                "total_cost": 0.0,
                "total_duration_ms": 0.0,
                "total_errors": 0,
            }
        
        perf = self._model_performance[model]
        perf["total_tasks"] += 1
        if outcome.success:
            perf["successful_tasks"] += 1
        perf["total_cost"] += outcome.cost_usd
        perf["total_duration_ms"] += outcome.duration_ms
        perf["total_errors"] += outcome.tool_errors
        
        self._dirty = True
        # Batch save: only write to disk every N outcomes
        if len(self._outcomes) % self._batch_size == 0:
            self._save()

    def flush(self) -> None:
        """Force immediate save of pending outcomes."""
        if self._dirty:
            self._save()

    @functools.lru_cache(maxsize=64)
    def get_model_score(self, model: str) -> float:
        """Get performance score for a model (0-1)."""
        perf = self._model_performance.get(model)
        if not perf or perf["total_tasks"] == 0:
            return 0.5
        
        success_rate = perf["successful_tasks"] / perf["total_tasks"]
        avg_cost = perf["total_cost"] / perf["total_tasks"]
        cost_penalty = min(avg_cost / 1.0, 1.0)
        
        return max(0, min(1, success_rate * 0.7 + (1 - cost_penalty) * 0.3))

    def get_best_model_for_task_type(
        self,
        task_text: str,
        candidate_models: list[str],
    ) -> str:
        """Pick the best model from candidates based on historical performance."""
        profile = extract_task_profile(task_text)
        
        best_model = candidate_models[0]
        best_score = -1.0
        
        for model in candidate_models:
            base_score = self.get_model_score(model)
            
            info = resolve_model_info(model)
            capability_bonus = 0.0
            
            if profile.requires_coding and info.supports_tools:
                capability_bonus += 0.1
            if profile.requires_reasoning and info.context_window > 128_000:
                capability_bonus += 0.05
            if profile.is_dangerous and info.pricing_input > 5.0:
                capability_bonus += 0.1
            
            final_score = base_score + capability_bonus
            
            if final_score > best_score:
                best_score = final_score
                best_model = model
        
        return best_model

    def get_performance_report(self) -> dict[str, Any]:
        """Get overall performance report."""
        report = {
            "total_tasks": len(self._outcomes),
            "models": {},
        }
        report_models: dict[str, Any] = report["models"]

        for model, perf in self._model_performance.items():
            if perf["total_tasks"] > 0:
                report_models[model] = {
                    "tasks": perf["total_tasks"],
                    "success_rate": round(
                        perf["successful_tasks"] / perf["total_tasks"], 3
                    ),
                    "avg_cost_usd": round(
                        perf["total_cost"] / perf["total_tasks"], 4
                    ),
                    "avg_duration_ms": round(
                        perf["total_duration_ms"] / perf["total_tasks"], 1
                    ),
                    "total_errors": perf["total_errors"],
                    "score": round(self.get_model_score(model), 3),
                }
        
        return report

    def _save(self) -> None:
        """Persist outcomes to disk (thread-safe, atomic write)."""
        if not self._storage:
            return
        with self._save_lock:
            if not self._dirty:
                return
            try:
                data = {
                    "outcomes": [
                        {
                            "task_text": o.task_text[:200],
                            "assigned_model": o.assigned_model,
                            "success": o.success,
                            "duration_ms": o.duration_ms,
                            "cost_usd": o.cost_usd,
                            "tool_errors": o.tool_errors,
                            "model_switches": o.model_switches,
                            "timestamp": o.timestamp,
                            "user_satisfaction": o.user_satisfaction,
                        }
                        for o in self._outcomes
                    ],
                    "model_performance": self._model_performance,
                }
                self._storage.parent.mkdir(parents=True, exist_ok=True)
                # Atomic write: tmp file then replace
                tmp_path = self._storage.with_suffix(".tmp")
                tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                import os
                os.replace(str(tmp_path), str(self._storage))
                self._dirty = False
                logger.debug("Saved %d outcomes to %s", len(self._outcomes), self._storage)
            except Exception as e:
                logger.warning("Failed to save feedback data: %s", e)

    def _load(self) -> None:
        """Load outcomes from disk."""
        if not self._storage or not self._storage.exists():
            return
        try:
            data = json.loads(self._storage.read_text())
            self._model_performance = data.get("model_performance", {})
            for o in data.get("outcomes", []):
                self._outcomes.append(TaskOutcome(
                    task_text=o["task_text"],
                    assigned_model=o["assigned_model"],
                    success=o["success"],
                    duration_ms=o["duration_ms"],
                    cost_usd=o["cost_usd"],
                    tool_errors=o["tool_errors"],
                    model_switches=o["model_switches"],
                    timestamp=o["timestamp"],
                    user_satisfaction=o.get("user_satisfaction"),
                ))
            logger.info("Loaded %d outcomes from %s", len(self._outcomes), self._storage)
        except Exception as e:
            logger.warning("Failed to load feedback data: %s", e)


class SmartRouter:
    """Intelligent routing engine combining routing, switching, and learning."""

    def __init__(
        self,
        router: AgentRouter | None = None,
        switcher: ModelSwitcher | None = None,
        feedback_path: Path | None = None,
    ):
        self._router = router or AgentRouter()
        self._switcher = switcher
        self._learner = FeedbackLearner(storage_path=feedback_path)
        self._current_task_start: float = 0.0
        self._current_model: str = ""

    @property
    def router(self) -> AgentRouter:
        return self._router

    @property
    def learner(self) -> FeedbackLearner:
        return self._learner

    def route_and_switch(
        self,
        task_text: str,
        current_model: str,
    ) -> tuple[RoutingDecision, SwitchResult | None]:
        """Route a task and switch model if needed."""
        self._current_task_start = time.time()
        self._current_model = current_model

        decision = self._router.route_task(task_text)

        if self._switcher and decision.selected_model != current_model:
            switch_result = self._switcher.switch_to(
                target_model=decision.selected_model,
                reason=f"auto_routed: {decision.reasoning}",
            )
            logger.info("Auto-switched model: %s", switch_result.to_log())
            return decision, switch_result

        return decision, None

    def record_task_outcome(
        self,
        task_text: str,
        success: bool,
        cost_usd: float = 0.0,
        tool_errors: int = 0,
        model_switches: int = 0,
    ) -> None:
        """Record the outcome of a completed task."""
        duration_ms = (time.time() - self._current_task_start) * 1000
        
        self._learner.record_outcome(TaskOutcome(
            task_text=task_text,
            assigned_model=self._current_model or self._router.force_model or "unknown",
            success=success,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            tool_errors=tool_errors,
            model_switches=model_switches,
        ))

    def get_performance_report(self) -> dict[str, Any]:
        """Get combined routing and performance report."""
        return {
            "routing_stats": self._router.get_routing_stats(),
            "model_performance": self._learner.get_performance_report(),
            "switch_history": self._switcher.get_switch_history() if self._switcher else [],
        }

    def force_model(self, model_name: str | None) -> None:
        """Force or unforce a specific model."""
        self._router.force_model_selection(model_name)


_default_smart_router: SmartRouter | None = None


def get_smart_router(feedback_path: Path | None = None) -> SmartRouter:
    """Get the global smart router instance."""
    global _default_smart_router
    if _default_smart_router is None:
        _default_smart_router = SmartRouter(feedback_path=feedback_path)
    return _default_smart_router


def reset_smart_router() -> None:
    """Reset the global smart router (for testing)."""
    global _default_smart_router
    _default_smart_router = None
