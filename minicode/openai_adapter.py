"""OpenAI-compatible API adapter for MiniCode.

Supports GPT-4o, GPT-4-turbo, GPT-4o-mini and any OpenAI-compatible endpoint
(e.g., Azure OpenAI, local LLMs with OpenAI-compatible API).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from minicode.api_retry import RETRYABLE_STATUS, calculate_backoff
from minicode.cost_tracker import calculate_cost
from minicode.state import Store, AppState, add_cost, record_api_error, update_context_usage
from minicode.types import AgentStep, StepDiagnostics

DEFAULT_MAX_RETRIES = 4
OPENAI_MODELS = {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini", "o3-mini"}


def _is_openai_model(model: str) -> bool:
    """Check if model name indicates an OpenAI-compatible API."""
    model_lower = model.lower()
    # Direct match
    if model_lower in OPENAI_MODELS:
        return True
    # Prefix match for versioned models
    for prefix in ("gpt-4", "gpt-3.5", "o1-", "o3-", "chatgpt-"):
        if model_lower.startswith(prefix):
            return True
    # Check if explicitly using OpenAI base URL
    base_url = os.environ.get("OPENAI_BASE_URL", os.environ.get("OPENAI_API_BASE", ""))
    if base_url and "openai" in base_url.lower():
        return True
    return False


def _get_openai_base_url(runtime: dict) -> str:
    """Get OpenAI-compatible base URL."""
    return (
        os.environ.get("OPENAI_BASE_URL", "")
        or os.environ.get("OPENAI_API_BASE", "")
        or runtime.get("openaiBaseUrl", "")
        or "https://api.openai.com"
    ).rstrip("/")


def _get_openai_api_key(runtime: dict) -> str:
    """Get OpenAI API key."""
    return (
        os.environ.get("OPENAI_API_KEY", "")
        or runtime.get("openaiApiKey", "")
    )


def _to_openai_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Convert internal message format to OpenAI Chat Completion format.
    
    Returns (system_message, chat_messages)
    """
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    
    for message in messages:
        role = message["role"]
        content = message.get("content", "")
        
        if role == "system":
            system_parts.append(content)
            continue
        
        if role == "user":
            converted.append({"role": "user", "content": content})
            continue
        
        if role in ("assistant", "assistant_progress"):
            text = content
            if role == "assistant_progress":
                text = f"<progress>\n{content}\n</progress>"
            converted.append({"role": "assistant", "content": text})
            continue
        
        if role == "assistant_tool_call":
            # OpenAI format: assistant message with tool_calls
            converted.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": message["toolUseId"],
                    "type": "function",
                    "function": {
                        "name": message["toolName"],
                        "arguments": json.dumps(message["input"]) if isinstance(message["input"], dict) else "{}",
                    },
                }],
            })
            continue
        
        if role == "tool_result":
            converted.append({
                "role": "tool",
                "tool_call_id": message["toolUseId"],
                "content": message.get("content", ""),
            })
            continue
    
    system_message = "\n\n".join(system_parts)
    return system_message, converted


def _parse_assistant_text(content: str) -> tuple[str, str | None]:
    """Parse progress/final markers from assistant text."""
    trimmed = content.strip()
    if not trimmed:
        return "", None
    markers = [
        ("<final>", "final", "</final>"),
        ("[FINAL]", "final", None),
        ("<progress>", "progress", "</progress>"),
        ("[PROGRESS]", "progress", None),
    ]
    for prefix, kind, closing_tag in markers:
        if trimmed.startswith(prefix):
            raw = trimmed[len(prefix):].strip()
            if closing_tag:
                raw = raw.replace(closing_tag, "").strip()
            return raw, kind
    return trimmed, None


