from __future__ import annotations

import argparse
import json
import sys
import os
from dataclasses import asdict
from pathlib import Path

from minicode.agent_loop import run_agent_turn
from minicode.cli_commands import try_handle_local_command
from minicode.config import load_runtime_config
from minicode.history import load_history_entries, save_history_entries
from minicode.local_tool_shortcuts import parse_local_tool_shortcut
from minicode.manage_cli import maybe_handle_management_command
from minicode.model_registry import create_model_adapter
from minicode.permissions import PermissionManager
from minicode.prompt import build_system_prompt_bundle
from minicode.session import (
    format_rewind_preview,
    format_session_checkpoints,
    format_session_inspect,
    format_session_list,
    format_session_replay,
    format_session_resume,
    get_latest_session,
    list_sessions,
    load_session,
    rewind_session,
)
from minicode.tools import create_default_tool_registry
from minicode.tooling import ToolContext
from minicode.tui.transcript import format_transcript_text
from minicode.tui.types import TranscriptEntry
from minicode.tty_app import run_tty_app
from minicode.workspace import resolve_tool_path


def _handle_local_command(user_input: str, tools) -> str | None:
    if user_input == "/tools":
        return "\n".join(f"{tool.name}: {tool.description}" for tool in tools.list())
    local_result = try_handle_local_command(user_input, tools=tools, cwd=str(Path.cwd()))
    return local_result


def _render_banner(runtime: dict | None, cwd: str, permission_summary: list[str], counts: dict[str, int]) -> str:
    model = runtime["model"] if runtime else "unconfigured"
    lines = [
        "╔══════════════════════════════════════════════════════════╗",
        "║  🤖 MiniCode Python - Your Terminal Coding Assistant    ║",
        "╠══════════════════════════════════════════════════════════╣",
        f"║  Model: {model:<46} ║",
        f"║  CWD: {cwd:<50} ║",
    ]
    if permission_summary:
        for perm in permission_summary[:2]:  # 只显示前2个权限摘要
            lines.append(f"║  {perm:<60} ║")
    lines.append("╠══════════════════════════════════════════════════════════╣")
    lines.append(
        f"║  📊 Skills: {counts['skillCount']:>2} | MCP Servers: {counts['mcpCount']:>2} | "
        f"Transcript: {counts['transcriptCount']:>3} ║"
    )
    lines.append("╚══════════════════════════════════════════════════════════╝")
    return "\n".join(lines)


def _render_quick_start() -> str:
    """显示快速入门指南"""
    return """
💡 Quick Start Guide:
  📝 Edit files:     edit_file.py or patch_file.py
  🔍 Search code:    /grep <pattern> or grep_files tool
  🏃 Run commands:   /cmd <command> or run_command tool
  🧠 Think deeply:   Use sequential_thinking MCP tool
  📚 View skills:    /skills
  ❓ Get help:       /help

🚀 Try saying:
  "帮我分析这个项目的结构"
  "用 TDD 方式实现 XX 功能"
  "系统性地调试这个 bug"
  "帮我写个技术方案"
"""


def _append_transcript(transcript: list[TranscriptEntry], **kwargs) -> None:
    transcript.append(TranscriptEntry(id=len(transcript) + 1, **kwargs))


def _make_cli_permission_prompt():
    """Create a simple CLI-based permission prompt for non-TTY fallback."""
    def _prompt(request: dict) -> dict:
        print(f"\n{request.get('summary', 'Permission Request')}")
        choices = request.get("choices", [])
        if choices:
            for choice in choices:
                print(f"  [{choice.get('key', '')}] {choice.get('label', '')}")
            answer = input("Choose: ").strip()
            for choice in choices:
                if answer == choice.get("key"):
                    return {"decision": choice.get("decision", "allow_once")}
        answer = input("Allow? (y/n): ").strip().lower()
        return {"decision": "allow_once" if answer in ("y", "yes") else "deny_once"}
    return _prompt


