from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlashCommand:
    name: str
    usage: str
    description: str


SLASH_COMMANDS = [
    SlashCommand("/help", "/help", "Show available slash commands."),
    SlashCommand("/tools", "/tools", "List tools available to the coding agent and tool shortcuts."),
    SlashCommand("/state", "/state", "Show detailed application state and Store summary."),
    SlashCommand("/status", "/status", "Show application state summary and current model."),
    SlashCommand("/cost", "/cost [--detailed]", "Show API cost and usage report."),
    SlashCommand("/context", "/context", "Show context window usage."),
    SlashCommand("/cybernetics", "/cybernetics", "Show cybernetic control system status."),
    SlashCommand("/tasks", "/tasks", "Show current task list."),
    SlashCommand("/memory", "/memory", "Show memory system status."),
    SlashCommand("/config", "/config", "Show configuration diagnostics and validation."),
    SlashCommand("/history", "/history", "Show recent prompt history from ~/.mini-code/history.json."),
    SlashCommand("/clear", "/clear", "Clear the current transcript view."),
    SlashCommand("/collapse", "/collapse", "Collapse all expanded tool-output blocks in the transcript."),
    SlashCommand("/retry", "/retry", "Retry the last natural-language prompt in this session."),
    SlashCommand("/session", "/session", "Inspect the active session, runtime, checkpoints, and recent transcript."),
    SlashCommand("/session", "/session <session-id|latest>", "Inspect a saved session for the current workspace."),
    SlashCommand("/session-replay", "/session-replay", "Replay the active session with checkpoint, history, and transcript timeline."),
    SlashCommand("/session-replay", "/session-replay <session-id|latest>", "Replay a saved session for the current workspace."),
    SlashCommand("/sessions", "/sessions", "List saved sessions for the current workspace."),
    SlashCommand("/instructions", "/instructions", "Inspect the active instruction layering surface."),
    SlashCommand("/hooks", "/hooks", "Inspect active hooks and recent hook telemetry."),
    SlashCommand("/delegation", "/delegation", "Inspect background delegation capacity and running tasks."),
    SlashCommand("/extensions", "/extensions", "Inspect local extension manifests for this workspace."),
    SlashCommand("/extension-inspect", "/extension-inspect <name>", "Inspect a local extension manifest and source path."),
    SlashCommand("/extension-enable", "/extension-enable <name>", "Enable a local extension manifest."),
    SlashCommand("/extension-disable", "/extension-disable <name>", "Disable a local extension manifest."),
    SlashCommand("/readiness", "/readiness", "Inspect provider/runtime readiness for the current workspace."),
    SlashCommand("/checkpoints", "/checkpoints", "List checkpoints for the active session."),
    SlashCommand("/checkpoints", "/checkpoints <session-id|latest>", "List checkpoints for a saved session in the current workspace."),
    SlashCommand("/rewind-preview", "/rewind-preview [latest|steps|checkpoint-id]", "Preview checkpointed file edits that would be rewound for the active session."),
    SlashCommand("/rewind", "/rewind [latest|steps|checkpoint-id]", "Rewind checkpointed file edits for the active session."),
    SlashCommand("/session-rewind-preview", "/session-rewind-preview <session-id|latest> [latest|steps|checkpoint-id]", "Preview checkpointed file edits that would be rewound for a saved session."),
    SlashCommand("/session-rewind", "/session-rewind <session-id|latest> [latest|steps|checkpoint-id]", "Rewind checkpointed file edits for a saved session in the current workspace."),
    SlashCommand("/transcript-save", "/transcript-save <path>", "Save the current session transcript to a text file."),
    SlashCommand("/model", "/model", "Show the current model."),
    SlashCommand("/model", "/model <model-name>", "Persist a model override into ~/.mini-code/settings.json."),
    SlashCommand("/config-paths", "/config-paths", "Show mini-code and Claude fallback settings paths."),
    SlashCommand("/skills", "/skills", "List discovered SKILL.md workflows."),
    SlashCommand("/mcp", "/mcp", "Show configured MCP servers and connection state."),
    SlashCommand("/permissions", "/permissions", "Show mini-code permission storage path."),
    SlashCommand("/exit", "/exit", "Exit mini-code."),
    SlashCommand("/debug", "/debug", "Show scroll and terminal diagnostics."),
    SlashCommand("/user", "/user", "Show or manage user profile (preferences, coding style)."),
    SlashCommand("/ls", "/ls [path]", "List files in a directory."),
    SlashCommand("/grep", "/grep <pattern>::[path]", "Search text in files."),
    SlashCommand("/read", "/read <path>", "Read a file directly."),
    SlashCommand("/write", "/write <path>::<content>", "Write a file directly."),
    SlashCommand("/modify", "/modify <path>::<content>", "Replace a file, showing a reviewable diff before applying it."),
    SlashCommand("/edit", "/edit <path>::<search>::<replace>", "Edit a file by exact replacement."),
    SlashCommand("/patch", "/patch <path>::<search1>::<replace1>::<search2>::<replace2>...", "Apply multiple replacements to one file in one command."),
    SlashCommand("/cmd", "/cmd [cwd::]<command> [args...]", "Run an allowed development command directly."),
]


def slash_command_usages() -> tuple[str, ...]:
    return tuple(command.usage for command in SLASH_COMMANDS)
