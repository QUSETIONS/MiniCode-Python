from __future__ import annotations

from minicode.agent_loop import run_agent_turn
from minicode.tooling import (
    ToolCapability,
    ToolDefinition,
    ToolMetadata,
    ToolRegistry,
    ToolResult,
)
from minicode.turn_events import TurnEvent, TurnEventQueue
from minicode.types import AgentStep, ChatMessage, ModelAdapter


class ScriptedModel(ModelAdapter):
    def __init__(self, steps: list[AgentStep]) -> None:
        self.steps = steps
        self.calls = 0

    def next(
        self,
        messages: list[ChatMessage],
        on_stream_chunk=None,
        on_thinking_delta=None,
        store=None,
    ) -> AgentStep:
        del messages, on_stream_chunk, on_thinking_delta, store
        step = self.steps[self.calls]
        self.calls += 1
        return step


class TransportProbeModel(ModelAdapter):
    def __init__(self) -> None:
        self.stream_callback = "unset"

    def next(
        self,
        messages: list[ChatMessage],
        on_stream_chunk=None,
        on_thinking_delta=None,
        store=None,
    ) -> AgentStep:
        del messages, on_thinking_delta, store
        self.stream_callback = on_stream_chunk
        return AgentStep(type="assistant", content="done")


def _echo_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolDefinition(
                name="echo",
                description="echo tool",
                input_schema={"type": "object"},
                validator=lambda value: value,
                run=lambda value, _context: ToolResult(
                    ok=True,
                    output=f"echo:{value['text']}",
                ),
            )
        ]
    )


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[TurnEvent] = []

    def on_event(self, event: TurnEvent) -> None:
        self.events.append(event)


def test_structured_turn_events_cover_tool_progress_assistant_and_done() -> None:
    tool_input = {"text": "hi"}
    recorder = EventRecorder()
    legacy: list[tuple[str, str]] = []
    model = ScriptedModel(
        [
            AgentStep(
                type="tool_calls",
                content="working",
                contentKind="progress",
                calls=[{"id": "1", "toolName": "echo", "input": tool_input}],
            ),
            AgentStep(type="assistant", content="done"),
        ]
    )

    messages = run_agent_turn(
        model=model,
        tools=_echo_registry(),
        messages=[{"role": "system", "content": "sys"}],
        cwd=".",
        callbacks=recorder,
        on_tool_start=lambda name, _input: legacy.append(("start", name)),
        on_tool_result=lambda name, _output, _error: legacy.append(("result", name)),
        on_assistant_message=lambda content: legacy.append(("assistant", content)),
        on_progress_message=lambda content: legacy.append(("progress", content)),
        enable_work_chain=False,
    )

    kinds = [event.kind for event in recorder.events]
    assert "tool_start" in kinds
    assert "tool_result" in kinds
    assert "progress" in kinds
    assert "assistant" in kinds
    assert kinds[-1] == "done"
    assert kinds.count("done") == 1

    tool_start = next(event for event in recorder.events if event.kind == "tool_start")
    assert tool_start.tool_name == "echo"
    assert tool_start.tool_input == {"text": "hi"}
    tool_input["text"] = "mutated-after-dispatch"
    assert tool_start.tool_input == {"text": "hi"}

    tool_result = next(event for event in recorder.events if event.kind == "tool_result")
    assert tool_result.output == "echo:hi"
    assert not tool_result.is_error

    done = recorder.events[-1]
    assert done.messages[-1] == {"role": "assistant", "content": "done"}
    assert ("progress", "working") in legacy
    assert ("start", "echo") in legacy
    assert ("result", "echo") in legacy
    assert ("assistant", "done") in legacy
    assert legacy.index(("start", "echo")) < legacy.index(("result", "echo"))
    assert legacy.index(("result", "echo")) < legacy.index(("assistant", "done"))
    assert messages[-1] == {"role": "assistant", "content": "done"}