def _configure_stdio_for_unicode() -> None:
    stdin_reconfigure = getattr(sys.stdin, "reconfigure", None)
    if stdin_reconfigure is not None:
        try:
            # PowerShell pipelines may prefix UTF-8 BOM bytes on stdin. Decode
            # with utf-8-sig so local slash commands are not polluted by BOM
            # artifacts like "锘?/memory" and accidentally routed to the model.
            stdin_reconfigure(encoding="utf-8-sig", errors="replace")
        except Exception:
            pass

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _save_transcript_file(cwd: str, permissions, transcript: list[TranscriptEntry], output_path: str) -> str:
    target = resolve_tool_path(ToolContext(cwd=cwd, permissions=permissions), output_path, "write")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(format_transcript_text(transcript), encoding="utf-8")
    return str(target)


def _resolve_target_session(cwd: str, session_id: str | None):
    workspace = str(Path(cwd).resolve())
    return (
        get_latest_session(workspace=workspace)
        if session_id in (None, "", "latest")
        else load_session(session_id)
    )


def _handle_list_sessions_request(cwd: str, *, workspace_only: bool) -> int:
    workspace = str(Path(cwd).resolve()) if workspace_only else None
    print(format_session_list(list_sessions(workspace=workspace)))
    return 0


def _handle_readiness_request(cwd: str, *, json_output: bool) -> int:
    if json_output:
        from minicode.product_surfaces import build_readiness_report

        print(
            json.dumps(
                asdict(build_readiness_report(cwd)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    result = try_handle_local_command("/readiness", cwd=cwd)
    print(result or "No readiness report is available.")
    return 0


def _handle_list_checkpoints_request(cwd: str, session_id: str | None) -> int:
    target_session = _resolve_target_session(cwd, session_id)
    if target_session is None:
        print("No saved session found for checkpoint inspection.", file=sys.stderr)
        return 1

    print(format_session_checkpoints(target_session))
    return 0


def _handle_inspect_session_request(cwd: str, session_id: str | None) -> int:
    target_session = _resolve_target_session(cwd, session_id)
    if target_session is None:
        print("No saved session found for inspection.", file=sys.stderr)
        return 1

    print(format_session_inspect(target_session))
    return 0


def _handle_replay_session_request(cwd: str, session_id: str | None) -> int:
    target_session = _resolve_target_session(cwd, session_id)
    if target_session is None:
        print("No saved session found for replay.", file=sys.stderr)
        return 1

    print(format_session_replay(target_session))
    return 0


def _handle_rewind_request(
    cwd: str,
    session_id: str | None,
    steps: int,
    checkpoint_id: str | None,
) -> int:
    target_session = _resolve_target_session(cwd, session_id)
    if target_session is None:
        print("No saved session found to rewind.", file=sys.stderr)
        return 1

    session, restored = rewind_session(
        target_session.session_id,
        steps=steps,
        checkpoint_id=checkpoint_id,
    )
    if session is None or not restored:
        print("No checkpoints available to rewind for that session.", file=sys.stderr)
        return 1

    if checkpoint_id:
        print(
            f"Rewound {len(restored)} checkpoint(s) through {checkpoint_id[:8]} "
            f"for session {session.session_id[:8]}."
        )
    else:
        print(f"Rewound {len(restored)} checkpoint(s) for session {session.session_id[:8]}.")
    for checkpoint in restored:
        print(f"  - [{checkpoint.checkpoint_id[:8]}] {checkpoint.file_path}")
    print(format_session_resume(session))
    return 0


def _handle_preview_rewind_request(
    cwd: str,
    session_id: str | None,
    steps: int,
    checkpoint_id: str | None,
) -> int:
    target_session = _resolve_target_session(cwd, session_id)
    if target_session is None:
        print("No saved session found to preview.", file=sys.stderr)
        return 1

    preview = format_rewind_preview(
        target_session,
        steps=steps,
        checkpoint_id=checkpoint_id,
    )
    if preview.startswith("No checkpoints available"):
        print(preview, file=sys.stderr)
        return 1
    print(preview)
    return 0

def main() -> None:
    _configure_stdio_for_unicode()

    parser = argparse.ArgumentParser(
        description="MiniCode Python - A lightweight terminal coding assistant",
        add_help=True,
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="latest",
        default=None,
        metavar="SESSION_ID",
        help="Resume a previous session (use 'latest' or session ID)",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List all saved sessions and exit",
    )
    parser.add_argument(
        "--list-workspace-sessions",
        action="store_true",
        help="List saved sessions for the current workspace and exit",
    )
    parser.add_argument(
        "--readiness",
        action="store_true",
        help="Print provider/runtime readiness and exit",
    )
    parser.add_argument(
        "--readiness-json",
        action="store_true",
        help="Print provider/runtime readiness as JSON and exit",
    )
    parser.add_argument(
        "--session",
        default=None,
        metavar="SESSION_ID",
        help="Start with a specific session ID",
    )
    parser.add_argument(
        "--rewind",
        nargs="?",
        const="latest",
        default=None,
        metavar="SESSION_ID",
        help="Rewind the latest checkpointed file edit for a saved session",
    )
    parser.add_argument(
        "--preview-rewind",
        nargs="?",
        const="latest",
        default=None,
        metavar="SESSION_ID",
        help="Preview the latest checkpointed file edit that would be rewound for a saved session",
    )
    parser.add_argument(
        "--list-checkpoints",
        nargs="?",
        const="latest",
        default=None,
        metavar="SESSION_ID",
        help="List saved rewind checkpoints for a session",
    )
    parser.add_argument(
        "--inspect-session",
        nargs="?",
        const="latest",
        default=None,
        metavar="SESSION_ID",
        help="Inspect a saved session with runtime, checkpoint, and transcript summary",
    )
    parser.add_argument(
        "--replay-session",
        nargs="?",
        const="latest",
        default=None,
        metavar="SESSION_ID",
        help="Replay a saved session with checkpoint, prompt history, and transcript timeline",
    )
    parser.add_argument(
        "--rewind-steps",
        type=int,
        default=1,
        metavar="N",
        help="Number of checkpoints to rewind when used with --rewind (default: 1)",
    )
    parser.add_argument(
        "--rewind-to",
        default=None,
        metavar="CHECKPOINT_ID",
        help="Rewind back through a specific checkpoint ID instead of using --rewind-steps",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Run the interactive installer",
    )
    parser.add_argument(
        "--validate-config",
        "--valid-config",
        action="store_true",
        help="Validate configuration and exit",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level (default: WARNING)",
    )
    parser.add_argument(
        "--structured-logs",
        action="store_true",
        help="Emit JSON structured logs (also enabled via MINI_CODE_LOG_STRUCTURED=true)",
    )
    parser.add_argument(
        "--trust-project-mcp",
        action="store_true",
        help="Load project-level .mcp.json (disabled by default for security; also via MINI_CODE_TRUST_PROJECT_MCP=1)",
    )

    args, remaining_argv = parser.parse_known_args()
    if remaining_argv and not any(not arg.startswith("--") for arg in remaining_argv):
        parser.error(f"unrecognized arguments: {' '.join(remaining_argv)}")

    # Initialize logging
    from minicode.logging_config import setup_logging, structured_logging_requested
    setup_logging(
        level=args.log_level,
        structured=structured_logging_requested(cli_flag=args.structured_logs),
    )

    # Run config validation if requested
    if args.validate_config:
        from minicode.config import format_config_diagnostic
        print(format_config_diagnostic())
        return
    
    # Run installer if requested
    if args.install:
        from minicode.install import main as install_main
        install_main()
        return
    
    cwd = str(Path.cwd())
    argv = remaining_argv

    if args.list_sessions or args.list_workspace_sessions:
        raise SystemExit(
            _handle_list_sessions_request(
                cwd,
                workspace_only=args.list_workspace_sessions,
            )
        )

    if args.readiness or args.readiness_json:
        raise SystemExit(
            _handle_readiness_request(cwd, json_output=args.readiness_json)
        )

    if args.list_checkpoints is not None:
        raise SystemExit(_handle_list_checkpoints_request(cwd, args.list_checkpoints))

    if args.inspect_session is not None:
        raise SystemExit(_handle_inspect_session_request(cwd, args.inspect_session))

    if args.replay_session is not None:
        raise SystemExit(_handle_replay_session_request(cwd, args.replay_session))

    if args.rewind is not None:
        raise SystemExit(
            _handle_rewind_request(
                cwd,
                args.rewind,
                max(1, args.rewind_steps),
                args.rewind_to,
            )
        )

    if args.preview_rewind is not None:
        raise SystemExit(
            _handle_preview_rewind_request(
                cwd,
                args.preview_rewind,
                max(1, args.rewind_steps),
                args.rewind_to,
            )
        )
    
    # Filter out our custom args before passing to management commands
    management_argv = [a for a in argv if not a.startswith("--")]
    if maybe_handle_management_command(cwd, management_argv):
        return

    runtime = None
    try:
        runtime = load_runtime_config(cwd, trust_project_mcp=args.trust_project_mcp)
    except Exception as e:  # noqa: BLE001
        runtime = None
        print(
            f"⚠️  Warning: Failed to load runtime config: {e}\n",
            file=sys.stderr,
        )
        print(
            "🔧 How to fix this:\n"
            "  1. Set your model name: export ANTHROPIC_MODEL=claude-sonnet-4-20250514\n"
            "  2. Set your API key: export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  3. Or edit ~/.mini-code/settings.json:\n"
            '     {"model": "claude-sonnet-4-20250514", "env": {"ANTHROPIC_API_KEY": "sk-ant-..."}}\n'
            "  4. Restart MiniCode\n\n"
            "📖 For more info: https://github.com/QUSETIONS/MiniCode-Python\n"
            "   Falling back to mock model for now...\n",
            file=sys.stderr,
        )

    prompt_handler = _make_cli_permission_prompt() if sys.stdin.isatty() else None
    tools = create_default_tool_registry(cwd, runtime=runtime)
    permissions = PermissionManager(cwd, prompt=prompt_handler)
    
    # Use unified model registry for adapter creation
    force_mock = runtime is None
    model = create_model_adapter(
        model=runtime.get("model", "") if runtime else "",
        tools=tools,
        runtime=runtime,
        force_mock=force_mock,
    )
    
    # Initialize ContextManager for context window management
    from minicode.context_manager import ContextManager
    from minicode.logging_config import get_logger
    logger = get_logger("main")
    context_mgr = None
    if runtime:
        context_mgr = ContextManager(model=runtime.get("model", "default"))
        logger.info("Context manager initialized for model: %s", runtime.get("model", "unknown"))
    
    # Initialize MemoryManager for cross-session knowledge retention
    from minicode.memory import MemoryManager
    memory_mgr = MemoryManager(project_root=Path(cwd))
    logger.info("Memory manager initialized")
    
    # Initialize UserProfileManager for user preferences
    from minicode.user_profile import UserProfileManager
    profile_manager = UserProfileManager(cwd=cwd)
    profile_manager.load_merged()
    logger.info("User profile manager initialized (global=%s, project=%s)",
                profile_manager.global_path.exists(),
                profile_manager.project_path.exists())
    
    # Initialize Store for global state management (inspired by Claude Code's Zustand store)
    from minicode.state import create_app_store
    app_store = create_app_store(
        initial={
            "session_id": args.session or "new",
            "workspace": cwd,
            "model": runtime.get("model", "mock") if runtime else "mock",
        }
    )
    logger.info("Store initialized with session: %s", app_store.get_state().session_id)
    
    prompt_bundle = build_system_prompt_bundle(
        cwd,
        permissions.get_summary(),
        {
            "skills": tools.get_skills(),
            "mcpServers": tools.get_mcp_servers(),
            "memory_context": memory_mgr.get_relevant_context(),  # Inject memory
            "runtime": runtime,
        },
    )
    messages = [
        {
            "role": "system",
            "content": prompt_bundle.prompt,
        }
    ]
    history = load_history_entries()
    transcript: list[TranscriptEntry] = []

    print(
        _render_banner(
            runtime,
            cwd,
            permissions.get_summary(),
            {
                "transcriptCount": 0,
                "messageCount": len(messages),
                "skillCount": len(tools.get_skills()),
                "mcpCount": len(tools.get_mcp_servers()),
            },
        )
    )
    
    # 显示快速入门指南
    if not sys.stdin.isatty() or os.environ.get("MINI_CODE_SHOW_GUIDE", "1") == "1":
        print(_render_quick_start())
    else:
        print("")

    try:
        if not sys.stdin.isatty():
            for raw_input in sys.stdin:
                user_input = raw_input.strip()
                if not user_input:
                    continue
                if user_input == "/exit":
                    break
                if user_input.startswith("/transcript-save "):
                    output_path = user_input[len("/transcript-save ") :].strip()
                    if not output_path:
                        print("Usage: /transcript-save <path>")
                        continue
                    saved_path = _save_transcript_file(cwd, permissions, transcript, output_path)
                    print(f"Saved transcript to {saved_path}")
                    continue
                memory_result = memory_mgr.handle_user_memory_input(user_input)
                if memory_result is not None:
                    _append_transcript(transcript, kind="user", body=user_input)
                    _append_transcript(transcript, kind="assistant", body=memory_result)
                    print(memory_result)
                    continue
                local_result = _handle_local_command(user_input, tools)
                if local_result is not None:
                    _append_transcript(transcript, kind="user", body=user_input)
                    _append_transcript(transcript, kind="assistant", body=local_result)
                    print(local_result)
                    continue
                shortcut = parse_local_tool_shortcut(user_input)
                if shortcut is not None:
                    _append_transcript(transcript, kind="user", body=user_input)
                    result = tools.execute(
                        shortcut["toolName"],
                        shortcut["input"],
                        context=ToolContext(cwd=cwd, permissions=permissions),
                    )
                    _append_transcript(
                        transcript,
                        kind="tool",
                        body=result.output,
                        toolName=shortcut["toolName"],
                        status="success" if result.ok else "error",
                    )
                    print(result.output)
                    continue
                _append_transcript(transcript, kind="user", body=user_input)
                messages.append({"role": "user", "content": user_input})
                history.append(user_input)
                save_history_entries(history)
                prompt_bundle = build_system_prompt_bundle(
                    cwd,
                    permissions.get_summary(),
                    {
                        "skills": tools.get_skills(),
                        "mcpServers": tools.get_mcp_servers(),
                        "memory_context": memory_mgr.get_relevant_context(query=user_input),
                        "runtime": runtime,
                    },
                )
                messages[0] = {
                    "role": "system",
                    "content": prompt_bundle.prompt,
                }
                permissions.begin_turn()
                messages = run_agent_turn(
                    model=model,
                    tools=tools,
                    messages=messages,
                    cwd=cwd,
                    permissions=permissions,
                    store=app_store,
                    context_manager=context_mgr,
                    memory_manager=memory_mgr,
                    runtime=runtime,
                )
                permissions.end_turn()
                
                # Log context usage after turn
                if context_mgr:
                    stats = context_mgr.get_stats()
                    logger.debug("After turn: %d tokens (%.0f%%)", stats.total_tokens, stats.usage_percentage)
                last_assistant = next((message for message in reversed(messages) if message["role"] == "assistant"), None)
                if last_assistant:
                    _append_transcript(transcript, kind="assistant", body=last_assistant["content"])
                    print(last_assistant["content"])
            return

        run_tty_app(
            runtime=runtime,
            tools=tools,
            model=model,
            messages=messages,
            cwd=cwd,
            permissions=permissions,
            resume_session=args.resume,
            list_sessions_only=args.list_sessions,
            list_workspace_sessions_only=args.list_workspace_sessions,
            memory_manager=memory_mgr,
            context_manager=context_mgr,
            prompt_bundle=prompt_bundle,
            product_snapshot=prompt_bundle.product_snapshot,
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Shutting down gracefully...")
    finally:
        # Graceful shutdown: clean up all resources
        from minicode.logging_config import get_logger
        logger = get_logger("main")
        logger.info("Shutting down...")
        
        # Dispose tools (closes MCP connections)
        try:
            tools.dispose()
            logger.info("Tools disposed successfully")
        except Exception as e:
            logger.warning("Error disposing tools: %s", e)
        
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
