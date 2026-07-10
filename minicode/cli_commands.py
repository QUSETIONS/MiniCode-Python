from __future__ import annotations

import json
from pathlib import Path

from Main.MinicodeFrontline.Src.Application.Entry.LocalCommandSurface import (
    SLASH_COMMANDS,
)
from minicode.config import (
    CLAUDE_SETTINGS_PATH,
    MINI_CODE_MCP_PATH,
    MINI_CODE_PERMISSIONS_PATH,
    MINI_CODE_SETTINGS_PATH,
    load_runtime_config,
    save_mini_code_settings,
)
from minicode.product_surfaces import (
    build_product_snapshot,
    extension_manifest_payload,
    resolve_extension_manifest,
    set_extension_enabled,
)
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
    rewind_session_data,
)


def format_slash_commands() -> str:
    lines = [
        "╔══════════════════════════════════════════════════════════╗",
        "║  📚 Available Commands                                  ║",
        "╠══════════════════════════════════════════════════════════╣",
    ]
    
    command_groups = {
        "🔧 Core Commands": [
            ("/help", "Show this help message"),
            ("/exit", "Exit mini-code"),
            ("/clear", "Clear the current transcript view"),
            ("/history", "Show recent prompt history"),
        ],
        "🛠️ Tool Commands": [
            ("/tools", "List all available tools"),
            ("/skills", "List discovered SKILL.md workflows"),
            ("/mcp", "Show MCP servers and connection state"),
            ("/cmd", "Run development commands directly"),
        ],
        "📊 Status & Info": [
            ("/status", "Show application state summary"),
            ("/model", "Show or change current model"),
            ("/user", "Show or manage user profile"),
            ("/cost", "Show API cost and usage report"),
            ("/context", "Show context window usage"),
            ("/cybernetics", "Show control-system status"),
            ("/tasks", "Show current task list"),
            ("/memory", "Show memory system status"),
        ],
        "✏️ File Operations": [
            ("/ls [path]", "List files in directory"),
            ("/grep <pattern>", "Search text in files"),
            ("/read <path>", "Read a file directly"),
            ("/write <path>", "Write content to file"),
            ("/edit <path>", "Edit file by exact replacement"),
            ("/patch <path>", "Apply multiple replacements in one go"),
            ("/modify <path>", "Replace file with reviewable diff"),
        ],
        "💾 Session Management": [
            ("/session", "Inspect current session state"),
            ("/session <id>", "Inspect saved session or latest"),
            ("/session-replay", "Replay active session timeline"),
            ("/session-replay <id>", "Replay saved session timeline"),
            ("/sessions", "List saved sessions for workspace"),
            ("/instructions", "Inspect active instruction layering"),
            ("/hooks", "Inspect hook telemetry and failures"),
            ("/delegation", "Inspect background task capacity"),
            ("/extensions", "Inspect local extension manifests"),
            ("/extension-inspect <name>", "Inspect one extension in detail"),
            ("/extension-enable <name>", "Enable a local extension"),
            ("/extension-disable <name>", "Disable a local extension"),
            ("/readiness", "Inspect provider/runtime readiness"),
            ("/checkpoints", "List active session checkpoints"),
            ("/checkpoints <id>", "List saved session checkpoints"),
            ("/rewind-preview [arg]", "Preview active session rewind plan"),
            ("/rewind [arg]", "Rewind active session file edits"),
            ("/session-rewind-preview <id> [arg]", "Preview saved session rewind plan"),
            ("/session-rewind <id> [arg]", "Rewind saved session file edits"),
            ("/transcript-save <path>", "Save transcript to text file"),
            ("/retry", "Retry the last prompt"),
            ("/permissions", "Show permission storage path"),
            ("/config-paths", "Show settings file paths"),
        ],
    }
    
    for group_name, commands in command_groups.items():
        lines.append(f"║  {group_name:<54}║")
        for cmd, desc in commands:
            cmd_display = f"    {cmd}"
            lines.append(f"║  {cmd_display:<20} {desc:<33} ║")
        lines.append("╠══════════════════════════════════════════════════════════╣")
    
    lines.extend([
        "║  💡 Tips:                                              ║",
        "║  - Use Tab to autocomplete commands                    ║",
        "║  - Prefix with / to access any command                 ║",
        "║  - Type naturally - I'll understand Chinese & English  ║",
        "╚══════════════════════════════════════════════════════════╝",
    ])
    
    return "\n".join(lines)