class OpenAIModelAdapter:
    """Model adapter for OpenAI-compatible APIs."""
    
    def __init__(self, runtime: dict[str, Any], tools) -> None:
        self.runtime = runtime
        self.tools = tools
        self._cached_tools_json: list[dict[str, Any]] | None = None
        self._tools_cache_key: int = 0
    
    def _get_serialized_tools(self) -> list[dict[str, Any]]:
        """Get serialized tool list in OpenAI function format with caching."""
        current_tools = self.tools.list()
        current_key = hash(tuple((t.name, t.description) for t in current_tools))
        if self._cached_tools_json is None or current_key != self._tools_cache_key:
            self._cached_tools_json = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in current_tools
            ]
            self._tools_cache_key = current_key
        return self._cached_tools_json
    
    def next(
        self,
        messages: list[dict[str, Any]],
        on_stream_chunk: Callable[[str], None] | None = None,
        store: Store[AppState] | None = None,
    ) -> AgentStep:
        system_message, converted_messages = _to_openai_messages(messages)
        
        request_body: dict[str, Any] = {
            "model": self.runtime["model"],
            "messages": converted_messages,
            "tools": self._get_serialized_tools(),
        }
        
        if system_message:
            request_body["messages"].insert(0, {"role": "system", "content": system_message})
        
        if self.runtime.get("maxOutputTokens") is not None:
            request_body["max_tokens"] = self.runtime["maxOutputTokens"]
        
        if on_stream_chunk:
            request_body["stream"] = True
        
        base_url = _get_openai_base_url(self.runtime)
        api_key = _get_openai_api_key(self.runtime)
        
        # Build headers — support OpenRouter and custom endpoints
        headers = {
            "content-type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        # OpenRouter extra headers (HTTP-Referer, X-Title)
        openrouter_headers = self.runtime.get("_openrouter_headers", {})
        headers.update(openrouter_headers)
        # Custom endpoint extra headers
        custom_headers = self.runtime.get("_custom_headers", {})
        headers.update(custom_headers)

        # OpenRouter extra params (transforms, etc.)
        openrouter_params = self.runtime.get("_openrouter_params", {})
        for k, v in openrouter_params.items():
            if v is not None:
                request_body[k] = v

        request = urllib.request.Request(
            url=f"{base_url}/v1/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        
        # Retry logic
        max_retries = 4
        response = None
        for attempt in range(max_retries + 1):
            try:
                response = urllib.request.urlopen(request, timeout=120)  # noqa: S310
                break
            except urllib.error.HTTPError as error:
                response = error
                if error.code not in RETRYABLE_STATUS or attempt >= max_retries:
                    break
                wait = calculate_backoff(attempt)
                time.sleep(wait)
            except urllib.error.URLError:
                if attempt >= max_retries:
                    raise
                wait = calculate_backoff(attempt)
                time.sleep(wait)
        
        if response is None:
            raise RuntimeError("OpenAI request failed before receiving a response")
        
        if not on_stream_chunk:
            # Non-streaming response
            data = json.loads(response.read().decode("utf-8"))
            status = getattr(response, "status", getattr(response, "code", 200))
            
            if status >= 400:
                if store:
                    store.set_state(record_api_error())
                error_msg = data.get("error", {}).get("message", f"OpenAI API error: {status}")
                raise RuntimeError(error_msg)
            
            # Cost tracking
            if store:
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                cost_usd = calculate_cost(
                    model=self.runtime["model"],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                if cost_usd > 0:
                    store.set_state(add_cost(cost_usd))
                store.set_state(update_context_usage(input_tokens + output_tokens))
            
            # Parse response
            choices = data.get("choices", [])
            if not choices:
                return AgentStep(type="assistant", content="")
            
            choice = choices[0]
            message = choice.get("message", {})
            text_content = message.get("content", "") or ""
            tool_calls_raw = message.get("tool_calls", [])
            
            stop_reason = choice.get("finish_reason")
            
            tool_calls = []
            if tool_calls_raw:
                for tc in tool_calls_raw:
                    func = tc.get("function", {})
                    try:
                        parsed_input = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        parsed_input = {}
                    tool_calls.append({
                        "id": tc.get("id", ""),
                        "toolName": func.get("name", ""),
                        "input": parsed_input,
                    })
            
            parsed_text, kind = _parse_assistant_text(text_content.strip())
            diagnostics = StepDiagnostics(
                stopReason=stop_reason,
                blockTypes=["tool_calls"] if tool_calls else (["text"] if text_content else []),
                ignoredBlockTypes=[],
            )
            
            if tool_calls:
                return AgentStep(
                    type="tool_calls",
                    calls=tool_calls,
                    content=parsed_text,
                    contentKind="progress" if kind == "progress" else None,
                    diagnostics=diagnostics,
                )
            return AgentStep(type="assistant", content=parsed_text, kind=kind, diagnostics=diagnostics)
        
        # Streaming response
        tool_calls = []
        text_parts = []
        active_tool_calls: dict[int, dict] = {}
        stop_reason = None
        stream_input_tokens = 0
        stream_output_tokens = 0
        
        for line in response:
            line_str = line.decode("utf-8").strip()
            if not line_str.startswith("data: "):
                continue
            data_str = line_str[6:]
            if data_str == "[DONE]":
                break
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            
            choices = event.get("choices", [])
            if not choices:
                # Maybe usage info
                usage = event.get("usage", {})
                if usage:
                    stream_input_tokens = usage.get("prompt_tokens", 0)
                    stream_output_tokens = usage.get("completion_tokens", 0)
                continue
            
            delta = choices[0].get("delta", {})
            finish_reason = choices[0].get("finish_reason")
            if finish_reason:
                stop_reason = finish_reason
            
            # Text content
            content = delta.get("content", "")
            if content:
                text_parts.append(content)
                on_stream_chunk(content)
            
            # Tool calls (incremental)
            tc_deltas = delta.get("tool_calls", [])
            for tc_delta in tc_deltas:
                idx = tc_delta.get("index", 0)
                if idx not in active_tool_calls:
                    active_tool_calls[idx] = {
                        "id": tc_delta.get("id", ""),
                        "name": "",
                        "arguments": "",
                    }
                func = tc_delta.get("function", {})
                if func.get("name"):
                    active_tool_calls[idx]["name"] = func["name"]
                if func.get("arguments"):
                    active_tool_calls[idx]["arguments"] += func["arguments"]
                if tc_delta.get("id"):
                    active_tool_calls[idx]["id"] = tc_delta["id"]
        
        # Finalize tool calls
        for idx in sorted(active_tool_calls.keys()):
            tc = active_tool_calls[idx]
            try:
                parsed_input = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                parsed_input = {}
            tool_calls.append({
                "id": tc["id"],
                "toolName": tc["name"],
                "input": parsed_input,
            })
        
        # Streaming cost tracking
        if store:
            # Estimate if not provided in stream
            if stream_input_tokens == 0:
                from minicode.context_manager import estimate_messages_tokens
                stream_input_tokens = estimate_messages_tokens(messages)
            if stream_output_tokens == 0:
                stream_output_tokens = len("".join(text_parts)) // 4
            
            cost_usd = calculate_cost(
                model=self.runtime["model"],
                input_tokens=stream_input_tokens,
                output_tokens=stream_output_tokens,
            )
            if cost_usd > 0:
                store.set_state(add_cost(cost_usd))
            store.set_state(update_context_usage(stream_input_tokens + stream_output_tokens))
        
        parsed_text, kind = _parse_assistant_text("".join(text_parts).strip())
        diagnostics = StepDiagnostics(
            stopReason=stop_reason,
            blockTypes=["tool_calls"] if tool_calls else (["text"] if text_parts else []),
            ignoredBlockTypes=[],
        )
        
        if tool_calls:
            return AgentStep(
                type="tool_calls",
                calls=tool_calls,
                content=parsed_text,
                contentKind="progress" if kind == "progress" else None,
                diagnostics=diagnostics,
            )
        return AgentStep(type="assistant", content=parsed_text, kind=kind, diagnostics=diagnostics)
