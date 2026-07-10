from minicode.cli_commands import find_matching_slash_commands, format_slash_commands, try_handle_local_command
from Main.MinicodeFrontline.Src.Application.Entry.LocalCommandSurface import (
    SLASH_COMMANDS as MAIN_SLASH_COMMANDS,
)
from minicode.cli_commands import SLASH_COMMANDS as COMPAT_SLASH_COMMANDS
from minicode.local_tool_shortcuts import parse_local_tool_shortcut
from minicode.session import FileCheckpoint, SessionData, SessionMetadata


def _write_extension_manifest(root, *, name: str, enabled: bool = True, version: str = "1.0.0"):
    extension_dir = root / name
    extension_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = extension_dir / "extension.json"
    manifest_path.write_text(
        (
            "{\n"
            f'  "name": "{name}",\n'
            f'  "version": "{version}",\n'
            '  "description": "Local helper bundle",\n'
            f'  "enabled": {"true" if enabled else "false"},\n'
            '  "entrypoint": "bundle.py"\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    (extension_dir / "bundle.py").write_text("print('ok')\n", encoding="utf-8")
    return manifest_path


def test_find_matching_slash_commands_returns_help_variants() -> None:
    matches = find_matching_slash_commands("/mo")
    assert "/model" in matches
    assert "/model <model-name>" in matches


def test_cli_command_compatibility_surface_uses_main_contract() -> None:
    assert COMPAT_SLASH_COMMANDS is MAIN_SLASH_COMMANDS


def test_find_matching_slash_commands_returns_cybernetics() -> None:
    matches = find_matching_slash_commands("/cy")
    assert "/cybernetics" in matches


def test_parse_local_tool_shortcut_parses_cmd() -> None:
    shortcut = parse_local_tool_shortcut("/cmd src::git status")
    assert shortcut == {
        "toolName": "run_command",
        "input": {"command": "git status", "cwd": "src"},
    }


def test_parse_local_tool_shortcut_parses_patch_pairs() -> None:
    shortcut = parse_local_tool_shortcut("/patch demo.txt::hello::hi::world::earth")
    assert shortcut == {
        "toolName": "patch_file",
        "input": {
            "path": "demo.txt",
            "replacements": [
                {"search": "hello", "replace": "hi"},
                {"search": "world", "replace": "earth"},
            ],
        },
    }


def test_format_slash_commands_includes_permissions() -> None:
    assert "/permissions" in format_slash_commands()


def test_format_slash_commands_describes_patch_replacements() -> None:
    commands = format_slash_commands()
    # 检查格式化后的帮助信息包含关键命令
    assert "/patch" in commands
    assert "replacements" in commands or "multiple" in commands


def test_format_slash_commands_includes_history_and_retry() -> None:
    commands = format_slash_commands()
    assert "/history" in commands
    assert "/retry" in commands
    assert "/cybernetics" in commands
    assert "/session" in commands
    assert "/session-replay" in commands
    assert "/sessions" in commands
    assert "/checkpoints" in commands
    assert "/rewind-preview" in commands
    assert "/rewind" in commands
    assert "/session-rewind-preview" in commands
    assert "/session-rewind" in commands


def test_session_command_returns_active_session_inspect() -> None:
    session = SessionData(
        session_id="session-1234",
        created_at=1.0,
        updated_at=2.0,
        workspace="D:/repo",
        transcript_entries=[{"kind": "assistant", "body": "done"}],
    )
    session.metadata.runtime_summary = "phase:verify@2 -> stop:done@3"

    result = try_handle_local_command("/session", session=session)

    assert result is not None
    assert "Session inspect: session-" in result
    assert "Runtime: phase:verify@2 -> stop:done@3" in result
    assert "Recent transcript" in result


def test_product_surface_commands_use_active_session_snapshot() -> None:
    session = SessionData(
        session_id="session-1234",
        created_at=1.0,
        updated_at=2.0,
        workspace="D:/repo",
        instruction_layers=[
            {
                "name": "project-managed",
                "scope": "project",
                "kind": "managed",
                "path": "D:/repo/.mini-code/MANAGED.md",
                "exists": True,
                "preview": "Prefer verification-first delivery.",
            }
        ],
        hook_status={
            "total_hooks": 2,
            "enabled_hooks": 1,
            "total_calls": 4,
            "total_duration_ms": 18,
            "failure_count": 1,
            "last_status": "error",
            "last_error": "pytest failed",
        },
        delegated_tasks=[
            {"label": "lint-worker", "status": "running"},
        ],
        delegation_status={
            "running_tasks": 1,
            "total_tracked": 2,
            "max_slots": 4,
            "available_slots": 3,
            "active_labels": ["lint-worker"],
        },
        extension_manifests=[
            {
                "name": "git-helpers",
                "scope": "project",
                "enabled": True,
                "version": "1.2.0",
                "description": "Extra git shortcuts",
                "entrypoint": "extensions/git_helpers.py",
            }
        ],
        readiness_report={
            "status": "warning",
            "provider": "anthropic-compatible",
            "provider_ready": True,
            "provider_channel": "anthropic-compatible via baseUrl/authToken",
            "fallback_ready": False,
            "fallback_candidates": ["qwen3.6-plus", "gpt-4o"],
            "viable_fallbacks": ["gpt-4o"],
            "fallback_guidance": [
                "Primary runtime is using a single anthropic-compatible channel from baseUrl/authToken.",
                "Add fallbackModels or anthropicFallbackModels to enable model failover.",
            ],
            "risk_scope": "fallback-gap",
            "next_actions": [
                "Configure at least one locally ready fallback model.",
                "Add fallbackModels or anthropicFallbackModels to enable model failover.",
            ],
            "repair_plan": [
                {
                    "step": "choose-fallback-provider",
                    "status": "manual",
                    "action": "Choose one fallback provider.",
                },
                {
                    "step": "verify-local-readiness",
                    "status": "verify",
                    "command": "minicode-readiness --json --fail-on blocked",
                },
            ],
            "fallback_config_examples": [
                {
                    "label": "OpenAI fallback",
                    "path": "D:/home/.mini-code/settings.json",
                    "settings": {
                        "fallbackModels": ["gpt-4o"],
                        "env": {"OPENAI_API_KEY": "sk-..."},
                    },
                }
            ],
            "preflight_checks": [
                {
                    "label": "primary-provider-config",
                    "status": "pass",
                    "summary": "anthropic-compatible via baseUrl/authToken",
                    "action": "Run a live provider smoke before release.",
                },
                {
                    "label": "fallback-coverage",
                    "status": "warning",
                    "summary": "1/2 fallback model(s) locally ready",
                    "action": "Configure at least one locally ready fallback model.",
                },
            ],
            "issues": ["Fallback 'qwen3.6-plus' is not locally ready: Missing provider channel"],
        },
    )
    session.update_metadata()

    instructions = try_handle_local_command("/instructions", session=session, cwd="D:/repo")
    hooks = try_handle_local_command("/hooks", session=session, cwd="D:/repo")
    delegation = try_handle_local_command("/delegation", session=session, cwd="D:/repo")
    extensions = try_handle_local_command("/extensions", session=session, cwd="D:/repo")
    readiness = try_handle_local_command("/readiness", session=session, cwd="D:/repo")

    assert instructions is not None
    assert "Instruction surface:" in instructions
    assert "project/managed: active" in instructions
    assert "Prefer verification-first delivery." in instructions

    assert hooks is not None
    assert "Hook surface:" in hooks
    assert "Failures: 1" in hooks
    assert "Last error: pytest failed" in hooks

    assert delegation is not None
    assert "Delegation surface:" in delegation
    assert "Tracked task details" in delegation
    assert "lint-worker [running]" in delegation

    assert extensions is not None
    assert "Extension surface:" in extensions
    assert "git-helpers [project, enabled] v1.2.0" in extensions
    assert "entrypoint: extensions/git_helpers.py" in extensions

    assert readiness is not None
    assert "Readiness surface:" in readiness
    assert "Provider ready: yes" in readiness
    assert "Fallback ready: no" in readiness
    assert "Risk scope: fallback-gap" in readiness
    assert "Channel: anthropic-compatible via baseUrl/authToken" in readiness
    assert "Configured fallbacks (1/2 locally ready):" in readiness
    assert "- qwen3.6-plus [not-ready]" in readiness
    assert "- gpt-4o [ready]" in readiness
    assert "Guidance:" in readiness
    assert "single anthropic-compatible channel" in readiness
    assert "Local preflight:" in readiness
    assert "primary-provider-config: pass" in readiness
    assert "fallback-coverage: warning" in readiness
    assert "Next actions:" in readiness
    assert "Configure at least one locally ready fallback model." in readiness
    assert "Repair plan:" in readiness
    assert "choose-fallback-provider: manual" in readiness
    assert "Command: minicode-readiness --json --fail-on blocked" in readiness
    assert "Config examples:" in readiness
    assert "OpenAI fallback" in readiness
    assert "OPENAI_API_KEY" in readiness
    assert "Missing provider channel" in readiness


def test_extension_inspect_command_reads_project_manifest(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    project_extensions = workspace / ".mini-code" / "extensions"
    project_extensions.mkdir(parents=True)
    _write_extension_manifest(project_extensions, name="git-helpers", enabled=True, version="1.2.3")
    global_extensions = tmp_path / "global-extensions"
    global_extensions.mkdir()
    monkeypatch.setattr("minicode.product_surfaces.MINI_CODE_EXTENSIONS_DIR", global_extensions)

    result = try_handle_local_command("/extension-inspect git-helpers", cwd=str(workspace))

    assert result is not None
    assert "Extension inspect: git-helpers" in result
    assert "Scope: project" in result
    assert "Enabled: yes" in result
    assert "Entrypoint exists: yes" in result


def test_extension_enable_and_disable_commands_update_manifest(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    project_extensions = workspace / ".mini-code" / "extensions"
    project_extensions.mkdir(parents=True)
    manifest_path = _write_extension_manifest(
        project_extensions,
        name="git-helpers",
        enabled=False,
    )
    global_extensions = tmp_path / "global-extensions"
    global_extensions.mkdir()
    monkeypatch.setattr("minicode.product_surfaces.MINI_CODE_EXTENSIONS_DIR", global_extensions)

    enabled = try_handle_local_command("/extension-enable git-helpers", cwd=str(workspace))
    assert enabled is not None
    assert "Extension project:git-helpers is now enabled." in enabled
    assert '"enabled": true' in manifest_path.read_text(encoding="utf-8")

    disabled = try_handle_local_command("/extension-disable project:git-helpers", cwd=str(workspace))
    assert disabled is not None
    assert "Extension project:git-helpers is now disabled." in disabled
    assert '"enabled": false' in manifest_path.read_text(encoding="utf-8")


def test_extension_inspect_requires_scope_when_names_are_ambiguous(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    project_extensions = workspace / ".mini-code" / "extensions"
    project_extensions.mkdir(parents=True)
    _write_extension_manifest(project_extensions, name="git-helpers", enabled=True)
    global_extensions = tmp_path / "global-extensions"
    global_extensions.mkdir()
    _write_extension_manifest(global_extensions, name="git-helpers", enabled=False)
    monkeypatch.setattr("minicode.product_surfaces.MINI_CODE_EXTENSIONS_DIR", global_extensions)

    result = try_handle_local_command("/extension-inspect git-helpers", cwd=str(workspace))

    assert result is not None
    assert "Multiple extensions matched 'git-helpers'." in result
    assert "global:git-helpers" in result
    assert "project:git-helpers" in result


def test_checkpoints_command_returns_active_session_checkpoints() -> None:
    session = SessionData(
        session_id="session-1234",
        created_at=1.0,
        updated_at=2.0,
        workspace="D:/repo",
        checkpoints=[
            FileCheckpoint(
                checkpoint_id="abc123456789",
                created_at=3.0,
                file_path="D:/repo/demo.txt",
                existed=True,
                previous_content="before",
            )
        ],
    )
    session.update_metadata()

    result = try_handle_local_command("/checkpoints", session=session)

    assert result is not None
    assert "Checkpoints for session session-" in result
    assert "[abc12345]" in result
    assert "demo.txt" in result


def test_sessions_command_lists_saved_workspace_sessions(tmp_path, monkeypatch) -> None:
    workspace = str(tmp_path.resolve())
    other_workspace = str((tmp_path / "other").resolve())
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
            ),
            SessionMetadata(
                session_id="bbb222222222",
                created_at=3.0,
                updated_at=4.0,
                first_message="beta",
                message_count=3,
                workspace=other_workspace,
            ),
        ],
        raising=False,
    )

    result = try_handle_local_command("/sessions", cwd=workspace)

    assert result is not None
    assert "Saved sessions:" in result
    assert "aaa11111" in result
    assert "bbb22222" not in result


def test_session_command_latest_uses_workspace_session(tmp_path, monkeypatch) -> None:
    workspace = str(tmp_path.resolve())
    session = SessionData(
        session_id="latest-12345",
        created_at=1.0,
        updated_at=2.0,
        workspace=workspace,
        transcript_entries=[{"kind": "assistant", "body": "restored"}],
    )
    monkeypatch.setattr(
        "minicode.cli_commands.get_latest_session",
        lambda workspace=None: session if workspace == str(tmp_path.resolve()) else None,
        raising=False,
    )

    result = try_handle_local_command("/session latest", cwd=workspace)

    assert result is not None
    assert "Session inspect: latest-1" in result
    assert "restored" in result


def test_session_replay_command_latest_uses_workspace_session(tmp_path, monkeypatch) -> None:
    workspace = str(tmp_path.resolve())
    session = SessionData(
        session_id="latest-12345",
        created_at=1.0,
        updated_at=2.0,
        workspace=workspace,
        history=["continue with runtime trace"],
        transcript_entries=[{"kind": "assistant", "body": "restored"}],
    )
    monkeypatch.setattr(
        "minicode.cli_commands.get_latest_session",
        lambda workspace=None: session if workspace == str(tmp_path.resolve()) else None,
        raising=False,
    )

    result = try_handle_local_command("/session-replay latest", cwd=workspace)

    assert result is not None
    assert "Session replay: latest-1" in result
    assert "Prompt history (1 shown):" in result
    assert "continue with runtime trace" in result


def test_checkpoints_command_latest_uses_workspace_session(tmp_path, monkeypatch) -> None:
    workspace = str(tmp_path.resolve())
    session = SessionData(
        session_id="latest-12345",
        created_at=1.0,
        updated_at=2.0,
        workspace=workspace,
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
    monkeypatch.setattr(
        "minicode.cli_commands.get_latest_session",
        lambda workspace=None: session if workspace == str(tmp_path.resolve()) else None,
        raising=False,
    )

    result = try_handle_local_command("/checkpoints latest", cwd=workspace)

    assert result is not None
    assert "Checkpoints for session latest-1" in result
    assert "[abc12345]" in result


def test_rewind_command_rewinds_active_session(monkeypatch) -> None:
    checkpoint = FileCheckpoint(
        checkpoint_id="abc123456789",
        created_at=3.0,
        file_path="D:/repo/demo.txt",
        existed=True,
        previous_content="before",
    )
    session = SessionData(
        session_id="session-1234",
        created_at=1.0,
        updated_at=2.0,
        workspace="D:/repo",
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

    result = try_handle_local_command("/rewind", session=session)

    assert result is not None
    assert "Rewound 1 checkpoint(s) for session session-" in result
    assert "Restored: [abc12345] demo.txt" in result
    assert "Resuming session session-" in result


def test_rewind_preview_command_shows_active_session_plan() -> None:
    checkpoint = FileCheckpoint(
        checkpoint_id="abc123456789",
        created_at=3.0,
        file_path="D:/repo/demo.txt",
        existed=True,
        previous_content="before",
    )
    session = SessionData(
        session_id="session-1234",
        created_at=1.0,
        updated_at=2.0,
        workspace="D:/repo",
        checkpoints=[checkpoint],
    )
    session.update_metadata()

    result = try_handle_local_command("/rewind-preview", session=session)

    assert result is not None
    assert "Rewind preview for session session-" in result
    assert "Would restore 1 checkpoint(s) across 1 file(s)." in result
    assert "Type: edit" in result


def test_session_rewind_command_rewinds_saved_workspace_session(tmp_path, monkeypatch) -> None:
    workspace = str(tmp_path.resolve())
    session = SessionData(
        session_id="latest-12345",
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

    result = try_handle_local_command("/session-rewind latest", cwd=workspace)

    assert result is not None
    assert "Rewound 1 checkpoint(s) for session latest-1" in result
    assert "Restored: [abc12345] demo.txt" in result
    assert "Resuming session latest-1" in result


def test_session_rewind_preview_command_uses_saved_workspace_session(tmp_path, monkeypatch) -> None:
    workspace = str(tmp_path.resolve())
    session = SessionData(
        session_id="latest-12345",
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

    result = try_handle_local_command("/session-rewind-preview latest", cwd=workspace)

    assert result is not None
    assert "Rewind preview for session latest-1" in result
    assert "Would restore 1 checkpoint(s) across 1 file(s)." in result
    assert "demo.txt" in result


def test_memory_command_uses_current_workspace(tmp_path) -> None:
    result = try_handle_local_command("/memory", cwd=str(tmp_path))

    assert result is not None
    assert "Memory System Status" in result


def test_cybernetics_command_shows_controller_inventory() -> None:
    result = try_handle_local_command("/cybernetics")

    assert result is not None
    assert "Cybernetic Control System" in result
    assert "CyberneticSupervisor" in result
    assert "ProgressController" in result


def test_cybernetics_command_uses_persisted_report(tmp_path, monkeypatch) -> None:
    import minicode.cybernetic_supervisor as supervisor_module
    from minicode.cybernetic_supervisor import ControlSnapshot, CyberneticSupervisor, save_supervisor_report

    monkeypatch.setattr(
        supervisor_module,
        "SUPERVISOR_STATE_PATH",
        tmp_path / "cybernetic_supervisor.json",
    )
    report = CyberneticSupervisor().report([
        ControlSnapshot(name="context", health=0.2, risk=0.9, action="compact")
    ])
    save_supervisor_report(report)

    result = try_handle_local_command("/cybernetics")

    assert result is not None
    assert "source: latest agent-loop report" in result
    assert "context: compact" in result
