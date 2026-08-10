from __future__ import annotations

import concurrent.futures
import inspect
import re
import time
from pathlib import Path
from typing import Any, Callable

from minicode.config import describe_fallback_guidance, describe_provider_channel
from minicode.context_manager import ContextManager, estimate_message_tokens
from minicode.logging_config import get_logger
from minicode.model_registry import detect_provider
from minicode.permissions import PermissionManager
from minicode.state import Store, AppState, increment_tool_calls, set_busy, set_idle
from minicode.tooling import ToolContext, ToolRegistry, ToolResult
from minicode.types import (
    AgentStep,
    ChatMessage,
    ModelAdapter,
    RuntimeEvent,
    RuntimeEventCategory,
)

# Hooks integration
from minicode.hooks import HookEvent, fire_hook_sync

# Intelligence integration
from minicode.agent_metrics import AgentMetricsCollector
from minicode.agent_intelligence import ErrorClassifier, NudgeGenerator, ToolScheduler
from minicode.working_memory import get_working_memory, protect_context

# Work chain integration
from minicode.intent_parser import parse_intent
from minicode.task_object import build_task, TaskObject, TaskState
from minicode.task_graph import TaskGraph, TaskState as GraphTaskState
from minicode.pipeline_engine import get_pipeline_engine
from minicode.capability_registry import get_registry, CapabilityDomain
from minicode.layered_context import ContextBuilder, LayeredContext
from minicode.decision_audit import get_auditor, DecisionOutcome
from minicode.runtime_profiles import resolve_runtime_profile

# 工程控制论集成
from minicode.cybernetic_orchestrator import CyberneticOrchestrator
from minicode.cybernetic_supervisor import save_supervisor_report
from minicode.feedforward_controller import FeedforwardController

# 高级控制论模块
from minicode.state_observer import MeasurementVector
from minicode.self_healing_engine import SelfHealingEngine

# 任务进度控制
from minicode.progress_controller import ProgressSignal, ProgressAction

# 记忆注入和模型选择控制
from minicode.memory_injector import MemoryInjectionSignal, MemoryInjector
from minicode.model_registry import ModelSelectionSignal

# 智能路由与自省 (Phase 3 导入)
from minicode.smart_router import TaskOutcome

# 上下文管理集成 (Claude Code-style + Engineering Cybernetics)
from minicode.context_compactor import (
    ContextCompactor,
    AutoCompactConfig,
)
from minicode.context_cybernetics import ContextCyberneticsOrchestrator
from minicode.cost_control import CostControlLoop
from minicode.micro_compact import MicroCompactor
from minicode.circuit_breaker import CompactionCircuitBreaker
from minicode.memory import MemoryManager
from minicode.turn_kernel import (
    TurnPreludeState,
    TurnRecurrentState,
    TurnVerificationState,
    build_stable_task_pack,
    build_turn_coda_summary,
    build_widening_transition_nudge,
    decide_tool_turn,
    decide_assistant_turn,
    derive_turn_step_policy,
    finalize_work_chain_task,
    render_turn_policy_message,
)
from minicode.turn_events import AgentTurnCallbacks, AgentTurnEventSink, TurnEvent

logger = get_logger("agent_loop")

# 甯搁噺锛氶伩鍏嶉噸澶嶇殑鎻愮ず鏂囨湰
NUDGE_CONTINUE = (
    "Continue immediately from your <progress> update with concrete tool calls, "
    "code changes, or an explicit <final> answer only if the task is complete. "
    "Prefer taking the next concrete action over explaining what you plan to do."
)

NUDGE_AFTER_TOOL_RESULT = (
    "You have received tool results. Review them briefly, then take the next "
    "concrete action: call another tool, edit code, or give an explicit <final> "
    "answer only if the task is truly complete. Do not restate what you just saw."
)

NUDGE_AFTER_EMPTY_RESPONSE = (
    "Your last response was empty. This often happens after tool errors or when "
    "the model is uncertain. Pick the most likely next action and try it — you can "
    "adjust based on results. Call a tool, edit code, or give <final> if done."
)

NUDGE_AFTER_EMPTY_NO_TOOLS = (
    "Your last response was empty but you have not used any tools yet. Start by "
    "inspecting the relevant files (read_file, grep_files, list_files) to understand "
    "the codebase before making changes."
)

RESUME_AFTER_PAUSE = (
    "Resume from the previous pause. Continue with the next concrete tool call, "
    "code change, or <final> answer."
)

RESUME_AFTER_MAX_TOKENS = (
    "Your previous response was cut short by the token limit. Resume immediately "
    "with the next concrete action — pick up where you left off."
)


STABLE_TASK_STATE_MARKER = "[Stable task state]"
_MODEL_FALLBACK_ERROR_HINTS = (
    "no available channel",
    "temporarily unavailable",
    "service unavailable",
    "please try again later",
    "capacity exceeded",
    "overloaded",
    "high demand",
    "503",
    "502",
    "500",
    "connection refused",
    "connection reset",
    "timed out",
    "timeout",
)
_MODEL_FALLBACK_BLOCK_HINTS = (
    "unauthorized",
    "forbidden",
    "invalid api key",
    "authentication",
    "bad request",
    "invalid_request",
    "validation",
    "tool schema",
    "context length",
)


def _upsert_stable_task_state_message(
    messages: list[ChatMessage],
    stable_text: str,
) -> list[ChatMessage]:
    filtered = [
        message
        for message in messages
        if not (
            message.get("role") == "system"
            and str(message.get("content", "")).startswith(STABLE_TASK_STATE_MARKER)
        )
    ]
    filtered.append(
        {
            "role": "system",
            "content": f"{STABLE_TASK_STATE_MARKER}\n{stable_text}",
        }
    )
    return filtered


def _should_attempt_model_fallback(error_message: str) -> bool:
    normalized = error_message.lower()
    if any(marker in normalized for marker in _MODEL_FALLBACK_BLOCK_HINTS):
        return False
    return any(marker in normalized for marker in _MODEL_FALLBACK_ERROR_HINTS)


def _looks_like_provider_availability_error(error_message: str) -> bool:
    normalized = error_message.lower()
    return any(
        marker in normalized
        for marker in (
            "no available channel",
            "temporarily unavailable",
            "service unavailable",
            "please try again later",
            "capacity exceeded",
            "overloaded",
            "high demand",
            "503",
            "502",
            "500",
        )
    )


def _summarize_model_api_failure(
    *,
    error_type: str,
    error: Exception,
    active_model_id: str = "",
    fallback_errors: list[str] | None = None,
    runtime: dict[str, Any] | None = None,
) -> str:
    fallback_errors = fallback_errors or []
    if fallback_errors:
        combined = " ".join(fallback_errors)
        if (
            "no viable fallback models were available" in combined.lower()
            and any(_looks_like_provider_availability_error(item) for item in fallback_errors + [str(error)])
        ):
            runtime = runtime or {}
            guidance_model = (
                str(runtime.get("configuredModel", "")).strip()
                or str(runtime.get("model", "")).strip()
                or active_model_id
                or "the active model"
            )
            model_label = guidance_model or active_model_id or "the active model"
            provider = detect_provider(guidance_model, runtime).value if guidance_model else "unknown"
            channel = describe_provider_channel(runtime, provider)
            guidance = describe_fallback_guidance(
                runtime,
                provider_name=provider,
                current_model=guidance_model,
            )
            guidance_suffix = f" Next step: {guidance[0]}" if guidance else ""
            return (
                f"Provider availability failure: {model_label} failed and all viable fallback models were unavailable. "
                f"Remaining blocker is upstream provider/channel availability, not a local retry loop. "
                f"Active channel: {channel}. Last error ({error_type}): {error}{guidance_suffix}"
            )
    return f"Model API error ({error_type}): {error}"


def _extract_model_id_from_provider_error(error: Exception) -> str:
    message = str(error)
    match = re.search(r"model\s+([^\s]+)\s+under\s+group", message, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _infer_active_model_id(
    model: ModelAdapter,
    runtime: dict[str, Any] | None,
    error: Exception | None = None,
) -> str:
    explicit = str(getattr(model, "model_id", "") or "").strip()
    if explicit:
        return explicit
    runtime_model = str((runtime or {}).get("model", "") or "").strip()
    if runtime_model:
        return runtime_model
    if error is not None:
        return _extract_model_id_from_provider_error(error)
    return ""


def _is_empty_assistant_response(content: str) -> bool:
    return len(content.strip()) == 0


def _extract_task_description(messages: list[ChatMessage]) -> str:
    """Extract the original task description from messages."""
    for msg in messages:
        if msg.get("role") == "user" and msg.get("content"):
            content = str(msg["content"])
            if not content.startswith("Continue") and not content.startswith("Your last"):
                return content[:500]
    return "Unknown task"


def _build_work_chain_task(messages: list[ChatMessage]) -> tuple[TaskObject | None, dict]:
    """Build TaskObject from conversation messages and return it with metadata."""
    raw_input = _extract_task_description(messages)
    if raw_input == "Unknown task":
        return None, {}
    intent = parse_intent(raw_input)
    task = build_task(intent, raw_input)
    metadata = {
        "intent_type": intent.intent_type.value,
        "action_type": intent.action_type.value,
        "confidence": intent.confidence,
        "entities": intent.entities,
        "complexity": intent.complexity_hint,
    }
    logger.info(
        "Work chain: intent=%s action=%s confidence=%.2f complexity=%s",
        intent.intent_type.value, intent.action_type.value,
        intent.confidence, intent.complexity_hint,
    )
    return task, metadata


def _build_layered_context(
    messages: list[ChatMessage],
    system_prompt: str = "",
    project_context: str = "",
    task: TaskObject | None = None,
) -> tuple[LayeredContext, ContextBuilder]:
    """Build layered context from conversation and task."""
    context = LayeredContext()
    builder = ContextBuilder(context)
    if system_prompt:
        builder.set_system_prompt(system_prompt)
    if project_context:
        builder.add_project_memory(project_context)
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content:
            builder.add_session_message(role, content)
    if task:
        scratchpad = (
            f"Task: {task.title}\n"
            f"Goal: {task.goal}\n"
            f"Constraints: {len(task.constraints)}\n"
            f"Expected outputs: {len(task.expected_outputs)}"
        )
        builder.add_scratchpad(scratchpad)
    return context, builder


def _register_tool_capabilities(tools: ToolRegistry) -> None:
    """Register existing tools as capabilities in the registry."""
    registry = get_registry()
    if registry.list_all():
        return
    for tool_name in tools.list_all():
        try:
            from minicode.capability_registry import CapabilityMetadata, CapabilityScope
            tool_def = tools.find(tool_name)
            if not tool_def:
                continue
            domain = CapabilityDomain.UNKNOWN
            if "file" in tool_name or "write" in tool_name or "read" in tool_name:
                domain = CapabilityDomain.FILE
            elif "search" in tool_name or "grep" in tool_name:
                domain = CapabilityDomain.SEARCH
            elif "web" in tool_name or "http" in tool_name or "fetch" in tool_name:
                domain = CapabilityDomain.WEB
            elif "command" in tool_name or "run" in tool_name or "exec" in tool_name:
                domain = CapabilityDomain.EXECUTION
            elif "code" in tool_name or "diff" in tool_name or "review" in tool_name:
                domain = CapabilityDomain.CODE
            elif "memory" in tool_name:
                domain = CapabilityDomain.MEMORY
            scope = CapabilityScope.READONLY
            if any(k in tool_name for k in ("write", "modify", "edit", "delete", "create")):
                scope = CapabilityScope.WRITE
            if any(k in tool_name for k in ("command", "exec", "run")):
                scope = CapabilityScope.DESTRUCTIVE
            if any(k in tool_name for k in ("web", "fetch", "http")):
                scope = CapabilityScope.EXTERNAL
            metadata = CapabilityMetadata(
                name=tool_name, domain=domain, scope=scope,
                description=tool_def.description or f"Tool: {tool_name}",
                tags=["tool", tool_name],
            )
            registry.register(metadata, lambda **kw: tools.execute(tool_name, kw, ToolContext(cwd=str(Path.cwd()))), None)
        except Exception as e:
            logger.debug("Failed to register tool %s as capability: %s", tool_name, e)


def _execute_single_tool(
    call: dict,
    tools: ToolRegistry,
    cwd: str,
    permissions: Any | None,
    session: Any | None,
    runtime: dict | None,
    store: Any | None,
    step: int,
    on_tool_start: Callable[[str, dict], None] | None,
    on_tool_result: Callable[[str, str, bool], None] | None,
    tool_scheduler: Any | None = None,
) -> ToolResult:
    """Execute a single tool call with hooks, state updates, and crash protection.
    
    Used both for serial execution and as a worker function for concurrent execution.
    When running concurrently (store/on_tool_start/on_tool_result are None),
    hooks and UI callbacks are deferred to the result processing phase.
    
    Includes a global exception safety net: any unexpected crash in the tool
    execution pipeline (hooks, state updates, etc.) is caught and converted
    to an error ToolResult, preventing the entire agent loop from crashing.
    """
    tool_name = call["toolName"]
    tool_input = call["input"]
    
    try:
        # Pre-tool hooks and UI (only for serial execution)
        if on_tool_start:
            on_tool_start(tool_name, tool_input)
        
        if store:
            store.set_state(set_busy(tool_name))
        
        # Execute the tool with timeout protection
        import concurrent.futures
        import os
        _base_timeout = int(os.environ.get("MINICODE_TOOL_TIMEOUT", "120"))
        TOOL_TIMEOUT = (
            int(getattr(tool_scheduler, '_force_tool_timeout', _base_timeout))
            if tool_scheduler and hasattr(tool_scheduler, '_force_tool_timeout')
            else _base_timeout
        )
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    tools.execute,
                    tool_name, tool_input,
                    ToolContext(cwd=cwd, permissions=permissions, session=session, _runtime=runtime),
                )
                result = future.result(timeout=TOOL_TIMEOUT)
        except concurrent.futures.TimeoutError:
            result = ToolResult(
                ok=False,
                output=f"Tool '{tool_name}' timed out after {TOOL_TIMEOUT}s",
            )
        except Exception:
            result = tools.execute(
                tool_name, tool_input,
                ToolContext(cwd=cwd, permissions=permissions, session=session, _runtime=runtime),
            )  # Fallback: direct execution
        
        # Post-tool state updates (only for serial execution)
        if store:
            store.set_state(increment_tool_calls())
            store.set_state(set_idle())
        
        if on_tool_result:
            on_tool_result(tool_name, result.output, not result.ok)
        
        return result
    
    except (KeyboardInterrupt, SystemExit):
        # Always propagate these
        raise
    except Exception as exc:  # noqa: BLE001
        # Global safety net: catch ANY unexpected error in the tool execution
        # pipeline (hooks, state updates, permission checks, etc.) and convert
        # it to an error result. This prevents a single tool crash from
        # cascading into a full session failure.
        import traceback
        tb_excerpt = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-3:]).strip()
        error_type = type(exc).__name__
        
        logger.error("Tool execution pipeline crashed (%s): %s", error_type, exc)
        
        # Ensure state is reset even on crash
        if store:
            try:
                store.set_state(set_idle())
            except Exception:
                pass
        
        return ToolResult(
            ok=False,
            output=f"[{error_type}] Tool execution pipeline crashed: {exc}\n"
                   f"Traceback:\n{tb_excerpt}"
        )


