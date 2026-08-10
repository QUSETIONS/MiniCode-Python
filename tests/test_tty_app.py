from types import SimpleNamespace

from minicode.tty_app import (
    _ThrottledRenderer,
    _apply_tool_result_visual_state,
    _format_history,
    _mark_unfinished_tools,
    _save_transcript,
    summarize_tool_input,
    summarize_tool_output,
)
import minicode.tui.input_handler as input_handler_module
from minicode.context_manager import ContextManager
from minicode.memory import MemoryManager, MemoryScope
from minicode.permissions import PermissionManager
from minicode.prompt import build_system_prompt_bundle
from minicode.session import (
    FileCheckpoint,
    SessionData,
    SessionMetadata,
    create_file_checkpoint,
    create_new_session,
    rewind_session,
)
from minicode.tooling import ToolRegistry
from minicode.turn_events import TurnEvent
from minicode.tui.runtime_control import _ThrottledRenderer as RuntimeThrottledRenderer
from minicode.tui.event_flow import _handle_event
from minicode.tui.input_parser import KeyEvent
from minicode.tui.renderer import _decorate_session_feed_body
from minicode.tui.session_flow import (
    build_tty_runtime_state,
    finalize_tty_session,
    load_or_create_session,
)
from minicode.tui.state import ScreenState, TtyAppArgs
from minicode.tui.transcript import format_runtime_summary_line, format_transcript_text
from minicode.tui.types import TranscriptEntry


def test_tty_app_uses_runtime_control_throttled_renderer() -> None:
    assert _ThrottledRenderer is RuntimeThrottledRenderer


def test_summarize_tool_output_prefers_first_meaningful_line() -> None:
    output = "\n\nFILE: README.md\nOFFSET: 0\nEND: 100"
    assert summarize_tool_output("read_file", output).startswith("FILE: README.md")


def test_summarize_tool_output_truncates_long_lines() -> None:
    output = "x" * 400
    summary = summarize_tool_output("run_command", output)
    assert len(summary) < 200
    assert summary.endswith("...")


def test_format_history_shows_recent_entries_with_numbers() -> None:
    rendered = _format_history(["/help", "build parser", "/cmd pytest -q"], limit=2)
    assert rendered == "2. build parser\n3. /cmd pytest -q"


def test_save_transcript_writes_plain_text(tmp_path) -> None:
    state_entries = [
        TranscriptEntry(id=1, kind="user", body="hello"),
        TranscriptEntry(id=2, kind="assistant", body="world"),
    ]
    permissions = PermissionManager(str(tmp_path), prompt=lambda request: {"decision": "allow_once"})

    path = _save_transcript(
        type("State", (), {"transcript": state_entries})(),
        str(tmp_path),
        permissions,
        "logs/session.txt",
    )

    assert path.endswith("logs\\session.txt") or path.endswith("logs/session.txt")
    assert (tmp_path / "logs" / "session.txt").read_text(encoding="utf-8") == "you\n  hello\n\n---\n\nassistant\n  world"


def test_format_transcript_text_uses_clean_separator() -> None:
    rendered = format_transcript_text(
        [
            TranscriptEntry(id=1, kind="user", body="one"),
            TranscriptEntry(id=2, kind="assistant", body="two"),
        ]
    )

    assert "\n\n---\n\n" in rendered


def test_format_transcript_text_marks_runtime_progress_entries() -> None:
    rendered = format_transcript_text(
        [
            TranscriptEntry(id=1, kind="progress", body="Runtime phase: verify. Use evidence."),
            TranscriptEntry(id=2, kind="progress", body="scanning files"),
        ]
    )

    assert "runtime\n  Runtime phase: verify. Use evidence." in rendered
    assert "progress\n  scanning files" in rendered


def test_format_transcript_text_marks_typed_runtime_entries() -> None:
    rendered = format_transcript_text(
        [
            TranscriptEntry(
                id=1,
                kind="progress",
                body="Turn completed with verification evidence.",
                category="runtime",
            ),
            TranscriptEntry(id=2, kind="progress", body="scanning files"),
        ]
    )

    assert "runtime\n  Turn completed with verification evidence." in rendered
    assert "progress\n  scanning files" in rendered


