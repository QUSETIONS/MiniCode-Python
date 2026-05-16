from __future__ import annotations

import concurrent.futures
import inspect
import time
from typing import Any, Callable

from minicode.context_manager import ContextManager, estimate_message_tokens
from minicode.logging_config import get_logger
from minicode.permissions import PermissionManager
from minicode.state import Store, AppState, increment_tool_calls, add_cost, record_api_error, update_context_usage, set_busy, set_idle
from minicode.tooling import ToolContext, ToolRegistry, ToolResult
from minicode.types import AgentStep, ChatMessage, ModelAdapter

# Hooks integration
from minicode.hooks import HookEvent, fire_hook_sync

# Intelligence integration
from minicode.agent_metrics import AgentMetricsCollector
from minicode.agent_intelligence import ErrorClassifier, NudgeGenerator, RecoveryStrategy, ToolScheduler
from minicode.working_memory import protect_context

# Work chain integration
from minicode.intent_parser import parse_intent
from minicode.task_object import build_task, TaskObject, TaskState
from minicode.pipeline_engine import get_pipeline_engine, PipelineEngine
from minicode.capability_registry import get_registry, CapabilityDomain
from minicode.layered_context import ContextBuilder, LayeredContext, ContextLayer
from minicode.decision_audit import get_auditor, DecisionType, DecisionOutcome

# 工程控制论集成
from minicode.feedback_controller import FeedbackController, SystemState
from minicode.feedforward_controller import FeedforwardController, PreemptiveConfig
from minicode.stability_monitor import StabilityMonitor, HealthLevel

# 高级控制论模块
from minicode.adaptive_pid_tuner import AdaptivePIDTuner, PIDParameters
from minicode.state_observer import StateObserver, MeasurementVector, ObservedState
from minicode.decoupling_controller import DecouplingController
from minicode.predictive_controller import PredictiveController, PredictionHorizon
from minicode.self_healing_engine import SelfHealingEngine, FaultType, FaultSeverity

# 上下文管理集成 (Claude Code-style)
from minicode.context_compactor import (
    ContextCompactor,
    AutoCompactConfig,
    CompactTrigger,
    CompactStrategy,
)
from minicode.memory import MemoryManager

logger = get_logger("agent_loop")

# 甯搁噺锛氶伩鍏嶉噸澶嶇殑鎻愮ず鏂囨湰
NUDGE_CONTINUE = (
    "Continue immediately from your <progress> update with concrete tool calls, "
    "code changes, or an explicit <final> answer only if the task is complete."
)

NUDGE_AFTER_TOOL_RESULT = (
    "Continue from your progress update. You have already used tools in this turn, "
    "so treat plain status text as progress, not a final answer. Respond with the "
    "next concrete tool call, code change, or an explicit <final> answer only if "
    "the task is truly complete."
)

NUDGE_AFTER_EMPTY_RESPONSE = (
    "Your last response was empty after recent tool results. Continue immediately "
    "by trying the next concrete step, adapting to any tool errors, or giving an "
    "explicit <final> answer only if the task is complete."
)

NUDGE_AFTER_EMPTY_NO_TOOLS = (
    "Your last response was empty. Continue immediately with concrete tool calls, "
    "code changes, or an explicit <final> answer only if the task is complete."
)

RESUME_AFTER_PAUSE = (
    "Resume from the previous pause and continue immediately with the next concrete "
    "tool call, code change, or an explicit <final> answer only if the task is complete."
)

RESUME_AFTER_MAX_TOKENS = (
    "Your previous response hit max_tokens during thinking before producing the next "
    "actionable step. Resume immediately and continue with the next concrete tool call, "
    "code change, or an explicit <final> answer only if the task is complete."
)


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
            registry.register(metadata, lambda **kw: tools.execute(tool_name, kw, ToolContext()), None)
        except Exception as e:
            logger.debug("Failed to register tool %s as capability: %s", tool_name, e)