def _format_diagnostics(stop_reason: str | None, block_types: list[str] | None, ignored_block_types: list[str] | None) -> str:
    parts: list[str] = []
    if stop_reason:
        parts.append(f"stop_reason={stop_reason}")
    if block_types:
        parts.append(f"blocks={','.join(block_types)}")
    if ignored_block_types:
        parts.append(f"ignored={','.join(ignored_block_types)}")
    return f" Diagnostics: {'; '.join(parts)}." if parts else ""


def _is_recoverable_thinking_stop(*, is_empty: bool, stop_reason: str | None, ignored_block_types: list[str] | None) -> bool:
    if not is_empty:
        return False
    if stop_reason not in {"pause_turn", "max_tokens"}:
        return False
    return "thinking" in (ignored_block_types or [])


def _should_treat_assistant_as_progress(*, kind: str | None, content: str, saw_tool_result: bool) -> bool:
    if kind == "progress":
        return True
    if kind == "final":
        return False
    if not saw_tool_result:
        return False
    return False


# ── Preemptive context guard (Claude Code-style blocking limit) ─────────────

def _is_at_blocking_limit(
    token_count: int,
    context_window: int,
    *,
    effective_window_ratio: float = 0.90,
    min_reserve_tokens: int = 3_000,
) -> bool:
    """Preemptively block API calls when context is nearly full.

    Inspired by Claude Code's `isAtBlockingLimit` — prevents 413 errors
    by refusing to send a request when the context window is too full.

    The effective window is model context_window * effective_window_ratio,
    minus min_reserve_tokens (reserved for the assistant response).

    Returns True if the request would likely trigger a 413.
    """
    effective_window = int(context_window * effective_window_ratio)
    blocking_limit = max(1, effective_window - min_reserve_tokens)
    return token_count >= blocking_limit


def _compute_effective_blocking_limit(
    context_window: int,
    *,
    effective_window_ratio: float = 0.90,
    min_reserve_tokens: int = 3_000,
) -> int:
    effective_window = int(context_window * effective_window_ratio)
    return max(1, effective_window - min_reserve_tokens)


def _try_compact_with_breaker(
    breaker: CompactionCircuitBreaker,
    compact_fn: Callable[[], tuple[list, bool]],
    current_messages: list,
    logger_fn: Callable[..., None],
) -> tuple[list, bool]:
    """Run compaction through the circuit breaker.

    Returns (messages, effective) — messages is the (possibly compacted)
    list, effective indicates whether compaction actually changed anything.
    """
    if not breaker.is_allowed():
        logger_fn("Compaction blocked by circuit breaker (consecutive failures)")
        return current_messages, False
    try:
        result_messages, effective = compact_fn()
        if effective:
            breaker.record_success()
        return result_messages, effective
    except Exception as exc:
        breaker.record_failure()
        bs = breaker.get_state()
        logger_fn("Compaction failed (breaker=%d/%d): %s",
                  bs.consecutive_failures, breaker.config.failure_threshold, exc)
        return current_messages, False


def _model_next(
    model: ModelAdapter,
    messages: list[ChatMessage],
    *,
    on_stream_chunk: Callable[[str], None] | None,
    on_thinking_chunk: Callable[[str], None] | None = None,
    store: Store[AppState] | None,
) -> AgentStep:
    """Call provider adapters with store/thinking support while preserving test doubles."""
    kwargs: dict[str, Any] = {"on_stream_chunk": on_stream_chunk}

    try:
        sig = inspect.signature(model.next)
        param_names = set(sig.parameters.keys())
        has_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if has_kwargs or "on_thinking_delta" in param_names:
            kwargs["on_thinking_delta"] = on_thinking_chunk
        if has_kwargs or "store" in param_names:
            kwargs["store"] = store
    except (TypeError, ValueError):
        # Can't inspect signature (e.g. some mock objects) — be conservative
        pass

    return model.next(messages, **kwargs)


def _apply_control_signal(
    *,
    control_signal: Any,
    system_state: Any,
    max_steps: int | None,
    tool_scheduler: ToolScheduler,
    context_compactor: ContextCompactor | None,
    model_switcher: Any | None,
    feedback_controller: Any | None = None,
) -> int | None:
    """Apply FeedbackController output to live runtime knobs."""
    if not control_signal or control_signal.confidence <= 0.6:
        return max_steps

    if (
        control_signal.limit_max_steps
        and max_steps is not None
        and control_signal.limit_max_steps < max_steps
    ):
        logger.info(
            "FeedbackController: limiting max_steps %d -> %d",
            max_steps, control_signal.limit_max_steps,
        )
        max_steps = control_signal.limit_max_steps

    if control_signal.adjust_token_budget != 1.0:
        if (
            context_compactor
            and hasattr(context_compactor, "_tool_budget")
            and context_compactor._tool_budget
        ):
            tb = context_compactor._tool_budget
            new_budget = max(
                1000,
                int(
                    getattr(tb, "budget_per_message", 2000)
                    * control_signal.adjust_token_budget
                ),
            )
            if hasattr(tb, "budget_per_message"):
                tb.budget_per_message = new_budget
            logger.info(
                "FeedbackController: token budget adjusted to %d (mult=%.2f)",
                new_budget, control_signal.adjust_token_budget,
            )

    if control_signal.reduce_parallelism:
        if hasattr(tool_scheduler, "_force_max_workers"):
            tool_scheduler._force_max_workers = min(
                getattr(tool_scheduler, "_force_max_workers", 2) or 2,
                2,
            )
        logger.info(
            "FeedbackController: reduce_parallelism -> max_workers=2 "
            "(oscillation=%.2f)",
            control_signal.oscillation_index,
        )

    if control_signal.adjust_concurrency != 0:
        cap = max(1, 4 + control_signal.adjust_concurrency)
        if hasattr(tool_scheduler, "_force_max_workers"):
            tool_scheduler._force_max_workers = cap
        logger.info(
            "FeedbackController: adjust_concurrency=%+d -> max_workers=%d",
            control_signal.adjust_concurrency, cap,
        )

    if control_signal.increase_model_level:
        logger.info(
            "FeedbackController: model upgrade recommended (errors=%.2f perf=%.2f)",
            system_state.error_frequency,
            system_state.performance_score(),
        )
        if model_switcher:
            if hasattr(model_switcher, '_pending_upgrade'):
                model_switcher._pending_upgrade = True  # type: ignore[attr-defined]

    if control_signal.decrease_model_level:
        logger.info(
            "FeedbackController: model downgrade recommended (efficiency=%.2f)",
            system_state.token_efficiency,
        )

    if control_signal.suggest_memory_persistence:
        logger.info("FeedbackController: persisting working memory")
        if context_compactor and hasattr(context_compactor, "_tool_budget"):
            try:
                if hasattr(context_compactor._tool_budget, "flush"):
                    context_compactor._tool_budget.flush()
            except Exception:
                pass

    if control_signal.recommend_skill_update:
        logger.info(
            "FeedbackController: skill update recommended (pattern=%.2f)",
            system_state.pattern_reuse_rate,
        )
        # Queue skill update for next maintenance cycle
        if not hasattr(tool_scheduler, "_pending_skill_update"):
            tool_scheduler._pending_skill_update = True  # type: ignore[attr-defined]
        logger.info("FeedbackController: skill update queued for next maintenance cycle")

    if control_signal.reduce_tool_timeout:
        new_timeout = max(5.0, control_signal.reduce_tool_timeout)
        if hasattr(tool_scheduler, "_force_tool_timeout"):
            tool_scheduler._force_tool_timeout = new_timeout  # type: ignore[attr-defined]
        logger.info(
            "FeedbackController: tool timeout reduced to %.1fs (high error rate)",
            new_timeout,
        )
    elif hasattr(tool_scheduler, '_force_tool_timeout'):
        # Reset timeout when signal no longer active
        if hasattr(tool_scheduler, '_force_tool_timeout'):
            del tool_scheduler._force_tool_timeout

    if control_signal.increase_nudge_frequency:
        tool_scheduler._force_nudge_frequency = True  # type: ignore[attr-defined]
        logger.info(
            "FeedbackController: nudge frequency increased (stability=%.2f)",
            system_state.stability_score(),
        )
    elif hasattr(tool_scheduler, '_force_nudge_frequency'):
        if hasattr(tool_scheduler, '_force_nudge_frequency'):
            del tool_scheduler._force_nudge_frequency

    if control_signal.promote_pattern:
        if feedback_controller:
            feedback_controller.record_pattern_effectiveness(
                control_signal.promote_pattern, True
            )
            logger.info(
                "FeedbackController: pattern promoted '%s'",
                control_signal.promote_pattern,
            )

    if control_signal.force_compaction and context_compactor:
        try:
            compacted = context_compactor.compact_messages() if hasattr(context_compactor, 'compact_messages') else False
            logger.info(
                "FeedbackController: forced compaction completed (%d messages)",
                len(compacted) if compacted else 0,
            )
        except Exception as exc:
            logger.warning("FeedbackController: forced compaction failed: %s", exc)

    return max_steps