def test_format_transcript_text_surfaces_runtime_metadata() -> None:
    rendered = format_transcript_text(
        [
            TranscriptEntry(
                id=1,
                kind="progress",
                body="Verification guard is holding the turn open.",
                category="runtime",
                runtimeKind="guard",
                runtimeStep=6,
                runtimePhase="verify",
                runtimeStopReason="verification_failed",
                runtimeVerificationFocus="tool_evidence",
            )
        ]
    )

    assert "runtime:guard [step=6 phase=verify reason=verification_failed verify=tool_evidence]" in rendered
    assert "  Verification guard is holding the turn open." in rendered


def test_format_transcript_text_adds_runtime_summary_timeline() -> None:
    entries = [
        TranscriptEntry(
            id=1,
            kind="progress",
            body="Runtime phase: explore.",
            category="runtime",
            runtimeKind="phase",
            runtimeStep=1,
            runtimePhase="explore",
        ),
        TranscriptEntry(
            id=2,
            kind="progress",
            body="Verification guard is holding the turn open.",
            category="runtime",
            runtimeKind="guard",
            runtimeStep=4,
            runtimePhase="verify",
            runtimeStopReason="verification_failed",
            runtimeVerificationFocus="tool_evidence",
        ),
        TranscriptEntry(
            id=3,
            kind="progress",
            body="Widening is now available.",
            category="runtime",
            runtimeKind="widening",
            runtimeStep=7,
            runtimeStopReason="widen_needed",
        ),
        TranscriptEntry(
            id=4,
            kind="progress",
            body="Turn complete.",
            category="runtime",
            runtimeKind="stop",
            runtimeStep=8,
            runtimeStopReason="done",
        ),
    ]
    rendered = format_transcript_text(entries)

    assert rendered.startswith(
        "runtime-summary\n  phase:explore@1 -> guard:tool_evidence@4 -> widen:widen_needed@7 -> stop:done@8"
    )
    assert "\n\n---\n\nruntime:phase" in rendered
    assert (
        format_runtime_summary_line(entries)
        == "runtime-summary: phase:explore@1 -> guard:tool_evidence@4 -> widen:widen_needed@7 -> stop:done@8"
    )


def test_decorate_session_feed_body_prepends_runtime_summary() -> None:
    entries = [
        TranscriptEntry(
            id=1,
            kind="progress",
            body="Runtime phase: verify.",
            category="runtime",
            runtimeKind="phase",
            runtimeStep=2,
            runtimePhase="verify",
        ),
        TranscriptEntry(
            id=2,
            kind="progress",
            body="Turn complete.",
            category="runtime",
            runtimeKind="stop",
            runtimeStep=3,
            runtimeStopReason="done",
        ),
    ]

    rendered = _decorate_session_feed_body("assistant\n  finished", entries)

    assert "runtime-summary: phase:verify@2 -> stop:done@3" in rendered
    assert rendered.endswith("assistant\n  finished")


def test_decorate_session_feed_body_prepends_checkpoint_summary() -> None:
    session = SimpleNamespace(
        checkpoints=[
            SimpleNamespace(
                checkpoint_id="abcd1234efgh5678",
                file_path="D:/tmp/alpha.py",
            ),
            SimpleNamespace(
                checkpoint_id="wxyz9876ijkl5432",
                file_path="D:/tmp/beta.py",
            ),
        ]
    )

    rendered = _decorate_session_feed_body(
        "assistant\n  finished",
        [],
        session,
    )

    assert "checkpoint-summary: 2 saved; latest [wxyz9876] beta.py, [abcd1234] alpha.py" in rendered
    assert rendered.endswith("assistant\n  finished")


