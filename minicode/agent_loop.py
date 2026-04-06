from __future__ import annotations

from typing import Callable

from minicode.context_manager import ContextManager, estimate_message_tokens
from minicode.logging_config import get_logger
from minicode.permissions import PermissionManager
from minicode.tooling import ToolContext, ToolRegistry
from minicode.types import AgentStep, ChatMessage, ModelAdapter

logger = get_logger("agent_loop")

# 常量：避免重复的提示文本
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


def run_agent_turn(
    *,
    model: ModelAdapter,
    tools: ToolRegistry,
    messages: list[ChatMessage],
    cwd: str,
    permissions: PermissionManager | None = None,
    max_steps: int = 50,
    on_tool_start: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str, bool], None] | None = None,
    on_assistant_message: Callable[[str], None] | None = None,
    on_progress_message: Callable[[str], None] | None = None,
    context_manager: ContextManager | None = None,
) -> list[ChatMessage]:
    current_messages = list(messages)
    saw_tool_result = False
    empty_response_retry_count = 0
    recoverable_thinking_retry_count = 0
    tool_error_count = 0
    step = 0

    # 检查上下文状态
    if context_manager:
        context_manager.messages = current_messages
        stats = context_manager.get_stats()
        logger.info("Context: %d tokens (%.0f%%), %d messages", 
                   stats.total_tokens, stats.usage_percentage, stats.messages_count)
        
        # 如果需要压缩，自动执行
        if context_manager.should_auto_compact():
            logger.warning("Context near limit, auto-compacting...")
            current_messages = context_manager.compact_messages()
            if on_assistant_message:
                on_assistant_message(context_manager.get_context_summary())

    while max_steps is None or step < max_steps:
        step += 1
        next_step: AgentStep
        try:
            next_step = model.next(current_messages)
        except KeyboardInterrupt:
            raise  # Let Ctrl-C propagate
        except ConnectionError as error:
            fallback = f"Network error (connection failed or dropped): {error}"
            logger.error("Model API connection error: %s", error)
            if on_assistant_message:
                on_assistant_message(fallback)
            current_messages.append({"role": "assistant", "content": fallback})
            return current_messages
        except TimeoutError as error:
            fallback = f"Model API timeout: {error}"
            logger.error("Model API timeout: %s", error)
            if on_assistant_message:
                on_assistant_message(fallback)
            current_messages.append({"role": "assistant", "content": fallback})
            return current_messages
        except Exception as error:
            # Catch-all for unexpected errors (rate limit, auth, server 5xx, etc.)
            error_type = type(error).__name__
            fallback = f"Model API error ({error_type}): {error}"
            logger.error("Model API error (%s): %s", error_type, error)
            if on_assistant_message:
                on_assistant_message(fallback)
            current_messages.append({"role": "assistant", "content": fallback})
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

        for call in next_step.calls:
            if on_tool_start:
                on_tool_start(call["toolName"], call["input"])
            result = tools.execute(
                call["toolName"],
                call["input"],
                ToolContext(cwd=cwd, permissions=permissions),
            )
            if on_tool_result:
                on_tool_result(call["toolName"], result.output, not result.ok)
            saw_tool_result = True
            if not result.ok:
                tool_error_count += 1
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
                    "content": result.output,
                    "isError": not result.ok,
                }
            )
            if result.awaitUser:
                if on_assistant_message:
                    on_assistant_message(result.output)
                current_messages.append({"role": "assistant", "content": result.output})
                return current_messages

    fallback = "Reached the maximum tool step limit for this turn."
    if on_assistant_message:
        on_assistant_message(fallback)
    current_messages.append({"role": "assistant", "content": fallback})
    return current_messages
