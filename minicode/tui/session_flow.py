from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from minicode.cost_tracker import CostTracker
from minicode.history import load_history_entries
from minicode.permissions import PermissionManager
from minicode.session import (
    AutosaveManager,
    SessionData,
    create_new_session,
    format_session_list,
    format_session_resume,
    get_latest_session,
    list_sessions,
    load_session,
    save_session,
)
from minicode.state import create_app_store
from minicode.tui.state import PendingApproval, ScreenState, TtyAppArgs
from minicode.tui.types import TranscriptEntry


def handle_session_listing(cwd: str, list_sessions_only: bool) -> bool:
    if not list_sessions_only:
        return False
    sessions = list_sessions()
    print(format_session_list(sessions))
    return True


def load_or_create_session(cwd: str, resume_session: str | None) -> SessionData:
    workspace = str(Path(cwd).resolve())
    if resume_session:
        if resume_session == "latest":
            session = get_latest_session(workspace=workspace)
            if session:
                print(format_session_resume(session))
                return session
            print("No previous session found for this workspace.")
            return create_new_session(workspace=workspace)

        session = load_session(resume_session)
        if not session:
            raise FileNotFoundError(f"Session '{resume_session}' not found.")
        print(format_session_resume(session))
        return session

    session = get_latest_session(workspace=workspace)
    if session:
        print(f"Previous session found: {session.session_id[:8]}")
        print("Use --resume to continue, or starting fresh session.")
        return create_new_session(workspace=workspace)

    return create_new_session(workspace=workspace)


def build_tty_runtime_state(
    runtime: dict | None,
    tools: Any,
    model: Any,
    messages: list[Any],
    cwd: str,
    permissions: PermissionManager,
    session: SessionData,
) -> tuple[TtyAppArgs, ScreenState]:
    args = TtyAppArgs(
        runtime=runtime,
        tools=tools,
        model=model,
        messages=messages,
        cwd=cwd,
        permissions=permissions,
    )

    state = ScreenState(
        history=load_history_entries(),
        session=session,
        autosave=AutosaveManager(session),
        app_state=create_app_store({
            "session_id": session.session_id,
            "workspace": cwd,
            "model": runtime.get("model", "unknown") if runtime else "unknown",
        }),
        cost_tracker=CostTracker(),
    )
    state.history_index = len(state.history)

    if session.messages:
        args.messages.clear()
        args.messages.extend(session.messages)
        for entry_data in session.transcript_entries:
            state.transcript.append(TranscriptEntry(**entry_data))
        print(f"Restored {len(session.messages)} messages, {len(state.transcript)} transcript entries.")

    return args, state


def install_permission_prompt(
    args: TtyAppArgs,
    state: ScreenState,
    rerender: Any,
) -> tuple[threading.Event, dict[str, Any], Any]:
    approval_event = threading.Event()
    approval_result: dict[str, Any] = {}

    def _permission_prompt_handler(request: dict[str, Any]) -> dict[str, Any]:
        nonlocal approval_result
        state.pending_approval = PendingApproval(
            request=request,
            resolve=lambda r: None,
        )
        rerender()
        approval_event.clear()
        approval_event.wait()
        result = approval_result.copy()
        state.pending_approval = None
        return result

    args.permissions.prompt = _permission_prompt_handler
    return approval_event, approval_result, _permission_prompt_handler


def finalize_tty_session(args: TtyAppArgs, state: ScreenState) -> None:
    if not state.session:
        return

    state.session.messages = list(args.messages)
    state.session.transcript_entries = [
        {
            "id": e.id,
            "kind": e.kind,
            "toolName": e.toolName,
            "status": e.status,
            "body": e.body,
            "collapsed": e.collapsed,
            "collapsedSummary": e.collapsedSummary,
            "collapsePhase": e.collapsePhase,
        }
        for e in state.transcript
    ]
    state.session.history = state.history
    state.session.permissions_summary = args.permissions.get_summary()
    state.session.skills = args.tools.get_skills()
    state.session.mcp_servers = args.tools.get_mcp_servers()

    if state.autosave:
        state.autosave.force_save()
    else:
        save_session(state.session)

    print(f"\nSession saved: {state.session.session_id[:8]}")