def test_decorate_session_feed_body_prepends_product_summaries() -> None:
    session = SimpleNamespace(
        checkpoints=[],
        metadata=SimpleNamespace(
            readiness_summary="readiness: blocked (anthropic-compatible) [Missing provider channel]",
            instruction_summary="instructions: 2 active layer(s) [global:user, project:managed]",
            hook_summary="hooks: 1/2 enabled, 4 call(s), 18ms total",
            delegation_summary="delegation: 1 running, 3/4 slots free [lint-worker]",
            extension_summary="extensions: 1/1 enabled (1 project, 0 global)",
        ),
    )

    rendered = _decorate_session_feed_body(
        "assistant\n  finished",
        [],
        session,
    )

    assert "readiness-summary: readiness: blocked (anthropic-compatible) [Missing provider channel]" in rendered
    assert "instruction-summary: instructions: 2 active layer(s) [global:user, project:managed]" in rendered
    assert "hook-summary: hooks: 1/2 enabled, 4 call(s), 18ms total" in rendered
    assert "delegation-summary: delegation: 1 running, 3/4 slots free [lint-worker]" in rendered
    assert "extension-summary: extensions: 1/1 enabled (1 project, 0 global)" in rendered
    assert rendered.endswith("assistant\n  finished")


def test_finalize_tty_session_persists_runtime_metadata() -> None:
    session = SimpleNamespace(
        session_id="session-1234",
        messages=[],
        transcript_entries=[],
        history=[],
        permissions_summary=None,
        skills=[],
        mcp_servers=[],
    )
    args = SimpleNamespace(
        messages=[],
        permissions=SimpleNamespace(get_summary=lambda: {"mode": "default"}),
        tools=SimpleNamespace(get_skills=lambda: ["runtime"], get_mcp_servers=lambda: ["memory"]),
    )
    state = SimpleNamespace(
        session=session,
        transcript=[
            TranscriptEntry(
                id=1,
                kind="progress",
                body="Widened mode is active.",
                category="runtime",
                runtimeKind="widening",
                runtimeStep=7,
                runtimePhase="verify",
                runtimeStopReason="widen_needed",
                runtimeVerificationFocus="comparison",
            )
        ],
        history=["continue"],
        autosave=SimpleNamespace(force_save=lambda: None),
    )

    finalize_tty_session(args, state)

    assert state.session.transcript_entries == [
        {
            "id": 1,
            "kind": "progress",
            "category": "runtime",
            "runtimeKind": "widening",
            "runtimeStep": 7,
            "runtimePhase": "verify",
            "runtimeStopReason": "widen_needed",
            "runtimeVerificationFocus": "comparison",
            "toolName": None,
            "status": None,
            "body": "Widened mode is active.",
            "collapsed": False,
            "collapsedSummary": None,
            "collapsePhase": None,
        }
    ]