def test_rust_named_callbacks_are_supported_without_an_event_method() -> None:
    calls: list[tuple[str, str]] = []

    class RustCallbacks:
        def on_tool_start(self, name: str, _input: object) -> None:
            calls.append(("start", name))

        def on_tool_result(self, name: str, _output: str, _is_error: bool) -> None:
            calls.append(("result", name))

        def on_assistant_message(self, content: str) -> None:
            calls.append(("assistant", content))

        def on_progress_message(self, content: str) -> None:
            calls.append(("progress", content))

    run_agent_turn(
        model=ScriptedModel(
            [
                AgentStep(
                    type="tool_calls",
                    content="working",
                    contentKind="progress",
                    calls=[
                        {
                            "id": "1",
                            "toolName": "echo",
                            "input": {"text": "hi"},
                        }
                    ],
                ),
                AgentStep(type="assistant", content="done"),
            ]
        ),
        tools=_echo_registry(),
        messages=[{"role": "system", "content": "sys"}],
        cwd=".",
        callbacks=RustCallbacks(),
        enable_work_chain=False,
    )

    assert ("progress", "working") in calls
    assert ("start", "echo") in calls
    assert ("result", "echo") in calls
    assert ("assistant", "done") in calls
    assert calls.index(("start", "echo")) < calls.index(("result", "echo"))
    assert calls.index(("result", "echo")) < calls.index(("assistant", "done"))


def test_structured_callback_failure_does_not_abort_the_turn() -> None:
    class FailingSink:
        def on_event(self, _event: TurnEvent) -> None:
            raise RuntimeError("telemetry sink unavailable")

    messages = run_agent_turn(
        model=ScriptedModel([AgentStep(type="assistant", content="done")]),
        tools=ToolRegistry([]),
        messages=[{"role": "system", "content": "sys"}],
        cwd=".",
        callbacks=FailingSink(),
        enable_work_chain=False,
    )

    assert messages[-1] == {"role": "assistant", "content": "done"}


def test_event_subscription_does_not_enable_provider_streaming() -> None:
    model = TransportProbeModel()

    run_agent_turn(
        model=model,
        tools=ToolRegistry([]),
        messages=[{"role": "system", "content": "sys"}],
        cwd=".",
        callbacks=EventRecorder(),
        enable_work_chain=False,
    )

    assert model.stream_callback is None

    stream_model = TransportProbeModel()
    run_agent_turn(
        model=stream_model,
        tools=ToolRegistry([]),
        messages=[{"role": "system", "content": "sys"}],
        cwd=".",
        callbacks=TurnEventQueue(include_stream_chunks=True),
        enable_work_chain=False,
    )
    assert callable(stream_model.stream_callback)


def test_turn_event_queue_preserves_fifo_and_isolates_consumer_failures() -> None:
    queue = TurnEventQueue()
    queue.on_event(TurnEvent.progress_message(step=1, content="first"))
    queue.on_event(TurnEvent.assistant_message(step=1, content="second"))
    received: list[str] = []

    def consume(event: TurnEvent) -> None:
        received.append(event.content)
        if event.content == "first":
            raise RuntimeError("render failed")

    assert queue.pending() == 2
    assert queue.drain(consume) == 2
    assert received == ["first", "second"]
    assert queue.pending() == 0


def test_structured_events_cover_deferred_concurrent_tool_callbacks() -> None:
    def make_tool(name: str) -> ToolDefinition:
        return ToolDefinition(
            name=name,
            description=name,
            input_schema={"type": "object"},
            validator=lambda value: value,
            run=lambda value, _context: ToolResult(
                ok=True,
                output=f"{name}:{value['value']}",
            ),
            metadata=ToolMetadata(
                name=name,
                description=name,
                capabilities={ToolCapability.CONCURRENCY_SAFE},
            ),
        )

    recorder = EventRecorder()
    messages = run_agent_turn(
        model=ScriptedModel(
            [
                AgentStep(
                    type="tool_calls",
                    calls=[
                        {"id": "1", "toolName": "alpha", "input": {"value": "a"}},
                        {"id": "2", "toolName": "beta", "input": {"value": "b"}},
                    ],
                ),
                AgentStep(type="assistant", content="finished"),
            ]
        ),
        tools=ToolRegistry([make_tool("alpha"), make_tool("beta")]),
        messages=[{"role": "system", "content": "sys"}],
        cwd=".",
        callbacks=recorder,
        enable_work_chain=False,
    )

    starts = [event.tool_name for event in recorder.events if event.kind == "tool_start"]
    results = [event.tool_name for event in recorder.events if event.kind == "tool_result"]
    assert starts == ["alpha", "beta"]
    assert results == ["alpha", "beta"]
    assert recorder.events[-1].kind == "done"
    assert messages[-1] == {"role": "assistant", "content": "finished"}