def _execute_single_tool(
    call: dict,
    tools: ToolRegistry,
    cwd: str,
    permissions: Any | None,
    runtime: dict | None,
    store: Any | None,
    step: int,
    on_tool_start: Callable[[str, dict], None] | None,
    on_tool_result: Callable[[str, str, bool], None] | None,
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
        
        # Execute the tool (ToolRegistry.execute already has its own safety net)
        result = tools.execute(
            tool_name,
            tool_input,
            ToolContext(cwd=cwd, permissions=permissions, _runtime=runtime),
        )
        
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


def _model_next(
    model: ModelAdapter,
    messages: list[ChatMessage],
    *,
    on_stream_chunk: Callable[[str], None] | None,
    store: Store[AppState] | None,
) -> AgentStep:
    """Call provider adapters with store support while preserving test doubles."""
    if store is None:
        return model.next(messages, on_stream_chunk=on_stream_chunk)

    try:
        signature = inspect.signature(model.next)
    except (TypeError, ValueError):
        return model.next(messages, on_stream_chunk=on_stream_chunk, store=store)

    supports_store = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == "store"
        for parameter in signature.parameters.values()
    )
    if supports_store:
        return model.next(messages, on_stream_chunk=on_stream_chunk, store=store)
    return model.next(messages, on_stream_chunk=on_stream_chunk)