def test_tty_resume_rehydrates_session_checkpoint_and_memory(tmp_path, monkeypatch) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr("minicode.session.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("minicode.session.MINI_CODE_DIR", tmp_path)
    monkeypatch.setattr("minicode.memory.MINI_CODE_DIR", tmp_path)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "README.md"
    target.write_text("before", encoding="utf-8")

    memory_manager = MemoryManager(project_root=workspace)
    memory_manager.add_entry(
        MemoryScope.PROJECT,
        "decision",
        "Resume continuity marker: keep the public API stable.",
    )

    session = create_new_session(str(workspace))
    session.messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "Continue the interrupted task."},
    ]
    session.transcript_entries = [
        {"id": 1, "kind": "user", "body": "Continue the interrupted task."},
    ]
    checkpoint = create_file_checkpoint(
        session,
        file_path=str(target),
        existed=True,
        previous_content="before",
    )
    assert checkpoint is not None
    target.write_text("after", encoding="utf-8")

    rewound, restored_checkpoints = rewind_session(session.session_id)
    assert rewound is not None
    assert restored_checkpoints
    assert target.read_text(encoding="utf-8") == "before"

    resumed = load_or_create_session(str(workspace), session.session_id)
    resumed_memory = MemoryManager(project_root=workspace)
    permissions = PermissionManager(str(workspace))
    args, state = build_tty_runtime_state(
        runtime={"model": "mock"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[{"role": "system", "content": "fresh process"}],
        cwd=str(workspace),
        permissions=permissions,
        session=resumed,
        memory_manager=resumed_memory,
    )

    assert args.messages == resumed.messages
    assert [entry.body for entry in state.transcript] == [
        "Continue the interrupted task."
    ]
    memory_context = resumed_memory.get_relevant_context(query="continuity")
    bundle = build_system_prompt_bundle(
        str(workspace),
        permissions.get_summary(),
        {
            "skills": [],
            "mcpServers": [],
            "memory_context": memory_context,
            "runtime": {"model": "mock"},
        },
    )
    assert "Resume continuity marker" in bundle.prompt


def test_summarize_tool_input_formats_patch_file() -> None:
    summary = summarize_tool_input(
        "patch_file",
        {"path": "demo.txt", "replacements": [{"search": "a", "replace": "b"}, {"search": "c", "replace": "d"}]},
    )

    assert summary == "patch_file path=demo.txt replacements=2"


def test_mark_unfinished_tools_marks_running_entries_as_errors() -> None:
    state = type(
        "State",
        (),
        {
            "transcript": [TranscriptEntry(id=1, kind="tool", body="running", toolName="run_command", status="running")],
            "recent_tools": [],
            "pending_tool_runs": {"run_command": [{"entry": "placeholder"}]},
            "active_tool": "run_command",
        },
    )()

    count = _mark_unfinished_tools(state)

    assert count == 1
    assert state.transcript[0].status == "error"
    assert "did not report a final result" in state.transcript[0].body
    assert state.recent_tools == [{"name": "run_command", "status": "error"}]
    assert state.pending_tool_runs == {}
    assert state.active_tool is None


def test_error_tool_entry_stays_expanded_for_visibility() -> None:
    entry = TranscriptEntry(id=1, kind="tool", body="boom", toolName="run_command", status="running")
    _apply_tool_result_visual_state(entry, "run_command", "boom", is_error=True)

    assert entry.status == "error"
    assert entry.collapsed is False
    assert entry.collapsedSummary is None


def test_success_tool_entry_collapses_to_summary() -> None:
    entry = TranscriptEntry(id=1, kind="tool", body="running", toolName="read_file", status="running")
    _apply_tool_result_visual_state(entry, "read_file", "FILE: README.md\nhello", is_error=False)

    assert entry.status == "success"
    assert entry.collapsed is True
    assert entry.collapsedSummary == "FILE: README.md"
    assert entry.collapsePhase == 3


def test_empty_tty_return_does_not_start_input_handler(tmp_path) -> None:
    calls = []
    state = ScreenState(input="   ", cursor_offset=3)
    args = TtyAppArgs(
        runtime=None,
        tools=None,
        model=None,
        messages=[],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    def rerender() -> None:
        calls.append("rerender")

    def handle_input(*_args, **_kwargs):
        calls.append("handle_input")
        return False

    _handle_event(
        args,
        state,
        KeyEvent(name="return", ctrl=False, meta=False),
        rerender,
        __import__("threading").Event(),
        {},
        handle_input,
    )

    assert "handle_input" not in calls
    assert state.input == ""


def test_tty_input_passes_and_persists_context_manager(tmp_path, monkeypatch) -> None:
    captured: dict = {}
    saved: list[ContextManager] = []
    context_manager = ContextManager(model="default", context_window=1000)
    memory_manager = SimpleNamespace(
        handle_user_memory_input=lambda _input: None,
        get_relevant_context=lambda **_kwargs: "",
    )

    def fake_run_agent_turn(**kwargs):
        captured.update(kwargs)
        manager = kwargs["context_manager"]
        manager.messages = list(kwargs["messages"])
        return [*kwargs["messages"], {"role": "assistant", "content": "done"}]

    monkeypatch.setattr(input_handler_module, "run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr(input_handler_module, "save_context_state", saved.append, raising=False)

    state = ScreenState(input="Please inspect context", cursor_offset=22)
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[{"role": "system", "content": "sys"}],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
        memory_manager=memory_manager,
        context_manager=context_manager,
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False
    state.agent_thread.join(timeout=5)

    assert captured["context_manager"] is context_manager
    assert captured["memory_manager"] is memory_manager
    assert saved == [context_manager]
    assert state.agent_result["messages"][-1] == {"role": "assistant", "content": "done"}


def test_tty_input_reduces_agent_events_on_the_ui_side(tmp_path, monkeypatch) -> None:
    captured: dict = {}

    def fake_run_agent_turn(**kwargs):
        captured.update(kwargs)
        sink = kwargs["callbacks"]
        sink.on_event(
            TurnEvent.tool_started(
                step=1,
                tool_name="read_marker",
                tool_input={"path": "README.md"},
            )
        )
        sink.on_event(
            TurnEvent.tool_finished(
                step=1,
                tool_name="read_marker",
                output="marker:ok",
                is_error=False,
            )
        )
        sink.on_event(TurnEvent.assistant_message(step=1, content="done"))
        return [*kwargs["messages"], {"role": "assistant", "content": "done"}]

    monkeypatch.setattr(input_handler_module, "run_agent_turn", fake_run_agent_turn)

    state = ScreenState(input="inspect marker", cursor_offset=14)
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[{"role": "system", "content": "sys"}],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False
    state.agent_thread.join(timeout=5)
    assert "callbacks" in captured
    assert "on_tool_start" not in captured

    state.agent_event_queue.drain(state.agent_event_handler)

    assert any(entry.kind == "tool" for entry in state.transcript)
    assert state.transcript[-1].kind == "assistant"
    assert state.transcript[-1].body == "done"


def test_tty_input_surfaces_agent_failure_without_rendering_exception_text(
    tmp_path, monkeypatch
) -> None:
    def fake_run_agent_turn(**kwargs):
        del kwargs
        raise RuntimeError("provider rejected sk-secret-token")

    monkeypatch.setattr(input_handler_module, "run_agent_turn", fake_run_agent_turn)

    state = ScreenState(input="trigger failure", cursor_offset=15)
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[{"role": "system", "content": "sys"}],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False
    state.agent_thread.join(timeout=5)
    state.agent_event_queue.drain(state.agent_event_handler)

    failure = next(
        entry
        for entry in state.transcript
        if entry.category == "runtime" and entry.runtimeStopReason == "error"
    )
    assert failure.body.startswith("Agent turn failed (RuntimeError)")
    assert "sk-secret-token" not in failure.body
    assert state.is_busy is False


def test_tty_session_command_uses_live_session_snapshot(tmp_path) -> None:
    session = SessionData(
        session_id="session-1234",
        created_at=1.0,
        updated_at=2.0,
        workspace=str(tmp_path),
    )
    state = ScreenState(
        input="/session",
        cursor_offset=len("/session"),
        transcript=[
            TranscriptEntry(
                id=1,
                kind="progress",
                body="Runtime phase: verify.",
                category="runtime",
                runtimeKind="phase",
                runtimeStep=2,
                runtimePhase="verify",
            )
        ],
        history=["continue"],
        session=session,
    )
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[{"role": "user", "content": "continue"}],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False

    assert state.transcript[-1].kind == "assistant"
    assert "Session inspect: session-" in state.transcript[-1].body
    assert "Runtime: phase:verify@2" in state.transcript[-1].body
    assert state.session.transcript_entries[0]["runtimeKind"] == "phase"


def test_tty_sessions_command_lists_workspace_history(tmp_path, monkeypatch) -> None:
    workspace = str(tmp_path.resolve())
    monkeypatch.setattr(
        "minicode.cli_commands.list_sessions",
        lambda: [
            SessionMetadata(
                session_id="aaa111111111",
                created_at=1.0,
                updated_at=2.0,
                first_message="alpha",
                message_count=2,
                workspace=workspace,
            )
        ],
        raising=False,
    )
    state = ScreenState(input="/sessions", cursor_offset=len("/sessions"))
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=workspace,
        permissions=PermissionManager(workspace),
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False

    assert state.transcript[-1].kind == "assistant"
    assert "Saved sessions:" in state.transcript[-1].body
    assert "aaa11111" in state.transcript[-1].body


def test_tty_checkpoints_command_lists_active_session_checkpoints(tmp_path) -> None:
    session = SessionData(
        session_id="session-1234",
        created_at=1.0,
        updated_at=2.0,
        workspace=str(tmp_path),
        checkpoints=[
            FileCheckpoint(
                checkpoint_id="abc123456789",
                created_at=3.0,
                file_path=str(tmp_path / "demo.txt"),
                existed=True,
                previous_content="before",
            )
        ],
    )
    session.update_metadata()
    state = ScreenState(
        input="/checkpoints",
        cursor_offset=len("/checkpoints"),
        session=session,
    )
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False

    assert state.transcript[-1].kind == "assistant"
    assert "Checkpoints for session session-" in state.transcript[-1].body
    assert "[abc12345]" in state.transcript[-1].body


def test_tty_rewind_command_rewinds_active_session(tmp_path, monkeypatch) -> None:
    checkpoint = FileCheckpoint(
        checkpoint_id="abc123456789",
        created_at=3.0,
        file_path=str(tmp_path / "demo.txt"),
        existed=True,
        previous_content="before",
    )
    session = SessionData(
        session_id="session-1234",
        created_at=1.0,
        updated_at=2.0,
        workspace=str(tmp_path),
        checkpoints=[checkpoint],
    )
    session.update_metadata()

    def fake_rewind(session_arg, *, steps=1, checkpoint_id=None):
        assert session_arg is session
        assert steps == 1
        assert checkpoint_id is None
        session_arg.checkpoints = []
        session_arg.update_metadata()
        return [checkpoint]

    monkeypatch.setattr("minicode.cli_commands.rewind_session_data", fake_rewind)

    state = ScreenState(
        input="/rewind",
        cursor_offset=len("/rewind"),
        session=session,
    )
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False

    assert state.transcript[-1].kind == "assistant"
    assert "Rewound 1 checkpoint(s) for session session-" in state.transcript[-1].body
    assert "Restored: [abc12345] demo.txt" in state.transcript[-1].body
    assert "Resuming session session-" in state.transcript[-1].body


def test_tty_session_rewind_command_rewinds_saved_session(tmp_path, monkeypatch) -> None:
    workspace = str(tmp_path.resolve())
    session = SessionData(
        session_id="aaa111111111",
        created_at=1.0,
        updated_at=2.0,
        workspace=workspace,
    )
    checkpoint = FileCheckpoint(
        checkpoint_id="abc123456789",
        created_at=3.0,
        file_path=str(tmp_path / "demo.txt"),
        existed=True,
        previous_content="before",
    )
    session.checkpoints = [checkpoint]
    session.update_metadata()
    monkeypatch.setattr(
        "minicode.cli_commands.get_latest_session",
        lambda workspace=None: session if workspace == str(tmp_path.resolve()) else None,
        raising=False,
    )

    def fake_rewind(session_id, *, steps=1, checkpoint_id=None):
        assert session_id == session.session_id
        assert steps == 1
        assert checkpoint_id is None
        session.checkpoints = []
        session.update_metadata()
        return session, [checkpoint]

    monkeypatch.setattr("minicode.cli_commands.rewind_session", fake_rewind)

    state = ScreenState(input="/session-rewind latest", cursor_offset=len("/session-rewind latest"))
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=workspace,
        permissions=PermissionManager(workspace),
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False

    assert state.transcript[-1].kind == "assistant"
    assert "Rewound 1 checkpoint(s) for session aaa11111" in state.transcript[-1].body
    assert "Restored: [abc12345] demo.txt" in state.transcript[-1].body
    assert "Resuming session aaa11111" in state.transcript[-1].body


def test_tty_session_replay_command_lists_saved_timeline(tmp_path, monkeypatch) -> None:
    workspace = str(tmp_path.resolve())
    monkeypatch.setattr(
        "minicode.cli_commands.get_latest_session",
        lambda workspace=None: SessionData(
            session_id="aaa111111111",
            created_at=1.0,
            updated_at=2.0,
            workspace=workspace,
            history=["check the runtime timeline"],
            transcript_entries=[{"kind": "assistant", "body": "restored"}],
        ),
        raising=False,
    )
    state = ScreenState(input="/session-replay latest", cursor_offset=len("/session-replay latest"))
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=workspace,
        permissions=PermissionManager(workspace),
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False

    assert state.transcript[-1].kind == "assistant"
    assert "Session replay: aaa11111" in state.transcript[-1].body
    assert "Prompt history (1 shown):" in state.transcript[-1].body
