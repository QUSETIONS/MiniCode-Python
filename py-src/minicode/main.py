from __future__ import annotations

import argparse
import json
import sys
import os
from pathlib import Path

from minicode.agent_loop import run_agent_turn
from minicode.cli_commands import find_matching_slash_commands, try_handle_local_command
from minicode.config import load_runtime_config
from minicode.history import load_history_entries, save_history_entries
from minicode.local_tool_shortcuts import parse_local_tool_shortcut
from minicode.manage_cli import maybe_handle_management_command
from minicode.model_registry import create_model_adapter, detect_provider, format_model_status, format_model_list
from minicode.agent_router import get_agent_router, reset_agent_router
from minicode.model_switcher import ModelSwitcher, SwitchResult
from minicode.smart_router import SmartRouter, get_smart_router, reset_smart_router
from minicode.session_persistence import SessionPersistence
from minicode.permissions import PermissionManager
from minicode.prompt import build_system_prompt
from minicode.tools import create_default_tool_registry
from minicode.tooling import ToolContext
from minicode.tui.transcript import format_transcript_text
from minicode.tui.types import TranscriptEntry
from minicode.tty_app import run_tty_app
from minicode.workspace import resolve_tool_path


def _handle_local_command(user_input: str, tools, session_persistence=None) -> str | None:
    if user_input == "/tools":
        return "\n".join(f"{tool.name}: {tool.description}" for tool in tools.list())
    if user_input == "/sessions" and session_persistence is not None:
        sessions = session_persistence.list_sessions()
        if not sessions:
            return "No saved sessions found."
        lines = ["Saved sessions:", ""]
        for i, s in enumerate(sessions, 1):
            lines.append(
                f"  {i}. [{s['session_id'][:8]}] {s['model']} - "
                f"{s['messages']} messages, {s['age_hours']}h ago"
            )
        lines.append("")
        lines.append(f"Total: {len(sessions)} session(s)")
        return "\n".join(lines)
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
        "--session",
        default=None,
        metavar="SESSION_ID",
        help="Start with a specific session ID",
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

    args, remaining_argv = parser.parse_known_args()
    if remaining_argv and not any(not arg.startswith("--") for arg in remaining_argv):
        parser.error(f"unrecognized arguments: {' '.join(remaining_argv)}")

    # Initialize logging
    from minicode.logging_config import setup_logging
    setup_logging(level=args.log_level)

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
    
    # Filter out our custom args before passing to management commands
    management_argv = [a for a in argv if not a.startswith("--")]
    if maybe_handle_management_command(cwd, management_argv):
        return

    runtime = None
    try:
        runtime = load_runtime_config(cwd)
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
    merged_profile = profile_manager.load_merged()
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

    # Initialize Session Persistence for auto-save/resume
    session_persistence = SessionPersistence(
        session_id=app_store.get_state().session_id,
        workspace=cwd,
    )

    # Initialize Smart Router for intelligent model routing
    feedback_path = Path(cwd) / ".minicode" / "routing_feedback.json"
    current_model_name = runtime.get("model", "") if runtime else ""
    switcher = ModelSwitcher(
        current_model=current_model_name,
        current_runtime=runtime or {},
        current_tools=tools,
    )
    smart_router = SmartRouter(
        switcher=switcher,
        feedback_path=feedback_path,
    )
    logger.info("Smart router initialized (feedback: %s)", feedback_path)
    
    messages = [
        {
            "role": "system",
            "content": build_system_prompt(
                cwd,
                permissions.get_summary(),
                {
                    "skills": tools.get_skills(),
                    "mcpServers": tools.get_mcp_servers(),
                    "memory_context": memory_mgr.get_relevant_context(),  # Inject memory
                },
            ),
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
                local_result = _handle_local_command(user_input, tools, session_persistence)
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

                # Handle smart routing commands
                if user_input.startswith("/model "):
                    model_arg = user_input[len("/model ") :].strip()
                    if model_arg == "status":
                        info = format_model_status(switcher.current_model, runtime)
                        print(info)
                    elif model_arg == "list":
                        print(format_model_list())
                    elif model_arg == "route":
                        report = smart_router.get_performance_report()
                        print(json.dumps(report, indent=2, default=str))
                    else:
                        switch_result = switcher.switch_to(model_arg, reason="manual_switch")
                        if switch_result.success:
                            model = switch_result.adapter
                            app_store.set("model", model_arg)
                            print(f"Model switched to {model_arg}")
                        else:
                            print(f"Switch failed: {'; '.join(switch_result.errors)}")
                    _append_transcript(transcript, kind="user", body=user_input)
                    _append_transcript(transcript, kind="assistant", body=user_input)
                    continue

                if user_input == "/route":
                    report = smart_router.get_performance_report()
                    routing_info = json.dumps(report["routing_stats"], indent=2, default=str)
                    _append_transcript(transcript, kind="user", body=user_input)
                    _append_transcript(transcript, kind="assistant", body=routing_info)
                    print(routing_info)
                    continue

                _append_transcript(transcript, kind="user", body=user_input)
                messages.append({"role": "user", "content": user_input})
                history.append(user_input)
                save_history_entries(history)

                # Smart routing: analyze task and switch model if needed
                decision, switch_result = smart_router.route_and_switch(
                    task_text=user_input,
                    current_model=switcher.current_model,
                )

                # Update active model if switched
                if switch_result and switch_result.success:
                    model = switch_result.adapter
                    app_store.set("model", decision.selected_model)
                    logger.info("Auto-routed to %s (%s)", decision.selected_model, decision.tier_name)
                    if sys.stdin.isatty():
                        print(f"  [Router] Complexity: {decision.profile.complexity.value} -> Using {decision.selected_model}")

                messages[0] = {
                    "role": "system",
                    "content": build_system_prompt(
                        cwd,
                        permissions.get_summary(),
                        {
                            "skills": tools.get_skills(),
                            "mcpServers": tools.get_mcp_servers(),
                            "memory_context": memory_mgr.get_relevant_context(query=user_input),
                        },
                    ),
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
                    runtime=runtime,
                )
                permissions.end_turn()

                # Log context usage after turn
                if context_mgr:
                    stats = context_mgr.get_stats()
                    logger.debug("After turn: %d tokens (%.0f%%)", stats.total_tokens, stats.usage_percentage)

                # Record task outcome for learning
                last_assistant = next((message for message in reversed(messages) if message["role"] == "assistant"), None)
                success = last_assistant is not None and not last_assistant["content"].startswith("Model API error")
                smart_router.record_task_outcome(
                    task_text=user_input,
                    success=success,
                    tool_errors=0,  # Would be tracked via metrics_collector
                )

                if last_assistant:
                    _append_transcript(transcript, kind="assistant", body=last_assistant["content"])
                    print(last_assistant["content"])

                # Auto-save session state
                session_persistence.save(
                    model=switcher.current_model,
                    messages=messages,
                    compaction_level=context_mgr._compaction_level if context_mgr else 0,
                )
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
            memory_manager=memory_mgr,
            context_manager=context_mgr,
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Shutting down gracefully...")
    finally:
        # Graceful shutdown: clean up all resources
        from minicode.logging_config import get_logger
        logger = get_logger("main")
        logger.info("Shutting down...")

        # Force save session before exit
        try:
            session_persistence.save(
                model=switcher.current_model,
                messages=messages,
                compaction_level=context_mgr._compaction_level if context_mgr else 0,
                force=True,
            )
            logger.info("Session saved before shutdown")
        except Exception as e:
            logger.warning("Error saving session: %s", e)

        # Dispose tools (closes MCP connections)
        try:
            tools.dispose()
            logger.info("Tools disposed successfully")
        except Exception as e:
            logger.warning("Error disposing tools: %s", e)

        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