def run_agent_turn(
    *,
    model: ModelAdapter,
    tools: ToolRegistry,
    messages: list[ChatMessage],
    cwd: str,
    permissions: PermissionManager | None = None,
    session: Any | None = None,
    store: Store[AppState] | None = None,
    max_steps: int = 50,
    on_tool_start: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str, bool], None] | None = None,
    on_assistant_message: Callable[[str], None] | None = None,
    on_progress_message: Callable[[str], None] | None = None,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
    on_assistant_stream_chunk: Callable[[str], None] | None = None,
    on_thinking_chunk: Callable[[str], None] | None = None,
    context_manager: ContextManager | None = None,
    memory_manager: MemoryManager | None = None,
    runtime: dict | None = None,
    metrics_collector: AgentMetricsCollector | None = None,
    system_prompt: str = "",
    project_context: str = "",
    enable_work_chain: bool = True,
    callbacks: AgentTurnCallbacks | AgentTurnEventSink | None = None,
) -> list[ChatMessage]:
    # Prelude: prepare per-turn state before we enter the recurrent think/act loop.
    current_messages = list(messages)
    runtime = runtime or {}
    configured_runtime_model = (
        str(runtime.get("configuredModel", "")).strip()
        or str(runtime.get("model", "")).strip()
        or str(getattr(model, "model_id", "") or "").strip()
    )
    if configured_runtime_model:
        runtime.setdefault("configuredModel", configured_runtime_model)
    runtime_profile = resolve_runtime_profile(runtime, fallback_max_steps=max_steps)
    turn_state = TurnRecurrentState(
        max_steps=runtime_profile.max_steps,
        profile_name=runtime_profile.name,
        widen_after_step=runtime_profile.widen_after_step,
        empty_response_retry_limit=runtime_profile.empty_response_retry_limit,
        recoverable_thinking_retry_limit=runtime_profile.recoverable_thinking_retry_limit,
        verification_state=TurnVerificationState(
            strict=runtime_profile.strict_step_verification,
            requires_explicit_final=runtime_profile.strict_step_verification,
        ),
    )
    max_steps = runtime_profile.max_steps

    # Keep the historical callback parameters as the source of truth for
    # existing callers, while exposing one Rust-shaped structured event sink.
    # The structured sink is deliberately isolated from the legacy callbacks:
    # a UI/telemetry consumer must not be able to break the agent turn merely
    # because its event handler failed.
    legacy_on_tool_start = on_tool_start
    legacy_on_tool_result = on_tool_result
    legacy_on_assistant_message = on_assistant_message
    legacy_on_progress_message = on_progress_message
    legacy_on_runtime_event = on_runtime_event
    legacy_on_assistant_stream_chunk = on_assistant_stream_chunk
    legacy_on_thinking_chunk = on_thinking_chunk

    def publish_turn_event(event: TurnEvent) -> None:
        if callbacks is None:
            return
        try:
            on_event = getattr(callbacks, "on_event", None)
            if callable(on_event):
                on_event(event)
                return

            # Also accept a Rust-style object that implements the four named
            # methods but has no aggregate ``on_event`` method.
            callback_name = {
                "tool_start": "on_tool_start",
                "tool_result": "on_tool_result",
                "assistant": "on_assistant_message",
                "progress": "on_progress_message",
                "runtime": "on_runtime_event",
                "assistant_stream": "on_assistant_stream_chunk",
                "thinking": "on_thinking_chunk",
            }.get(event.kind)
            handler = getattr(callbacks, callback_name, None) if callback_name else None
            if not callable(handler):
                return
            if event.kind == "tool_start":
                handler(event.tool_name, event.tool_input)
            elif event.kind == "tool_result":
                handler(event.tool_name, event.output, event.is_error)
            elif event.kind == "runtime" and event.runtime_event is not None:
                handler(event.runtime_event)
            else:
                handler(event.content)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Structured agent-turn callback failed for event=%s",
                event.kind,
                exc_info=True,
            )

    def on_tool_start(tool_name: str, tool_input: dict) -> None:
        publish_turn_event(
            TurnEvent.tool_started(
                step=turn_state.step or None,
                tool_name=tool_name,
                tool_input=tool_input,
            )
        )
        if legacy_on_tool_start:
            legacy_on_tool_start(tool_name, tool_input)

    def on_tool_result(tool_name: str, output: str, is_error: bool) -> None:
        publish_turn_event(
            TurnEvent.tool_finished(
                step=turn_state.step or None,
                tool_name=tool_name,
                output=output,
                is_error=is_error,
            )
        )
        if legacy_on_tool_result:
            legacy_on_tool_result(tool_name, output, is_error)

    def on_assistant_message(content: str) -> None:
        publish_turn_event(
            TurnEvent.assistant_message(
                step=turn_state.step or None,
                content=content,
            )
        )
        if legacy_on_assistant_message:
            legacy_on_assistant_message(content)

    def on_progress_message(content: str) -> None:
        publish_turn_event(
            TurnEvent.progress_message(
                step=turn_state.step or None,
                content=content,
            )
        )
        if legacy_on_progress_message:
            legacy_on_progress_message(content)

    def on_runtime_event(event: RuntimeEvent) -> None:
        publish_turn_event(
            TurnEvent.runtime_message(
                step=turn_state.step or event.step,
                event=event,
            )
        )
        if legacy_on_runtime_event:
            legacy_on_runtime_event(event)

    def on_assistant_stream_chunk(content: str) -> None:
        publish_turn_event(
            TurnEvent.assistant_stream_chunk(
                step=turn_state.step or None,
                content=content,
            )
        )
        if legacy_on_assistant_stream_chunk:
            legacy_on_assistant_stream_chunk(content)

    def on_thinking_chunk(content: str) -> None:
        publish_turn_event(
            TurnEvent.thinking_chunk(
                step=turn_state.step or None,
                content=content,
            )
        )
        if legacy_on_thinking_chunk:
            legacy_on_thinking_chunk(content)

    # Provider adapters use ``None`` to select their non-streaming protocol.
    # Do not turn an absent callback into a truthy no-op wrapper: that changes
    # the wire format for callers that never asked for streaming.
    if callbacks is None:
        if legacy_on_tool_start is None:
            on_tool_start = None
        if legacy_on_tool_result is None:
            on_tool_result = None
        if legacy_on_assistant_message is None:
            on_assistant_message = None
        if legacy_on_progress_message is None:
            on_progress_message = None
        if legacy_on_runtime_event is None:
            on_runtime_event = None
    # Structured callbacks observe stream/thinking chunks when a caller has
    # already enabled those legacy channels; merely subscribing to turn
    # events must not silently change a provider from non-streaming to
    # streaming mode.
    if (
        legacy_on_assistant_stream_chunk is None
        and not bool(getattr(callbacks, "include_stream_chunks", False))
    ):
        on_assistant_stream_chunk = None
    if (
        legacy_on_thinking_chunk is None
        and not bool(getattr(callbacks, "include_thinking_chunks", False))
    ):
        on_thinking_chunk = None

    def emit_runtime_event(
        *,
        category: RuntimeEventCategory,
        message: str,
        emit_progress: bool = True,
        stop_reason: str = "",
        widening_reason: str = "",
        evidence_summary: str = "",
    ) -> None:
        policy = turn_state.step_policy
        event = RuntimeEvent(
            category=category,
            message=message,
            step=turn_state.step or None,
            profile=runtime_profile.name,
            phase=policy.phase if policy is not None else "",
            verification_focus=(
                policy.verification_focus if policy is not None else ""
            ),
            stop_reason=stop_reason,
            widening_reason=widening_reason,
            evidence_summary=evidence_summary,
        )
        if on_runtime_event:
            on_runtime_event(event)
        if emit_progress and on_progress_message:
            on_progress_message(message)

    tool_scheduler = ToolScheduler(metrics_collector=metrics_collector)

    prelude = TurnPreludeState(auditor=get_auditor() if enable_work_chain else None)

    # 工程控制论控制器初始化（通过 Orchestrator 统一管理）
    orch: CyberneticOrchestrator | None = None
    feedback_controller: Any = None
    feedforward_controller: Any = None
    stability_monitor: Any = None
    cybernetic_supervisor: Any = None

    adaptive_pid_tuner: Any = None
    state_observer: Any = None
    decoupling_controller: Any = None
    predictive_controller: Any = None
    self_healing_engine: Any = None
    progress_controller: Any = None
    memory_injection_ctrl: Any = None
    model_selection_ctrl: Any = None
    smart_router: Any = None
    reflection_engine: Any = None
    model_switcher: Any = None
    memory_injector: Any = None

    # These objects are created by the work-chain/context branches below but
    # are also consulted by the common prelude/coda paths.  Keep the disabled
    # mode a valid lightweight execution path instead of relying on branch
    # local assignment side effects.
    context_compactor: ContextCompactor | None = None
    context_cybernetics: ContextCyberneticsOrchestrator | None = None
    memory_mgr: MemoryManager | None = None
    micro_compactor: MicroCompactor | None = MicroCompactor()
    compaction_breaker: CompactionCircuitBreaker | None = CompactionCircuitBreaker()
    cost_control: CostControlLoop | None = None

    if enable_work_chain:
        prelude.task, prelude.task_metadata = _build_work_chain_task(current_messages)
        if prelude.task:
            prelude.task_graph = TaskGraph(name=f"turn-{prelude.task.id}")
            graph_task = prelude.task_graph.add_task(
                name=prelude.task.title or prelude.task.id,
                description=prelude.task.goal or prelude.task.description,
            )
            prelude.task_graph_id = graph_task.id
            slot = prelude.task_graph.assign_slot(graph_task.id, slot_name="turn")
            prelude.task_slot_key = f"{slot.slot_name}:{slot.task_id}"
            prelude.task_graph.start_task(prelude.task_slot_key)
        prelude.layered_context, prelude.context_builder = _build_layered_context(
            current_messages, system_prompt, project_context, prelude.task,
        )
        get_pipeline_engine()
        _register_tool_capabilities(tools)

        # 初始化所有工程控制论控制器（通过 Orchestrator 统一管理）
        orch = CyberneticOrchestrator()
        orch.initialize(model, tools, runtime)
        feedback_controller = orch.feedback
        cybernetic_supervisor = orch.cyber_supervisor
        stability_monitor = orch.stability
        adaptive_pid_tuner = orch.adaptive_tuner
        state_observer = orch.state_observer
        decoupling_controller = orch.decoupling
        predictive_controller = orch.predictive
        progress_controller = orch.progress
        memory_injection_ctrl = orch.memory_ctrl
        model_selection_ctrl = orch.model_ctrl
        smart_router = orch.smart_router
        reflection_engine = orch.reflection
        model_switcher = orch.model_switcher
        logger.info("CyberneticOrchestrator: %d controllers initialized", 15)
        if smart_router and prelude.task:
            try:
                current_model_id = model.model_id if hasattr(model, 'model_id') else ""
                task_text = prelude.task.raw_input if hasattr(prelude.task, 'raw_input') else str(current_messages[-1].get('content', ''))
                routing, switch_result = smart_router.route_and_switch(
                    task_text,
                    current_model=current_model_id,
                )
                logger.info(
                    "SmartRouter: model=%s tier=%s cost=$%.4f reason=%s",
                    routing.selected_model, routing.tier_name,
                    routing.estimated_cost, routing.reasoning[:80],
                )
                # 如果路由推荐了不同模型且切换成功，更新 model 引用
                if switch_result and switch_result.success:
                    model = switch_result.adapter
                    logger.info(
                        "SmartRouter: switched model %s -> %s",
                        switch_result.old_model, switch_result.new_model,
                    )
            except Exception:
                pass

        # 初始化前馈控制器（预判式优化）
        if prelude.task:
            feedforward_controller = FeedforwardController()
            preemptive_config = feedforward_controller.preconfigure(prelude.task.parsed_intent, prelude.task.raw_input)
            risk_assessment = feedforward_controller.assess_risks(prelude.task.parsed_intent, preemptive_config)
            logger.info(
                "Feedforward control: config=%s risk=%s",
                preemptive_config.recommended_model, risk_assessment.risk_level,
            )
            # Apply feedforward preemptive config to execution parameters
            if preemptive_config.confidence > 0.6:
                if turn_state.max_steps is None:
                    turn_state.max_steps = preemptive_config.max_turn_steps
                else:
                    turn_state.max_steps = min(
                        turn_state.max_steps,
                        preemptive_config.max_turn_steps,
                    )
                max_steps = turn_state.max_steps
                logger.info(
                    "Feedforward: max_steps=%d model=%s timeout=%.1fs",
                    preemptive_config.max_turn_steps,
                    preemptive_config.recommended_model,
                    preemptive_config.tool_timeout_seconds,
                )
            if risk_assessment.risk_level in ("high", "critical"):
                logger.warning(
                    "Feedforward risk assessment: level=%s probability=%.2f risks=%s",
                    risk_assessment.risk_level,
                    risk_assessment.estimated_failure_probability,
                    ", ".join(risk_assessment.identified_risks[:3]),
                )

        # 模型选择控制器：根据任务特征推荐模型
        if model_selection_ctrl and prelude.task:
            try:
                model_signal = ModelSelectionSignal(
                    task_complexity=getattr(prelude.task, 'complexity', 'moderate') if hasattr(prelude.task, 'complexity') else "moderate",
                    budget_pressure=0.3,
                    latency_pressure=0.3,
                    recent_failures=0,
                    current_model=model.model_id if hasattr(model, 'model_id') else "",
                )
                model_decision = model_selection_ctrl.decide(model_signal)
                logger.info(
                    "ModelSelectionController: model=%s score=%.2f effort=%s reasons=%s",
                    model_decision.model, model_decision.score,
                    model_decision.reasoning_effort.value,
                    ", ".join(model_decision.reasons),
                )
            except Exception:
                pass

        # 初始化上下文管理器 (Claude Code-style + Engineering Cybernetics)
        # 必须在 SelfHealingEngine 之前初始化，因为自愈引擎需要委托压缩操作
        if context_manager:
            compact_config = AutoCompactConfig(
                threshold_ratio=0.85,
                circuit_breaker_limit=3,
                session_memory_enabled=True,
            )
            memory_mgr = (
                memory_manager
                if memory_manager is not None
                else MemoryManager(project_root=cwd)
            )
            # 将 memory_mgr 注入 ReflectionEngine，使自省经验持久化
            if reflection_engine:
                reflection_engine.memory = memory_mgr
            # 初始化 MemoryInjector，将控制论决策落地为实际记忆注入
            # 同时创建 Reranker（使用真实 LLM 做记忆策展）
            memory_reranker = None
            try:
                from minicode.memory_reranker import MemoryReranker
                # Use the agent's model for reranking (lightweight prompt, ~500 tokens)
                memory_reranker = MemoryReranker(model_adapter=model)
            except Exception:
                pass
            memory_injector = MemoryInjector(
                memory_manager=memory_mgr,
                controller=memory_injection_ctrl,
                reranker=memory_reranker,
            )
            if orch:
                orch._last_model = model
                orch._workspace = cwd
                orch.wire_memory(memory_mgr)
                if orch.memory_pipeline is not None:
                    memory_injector = getattr(orch.memory_pipeline, "_injector", memory_injector)
            # 记忆注入控制器：根据上下文压力决定注入策略
            if memory_injection_ctrl:
                try:
                    inj_signal = MemoryInjectionSignal(
                        context_usage=context_manager.get_stats().usage_percentage / 100.0,
                        retrieval_quality=0.5,
                        recent_failure=False,
                    )
                    inj_decision = memory_injection_ctrl.decide(
                        inj_signal,
                        base_max_memories=5,
                        base_min_relevance=0.3,
                        base_max_tokens=200,
                    )
                    logger.info(
                        "MemoryInjectionController: mode=%s max_mem=%d min_rel=%.2f max_tok=%d",
                        inj_decision.mode.value, inj_decision.max_memories,
                        inj_decision.min_relevance, inj_decision.max_tokens_per_memory,
                    )
                except Exception:
                    pass
            # 执行实际记忆注入：将相关记忆注入到系统 prompt 中
            if orch and prelude.task:
                try:
                    task_desc = prelude.task.raw_input if hasattr(prelude.task, 'raw_input') else ""
                    current_messages = orch.inject_memories(task_desc, current_messages)
                except Exception:
                    pass
            elif memory_injector and prelude.task:
                try:
                    task_desc = prelude.task.raw_input if hasattr(prelude.task, 'raw_input') else ""
                    injected = memory_injector.inject_for_task(task_desc)
                    if injected:
                        logger.info(
                            "MemoryInjector: injected %d memories (mode=%s)",
                            len(injected),
                            memory_injector._last_decision.mode.value if memory_injector._last_decision else "?",
                        )
                        # 将注入的记忆追加到系统 prompt
                        memory_context = "\n## Injected Memory\n" + "\n".join(
                            f"- {m.content[:200]}" for m in injected[:5]
                        )
                        for i, msg in enumerate(current_messages):
                            if msg.get("role") == "system":
                                current_messages[i] = {
                                    **msg,
                                    "content": msg["content"] + memory_context,
                                }
                                break
                except Exception:
                    pass
            context_compactor = ContextCompactor(
                context_window=context_manager.context_window,
                workspace=cwd,
                memory_manager=memory_mgr,
                estimate_fn=estimate_message_tokens,
                config=compact_config,
            )
            context_cybernetics = ContextCyberneticsOrchestrator(
                context_compactor,
                kp=2.0, ki=0.15, kd=0.3,
                pid_setpoint=0.70,
                base_threshold=0.85,
                safety_margin_turns=3,
                enabled=True,
            )
            if prelude.task and hasattr(prelude.task, 'parsed_intent') and prelude.task.parsed_intent:
                context_cybernetics.set_intent(str(prelude.task.parsed_intent.intent_type))
            logger.info("ContextCybernetics initialized: PID control loop + predictive guard")
            if orch:
                orch.context_compactor = context_compactor
                orch.context_cybernetics = context_cybernetics

        # 初始化自愈引擎（接收 cybernetics 引用用于 CONTEXT_OVERFLOW 委托）
        if orch:
            orch.wire_healing(tool_scheduler, context_compactor)
            self_healing_engine = orch.healing
        else:
            self_healing_engine = SelfHealingEngine(
                orchestrator=context_cybernetics,
                tool_scheduler=tool_scheduler,
                compactor=context_compactor,
            )
        logger.info("Self-healing engine initialized: automated recovery + compaction delegation")

        # ── Micro-compaction + circuit breaker (CC-style layered defense) ─────
        logger.info("Micro-compactor + circuit breaker initialized for layered context defense")

        # 初始化成本控制闭环 (CostTracker → PID → ToolResultBudgetManager)
        cost_control = orch.cost_control if orch else None
        if cost_control is None:
            cost_control = CostControlLoop(
                target_cost_per_min=0.50,
                kp=1.5, ki=0.08, kd=0.2,
                enabled=True,
            )
        if orch:
            orch.cost_control = cost_control
        logger.info("CostControlLoop initialized: BudgetPIDController for cost regulation")

    # 检查上下文状态 + 运行 Claude Code-style 预请求优化管线
    if context_manager:
        context_manager.messages = current_messages
        stats = context_manager.get_stats()
        logger.info("Context: %d tokens (%.0f%%), %d messages",
                   stats.total_tokens, stats.usage_percentage, stats.messages_count)

        # ── Layer 1: Micro-compaction (lightest defense) ───────────────────
        current_messages, mc_stats = micro_compactor.compact(current_messages)
        if mc_stats.reason != "no_action":
            context_manager.messages = current_messages
            logger.info(
                "MicroCompact: %s — %d → %d messages",
                mc_stats.reason,
                mc_stats.messages_before,
                mc_stats.messages_after,
            )

        # 运行控制论闭环优化管线 (Sense → Predict → Control → Act → Learn)
        if context_cybernetics:
            if cost_control:
                est_cost = stats.total_tokens * 0.000015
                adj = cost_control.run(
                    cost_usd=est_cost,
                    total_tokens=stats.total_tokens,
                    total_calls=max(turn_state.step, 1),
                )
                if context_compactor and hasattr(context_compactor, '_tool_budget') and context_compactor._tool_budget:
                    cost_control.apply_to_budget_manager(context_compactor._tool_budget)
                elif adj and adj.budget_multiplier < 0.8:
                    logger.warning(
                        "CostControl: budget tightened (mult=%.2f reason=%s) but no compactor active",
                        adj.budget_multiplier, adj.reason,
                    )

            if compaction_breaker.is_allowed():
                try:
                    cyber_messages, cyber_result, cyber_action = context_cybernetics.run_cycle(
                        current_messages,
                        error_rate=float(turn_state.tool_error_count) / max(turn_state.step, 1) if turn_state.step > 0 else 0.0,
                        avg_latency=turn_state.step * 2.0,
                        turn_id=turn_state.step,
                    )
                except Exception as exc:
                    compaction_breaker.record_failure()
                    logger.warning("Cybernetics compaction raised: %s", exc)
                    cyber_result = None
                if cyber_result and cyber_result.effective:
                    compaction_breaker.record_success()
                    current_messages = cyber_messages
                    context_manager.messages = current_messages
                    logger.info(
                        "Cybernetics[%s]: %s intensity=%.2f freed=%d tokens [%s]",
                        cyber_action.reason if cyber_action else "unknown",
                        cyber_result.strategy.value,
                        cyber_action.compaction_intensity if cyber_action else 0,
                        cyber_result.tokens_freed,
                        cyber_result.summary_text[:80] if cyber_result.summary_text else "",
                    )
            else:
                logger.warning("Cybernetics compaction blocked by circuit breaker")
        elif context_compactor:
            if compaction_breaker.is_allowed():
                try:
                    compaction_result = context_compactor.process_request(current_messages)
                except Exception as exc:
                    compaction_breaker.record_failure()
                    logger.warning("Compactor raised: %s", exc)
                    compaction_result = None
                if compaction_result and compaction_result.effective:
                    compaction_breaker.record_success()
                    current_messages = compaction_result.messages
                    context_manager.messages = current_messages
                    logger.info(
                        "ContextCompactor: %s freed %d tokens [%s]",
                        compaction_result.strategy.value,
                        compaction_result.tokens_freed,
                        compaction_result.summary_text[:80],
                    )
            else:
                logger.warning("Compactor blocked by circuit breaker")
        elif context_manager.should_auto_compact():
            if compaction_breaker.is_allowed():
                try:
                    logger.warning("Context near limit, auto-compacting...")
                    current_messages = getattr(context_manager, 'compact_messages', lambda: current_messages)()
                    compaction_breaker.record_success()
                except Exception as exc:
                    compaction_breaker.record_failure()
                    logger.warning("Auto-compact failed: %s", exc)
                if on_assistant_message:
                    on_assistant_message(context_manager.get_context_summary())
            else:
                logger.warning("Auto-compact blocked by circuit breaker")

    try:
        # Recurrent kernel: repeated think/act/observe iterations over one turn.
        while turn_state.has_remaining_steps():
            step = turn_state.begin_step()
            previous_policy = turn_state.step_policy
            current_policy = derive_turn_step_policy(turn_state)
            policy_message = render_turn_policy_message(
                previous_policy=previous_policy,
                current_policy=current_policy,
            )
            if policy_message:
                turn_state.set_progress_summary(policy_message)
                emit_runtime_event(category="phase", message=policy_message)
                logger.info("Turn policy update: %s", policy_message)
            if (
                current_policy.should_compact_aggressively
                and context_manager
                and context_manager.should_auto_compact()
                and compaction_breaker.is_allowed()
            ):
                try:
                    current_messages = getattr(context_manager, 'compact_messages', lambda: current_messages)()
                    compaction_breaker.record_success()
                except Exception as exc:
                    compaction_breaker.record_failure()
                    logger.warning("Aggressive compaction failed: %s", exc)
                emit_runtime_event(
                    category="compaction",
                    message="Compacted context for the current runtime phase.",
                )
            protected_context = get_working_memory().get_protected_content()
            turn_state.stable_task_pack = build_stable_task_pack(
                task=prelude.task,
                task_metadata=prelude.task_metadata,
                protected_context=protected_context,
                task_graph=prelude.task_graph,
                task_slot_key=prelude.task_slot_key,
                latest_tool_result_summary=turn_state.latest_tool_result_summary,
                progress_state=turn_state.progress_state,
                verification_state=turn_state.verification_state,
                budget_signals=turn_state.budget_signals,
            )
            if turn_state.stable_task_pack:
                stable_text = turn_state.stable_task_pack.to_protected_text()
                current_messages = _upsert_stable_task_state_message(
                    current_messages,
                    stable_text,
                )
                if runtime_profile.name == "single-deep":
                    protect_context(
                        content=stable_text,
                        entry_type="active_task",
                        ttl_seconds=runtime_profile.working_memory_ttl_seconds,
                        importance=runtime_profile.working_memory_importance,
                    )
                if context_manager:
                    context_manager.messages = current_messages

            # Hook: agent turn started
            fire_hook_sync(HookEvent.AGENT_START, step=step, cwd=cwd)

            # 高级控制论闭环（每个 step 开始时执行）
            if enable_work_chain and orch:
                orch.step_start(
                    context_manager=context_manager,
                    step=step,
                    tool_error_count=turn_state.tool_error_count,
                    saw_tool_result=turn_state.saw_tool_result,
                )
            elif enable_work_chain:
                # 状态观测：通过可测量输出估计系统内部状态
                if state_observer:
                    measurement = MeasurementVector(
                        timestamp=time.time(),
                        response_time=step * 2.0,  # 估算响应时间
                        success_rate=1.0 - (turn_state.tool_error_count / max(step, 1)),
                        context_length=context_manager.get_stats().total_tokens if context_manager else 0,
                        error_count=turn_state.tool_error_count,
                        tool_calls=0,
                    )
                    observed_state = state_observer.update(measurement)

                    # 将 Kalman 估计值输入到控制器
                    if observed_state.confidence > 0.4:
                        if observed_state.internal_load > 0.8:
                            logger.info(
                                "StateObserver: high internal_load=%.2f, reduce concurrency",
                                observed_state.internal_load,
                            )
                        if observed_state.hidden_errors > 0.5 and self_healing_engine:
                            self_healing_engine.detect_and_heal({
                                "error_rate": observed_state.hidden_errors * 5.0,
                                "context_usage": observed_state.context_pressure,
                            })
                        if observed_state.system_degradation > 0.4:
                            logger.warning(
                                "StateObserver: system degradation=%.2f confidence=%.2f",
                                observed_state.system_degradation,
                                observed_state.confidence,
                            )

                # 预测控制：预测未来趋势并提前调整
                if predictive_controller:
                    if context_manager:
                        stats = context_manager.get_stats()
                        predictive_controller.update("context_usage", stats.usage_percentage / 100.0)
                    predictive_controller.update("error_rate", turn_state.tool_error_count / max(step, 1))

                    if step > 2:
                        actions = predictive_controller.generate_predictive_actions()
                        if actions and actions[0].urgency > 0.7:
                            action = actions[0]
                            logger.info(
                                "Predictive action: %s urgency=%.2f horizon=%s",
                                action.recommended_action, action.urgency,
                                getattr(action, 'horizon', 'unknown'),
                            )
                            # Execute predictive actions via dispatch
                            dispatch: dict[str, Callable[[], None]] = {
                                "trigger_compaction": lambda: (
                                    context_cybernetics.try_reactive_recover(current_messages, "predictive")
                                    if context_cybernetics else None
                                ),
                                "enable_safe_mode": lambda: logger.info(
                                    "Predictive: safe_mode recommended (reduce concurrency, extend timeouts)"
                                ),
                                "reduce_concurrency": lambda: logger.info(
                                    "Predictive: reduce_concurrency recommended"
                                ),
                            }
                            handler = dispatch.get(action.recommended_action)
                            if handler:
                                try:
                                    handler()
                                except Exception as exc:
                                    logger.warning(
                                        "Predictive action %s failed: %s",
                                        action.recommended_action, exc,
                                    )
                            # Also run self-healing for corroboration
                            if self_healing_engine:
                                healing_actions = self_healing_engine.detect_and_heal({
                                    "context_usage": stats.usage_percentage / 100.0 if context_manager else 0.0,
                                    "error_rate": turn_state.tool_error_count / max(step, 1),
                                })
                                if healing_actions:
                                    logger.info("Self-healing: %s", healing_actions[0].strategy)

            if metrics_collector:
                metrics_collector.start_turn(step)

            next_step: AgentStep
            try:
                # ── Layer 0: Preemptive context guard (CC-style blocking limit)
                if context_manager:
                    cm_stats = context_manager.get_stats()
                    if _is_at_blocking_limit(
                        cm_stats.total_tokens,
                        context_manager.context_window,
                    ):
                        blocking_msg = (
                            f"Context near limit ({cm_stats.total_tokens} / "
                            f"{context_manager.context_window} tokens). "
                            "Use /compact manually, or reduce task scope."
                        )
                        logger.warning("Preemptive guard: %s", blocking_msg)
                        emit_runtime_event(
                            category="stop",
                            message=blocking_msg,
                            stop_reason="blocked",
                        )
                        if on_assistant_message:
                            on_assistant_message(blocking_msg)
                        current_messages.append(
                            {"role": "assistant", "content": blocking_msg}
                        )
                        return current_messages

                next_step = _model_next(
                    model,
                    current_messages,
                    on_stream_chunk=on_assistant_stream_chunk,
                    on_thinking_chunk=on_thinking_chunk,
                    store=store,
                )
            except KeyboardInterrupt:
                raise  # Let Ctrl-C propagate
            except ConnectionError as error:
                fallback = f"Network error (connection failed or dropped): {error}"
                logger.error("Model API connection error: %s", error)
                turn_state.set_stop_reason("blocked")
                emit_runtime_event(
                    category="stop",
                    message=fallback,
                    emit_progress=False,
                    stop_reason="blocked",
                )
                if on_assistant_message:
                    on_assistant_message(fallback)
                current_messages.append({"role": "assistant", "content": fallback})
                if metrics_collector:
                    metrics_collector.end_turn(total_tokens=0)
                return current_messages
            except TimeoutError as error:
                fallback = f"Model API timeout: {error}"
                logger.error("Model API timeout: %s", error)
                turn_state.set_stop_reason("blocked")
                emit_runtime_event(
                    category="stop",
                    message=fallback,
                    emit_progress=False,
                    stop_reason="blocked",
                )
                if on_assistant_message:
                    on_assistant_message(fallback)
                current_messages.append({"role": "assistant", "content": fallback})
                if metrics_collector:
                    metrics_collector.end_turn(total_tokens=0)
                return current_messages
            except Exception as error:
                # Catch-all for unexpected errors (rate limit, auth, server 5xx, etc.)
                error_type = type(error).__name__
                active_model_id = _infer_active_model_id(model, runtime, error)
                fallback = _summarize_model_api_failure(
                    error_type=error_type,
                    error=error,
                    active_model_id=active_model_id,
                    runtime=runtime,
                )
                logger.error("Model API error (%s): %s", error_type, error)

                # Reactive Compact: 控制论恢复路径
                error_str = str(error).lower()
                needs_recovery = "prompt" in error_str and ("too long" in error_str or "exceeds" in error_str)
                if context_cybernetics and needs_recovery:
                    recovered_messages, recovery_result = context_cybernetics.try_reactive_recover(current_messages, error_str)
                    if recovery_result and recovery_result.effective:
                        current_messages = recovered_messages
                        if context_manager:
                            context_manager.messages = current_messages
                        logger.info(
                            "Cybernetics Reactive recovered: freed %d tokens",
                            recovery_result.tokens_freed,
                        )
                        continue
                elif context_compactor and needs_recovery:
                    recovery_result = context_compactor.reactive_recover(current_messages, error_str)
                    if recovery_result and recovery_result.effective:
                        current_messages = recovery_result.messages
                        if context_manager:
                            context_manager.messages = current_messages
                        logger.info(
                            "Reactive Compact recovered: freed %d tokens",
                            recovery_result.tokens_freed,
                        )
                        continue

                # ModelSwitcher: 尝试切换到备用模型并重试
                if model_switcher and "rate" not in error_str and _should_attempt_model_fallback(error_str):
                    try:
                        if hasattr(model_switcher, "sync_current_model"):
                            model_switcher.sync_current_model(active_model_id, adapter=model)
                        if hasattr(model_switcher, "record_runtime_failure"):
                            model_switcher.record_runtime_failure(active_model_id)
                        if runtime is not None:
                            runtime["recentFailures"] = int(runtime.get("recentFailures", 0) or 0) + 1
                        switch_result = model_switcher.switch_to(
                            "",  # Let switcher pick fallback
                            reason=f"{error_type}: {error_str[:80]}",
                        )
                        if switch_result.success and switch_result.adapter is not None:
                            model = switch_result.adapter
                            fallback_message = (
                                f"Model fallback: switched from {switch_result.old_model} "
                                f"to {switch_result.new_model} after {error_type}."
                            )
                            logger.info(
                                "ModelSwitcher: switched to %s, retrying with new adapter",
                                switch_result.new_model,
                            )
                            emit_runtime_event(
                                category="recovery",
                                message=fallback_message,
                            )
                            continue
                        fallback = _summarize_model_api_failure(
                            error_type=error_type,
                            error=error,
                            active_model_id=active_model_id,
                            fallback_errors=switch_result.errors,
                            runtime=runtime,
                        )
                    except Exception:
                        pass

                if on_assistant_message:
                    on_assistant_message(fallback)
                turn_state.set_stop_reason("blocked")
                emit_runtime_event(
                    category="stop",
                    message=fallback,
                    emit_progress=False,
                    stop_reason="blocked",
                )
                current_messages.append({"role": "assistant", "content": fallback})
                if metrics_collector:
                    metrics_collector.end_turn(total_tokens=0)
                return current_messages

            if next_step.type == "assistant":
                is_empty = _is_empty_assistant_response(next_step.content)
                diagnostics = next_step.diagnostics
                assistant_decision = decide_assistant_turn(
                    turn_state=turn_state,
                    step_content=next_step.content,
                    step_kind=getattr(next_step, "kind", None),
                    stop_reason=diagnostics.stopReason if diagnostics else None,
                    block_types=diagnostics.blockTypes if diagnostics else None,
                    ignored_block_types=diagnostics.ignoredBlockTypes if diagnostics else None,
                    is_empty=is_empty,
                    treat_as_progress=(
                        not is_empty
                        and _should_treat_assistant_as_progress(
                            kind=getattr(next_step, "kind", None),
                            content=next_step.content,
                            saw_tool_result=turn_state.saw_tool_result,
                        )
                    ),
                    is_recoverable_thinking_stop=_is_recoverable_thinking_stop(
                        is_empty=is_empty,
                        stop_reason=diagnostics.stopReason if diagnostics else None,
                        ignored_block_types=diagnostics.ignoredBlockTypes if diagnostics else None,
                    ),
                    format_diagnostics=_format_diagnostics,
                    nudge_continue=NUDGE_CONTINUE,
                    nudge_after_tool_result=NUDGE_AFTER_TOOL_RESULT,
                    resume_after_pause=RESUME_AFTER_PAUSE,
                    resume_after_max_tokens=RESUME_AFTER_MAX_TOKENS,
                    nudge_after_empty_response=NUDGE_AFTER_EMPTY_RESPONSE,
                    nudge_after_empty_no_tools=NUDGE_AFTER_EMPTY_NO_TOOLS,
                    step_policy=turn_state.step_policy,
                )

                if assistant_decision.kind == "progress":
                    if assistant_decision.assistant_content:
                        turn_state.set_progress_summary(assistant_decision.assistant_content)
                        if assistant_decision.runtime_event_category is not None:
                            emit_runtime_event(
                                category=assistant_decision.runtime_event_category,
                                message=assistant_decision.assistant_content,
                                evidence_summary=(
                                    turn_state.verification_state.evidence_summary
                                    or turn_state.latest_tool_result_summary
                                ),
                            )
                        elif on_progress_message:
                            on_progress_message(assistant_decision.assistant_content)
                        current_messages.append(
                            {
                                "role": "assistant_progress",
                                "content": assistant_decision.assistant_content,
                            }
                        )
                    if assistant_decision.user_content:
                        current_messages.append(
                            {
                                "role": "user",
                                "content": assistant_decision.user_content,
                            }
                        )
                    continue

                if assistant_decision.kind == "retry":
                    if assistant_decision.user_content:
                        current_messages.append(
                            {
                                "role": "user",
                                "content": assistant_decision.user_content,
                            }
                        )
                    continue

                if assistant_decision.kind == "fallback":
                    if assistant_decision.stop_reason == "widen_needed":
                        transitioned = turn_state.activate_widening(
                            extra_steps=runtime_profile.widening_step_bonus,
                        )
                        if transitioned:
                            widening_message = (
                                assistant_decision.assistant_content
                                or "Depth stalled; switching to widened mode."
                            )
                            if turn_state.widening_trigger_reason:
                                widening_message += (
                                    " Escalation trigger: "
                                    f"{turn_state.widening_trigger_reason}."
                                )
                            turn_state.set_progress_summary(
                                "runtime widened after the narrow path stalled"
                            )
                            emit_runtime_event(
                                category="widening",
                                message=widening_message,
                                widening_reason=turn_state.widening_trigger_reason,
                                evidence_summary=turn_state.widening_trigger_evidence,
                            )
                            current_messages.append(
                                {
                                    "role": "assistant_progress",
                                    "content": widening_message,
                                }
                            )
                            current_messages.append(
                                {
                                    "role": "user",
                                    "content": build_widening_transition_nudge(
                                        turn_state.latest_tool_result_summary,
                                        widening_reason=turn_state.widening_trigger_reason,
                                        widening_evidence_summary=turn_state.widening_trigger_evidence,
                                    ),
                                }
                            )
                            continue
                    if assistant_decision.stop_reason:
                        turn_state.set_stop_reason(assistant_decision.stop_reason)
                        emit_runtime_event(
                            category="stop",
                            message=(
                                assistant_decision.assistant_content
                                or "Turn stopped without a final answer."
                            ),
                            emit_progress=False,
                            stop_reason=assistant_decision.stop_reason,
                            evidence_summary=(
                                turn_state.verification_state.evidence_summary
                                or turn_state.latest_tool_result_summary
                            ),
                        )
                    if assistant_decision.assistant_content and on_assistant_message:
                        on_assistant_message(assistant_decision.assistant_content)
                    if assistant_decision.assistant_content:
                        current_messages.append(
                            {
                                "role": "assistant",
                                "content": assistant_decision.assistant_content,
                            }
                        )
                    return current_messages

                if assistant_decision.stop_reason:
                    turn_state.set_stop_reason(assistant_decision.stop_reason)
                    emit_runtime_event(
                        category="stop",
                        message=assistant_decision.assistant_content or "Turn completed.",
                        emit_progress=False,
                        stop_reason=assistant_decision.stop_reason,
                        evidence_summary=(
                            turn_state.verification_state.evidence_summary
                            or turn_state.latest_tool_result_summary
                        ),
                    )
                if model_switcher and hasattr(model_switcher, "clear_runtime_failures"):
                    model_switcher.clear_runtime_failures()
                if assistant_decision.assistant_content:
                    turn_state.set_progress_summary("assistant finalized the turn")
                    if on_assistant_message:
                        on_assistant_message(assistant_decision.assistant_content)
                    current_messages.append(
                        {
                            "role": "assistant",
                            "content": assistant_decision.assistant_content,
                        }
                    )
                if assistant_decision.protect_final_answer and assistant_decision.assistant_content:
                    protect_context(
                        content=assistant_decision.assistant_content[:500],
                        entry_type="key_decision",
                        ttl_seconds=runtime_profile.working_memory_ttl_seconds,
                        importance=runtime_profile.working_memory_importance,
                    )
                return current_messages

            if next_step.content:
                role = "assistant_progress" if next_step.contentKind == "progress" else "assistant"
                if role == "assistant_progress":
                    turn_state.set_progress_summary(next_step.content)
                    if on_progress_message:
                        on_progress_message(next_step.content)
                    current_messages.append({"role": role, "content": next_step.content})
                    current_messages.append(
                        {
                            "role": "user",
                            "content": NUDGE_CONTINUE,
                        }
                    )
                else:
                    turn_state.set_progress_summary(next_step.content)
                    if on_assistant_message:
                        on_assistant_message(next_step.content)
                    current_messages.append({"role": role, "content": next_step.content})

            if not next_step.calls and next_step.content and next_step.contentKind != "progress":
                turn_state.set_stop_reason("done")
                emit_runtime_event(
                    category="stop",
                    message=next_step.content,
                    emit_progress=False,
                    stop_reason="done",
                    evidence_summary=(
                        turn_state.verification_state.evidence_summary
                        or turn_state.latest_tool_result_summary
                    ),
                )
                return current_messages

            # --- Concurrent tool execution ---
            # Classify calls into concurrent-safe (read-only) vs serial (writes/commands)
            calls = next_step.calls
            _results: list[tuple[dict, ToolResult]] = []

            if len(calls) <= 1:
                # Single call — no benefit from concurrency, run directly
                call = calls[0]
                if metrics_collector:
                    metrics_collector.start_tool(call["toolName"])
                result = _execute_single_tool(
                    call, tools, cwd, permissions, session, runtime, store, step,
                    on_tool_start, on_tool_result, tool_scheduler,
                )
                if metrics_collector:
                    metrics_collector.end_tool(
                        success=result.ok,
                        error=result.output if not result.ok else "",
                    )
                _results.append((call, result))
            else:
                # Multiple calls — use ToolScheduler for intelligent partitioning
                concurrent_calls, serial_calls = tool_scheduler.schedule_calls(calls, tools)

                _results.clear()  # Reuse outer declaration

                # Phase 1: Run all concurrent-safe tools in parallel
                if concurrent_calls:
                    max_workers = tool_scheduler.get_recommended_max_workers(
                        concurrent_calls,
                        error_rate=turn_state.tool_error_count / max(step, 1),
                        avg_latency=step * 2.0,
                        recent_failures=turn_state.tool_error_count,
                    )
                    # Apply cybernetic concurrency cap if FeedbackController reduced parallelism
                    force_cap = getattr(tool_scheduler, '_force_max_workers', None)
                    if force_cap:
                        max_workers = min(max_workers, force_cap)
                    if tool_scheduler.last_decision:
                        logger.info(
                            "ToolSchedulerController: workers=%d multiplier=%.2f cooldown=%.2fs [%s]",
                            max_workers,
                            tool_scheduler.last_decision.concurrency_multiplier,
                            tool_scheduler.last_decision.cooldown_seconds,
                            ", ".join(tool_scheduler.last_decision.reasons or []),
                        )
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=max_workers,
                        thread_name_prefix="mc-tool",
                    ) as pool:
                        future_to_call = {
                            pool.submit(
                                _execute_single_tool,
                                call, tools, cwd, permissions, session, runtime, None, step,
                                None, None, tool_scheduler,  # No UI callbacks during concurrent phase
                            ): call
                            for call in concurrent_calls
                        }
                        for future in concurrent.futures.as_completed(future_to_call):
                            call = future_to_call[future]
                            try:
                                result = future.result()
                            except Exception as exc:
                                result = ToolResult(ok=False, output=f"Concurrent execution error: {exc}")
                            _results.append((call, result))

                # Phase 2: Run serial tools sequentially (in original order)
                if serial_calls:
                    for call in serial_calls:
                        if metrics_collector:
                            metrics_collector.start_tool(call["toolName"])
                        result = _execute_single_tool(
                            call, tools, cwd, permissions, session, runtime, store, step,
                            on_tool_start, on_tool_result, tool_scheduler,
                        )
                        if metrics_collector:
                            metrics_collector.end_tool(
                                success=result.ok,
                                error=result.output if not result.ok else "",
                            )
                        _results.append((call, result))
                        # If a serial tool awaits user, return immediately
                        if result.awaitUser:
                            # Still need to process remaining results for messages
                            break
            
            # Process all results and build messages (preserve original call order)
            call_order = {call["id"]: idx for idx, call in enumerate(calls)}
            _results.sort(key=lambda pair: call_order.get(pair[0]["id"], 999))
            
            for call, result in _results:
                # Fire hooks and UI callbacks for concurrent calls (deferred)
                tool_def = tools.find(call["toolName"])
                is_concurrent = tool_def and tool_def.is_concurrency_safe and len(calls) > 1
                
                if is_concurrent:
                    # Deferred UI callbacks for concurrent tools
                    if on_tool_start:
                        on_tool_start(call["toolName"], call["input"])
                    if store:
                        store.set_state(set_busy(call["toolName"]))
                        store.set_state(increment_tool_calls())
                        store.set_state(set_idle())
                    # Hook: pre-tool-use (fire after the fact for concurrent tools)
                    fire_hook_sync(
                        HookEvent.PRE_TOOL_USE,
                        tool_name=call["toolName"],
                        tool_input=call["input"],
                        step=step,
                    )
                
                # Hook: post-tool-use
                fire_hook_sync(
                    HookEvent.POST_TOOL_USE,
                    tool_name=call["toolName"],
                    tool_output=result.output,
                    is_error=not result.ok,
                    step=step,
                )
                
                if is_concurrent:
                    if on_tool_result:
                        on_tool_result(call["toolName"], result.output, not result.ok)
                
                tool_summary = f"{call['toolName']}: {result.output[:200]}"
                turn_state.record_tool_result(result.ok, summary=tool_summary)
                tool_decision = decide_tool_turn(
                    tool_name=call["toolName"],
                    result_output=result.output,
                    await_user=result.awaitUser,
                )
                if tool_decision.progress_summary:
                    turn_state.set_progress_summary(tool_decision.progress_summary)
                if not result.ok:
                    # Use ErrorClassifier for intelligent error handling
                    classified = ErrorClassifier.classify(result.output, tool_name=call["toolName"])
                    nudge = NudgeGenerator.generate(classified, retry_count=turn_state.tool_error_count)
                    # Append nudge to tool result content for model context
                    result_output = result.output + "\n\n[System note: " + nudge + "]"
                else:
                    result_output = result.output
                    # Increased nudge frequency: provide steering even on success
                    if getattr(tool_scheduler, '_force_nudge_frequency', False):
                        success_nudge = (
                            f"Tool '{call['toolName']}' succeeded. "
                            "The system is under stability pressure — prefer smaller, "
                            "incremental steps and verify each result before proceeding."
                        )
                        result_output = result.output + "\n\n[System note: " + success_nudge + "]"

                # Record conflicts between concurrent tools if both failed
                if not result.ok and len(calls) > 1:
                    for other_call, other_result in _results:
                        if other_call["id"] == call["id"]:
                            continue
                        if not other_result.ok:
                            tool_scheduler.record_conflict(call["toolName"], other_call["toolName"])

                # ReadDedup: 去重相同文件的重复读取，节省上下文空间
                if (
                    context_compactor
                    and result.ok
                    and call.get("toolName") == "read_file"
                ):
                    file_path = call.get("input", {}).get("path", "")
                    if file_path:
                        dedup_mgr = context_compactor.read_dedup
                        if dedup_mgr.should_dedup(file_path, result_output):
                            result_output = dedup_mgr.get_stub(file_path)
                            logger.debug("ReadDedup replaced content for %s (stub)", file_path)
                        dedup_mgr.register_read(file_path, result_output, len(current_messages))

                current_messages.append(
                    {
                        "role": "assistant_tool_call",
                        "toolUseId": call["id"],
                        "toolName": call["toolName"],
                        "input": call["input"],
                    }
                )
                current_messages.append(
                    {
                        "role": "tool_result",
                        "toolUseId": call["id"],
                        "toolName": call["toolName"],
                        "content": result_output,
                        "isError": not result.ok,
                    }
                )
                if tool_decision.kind == "await_user":
                    if tool_decision.stop_reason:
                        turn_state.set_stop_reason(tool_decision.stop_reason)
                        emit_runtime_event(
                            category="stop",
                            message=tool_decision.assistant_content or result_output,
                            emit_progress=False,
                            stop_reason=tool_decision.stop_reason,
                            evidence_summary=turn_state.latest_tool_result_summary,
                        )
                    if tool_decision.assistant_content and on_assistant_message:
                        on_assistant_message(tool_decision.assistant_content)
                    current_messages.append(
                        {
                            "role": "assistant",
                            "content": tool_decision.assistant_content or result_output,
                        }
                    )
                    if metrics_collector:
                        metrics_collector.end_turn(total_tokens=0)
                    return current_messages

            # 工具执行完成后的控制论反馈
            if enable_work_chain:
                # 多变量解耦：消除工具间的耦合影响
                if decoupling_controller:
                    decoupling_controller.record_measurement({
                        "token_usage_to_latency": (
                            context_manager.get_stats().usage_percentage / 100.0 if context_manager else 0.0,
                            step * 2.0 / 60.0,
                        ),
                        "context_pressure_to_errors": (
                            context_manager.get_stats().usage_percentage / 100.0 if context_manager else 0.0,
                            turn_state.tool_error_count / max(step, 1),
                        ),
                    })
                    decoupling_controller.compute_decoupling_matrix()

                if orch:
                    step_summary = orch.step_end(
                        tool_scheduler=tool_scheduler,
                        context_manager=context_manager,
                        step=step,
                        tool_error_count=turn_state.tool_error_count,
                        saw_tool_result=turn_state.saw_tool_result,
                        max_steps=turn_state.max_steps,
                    )
                    turn_state.max_steps = _apply_control_signal(
                        control_signal=step_summary.get("control_signal"),
                        system_state=step_summary.get("system_state"),
                        max_steps=turn_state.max_steps,
                        tool_scheduler=tool_scheduler,
                        context_compactor=context_compactor,
                        model_switcher=model_switcher,
                        feedback_controller=feedback_controller,
                    )
                else:
                    # 自愈检测：检测并修复故障
                    if self_healing_engine:
                        metrics_for_healing = {
                            "error_rate": turn_state.tool_error_count / max(step, 1),
                            "context_usage": context_manager.get_stats().usage_percentage / 100.0 if context_manager else 0.0,
                            "oscillation_index": feedback_controller._compute_oscillation() if feedback_controller else 0.0,
                        }
                        healing_actions = self_healing_engine.detect_and_heal(metrics_for_healing)
                        if healing_actions:
                            logger.info("Self-healing triggered: %s", healing_actions[0].strategy)

                    # 进度控制：检测任务是否卡住或完成
                    if progress_controller:
                        progress_signal = ProgressSignal(
                            total_steps=turn_state.max_steps,
                            completed_steps=step - turn_state.tool_error_count,
                            failed_steps=turn_state.tool_error_count,
                            tool_calls=step,
                            tool_errors=turn_state.tool_error_count,
                            output_changed=turn_state.saw_tool_result,
                            elapsed_seconds=step * 2.0,
                            max_steps=turn_state.max_steps,
                        )
                        progress_decision = progress_controller.decide(progress_signal)
                        if progress_decision.action in (ProgressAction.STOP, ProgressAction.REQUEST_CONFIRMATION):
                            logger.warning(
                                "ProgressController: action=%s health=%.2f stall=%.2f reasons=%s",
                                progress_decision.action.value,
                                progress_decision.health_score,
                                progress_decision.stall_score,
                                ", ".join(progress_decision.reasons),
                            )

            # Tool execution completed for this step; ask the model for the next turn
            # instead of falling through to the max-step fallback.
            if metrics_collector:
                total_tokens = sum(
                    estimate_message_tokens(m) for m in current_messages
                ) if context_manager else 0
                metrics_collector.end_turn(total_tokens=total_tokens)
            continue

        fallback = "Reached the maximum tool step limit for this turn."
        turn_state.set_stop_reason("max_steps")
        emit_runtime_event(
            category="stop",
            message=fallback,
            emit_progress=False,
            stop_reason="max_steps",
            evidence_summary=(
                turn_state.verification_state.evidence_summary
                or turn_state.latest_tool_result_summary
            ),
        )
        if on_assistant_message:
            on_assistant_message(fallback)
        current_messages.append({"role": "assistant", "content": fallback})
        return current_messages
    finally:
        # Emit the terminal snapshot before coda bookkeeping so every return
        # path (including an exception) produces exactly one structured Done
        # event with the messages accumulated by the loop.
        publish_turn_event(
            TurnEvent.completed(
                step=turn_state.step or None,
                messages=current_messages,
                stop_reason=str(turn_state.stop_reason or ""),
            )
        )
        # Coda: finalize metrics, work-chain bookkeeping, and control summaries.
        fire_hook_sync(
            HookEvent.AGENT_STOP,
            step=turn_state.step,
            tool_errors=turn_state.tool_error_count,
        )
        step = turn_state.step
        if metrics_collector and metrics_collector._current_turn is not None:
            total_tokens = sum(
                estimate_message_tokens(m) for m in current_messages
            ) if context_manager else 0
            metrics_collector.end_turn(total_tokens=total_tokens)

        context_usage = 0.0
        if context_manager:
            try:
                context_usage = context_manager.get_stats().usage_percentage / 100.0
            except Exception:
                context_usage = 0.0
        coda_summary = build_turn_coda_summary(
            turn_state=turn_state,
            context_usage=context_usage,
        )

        if enable_work_chain and prelude.task:
            finalize_work_chain_task(
                task=prelude.task,
                auditor=prelude.auditor,
                coda_summary=coda_summary,
                success_outcome=DecisionOutcome.SUCCESS,
                failure_outcome=DecisionOutcome.FAILURE,
            )

            if prelude.task_graph and prelude.task_slot_key:
                try:
                    if coda_summary.task_state is TaskState.COMPLETED:
                        prelude.task_graph.complete_task(
                            prelude.task_slot_key,
                            result=prelude.task.result_summary,
                        )
                    elif coda_summary.task_state is TaskState.PAUSED:
                        slot = prelude.task_graph.slots.get(prelude.task_slot_key)
                        if slot is not None:
                            slot.state = GraphTaskState.QUEUED
                            slot.result = prelude.task.result_summary
                            prelude.task_graph.updated_at = time.time()
                    else:
                        prelude.task_graph.fail_task(
                            prelude.task_slot_key,
                            prelude.task.result_summary,
                        )
                except Exception:
                    logger.debug("TaskGraph finalization skipped", exc_info=True)

            logger.info(
                "Work chain completed: task=%s state=%s stop_reason=%s steps=%d errors=%d",
                prelude.task.id,
                prelude.task.state.value,
                coda_summary.stop_reason,
                turn_state.step,
                turn_state.tool_error_count,
            )

            # 任务后自省：提取经验教训
            if orch and prelude.task:
                try:
                    execution_trace: list[dict[str, Any]] = [
                        {"type": "tool_call", "count": turn_state.step},
                        {
                            "type": "error",
                            "count": turn_state.tool_error_count,
                            "content": f"{turn_state.tool_error_count} errors",
                        }
                        if turn_state.tool_error_count > 0
                        else {},
                        {"type": "assistant", "steps": turn_state.step},
                    ]
                    orch.reflect_on_task(
                        task_description=(
                            prelude.task.raw_input
                            if hasattr(prelude.task, "raw_input")
                            else str(prelude.task.id)
                        ),
                        step=turn_state.step,
                        tool_error_count=turn_state.tool_error_count,
                        execution_trace=execution_trace,
                    )
                except Exception:
                    pass
            elif reflection_engine and prelude.task:
                try:
                    _trace: list[dict[str, Any]] = [
                        {"type": "tool_call", "count": turn_state.step},
                        {
                            "type": "error",
                            "count": turn_state.tool_error_count,
                            "content": f"{turn_state.tool_error_count} errors",
                        }
                        if turn_state.tool_error_count > 0
                        else {},
                        {"type": "assistant", "steps": turn_state.step},
                    ]
                    reflection = reflection_engine.reflect(
                        task_description=(
                            prelude.task.raw_input
                            if hasattr(prelude.task, "raw_input")
                            else str(prelude.task.id)
                        ),
                        execution_trace=execution_trace,
                    )
                    logger.info(
                        "AgentReflection: success=%s confidence=%.2f lessons=%d improvements=%d",
                        reflection.success, reflection.confidence,
                        len(reflection.lessons_learned), len(reflection.suggested_improvements),
                    )
                except Exception:
                    pass

            # 记忆质量反馈：任务成功→注入的记忆 usage_count+1
            if memory_injector and hasattr(memory_injector, '_cached_result'):
                try:
                    from minicode.memory import MemoryScope
                    for mem in memory_injector._cached_result:
                        if not hasattr(mem, 'id'):
                            continue
                        try:
                            _mgr = memory_mgr
                        except NameError:
                            continue
                        for scope_name in ['project', 'local', 'user']:
                            try:
                                scope = MemoryScope(scope_name)
                                if scope in _mgr.memories:
                                    mem_store = _mgr.memories[scope]
                                    if hasattr(mem_store, "_id_index"):
                                        entry = mem_store._id_index.get(mem.id)
                                        if entry:
                                            entry.usage_count += (
                                                2 if turn_state.tool_error_count == 0 else -1
                                            )
                                            entry.last_accessed = time.time()
                                            break
                                        entry.last_accessed = time.time()
                                        break
                            except (ValueError, KeyError):
                                continue
                except Exception:
                    pass

            # 路由反馈学习：记录任务结果以优化未来路由
            if smart_router and prelude.task:
                try:
                    outcome = TaskOutcome(
                        task_text=(
                            prelude.task.raw_input
                            if hasattr(prelude.task, "raw_input")
                            else str(prelude.task.id)
                        ),
                        assigned_model=(
                            model.model_id if hasattr(model, "model_id") else "unknown"
                        ),
                        success=(turn_state.tool_error_count == 0),
                        duration_ms=turn_state.step * 2000.0,
                        cost_usd=0.0,
                        tool_errors=turn_state.tool_error_count,
                        model_switches=model_switcher.switch_count() if model_switcher else 0,
                    )
                    smart_router.learner().record_outcome(outcome)
                except Exception:
                    pass

        # 控制论反馈：记录模式有效性
        if enable_work_chain and feedback_controller and prelude.task:
            pattern_id = (
                f"{prelude.task_metadata.get('intent_type', 'unknown')}_{prelude.task.id}"
            )
            feedback_controller.record_pattern_effectiveness(
                pattern_id, turn_state.tool_error_count == 0
            )

        # 稳定性监测：记录快照
        if stability_monitor:
            from minicode.stability_monitor import MetricSnapshot
            snapshot = MetricSnapshot(
                timestamp=time.time(),
                error_rate=float(turn_state.tool_error_count) / max(turn_state.step, 1),
                avg_latency=step * 2.0,  # 简化估算
                context_usage=context_manager.get_stats().usage_percentage if context_manager else 0.0,
                active_tasks=1,
            )
            stability_monitor.record_snapshot(snapshot)
            if context_cybernetics:
                stability_monitor.feed_orchestrator(context_cybernetics)

        # 高级控制论：最终状态报告
        if enable_work_chain:
            # 状态观测器报告
            if state_observer:
                state_summary = state_observer.get_state_summary()
                logger.info("State observer summary: %s", state_summary)

            # 预测控制器报告
            if predictive_controller:
                pred_summary = predictive_controller.get_prediction_summary()
                logger.info("Prediction summary: accuracy=%s", pred_summary.get("accuracy", {}))

            # 自愈引擎统计
            if self_healing_engine:
                healing_stats = self_healing_engine.get_healing_statistics()
                logger.info("Self-healing stats: %s", healing_stats)

            # 多变量解耦状态
            if decoupling_controller:
                coupling_status = decoupling_controller.get_coupling_status()
                logger.info("Coupling status: strong=%s", coupling_status.get("strong_couplings", []))

        # 上下文管理管线统计 (Claude Code-style + Cybernetics)
        if context_compactor:
            compactor_stats = context_compactor.get_stats()
            logger.info(
                "ContextCompactor: passes=%d persisted=%d dedup=%d "
                "microcompact=%d boundaries=%d circuit=%s",
                compactor_stats["total_passes"],
                compactor_stats["tool_results_persisted"],
                compactor_stats["read_dedup_entries"],
                compactor_stats["microcompact_tokens_cleared"],
                compactor_stats["auto_compact_boundaries"],
                "TRIPPED" if compactor_stats["circuit_breaker_tripped"] else "OK",
            )
        # 控制论闭环统计 (Engineering Cybernetics)
        if context_cybernetics:
            cyber_stats = context_cybernetics.get_stats()
            logger.info(
                "Cybernetics: cycles=%d usage=%.1f%% pid_out=%.2f "
                "predict_overflow=%s urgency=%.2f threshold=%.2f feedback_eff=%.0f%%",
                cyber_stats["cycles_executed"],
                (cyber_stats["sensor"]["current_usage"] or 0) * 100,
                cyber_stats["pid"]["last_output"] or 0,
                cyber_stats["predictor"]["turns_until_overflow"],
                cyber_stats["predictor"]["urgency"] or 0,
                cyber_stats["threshold"]["effective_threshold"] or 0,
                (cyber_stats["feedback"]["effectiveness_rate"] or 0) * 100,
            )
        # 成本控制闭环统计 (BudgetPIDController)
        if cost_control:
            cc_stats = cost_control.get_stats()
            adj = cc_stats.get("adjustment")
            logger.info(
                "CostControl: cycles=%d cost/min=$%.4f pid_out=%.2f "
                "budget_mult=%.2f threshold_mult=%.2f [%s]",
                cc_stats["cycles_executed"],
                cc_stats["sensor"]["cost_per_min"],
                cc_stats["pid"]["last_output"] or 1.0,
                adj["budget_mult"] if adj else 1.0,
                adj["threshold_mult"] if adj else 1.0,
                adj["reason"] if adj else "none",
            )
        # 双层 PID 闭环: Cybernetics → FeedbackController
        if context_cybernetics and feedback_controller:
            system_state = context_cybernetics.to_system_state()
            control_signal = feedback_controller.observe(system_state)
            if control_signal.force_compaction and context_cybernetics.enabled:
                logger.info(
                    "Dual-PID: FeedbackController force_compaction=True, "
                    "stability=%.2f performance=%.2f",
                    system_state.stability_score(),
                    system_state.performance_score(),
                )
            # Apply outer-loop ControlSignal to runtime parameters
            if control_signal.confidence > 0.6:
                if control_signal.limit_max_steps and control_signal.limit_max_steps < max_steps:
                    logger.info(
                        "FeedbackController: limiting max_steps %d → %d",
                        max_steps, control_signal.limit_max_steps,
                    )
                    max_steps = control_signal.limit_max_steps
                if control_signal.adjust_token_budget != 1.0:
                    if context_compactor and hasattr(context_compactor, '_tool_budget') and context_compactor._tool_budget:
                        new_budget = max(
                            1000,
                            int(context_compactor._tool_budget.budget_per_message * control_signal.adjust_token_budget),
                        )
                        context_compactor._tool_budget.budget_per_message = new_budget
                        logger.info(
                            "FeedbackController: token budget adjusted to %d (mult=%.2f)",
                            new_budget, control_signal.adjust_token_budget,
                        )
                if control_signal.reduce_parallelism:
                    # Cap tool concurrency at 2
                    if not hasattr(tool_scheduler, '_force_max_workers'):
                        tool_scheduler._force_max_workers = 2
                    logger.info(
                        "FeedbackController: reduce_parallelism → max_workers=2 "
                        "(oscillation=%.2f)", control_signal.oscillation_index,
                    )
                if control_signal.adjust_concurrency != 0:
                    cap = max(1, 4 + control_signal.adjust_concurrency)
                    tool_scheduler._force_max_workers = cap
                    logger.info(
                        "FeedbackController: adjust_concurrency=%+d → max_workers=%d",
                        control_signal.adjust_concurrency, cap,
                    )
                if control_signal.increase_model_level:
                    logger.info(
                        "FeedbackController: model upgrade recommended (errors=%.2f perf=%.2f)",
                        system_state.error_frequency, system_state.performance_score(),
                    )
                    if model_switcher:
                        if hasattr(model_switcher, '_pending_upgrade'):
                            model_switcher._pending_upgrade = True  # type: ignore[attr-defined]
                if control_signal.decrease_model_level:
                    logger.info(
                        "FeedbackController: model downgrade recommended (efficiency=%.2f)",
                        system_state.token_efficiency,
                    )
                if control_signal.suggest_memory_persistence:
                    logger.info("FeedbackController: persisting working memory")
                    if context_compactor and hasattr(context_compactor, '_tool_budget'):
                        try:
                            context_compactor._tool_budget.flush()
                        except Exception:
                            pass
                if control_signal.recommend_skill_update:
                    logger.info("FeedbackController: skill update recommended (pattern=%.2f)",
                               system_state.pattern_reuse_rate)
                    if not hasattr(tool_scheduler, '_pending_skill_update'):
                        tool_scheduler._pending_skill_update = True

                if control_signal.reduce_tool_timeout:
                    new_timeout = max(5.0, control_signal.reduce_tool_timeout)
                    if hasattr(tool_scheduler, "_force_tool_timeout"):
                        tool_scheduler._force_tool_timeout = new_timeout  # type: ignore[attr-defined]
                    logger.info(
                        "FeedbackController: tool timeout reduced to %.1fs",
                        new_timeout,
                    )
                elif hasattr(tool_scheduler, '_force_tool_timeout'):
                    if hasattr(tool_scheduler, '_force_tool_timeout'):
                        del tool_scheduler._force_tool_timeout

                if control_signal.increase_nudge_frequency:
                    tool_scheduler._force_nudge_frequency = True  # type: ignore[attr-defined]
                    logger.info(
                        "FeedbackController: nudge frequency increased (stability=%.2f)",
                        system_state.stability_score(),
                    )
                elif hasattr(tool_scheduler, '_force_nudge_frequency'):
                    if hasattr(tool_scheduler, '_force_nudge_frequency'):
                        del tool_scheduler._force_nudge_frequency

                if control_signal.promote_pattern:
                    feedback_controller.record_pattern_effectiveness(
                        control_signal.promote_pattern, True
                    )
                    logger.info(
                        "FeedbackController: pattern promoted '%s'",
                        control_signal.promote_pattern,
                    )

                if control_signal.force_compaction and context_compactor:
                    try:
                        compacted = context_compactor.compact_messages() if hasattr(context_compactor, 'compact_messages') else False
                        logger.info(
                            "FeedbackController: forced compaction (%d messages)",
                            len(compacted) if compacted else 0,
                        )
                    except Exception as exc:
                        logger.warning("FeedbackController: forced compaction failed: %s", exc)

            # 自适应PID调参：每20轮自动调节内外环PID参数
            if adaptive_pid_tuner and step > 0 and step % 20 == 0 and feedback_controller:
                try:
                    stability_error = 1.0 - system_state.stability_score()
                    perf_score = system_state.performance_score()
                    tuned = adaptive_pid_tuner.tune(
                        stability_error, dt=1.0, performance_score=perf_score
                    )
                    if tuned and adaptive_pid_tuner._performance_history:
                        recent_perf = adaptive_pid_tuner._performance_history[-5:]
                        avg_perf = sum(recent_perf) / len(recent_perf)
                        if context_cybernetics:
                            cp = context_cybernetics.pid
                            cp.kp = tuned.kp
                            cp.ki = tuned.ki
                            cp.kd = tuned.kd
                            logger.info(
                                "AdaptivePIDTuner: context PID tuned kp=%.3f ki=%.3f kd=%.3f "
                                "method=%s perf=%.2f",
                                tuned.kp, tuned.ki, tuned.kd,
                                adaptive_pid_tuner._active_method.value if hasattr(adaptive_pid_tuner, '_active_method') else 'unknown',
                                avg_perf,
                            )
                except Exception:
                    pass  # 调参失败不能拖垮主循环

        # 总监督层: 汇总局部控制器输出为统一风险视图
        if cybernetic_supervisor:
            supervisor_snapshots = []
            if context_cybernetics:
                supervisor_snapshots.append(
                    cybernetic_supervisor.snapshot_from_context(context_cybernetics.get_stats())
                )
            if cost_control:
                supervisor_snapshots.append(
                    cybernetic_supervisor.snapshot_from_cost(cost_control.get_stats())
                )
            if tool_scheduler.last_decision:
                supervisor_snapshots.append(
                    cybernetic_supervisor.snapshot_from_tool_decision(
                        tool_scheduler.last_decision.to_dict()
                    )
                )
            supervisor_report = cybernetic_supervisor.report(supervisor_snapshots)
            save_supervisor_report(supervisor_report)
            logger.info(
                "CyberneticSupervisor: health=%.2f risk=%s actions=%s",
                supervisor_report.overall_health,
                supervisor_report.risk_level.value,
                "; ".join(supervisor_report.recommended_actions[:3]),
            )