def run_agent_turn(
    *,
    model: ModelAdapter,
    tools: ToolRegistry,
    messages: list[ChatMessage],
    cwd: str,
    permissions: PermissionManager | None = None,
    store: Store[AppState] | None = None,
    max_steps: int = 50,
    on_tool_start: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str, bool], None] | None = None,
    on_assistant_message: Callable[[str], None] | None = None,
    on_progress_message: Callable[[str], None] | None = None,
    on_assistant_stream_chunk: Callable[[str], None] | None = None,
    context_manager: ContextManager | None = None,
    runtime: dict | None = None,
    metrics_collector: AgentMetricsCollector | None = None,
    system_prompt: str = "",
    project_context: str = "",
    enable_work_chain: bool = True,
) -> list[ChatMessage]:
    current_messages = list(messages)
    saw_tool_result = False
    empty_response_retry_count = 0
    recoverable_thinking_retry_count = 0
    tool_error_count = 0
    step = 0

    tool_scheduler = ToolScheduler(metrics_collector=metrics_collector)

    # Initialize work chain if enabled
    task: TaskObject | None = None
    task_metadata: dict = {}
    layered_context: LayeredContext | None = None
    context_builder: ContextBuilder | None = None
    pipeline_engine: PipelineEngine | None = None
    auditor = get_auditor() if enable_work_chain else None

    # 工程控制论控制器初始化
    feedback_controller: FeedbackController | None = None
    feedforward_controller: FeedforwardController | None = None
    stability_monitor: StabilityMonitor | None = None

    # 高级控制论模块
    adaptive_pid_tuner: AdaptivePIDTuner | None = None
    state_observer: StateObserver | None = None
    decoupling_controller: DecouplingController | None = None
    predictive_controller: PredictiveController | None = None
    self_healing_engine: SelfHealingEngine | None = None

    if enable_work_chain:
        task, task_metadata = _build_work_chain_task(current_messages)
        layered_context, context_builder = _build_layered_context(
            current_messages, system_prompt, project_context, task,
        )
        pipeline_engine = get_pipeline_engine()
        _register_tool_capabilities(tools)

        # 初始化反馈控制器（负反馈 + 正反馈）
        feedback_controller = FeedbackController()
        logger.info("Feedback controller initialized: negative + positive feedback loops")

        # 初始化前馈控制器（预判式优化）
        if task:
            feedforward_controller = FeedforwardController()
            preemptive_config = feedforward_controller.preconfigure(task.parsed_intent, task.raw_input)
            risk_assessment = feedforward_controller.assess_risks(task.parsed_intent, preemptive_config)
            logger.info(
                "Feedforward control: config=%s risk=%s",
                preemptive_config.recommended_model, risk_assessment.risk_level,
            )

        # 初始化稳定性监测器（系统观测器）
        stability_monitor = StabilityMonitor(window_size=100)
        logger.info("Stability monitor initialized: real-time health tracking")

        # 初始化自适应PID调参器
        adaptive_pid_tuner = AdaptivePIDTuner()
        logger.info("Adaptive PID tuner initialized: self-tuning control")

        # 初始化状态观测器（卡尔曼滤波）
        state_observer = StateObserver()
        logger.info("State observer initialized: Kalman filter-based estimation")

        # 初始化多变量解耦控制器
        decoupling_controller = DecouplingController()
        logger.info("Decoupling controller initialized: multi-variable control")

        # 初始化预测控制器
        predictive_controller = PredictiveController()
        logger.info("Predictive controller initialized: proactive control")

        # 初始化自愈引擎
        self_healing_engine = SelfHealingEngine()
        logger.info("Self-healing engine initialized: automated recovery")

        # 初始化上下文管理器 (Claude Code-style 三段式)
        context_compactor: ContextCompactor | None = None
        if context_manager:
            compact_config = AutoCompactConfig(
                threshold_ratio=0.85,
                circuit_breaker_limit=3,
                session_memory_enabled=True,
            )
            memory_mgr = MemoryManager(project_root=cwd)
            context_compactor = ContextCompactor(
                context_window=context_manager.context_window,
                workspace=cwd,
                memory_manager=memory_mgr,
                estimate_fn=estimate_message_tokens,
                config=compact_config,
            )
            logger.info("ContextCompactor initialized: Claude Code-style pipeline + MemoryManager linked")

    # 检查上下文状态 + 运行 Claude Code-style 预请求优化管线
    if context_manager:
        context_manager.messages = current_messages
        stats = context_manager.get_stats()
        logger.info("Context: %d tokens (%.0f%%), %d messages",
                   stats.total_tokens, stats.usage_percentage, stats.messages_count)

        # 运行完整预请求优化管线 (Tool Budget → Microcompact → Auto Compact)
        if context_compactor:
            compaction_result = context_compactor.process_request(current_messages)
            if compaction_result.effective:
                current_messages = compaction_result.messages
                context_manager.messages = current_messages
                logger.info(
                    "ContextCompactor: %s freed %d tokens [%s]",
                    compaction_result.strategy.value,
                    compaction_result.tokens_freed,
                    compaction_result.summary_text[:80],
                )
        elif context_manager.should_auto_compact():
            logger.warning("Context near limit, auto-compacting...")
            current_messages = context_manager.compact_messages()
            if on_assistant_message:
                on_assistant_message(context_manager.get_context_summary())

    try:
        while max_steps is None or step < max_steps:
            step += 1

            # Hook: agent turn started
            fire_hook_sync(HookEvent.AGENT_START, step=step, cwd=cwd)

            # 高级控制论闭环（每个 step 开始时执行）
            if enable_work_chain:
                # 状态观测：通过可测量输出估计系统内部状态
                if state_observer:
                    measurement = MeasurementVector(
                        timestamp=time.time(),
                        response_time=step * 2.0,  # 估算响应时间
                        success_rate=1.0 - (tool_error_count / max(step, 1)),
                        context_length=context_manager.get_stats().total_tokens if context_manager else 0,
                        error_count=tool_error_count,
                        tool_calls=0,
                    )
                    observed_state = state_observer.update(measurement)

                # 预测控制：预测未来趋势并提前调整
                if predictive_controller:
                    if context_manager:
                        stats = context_manager.get_stats()
                        predictive_controller.update("context_usage", stats.usage_percentage / 100.0)
                    predictive_controller.update("error_rate", tool_error_count / max(step, 1))

                    if step > 2:
                        actions = predictive_controller.generate_predictive_actions()
                        if actions and actions[0].urgency > 0.7:
                            logger.info("Predictive action triggered: %s", actions[0].recommended_action)
                            if self_healing_engine:
                                healing_actions = self_healing_engine.detect_and_heal({
                                    "context_usage": stats.usage_percentage / 100.0 if context_manager else 0.0,
                                    "error_rate": tool_error_count / max(step, 1),
                                })
                                if healing_actions:
                                    logger.info("Self-healing: %s", healing_actions[0].strategy)

            if metrics_collector:
                metrics_collector.start_turn(step)

            next_step: AgentStep
            try:
                next_step = _model_next(
                    model,
                    current_messages,
                    on_stream_chunk=on_assistant_stream_chunk,
                    store=store,
                )
            except KeyboardInterrupt:
                raise  # Let Ctrl-C propagate
            except ConnectionError as error:
                fallback = f"Network error (connection failed or dropped): {error}"
                logger.error("Model API connection error: %s", error)
                if on_assistant_message:
                    on_assistant_message(fallback)
                current_messages.append({"role": "assistant", "content": fallback})
                if metrics_collector:
                    metrics_collector.end_turn(total_tokens=0)
                return current_messages
            except TimeoutError as error:
                fallback = f"Model API timeout: {error}"
                logger.error("Model API timeout: %s", error)
                if on_assistant_message:
                    on_assistant_message(fallback)
                current_messages.append({"role": "assistant", "content": fallback})
                if metrics_collector:
                    metrics_collector.end_turn(total_tokens=0)
                return current_messages
            except Exception as error:
                # Catch-all for unexpected errors (rate limit, auth, server 5xx, etc.)
                error_type = type(error).__name__
                fallback = f"Model API error ({error_type}): {error}"
                logger.error("Model API error (%s): %s", error_type, error)

                # Reactive Compact: 尝试从上下文溢出中恢复
                if context_compactor and "prompt" in str(error).lower() or "too long" in str(error).lower():
                    recovery_result = context_compactor.reactive_recover(current_messages, str(error))
                    if recovery_result and recovery_result.effective:
                        current_messages = recovery_result.messages
                        if context_manager:
                            context_manager.messages = current_messages
                        logger.info(
                            "Reactive Compact recovered: freed %d tokens",
                            recovery_result.tokens_freed,
                        )
                        continue  # Retry with compacted messages

                if on_assistant_message:
                    on_assistant_message(fallback)
                current_messages.append({"role": "assistant", "content": fallback})
                if metrics_collector:
                    metrics_collector.end_turn(total_tokens=0)
                return current_messages

            if next_step.type == "assistant":
                is_empty = _is_empty_assistant_response(next_step.content)
                if not is_empty and _should_treat_assistant_as_progress(
                    kind=getattr(next_step, 'kind', None),
                    content=next_step.content,
                    saw_tool_result=saw_tool_result,
                ):
                    if on_progress_message:
                        on_progress_message(next_step.content)
                    current_messages.append({"role": "assistant_progress", "content": next_step.content})
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                NUDGE_AFTER_TOOL_RESULT
                                if saw_tool_result and getattr(next_step, 'kind', None) != "progress"
                                else NUDGE_CONTINUE
                            ),
                        }
                    )
                    continue

                diagnostics = next_step.diagnostics

                if _is_recoverable_thinking_stop(
                    is_empty=is_empty,
                    stop_reason=diagnostics.stopReason if diagnostics else None,
                    ignored_block_types=diagnostics.ignoredBlockTypes if diagnostics else None,
                ) and recoverable_thinking_retry_count < 3:
                    recoverable_thinking_retry_count += 1
                    stop_reason = diagnostics.stopReason if diagnostics else None
                    progress_content = (
                        "Model hit max_tokens during thinking; requesting the next step."
                        if stop_reason == "max_tokens"
                        else "Model returned pause_turn; requesting the next step."
                    )
                    if on_progress_message:
                        on_progress_message(progress_content)
                    current_messages.append({"role": "assistant_progress", "content": progress_content})
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                RESUME_AFTER_PAUSE
                                if stop_reason == "pause_turn"
                                else RESUME_AFTER_MAX_TOKENS
                            ),
                        }
                    )
                    continue

                if is_empty and empty_response_retry_count < 2:
                    empty_response_retry_count += 1
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                NUDGE_AFTER_EMPTY_RESPONSE
                                if saw_tool_result
                                else NUDGE_AFTER_EMPTY_NO_TOOLS
                            ),
                        }
                    )
                    continue

                if is_empty:
                    diagnostics_suffix = _format_diagnostics(
                        diagnostics.stopReason if diagnostics else None,
                        diagnostics.blockTypes if diagnostics else None,
                        diagnostics.ignoredBlockTypes if diagnostics else None,
                    )
                    if saw_tool_result:
                        fallback = (
                            f"Model returned an empty response after tool execution and the turn was stopped. There were {tool_error_count} tool error(s); retry, adjust the command, or choose a different approach.{diagnostics_suffix}"
                            if tool_error_count > 0
                            else f"Model returned an empty response after tool execution and the turn was stopped. Retry or ask the model to continue the remaining steps.{diagnostics_suffix}"
                        )
                    else:
                        fallback = f"Model returned an empty response and the turn was stopped.{diagnostics_suffix}"
                    if on_assistant_message:
                        on_assistant_message(fallback)
                    current_messages.append({"role": "assistant", "content": fallback})
                    return current_messages

                if on_assistant_message:
                    on_assistant_message(next_step.content)
                current_messages.append({"role": "assistant", "content": next_step.content})
                # Protect final answer in working memory
                protect_context(
                    content=next_step.content[:500],
                    entry_type="key_decision",
                    ttl_seconds=3600,
                )
                return current_messages

            if next_step.content:
                role = "assistant_progress" if next_step.contentKind == "progress" else "assistant"
                if role == "assistant_progress":
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
                    if on_assistant_message:
                        on_assistant_message(next_step.content)
                    current_messages.append({"role": role, "content": next_step.content})

            if not next_step.calls and next_step.content and next_step.contentKind != "progress":
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
                    call, tools, cwd, permissions, runtime, store, step,
                    on_tool_start, on_tool_result,
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

                _results: list[tuple[dict, ToolResult]] = []

                # Phase 1: Run all concurrent-safe tools in parallel
                if concurrent_calls:
                    max_workers = tool_scheduler.get_recommended_max_workers(concurrent_calls)
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=max_workers,
                        thread_name_prefix="mc-tool",
                    ) as pool:
                        future_to_call = {
                            pool.submit(
                                _execute_single_tool,
                                call, tools, cwd, permissions, runtime, None, step,
                                None, None,  # No UI callbacks during concurrent phase
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
                            call, tools, cwd, permissions, runtime, store, step,
                            on_tool_start, on_tool_result,
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
                
                saw_tool_result = True
                if not result.ok:
                    tool_error_count += 1
                    # Use ErrorClassifier for intelligent error handling
                    classified = ErrorClassifier.classify(result.output, tool_name=call["toolName"])
                    nudge = NudgeGenerator.generate(classified, retry_count=tool_error_count)
                    # Append nudge to tool result content for model context
                    result_output = result.output + "\n\n[System note: " + nudge + "]"
                else:
                    result_output = result.output

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
                if result.awaitUser:
                    if on_assistant_message:
                        on_assistant_message(result_output)
                    current_messages.append({"role": "assistant", "content": result_output})
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
                            tool_error_count / max(step, 1),
                        ),
                    })
                    decoupling_controller.compute_decoupling_matrix()

                # 自愈检测：检测并修复故障
                if self_healing_engine:
                    metrics_for_healing = {
                        "error_rate": tool_error_count / max(step, 1),
                        "context_usage": context_manager.get_stats().usage_percentage / 100.0 if context_manager else 0.0,
                        "oscillation_index": 0.0,  # 从反馈控制器获取
                    }
                    healing_actions = self_healing_engine.detect_and_heal(metrics_for_healing)
                    if healing_actions:
                        logger.info("Self-healing triggered: %s", healing_actions[0].strategy)

            # Tool execution completed for this step; ask the model for the next turn
            # instead of falling through to the max-step fallback.
            if metrics_collector:
                total_tokens = sum(
                    estimate_message_tokens(m) for m in current_messages
                ) if context_manager else 0
                metrics_collector.end_turn(total_tokens=total_tokens)
            continue

        fallback = "Reached the maximum tool step limit for this turn."
        if on_assistant_message:
            on_assistant_message(fallback)
        current_messages.append({"role": "assistant", "content": fallback})
        return current_messages
    finally:
        fire_hook_sync(HookEvent.AGENT_STOP, step=step, tool_errors=tool_error_count)

        if metrics_collector and metrics_collector._current_turn is not None:
            total_tokens = sum(
                estimate_message_tokens(m) for m in current_messages
            ) if context_manager else 0
            metrics_collector.end_turn(total_tokens=total_tokens)

        if enable_work_chain and task:
            final_state = TaskState.COMPLETED if tool_error_count == 0 else TaskState.FAILED
            task.set_state(final_state)
            task.result_summary = f"Turn completed: {step} steps, {tool_error_count} errors"

            if auditor:
                outcome = DecisionOutcome.SUCCESS if tool_error_count == 0 else DecisionOutcome.FAILURE
                auditor.complete_decision(
                    outcome,
                    step * 100.0,
                    task.result_summary,
                    task.error_message if tool_error_count > 0 else "",
                )

            logger.info(
                "Work chain completed: task=%s state=%s steps=%d errors=%d",
                task.id, task.state.value, step, tool_error_count,
            )

        # 控制论反馈：记录模式有效性
        if enable_work_chain and feedback_controller and task:
            pattern_id = f"{task_metadata.get('intent_type', 'unknown')}_{task.id}"
            feedback_controller.record_pattern_effectiveness(
                pattern_id, tool_error_count == 0
            )

        # 稳定性监测：记录快照
        if stability_monitor:
            from minicode.stability_monitor import MetricSnapshot
            snapshot = MetricSnapshot(
                timestamp=time.time(),
                error_rate=float(tool_error_count) / max(step, 1),
                avg_latency=step * 2.0,  # 简化估算
                context_usage=context_manager.get_stats().usage_percentage if context_manager else 0.0,
                active_tasks=1,
            )
            stability_monitor.record_snapshot(snapshot)

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

        # 上下文管理管线统计 (Claude Code-style)
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