def find_matching_slash_commands(user_input: str) -> list[str]:
    """Find slash commands matching user input.

    Tries exact prefix first, falls back to fuzzy subsequence matching.
    """
    commands = [c.usage for c in SLASH_COMMANDS]
    prefix_matches = [c for c in commands if c.startswith(user_input)]
    if prefix_matches:
        return prefix_matches
    # Fuzzy fallback: subsequence match (e.g., "mem" matches "/memory")
    lower = user_input.lower()
    fuzzy = [c for c in commands if all(ch in c.lower() for ch in lower)]
    return fuzzy if fuzzy else commands


def complete_slash_command(line: str) -> tuple[list[str], str]:
    commands = [c.usage for c in SLASH_COMMANDS]
    hits = [c for c in commands if c.startswith(line)]
    if not hits and line:
        lower = line.lower()
        hits = [c for c in commands if all(ch in c.lower() for ch in lower)]
    return (hits if hits else commands, line)


def try_handle_local_command(
    user_input: str,
    tools=None,
    cwd: str | None = None,
    session=None,
) -> str | None:
    def _product_snapshot() -> dict:
        if session is not None:
            instruction_layers = list(getattr(session, "instruction_layers", []) or [])
            hook_status = dict(getattr(session, "hook_status", {}) or {})
            delegated_tasks = list(getattr(session, "delegated_tasks", []) or [])
            delegation_status = dict(getattr(session, "delegation_status", {}) or {})
            extension_manifests = list(getattr(session, "extension_manifests", []) or [])
            readiness_report = dict(getattr(session, "readiness_report", {}) or {})
            if any(
                [
                    instruction_layers,
                    hook_status,
                    delegated_tasks,
                    delegation_status,
                    extension_manifests,
                    readiness_report,
                ]
            ):
                metadata = getattr(session, "metadata", None)
                return {
                    "instruction_layers": instruction_layers,
                    "instruction_summary": getattr(metadata, "instruction_summary", ""),
                    "hook_status": hook_status,
                    "hook_summary": getattr(metadata, "hook_summary", ""),
                    "delegated_tasks": delegated_tasks,
                    "delegation_status": delegation_status,
                    "delegation_summary": getattr(metadata, "delegation_summary", ""),
                    "extension_manifests": extension_manifests,
                    "extension_summary": getattr(metadata, "extension_summary", ""),
                    "readiness_report": readiness_report,
                    "readiness_summary": getattr(metadata, "readiness_summary", ""),
                }
        if cwd is None:
            return {}
        return build_product_snapshot(cwd)

    def _format_instruction_surface(snapshot: dict) -> str:
        layers = list(snapshot.get("instruction_layers", []) or [])
        lines = [
            "Instruction surface:",
            snapshot.get("instruction_summary", "instructions: unavailable"),
        ]
        if not layers:
            lines.append("No instruction layers discovered for this workspace.")
            return "\n".join(lines)
        lines.append("")
        lines.append(f"Layers ({len(layers)}):")
        for layer in layers:
            scope = str(layer.get("scope") or "unknown")
            kind = str(layer.get("kind") or "unknown")
            exists = "active" if layer.get("exists") else "missing"
            path = str(layer.get("path") or "")
            preview = str(layer.get("preview") or "")
            detail = f"- {scope}/{kind}: {exists}"
            if path:
                detail += f" [{path}]"
            lines.append(detail)
            if preview:
                lines.append(f"  preview: {preview}")
        return "\n".join(lines)

    def _format_hook_surface(snapshot: dict) -> str:
        status = dict(snapshot.get("hook_status", {}) or {})
        lines = [
            "Hook surface:",
            snapshot.get("hook_summary", "hooks: unavailable"),
        ]
        if not status:
            lines.append("No hook telemetry is available.")
            return "\n".join(lines)
        lines.extend(
            [
                "",
                f"Registered hooks: {status.get('enabled_hooks', 0)}/{status.get('total_hooks', 0)} enabled",
                f"Calls: {status.get('total_calls', 0)}",
                f"Duration: {status.get('total_duration_ms', 0)}ms",
            ]
        )
        failure_count = status.get("failure_count")
        last_status = status.get("last_status")
        last_error = status.get("last_error")
        if failure_count is not None:
            lines.append(f"Failures: {failure_count}")
        if last_status:
            lines.append(f"Last status: {last_status}")
        if last_error:
            lines.append(f"Last error: {last_error}")
        return "\n".join(lines)

    def _format_delegation_surface(snapshot: dict) -> str:
        status = dict(snapshot.get("delegation_status", {}) or {})
        tasks = list(snapshot.get("delegated_tasks", []) or [])
        lines = [
            "Delegation surface:",
            snapshot.get("delegation_summary", "delegation: unavailable"),
        ]
        if not status and not tasks:
            lines.append("No delegation state is available.")
            return "\n".join(lines)
        if status:
            lines.extend(
                [
                    "",
                    f"Running tasks: {status.get('running_tasks', 0)}",
                    f"Tracked tasks: {status.get('total_tracked', 0)}",
                    f"Slots: {status.get('available_slots', 0)}/{status.get('max_slots', 0)} free",
                ]
            )
            labels = list(status.get("active_labels", []) or [])
            if labels:
                lines.append(f"Active labels: {', '.join(str(label) for label in labels)}")
        if tasks:
            lines.append("")
            lines.append(f"Tracked task details ({min(len(tasks), 5)} shown):")
            for task in tasks[:5]:
                label = str(task.get("label") or task.get("command") or task.get("taskId") or "task")
                task_status = str(task.get("status") or "unknown")
                lines.append(f"- {label} [{task_status}]")
        return "\n".join(lines)

    def _format_extension_surface(snapshot: dict) -> str:
        manifests = list(snapshot.get("extension_manifests", []) or [])
        lines = [
            "Extension surface:",
            snapshot.get("extension_summary", "extensions: unavailable"),
        ]
        if not manifests:
            lines.append("No extension manifests were discovered.")
            return "\n".join(lines)
        lines.append("")
        lines.append(f"Extensions ({len(manifests)}):")
        for manifest in manifests:
            name = str(manifest.get("name") or "extension")
            scope = str(manifest.get("scope") or "unknown")
            enabled = "enabled" if manifest.get("enabled", True) else "disabled"
            version = str(manifest.get("version") or "").strip()
            detail = f"- {name} [{scope}, {enabled}]"
            if version:
                detail += f" v{version}"
            lines.append(detail)
            description = str(manifest.get("description") or "").strip()
            entrypoint = str(manifest.get("entrypoint") or "").strip()
            if description:
                lines.append(f"  {description}")
            if entrypoint:
                lines.append(f"  entrypoint: {entrypoint}")
        return "\n".join(lines)

    def _format_readiness_surface(snapshot: dict) -> str:
        report = dict(snapshot.get("readiness_report", {}) or {})
        lines = [
            "Readiness surface:",
            snapshot.get("readiness_summary", "readiness: unavailable"),
        ]
        if not report:
            lines.append("No readiness report is available.")
            return "\n".join(lines)
        status = str(report.get("status") or "unknown")
        provider = str(report.get("provider") or "unknown")
        provider_ready = bool(report.get("provider_ready"))
        fallback_ready = bool(report.get("fallback_ready"))
        fallback_candidates = [
            str(candidate)
            for candidate in list(report.get("fallback_candidates", []) or [])
            if str(candidate).strip()
        ]
        viable_fallbacks = [
            str(candidate)
            for candidate in list(report.get("viable_fallbacks", []) or [])
            if str(candidate).strip()
        ]
        lines.extend(
            [
                "",
                f"Status: {status}",
                f"Provider: {provider}",
                f"Provider ready: {'yes' if provider_ready else 'no'}",
                f"Channel: {str(report.get('provider_channel') or 'unknown')}",
                f"Fallback ready: {'yes' if fallback_ready else 'no'}",
                f"Risk scope: {str(report.get('risk_scope') or 'unknown')}",
            ]
        )
        if fallback_candidates:
            lines.append(
                f"Configured fallbacks ({len(viable_fallbacks)}/{len(fallback_candidates)} locally ready):"
            )
            for candidate in fallback_candidates:
                label = "ready" if candidate in viable_fallbacks else "not-ready"
                lines.append(f"- {candidate} [{label}]")
        issues = [str(issue) for issue in list(report.get("issues", []) or []) if str(issue).strip()]
        if issues:
            lines.append("Issues:")
            lines.extend(f"- {issue}" for issue in issues)
        guidance = [
            str(item)
            for item in list(report.get("fallback_guidance", []) or [])
            if str(item).strip()
        ]
        if guidance:
            lines.append("Guidance:")
            lines.extend(f"- {item}" for item in guidance)
        preflight_checks = [
            dict(item)
            for item in list(report.get("preflight_checks", []) or [])
            if isinstance(item, dict)
        ]
        if preflight_checks:
            lines.append("Local preflight:")
            for check in preflight_checks:
                label = str(check.get("label") or "check").strip()
                status_text = str(check.get("status") or "unknown").strip()
                summary = str(check.get("summary") or "").strip()
                action = str(check.get("action") or "").strip()
                detail = f"- {label}: {status_text}"
                if summary:
                    detail += f" - {summary}"
                lines.append(detail)
                if action:
                    lines.append(f"  Action: {action}")
        next_actions = [
            str(item)
            for item in list(report.get("next_actions", []) or [])
            if str(item).strip()
        ]
        if next_actions:
            lines.append("Next actions:")
            lines.extend(f"- {item}" for item in next_actions)
        repair_plan = [
            dict(item)
            for item in list(report.get("repair_plan", []) or [])
            if isinstance(item, dict)
        ]
        if repair_plan:
            lines.append("Repair plan:")
            for item in repair_plan:
                step = str(item.get("step") or "step").strip()
                status_text = str(item.get("status") or "unknown").strip()
                action = str(item.get("action") or "").strip()
                command = str(item.get("command") or "").strip()
                detail = f"- {step}: {status_text}"
                if action:
                    detail += f" - {action}"
                lines.append(detail)
                if command:
                    lines.append(f"  Command: {command}")
        config_examples = [
            dict(item)
            for item in list(report.get("fallback_config_examples", []) or [])
            if isinstance(item, dict)
        ]
        if config_examples:
            lines.append("Config examples:")
            for item in config_examples:
                label = str(item.get("label") or "fallback config").strip()
                path = str(item.get("path") or "").strip()
                settings = item.get("settings", {})
                rendered_settings = json.dumps(settings, ensure_ascii=False, sort_keys=True)
                location = f" [{path}]" if path else ""
                lines.append(f"- {label}{location}: {rendered_settings}")
        return "\n".join(lines)

    def _format_extension_manifest_detail(identifier: str) -> str:
        if cwd is None:
            return "No workspace is available for extension inspection."
        try:
            manifest = resolve_extension_manifest(cwd, identifier)
            payload = extension_manifest_payload(manifest)
        except ValueError as exc:
            return str(exc)
        lines = [
            f"Extension inspect: {manifest.name}",
            f"Scope: {manifest.scope}",
            f"Enabled: {'yes' if manifest.enabled else 'no'}",
            f"Manifest: {manifest.path}",
        ]
        if manifest.version:
            lines.append(f"Version: {manifest.version}")
        if manifest.description:
            lines.append(f"Description: {manifest.description}")
        if manifest.entrypoint:
            entrypoint = Path(manifest.path).parent / manifest.entrypoint
            exists = "yes" if entrypoint.exists() else "no"
            lines.append(f"Entrypoint: {manifest.entrypoint}")
            lines.append(f"Entrypoint path: {entrypoint}")
            lines.append(f"Entrypoint exists: {exists}")
        extra_keys = sorted(
            key for key in payload.keys()
            if key not in {"name", "version", "description", "enabled", "entrypoint"}
        )
        if extra_keys:
            lines.append("Extra manifest keys:")
            lines.extend(f"- {key}" for key in extra_keys)
        return "\n".join(lines)

    def _set_extension_state(identifier: str, enabled: bool) -> str:
        if cwd is None:
            return "No workspace is available for extension changes."
        try:
            manifest = set_extension_enabled(cwd, identifier, enabled)
        except ValueError as exc:
            return str(exc)
        status = "enabled" if enabled else "disabled"
        return (
            f"Extension {manifest.scope}:{manifest.name} is now {status}.\n\n"
            f"{_format_extension_manifest_detail(f'{manifest.scope}:{manifest.name}')}"
        )

    def _format_rewind_result(target_session, restored, prefix: str) -> str:
        restored_preview = ", ".join(
            f"[{item.checkpoint_id[:8]}] {Path(item.file_path).name or item.file_path}"
            for item in restored
        )
        return (
            f"{prefix} {len(restored)} checkpoint(s) for session {target_session.session_id[:8]}.\n"
            f"Restored: {restored_preview}\n\n"
            f"{format_session_resume(target_session)}"
        )

    def _workspace_session(target: str):
        workspace = str(Path(cwd).resolve()) if cwd else None
        return (
            get_latest_session(workspace=workspace)
            if target == "latest"
            else load_session(target)
        )

    if user_input in {"/", "/help"}:
        return format_slash_commands()

    if user_input == "/config-paths":
        return "\n".join(
            [
                f"mini-code settings: {MINI_CODE_SETTINGS_PATH}",
                f"mini-code permissions: {MINI_CODE_PERMISSIONS_PATH}",
                f"mini-code mcp: {MINI_CODE_MCP_PATH}",
                f"compat fallback: {CLAUDE_SETTINGS_PATH}",
            ]
        )

    if user_input == "/permissions":
        return f"permission store: {MINI_CODE_PERMISSIONS_PATH}"

    if user_input == "/sessions":
        workspace = str(Path(cwd).resolve()) if cwd else None
        sessions = list_sessions()
        if workspace is not None:
            sessions = [meta for meta in sessions if meta.workspace == workspace]
        return format_session_list(sessions)

    if user_input == "/instructions":
        return _format_instruction_surface(_product_snapshot())

    if user_input == "/hooks":
        return _format_hook_surface(_product_snapshot())

    if user_input == "/delegation":
        return _format_delegation_surface(_product_snapshot())

    if user_input == "/extensions":
        return _format_extension_surface(_product_snapshot())

    if user_input.startswith("/extension-inspect "):
        identifier = user_input[len("/extension-inspect ") :].strip()
        if not identifier:
            return "Usage: /extension-inspect <name>"
        return _format_extension_manifest_detail(identifier)

    if user_input.startswith("/extension-enable "):
        identifier = user_input[len("/extension-enable ") :].strip()
        if not identifier:
            return "Usage: /extension-enable <name>"
        return _set_extension_state(identifier, True)

    if user_input.startswith("/extension-disable "):
        identifier = user_input[len("/extension-disable ") :].strip()
        if not identifier:
            return "Usage: /extension-disable <name>"
        return _set_extension_state(identifier, False)

    if user_input == "/readiness":
        return _format_readiness_surface(_product_snapshot())

    if user_input == "/session":
        if session is None:
            return "No active session."
        return format_session_inspect(session)

    if user_input == "/session-replay":
        if session is None:
            return "No active session."
        return format_session_replay(session)

    if user_input == "/checkpoints":
        if session is None:
            return "No active session."
        return format_session_checkpoints(session)

    if user_input.startswith("/session "):
        target = user_input[len("/session ") :].strip()
        if not target:
            return "Usage: /session <session-id|latest>"
        if session is not None and target == getattr(session, "session_id", None):
            return format_session_inspect(session)
        target_session = _workspace_session(target)
        if target_session is None:
            return "No saved session found for inspection."
        return format_session_inspect(target_session)

    if user_input.startswith("/session-replay "):
        target = user_input[len("/session-replay ") :].strip()
        if not target:
            return "Usage: /session-replay <session-id|latest>"
        if session is not None and target == getattr(session, "session_id", None):
            return format_session_replay(session)
        target_session = _workspace_session(target)
        if target_session is None:
            return "No saved session found for replay."
        return format_session_replay(target_session)

    if user_input.startswith("/checkpoints "):
        target = user_input[len("/checkpoints ") :].strip()
        if not target:
            return "Usage: /checkpoints <session-id|latest>"
        if session is not None and target == getattr(session, "session_id", None):
            return format_session_checkpoints(session)
        target_session = _workspace_session(target)
        if target_session is None:
            return "No saved session found for checkpoint inspection."
        return format_session_checkpoints(target_session)

    if user_input == "/rewind-preview" or user_input.startswith("/rewind-preview "):
        if session is None:
            return "No active session."
        target = user_input[len("/rewind-preview") :].strip()
        steps = 1
        checkpoint_id = None
        if target and target != "latest":
            if target.isdigit():
                steps = max(1, int(target))
            else:
                checkpoint_id = target
        return format_rewind_preview(
            session,
            steps=steps,
            checkpoint_id=checkpoint_id,
        )

    if user_input == "/rewind" or user_input.startswith("/rewind "):
        if session is None:
            return "No active session."
        target = user_input[len("/rewind") :].strip()
        steps = 1
        checkpoint_id = None
        if target and target != "latest":
            if target.isdigit():
                steps = max(1, int(target))
            else:
                checkpoint_id = target
        restored = rewind_session_data(
            session,
            steps=steps,
            checkpoint_id=checkpoint_id,
        )
        if not restored:
            return "No checkpoints available to rewind."
        return _format_rewind_result(session, restored, "Rewound")

    if user_input.startswith("/session-rewind "):
        raw = user_input[len("/session-rewind ") :].strip()
        if not raw:
            return "Usage: /session-rewind <session-id|latest> [latest|steps|checkpoint-id]"
        parts = raw.split(maxsplit=1)
        target = parts[0]
        rewind_arg = parts[1].strip() if len(parts) > 1 else "latest"
        steps = 1
        checkpoint_id = None
        if rewind_arg and rewind_arg != "latest":
            if rewind_arg.isdigit():
                steps = max(1, int(rewind_arg))
            else:
                checkpoint_id = rewind_arg
        if session is not None and target == getattr(session, "session_id", None):
            restored = rewind_session_data(
                session,
                steps=steps,
                checkpoint_id=checkpoint_id,
            )
            if not restored:
                return "No checkpoints available to rewind for that session."
            return _format_rewind_result(session, restored, "Rewound")
        target_session = _workspace_session(target)
        if target_session is None:
            return "No saved session found to rewind."
        rewound_session, restored = rewind_session(
            target_session.session_id,
            steps=steps,
            checkpoint_id=checkpoint_id,
        )
        if rewound_session is None or not restored:
            return "No checkpoints available to rewind for that session."
        return _format_rewind_result(rewound_session, restored, "Rewound")

    if user_input.startswith("/session-rewind-preview "):
        raw = user_input[len("/session-rewind-preview ") :].strip()
        if not raw:
            return "Usage: /session-rewind-preview <session-id|latest> [latest|steps|checkpoint-id]"
        parts = raw.split(maxsplit=1)
        target = parts[0]
        rewind_arg = parts[1].strip() if len(parts) > 1 else "latest"
        steps = 1
        checkpoint_id = None
        if rewind_arg and rewind_arg != "latest":
            if rewind_arg.isdigit():
                steps = max(1, int(rewind_arg))
            else:
                checkpoint_id = rewind_arg
        if session is not None and target == getattr(session, "session_id", None):
            return format_rewind_preview(
                session,
                steps=steps,
                checkpoint_id=checkpoint_id,
            )
        target_session = _workspace_session(target)
        if target_session is None:
            return "No saved session found to preview."
        return format_rewind_preview(
            target_session,
            steps=steps,
            checkpoint_id=checkpoint_id,
        )

    if user_input == "/skills":
        skills = tools.get_skills() if tools else []
        if not skills:
            return "No skills discovered. Add skills under ~/.mini-code/skills/<name>/SKILL.md, .mini-code/skills/<name>/SKILL.md, .claude/skills/<name>/SKILL.md, or ~/.claude/skills/<name>/SKILL.md."
        return "\n".join(
            f"{skill['name']}  {skill['description']}  [{skill['source']}]"
            for skill in skills
        )

    if user_input == "/config":
        from minicode.config import format_config_diagnostic
        return format_config_diagnostic()

    if user_input == "/state":
        try:
            from minicode.state import handle_state_command
            return handle_state_command()
        except ImportError:
            return "State system not available. Please ensure state.py exists."

    if user_input == "/memory":
        # Memory system display
        try:
            from minicode.memory import MemoryManager
            memory_mgr = MemoryManager(project_root=Path(cwd) if cwd else Path.cwd())
            return memory_mgr.format_stats()
        except Exception as e:
            return f"Error loading memory: {e}"

    if user_input == "/context":
        # Context usage display
        try:
            from minicode.context_manager import load_context_state
            ctx_mgr = load_context_state()
            if ctx_mgr:
                return ctx_mgr.format_context_details()
            else:
                return "No context state available. Context tracking starts after first turn."
        except Exception as e:
            return f"Error loading context: {e}"

    if user_input == "/cybernetics":
        return format_cybernetics_status()

    if user_input == "/mcp":
        servers = tools.get_mcp_servers() if tools else []
        if not servers:
            return "No MCP servers configured. Add mcpServers to ~/.mini-code/settings.json, ~/.mini-code/mcp.json, or project .mcp.json."
        lines = []
        for server in servers:
            suffix = f"  error={server['error']}" if server.get("error") else ""
            protocol = f"  protocol={server['protocol']}" if server.get("protocol") else ""
            resources = f"  resources={server['resourceCount']}" if server.get("resourceCount") is not None else ""
            prompts = f"  prompts={server['promptCount']}" if server.get("promptCount") is not None else ""
            lines.append(
                f"{server['name']}  status={server['status']}  tools={server['toolCount']}{resources}{prompts}{protocol}{suffix}"
            )
        return "\n".join(lines)

    if user_input == "/status":
        try:
            runtime = load_runtime_config()
        except Exception as error:  # noqa: BLE001
            return f"runtime not configured: {error}"
        from minicode.model_registry import detect_provider
        provider = detect_provider(runtime["model"], runtime)
        auth_methods = []
        if runtime.get("authToken"):
            auth_methods.append("ANTHROPIC_AUTH_TOKEN")
        if runtime.get("apiKey"):
            auth_methods.append("ANTHROPIC_API_KEY")
        if runtime.get("openaiApiKey"):
            auth_methods.append("OPENAI_API_KEY")
        if runtime.get("openrouterApiKey"):
            auth_methods.append("OPENROUTER_API_KEY")
        if runtime.get("customApiKey"):
            auth_methods.append("CUSTOM_API_KEY")
        return "\n".join(
            [
                f"model: {runtime['model']}",
                f"provider: {provider.value}",
                f"baseUrl: {runtime['baseUrl']}",
                f"auth: {', '.join(auth_methods) or 'none'}",
                f"mcp servers: {len(runtime.get('mcpServers', {}))}",
                runtime["sourceSummary"],
            ]
        )

    if user_input == "/model":
        try:
            runtime = load_runtime_config()
            from minicode.model_registry import format_model_status
            return format_model_status(runtime["model"], runtime)
        except Exception as error:  # noqa: BLE001
            return f"runtime not configured: {error}"

    if user_input.startswith("/model "):
        arg = user_input[len("/model "):].strip()
        if not arg:
            from minicode.model_registry import format_model_list
            return format_model_list()
        # Subcommands
        if arg in ("status", "info"):
            try:
                runtime = load_runtime_config()
                from minicode.model_registry import format_model_status
                return format_model_status(runtime["model"], runtime)
            except Exception as error:  # noqa: BLE001
                return f"runtime not configured: {error}"
        if arg in ("list", "ls"):
            from minicode.model_registry import format_model_list
            return format_model_list()
        # Provider filter: /model anthropic, /model openrouter, etc.
        from minicode.model_registry import Provider, format_model_list
        for p in Provider:
            if arg.lower() == p.value:
                return format_model_list(provider=p)
        # Otherwise: set model name
        save_mini_code_settings({"model": arg})
        return f"saved model={arg} to {MINI_CODE_SETTINGS_PATH}\nRestart MiniCode for the change to take effect."

    if user_input == "/user" or user_input.startswith("/user "):
        from minicode.user_profile import handle_user_command
        args = user_input[len("/user"):].strip()
        return handle_user_command(args)

    return None


