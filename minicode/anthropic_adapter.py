from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from typing import Any

from minicode.types import AgentStep, StepDiagnostics

DEFAULT_MAX_RETRIES = 4
BASE_RETRY_DELAY_MS = 500
MAX_RETRY_DELAY_MS = 8000


def _sleep(milliseconds: int) -> None:
    time.sleep(max(0, milliseconds) / 1000)


def _get_retry_limit() -> int:
    try:
        value = int(float(__import__("os").environ.get("MINI_CODE_MAX_RETRIES", DEFAULT_MAX_RETRIES)))
    except ValueError:
        value = DEFAULT_MAX_RETRIES
    return max(0, value)


def _should_retry_status(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def _parse_retry_after_ms(retry_after: str | None) -> int | None:
    if not retry_after:
        return None
    # Try numeric seconds first
    try:
        seconds = float(retry_after)
        if seconds >= 0:
            return int(seconds * 1000)
    except ValueError:
        pass
    # Try HTTP-date format: "Thu, 01 Dec 2025 16:00:00 GMT"
    try:
        from email.utils import parsedate_to_datetime
        target = parsedate_to_datetime(retry_after)
        import datetime
        delta_ms = int((target.timestamp() - time.time()) * 1000)
        return max(0, delta_ms)
    except (ValueError, TypeError):
        pass
    return None


def _get_retry_delay_ms(attempt: int, retry_after_ms: int | None) -> int:
    if retry_after_ms is not None:
        return retry_after_ms
    base = min(BASE_RETRY_DELAY_MS * (2 ** max(0, attempt - 1)), MAX_RETRY_DELAY_MS)
    jitter = random.random() * 0.25 * base
    return int(base + jitter)


def _read_json_body(response) -> Any:
    text = response.read().decode("utf-8")
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": {"message": text.strip()}}


def _extract_error_message(data: Any, status: int) -> str:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    return f"Model request failed: {status}"


def _parse_assistant_text(content: str) -> tuple[str, str | None]:
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
            raw = trimmed[len(prefix) :].strip()
            if closing_tag:
                raw = raw.replace(closing_tag, "").strip()
            return raw, kind
    return trimmed, None


def _to_text_block(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _to_assistant_text(message: dict[str, Any]) -> str:
    if message["role"] == "assistant_progress":
        return f"<progress>\n{message['content']}\n</progress>"
    return message["content"]


def _push_anthropic_message(messages: list[dict[str, Any]], role: str, block: dict[str, Any]) -> None:
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].append(block)
    else:
        messages.append({"role": role, "content": [block]})


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "system":
            continue
        if role == "user":
            _push_anthropic_message(converted, "user", _to_text_block(message["content"]))
            continue
        if role in {"assistant", "assistant_progress"}:
            _push_anthropic_message(converted, "assistant", _to_text_block(_to_assistant_text(message)))
            continue
        if role == "assistant_tool_call":
            _push_anthropic_message(
                converted,
                "assistant",
                {"type": "tool_use", "id": message["toolUseId"], "name": message["toolName"], "input": message["input"]},
            )
            continue
        _push_anthropic_message(
            converted,
            "user",
            {
                "type": "tool_result",
                "tool_use_id": message["toolUseId"],
                "content": message["content"],
                "is_error": message["isError"],
            },
        )
    return system, converted


class AnthropicModelAdapter:
    def __init__(self, runtime: dict[str, Any], tools) -> None:
        self.runtime = runtime
        self.tools = tools

    def next(self, messages: list[dict[str, Any]]) -> AgentStep:
        system_message, converted_messages = _to_anthropic_messages(messages)
        request_body = {
            "model": self.runtime["model"],
            "system": system_message,
            "messages": converted_messages,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in self.tools.list()
            ],
        }
        if self.runtime.get("maxOutputTokens") is not None:
            request_body["max_tokens"] = self.runtime["maxOutputTokens"]

        request = urllib.request.Request(
            url=self.runtime["baseUrl"].rstrip("/") + "/v1/messages",
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
                **(
                    {"x-api-key": self.runtime["apiKey"]}
                    if self.runtime.get("apiKey")
                    else {"Authorization": f"Bearer {self.runtime['authToken']}"}
                ),
            },
            method="POST",
        )

        max_retries = _get_retry_limit()
        response = None
        for attempt in range(max_retries + 1):
            try:
                response = urllib.request.urlopen(request, timeout=60)  # noqa: S310
                break
            except urllib.error.HTTPError as error:
                response = error
                if not _should_retry_status(error.code) or attempt >= max_retries:
                    break
                _sleep(_get_retry_delay_ms(attempt + 1, _parse_retry_after_ms(error.headers.get("retry-after"))))
            except urllib.error.URLError:
                if attempt >= max_retries:
                    raise
                _sleep(_get_retry_delay_ms(attempt + 1, None))

        if response is None:
            raise RuntimeError("Model request failed before receiving a response")

        data = _read_json_body(response)
        status = getattr(response, "status", getattr(response, "code", 200))
        if status >= 400:
            raise RuntimeError(_extract_error_message(data, status))

        tool_calls: list[dict[str, Any]] = []
        text_parts: list[str] = []
        block_types: list[str] = []
        ignored_block_types: list[str] = []

        for block in data.get("content", []) if isinstance(data, dict) else []:
            block_type = block.get("type")
            block_types.append(block_type)
            if block_type == "text" and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
            elif block_type == "tool_use" and isinstance(block.get("id"), str) and isinstance(block.get("name"), str):
                tool_calls.append({"id": block["id"], "toolName": block["name"], "input": block.get("input")})
            else:
                ignored_block_types.append(str(block_type))

        parsed_text, kind = _parse_assistant_text("\n".join(text_parts).strip())
        diagnostics = StepDiagnostics(
            stopReason=data.get("stop_reason") if isinstance(data, dict) else None,
            blockTypes=block_types,
            ignoredBlockTypes=ignored_block_types,
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
