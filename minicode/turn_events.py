"""Structured events emitted while a single agent turn is running.

The Rust implementation keeps the agent core independent from the TUI by
exposing ``AgentTurnCallbacks``.  Python historically exposed the same hooks
as individual keyword arguments.  This module is the small, typed bridge
between the two surfaces: callers that need a single event stream can consume
``TurnEvent`` objects, while Rust-shaped callback objects remain supported by
the dispatch adapter in :mod:`minicode.agent_loop`.
"""

from __future__ import annotations

import copy
import logging
from collections import deque
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any, Callable, Literal, Protocol

from minicode.types import ChatMessage, RuntimeEvent


logger = logging.getLogger("minicode.turn_events")


TurnEventKind = Literal[
    "tool_start",
    "tool_result",
    "assistant",
    "progress",
    "runtime",
    "assistant_stream",
    "thinking",
    "done",
]


def _snapshot_value(value: Any) -> Any:
    """Copy callback payloads when possible so events are stable snapshots."""

    try:
        return copy.deepcopy(value)
    except Exception:  # noqa: BLE001
        return value


@dataclass(frozen=True, slots=True)
class TurnEvent:
    """A typed, loss-minimizing event from one agent turn.

    The common fields are intentionally present on every event so consumers
    can route events without a second variant-specific wrapper.  Only the
    fields relevant to a particular ``kind`` are populated.
    """

    kind: TurnEventKind
    step: int | None = None
    tool_name: str = ""
    tool_input: Any = None
    output: str = ""
    is_error: bool = False
    content: str = ""
    runtime_event: RuntimeEvent | None = None
    messages: tuple[ChatMessage, ...] = ()
    stop_reason: str = ""

    @classmethod
    def tool_started(
        cls,
        *,
        step: int | None,
        tool_name: str,
        tool_input: Any,
    ) -> "TurnEvent":
        return cls(
            kind="tool_start",
            step=step,
            tool_name=tool_name,
            tool_input=_snapshot_value(tool_input),
        )

    @classmethod
    def tool_finished(
        cls,
        *,
        step: int | None,
        tool_name: str,
        output: str,
        is_error: bool,
    ) -> "TurnEvent":
        return cls(
            kind="tool_result",
            step=step,
            tool_name=tool_name,
            output=output,
            is_error=is_error,
        )

    @classmethod
    def assistant_message(cls, *, step: int | None, content: str) -> "TurnEvent":
        return cls(kind="assistant", step=step, content=content)

    @classmethod
    def progress_message(cls, *, step: int | None, content: str) -> "TurnEvent":
        return cls(kind="progress", step=step, content=content)

    @classmethod
    def runtime_message(
        cls,
        *,
        step: int | None,
        event: RuntimeEvent,
    ) -> "TurnEvent":
        return cls(
            kind="runtime",
            step=step,
            content=event.message,
            runtime_event=event,
            stop_reason=event.stop_reason,
        )

    @classmethod
    def assistant_stream_chunk(cls, *, step: int | None, content: str) -> "TurnEvent":
        return cls(kind="assistant_stream", step=step, content=content)

    @classmethod
    def thinking_chunk(cls, *, step: int | None, content: str) -> "TurnEvent":
        return cls(kind="thinking", step=step, content=content)

    @classmethod
    def completed(
        cls,
        *,
        step: int | None,
        messages: list[ChatMessage],
        stop_reason: str,
    ) -> "TurnEvent":
        snapshot = _snapshot_value(messages)
        return cls(
            kind="done",
            step=step,
            messages=tuple(snapshot),
            stop_reason=stop_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation for logs and adapters."""

        data = asdict(self)
        data["messages"] = list(data["messages"])
        return data


class AgentTurnCallbacks(Protocol):
    """Rust-compatible callback surface for the core agent loop."""

    def on_tool_start(self, tool_name: str, tool_input: Any) -> None: ...

    def on_tool_result(self, tool_name: str, output: str, is_error: bool) -> None: ...

    def on_assistant_message(self, content: str) -> None: ...

    def on_progress_message(self, content: str) -> None: ...


class AgentTurnEventSink(Protocol):
    """Single-method sink for consumers that want the complete event stream."""

    def on_event(self, event: TurnEvent) -> None: ...


class TurnEventQueue:
    """Thread-safe unbounded turn-event channel, mirroring Rust's TUI mpsc.

    The agent thread only calls :meth:`on_event`; the TUI thread calls
    :meth:`drain`.  Stream and thinking channels are opt-in because enabling
    either one changes how some provider adapters format their request.
    """

    def __init__(
        self,
        *,
        include_stream_chunks: bool = False,
        include_thinking_chunks: bool = False,
    ) -> None:
        self.include_stream_chunks = include_stream_chunks
        self.include_thinking_chunks = include_thinking_chunks
        self._events: deque[TurnEvent] = deque()
        self._lock = Lock()

    def on_event(self, event: TurnEvent) -> None:
        """Append an event without blocking the agent thread."""

        with self._lock:
            self._events.append(event)

    def drain(
        self,
        handler: Callable[[TurnEvent], None],
        *,
        max_events: int | None = None,
    ) -> int:
        """Deliver queued events in FIFO order and return the count delivered."""

        delivered = 0
        while max_events is None or delivered < max_events:
            with self._lock:
                if not self._events:
                    break
                event = self._events.popleft()
            try:
                handler(event)
            except Exception:  # noqa: BLE001
                # A UI reducer must not wedge the TUI event loop.  The event
                # is considered consumed after this diagnostic is recorded.
                logger.debug(
                    "Turn event consumer failed for event=%s",
                    event.kind,
                    exc_info=True,
                )
            delivered += 1
        return delivered

    def pending(self) -> int:
        """Return a diagnostic-only snapshot of queued event count."""

        with self._lock:
            return len(self._events)


__all__ = [
    "AgentTurnCallbacks",
    "AgentTurnEventSink",
    "TurnEventQueue",
    "TurnEvent",
    "TurnEventKind",
]