def format_cybernetics_status() -> str:
    """Format cybernetic controller inventory and persisted state hints."""
    from minicode.cybernetic_supervisor import CyberneticSupervisor, load_supervisor_report
    from minicode.context_manager import load_context_state

    controllers = [
        ("ContextCyberneticsOrchestrator", "context pressure PID + prediction"),
        ("CostControlLoop", "budget PID for tool-result persistence"),
        ("VerificationController", "risk-adaptive verification planning"),
        ("ToolSchedulerController", "error/latency-aware concurrency control"),
        ("MemoryInjectionController", "context-aware memory injection"),
        ("ModelSelectionController", "cost/latency/failure-aware model routing"),
        ("ProgressController", "health/stall task progress control"),
        ("CyberneticSupervisor", "global health and risk aggregation"),
    ]

    ctx = load_context_state()
    snapshots = []
    if ctx:
        stats = ctx.get_stats()
        usage = stats.usage_percentage / 100.0
        snapshots.append(CyberneticSupervisor().snapshot_from_context({
            "sensor": {"current_usage": usage},
            "predictor": {"urgency": 0.0},
        }))
    persisted_report = load_supervisor_report()
    report = persisted_report or CyberneticSupervisor().report(snapshots)

    lines = [
        "Cybernetic Control System",
        "=" * 50,
        f"overall_health: {report.overall_health:.2f}",
        f"risk_level: {report.risk_level.value}",
        f"source: {'latest agent-loop report' if persisted_report else 'current persisted context'}",
        "",
        "Controllers:",
    ]
    for name, desc in controllers:
        lines.append(f"  - {name}: {desc}")
    lines.extend([
        "",
        "Runtime aggregation:",
        "  - pipeline outputs: progress_control + verification_plan + cybernetic_supervisor",
        "  - agent loop logs: context + cost + tool scheduling supervisor report",
    ])
    if report.recommended_actions:
        lines.append("")
        lines.append("Current actions:")
        for action in report.recommended_actions[:5]:
            lines.append(f"  - {action}")
    return "\n".join(lines)
