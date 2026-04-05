from __future__ import annotations

from pathlib import Path


def _maybe_read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def build_system_prompt(
    cwd: str,
    permission_summary: list[str] | None = None,
    extras: dict | None = None,
) -> str:
    cwd_path = Path(cwd)
    permission_summary = permission_summary or []
    extras = extras or {}
    global_claude_md = _maybe_read(Path.home() / ".claude" / "CLAUDE.md")
    project_claude_md = _maybe_read(cwd_path / "CLAUDE.md")

    parts = [
        "You are mini-code, a terminal coding assistant.",
        "Default behavior: inspect the repository, use tools, make code changes when appropriate, and explain results clearly.",
        "Prefer reading files, searching code, editing files, and running verification commands over giving purely theoretical advice.",
        f"Current cwd: {cwd}",
        "You can inspect or modify paths outside the current cwd when the user asks, but tool permissions may pause for approval first.",
        "When making code changes, keep them minimal, practical, and working-oriented.",
        "If the user clearly asked you to build, modify, optimize, or generate something, do the work instead of stopping at a plan.",
        "If you need user clarification, call the ask_user tool with one concise question and wait for the user reply. Do not ask clarifying questions as plain assistant text.",
        "Do not choose subjective preferences such as colors, visual style, copy tone, or naming unless the user explicitly told you to decide yourself.",
        "When using read_file, pay attention to the header fields. If it says TRUNCATED: yes, continue reading with a larger offset before concluding that the file itself is cut off.",
        "If the user names a skill or clearly asks for a workflow that matches a listed skill, call load_skill before following it.",
        "Structured response protocol:",
        "- When you are still working and will continue with more tool calls, start your text with <progress>.",
        "- Only when the task is actually complete and you are ready to hand control back, start your text with <final>.",
        "- Use ask_user when clarification is required; that tool ends the turn and waits for user input.",
        "- Do not stop after a progress update. After a <progress> message, continue the task in the next step.",
        "- Plain assistant text without <progress> is treated as a completed assistant message for this turn.",
    ]

    if permission_summary:
        parts.append("Permission context:\n" + "\n".join(permission_summary))

    skills = extras.get("skills", [])
    if skills:
        parts.append(
            "Available skills:\n"
            + "\n".join(f"- {skill['name']}: {skill['description']}" for skill in skills)
        )
    else:
        parts.append("Available skills:\n- none discovered")

    mcp_servers = extras.get("mcpServers", [])
    if mcp_servers:
        parts.append(
            "Configured MCP servers:\n"
            + "\n".join(
                "- "
                + server["name"]
                + f": {server['status']}, tools={server['toolCount']}"
                + (f", resources={server['resourceCount']}" if server.get("resourceCount") is not None else "")
                + (f", prompts={server['promptCount']}" if server.get("promptCount") is not None else "")
                + (f", protocol={server['protocol']}" if server.get("protocol") else "")
                + (f" ({server['error']})" if server.get("error") else "")
                for server in mcp_servers
            )
        )
        if any(server.get("status") == "connected" for server in mcp_servers):
            parts.append(
                "Connected MCP tools are already exposed in the tool list with names prefixed like mcp__server__tool. Use list_mcp_resources/read_mcp_resource and list_mcp_prompts/get_mcp_prompt when a server exposes those capabilities."
            )
        sequential_servers = [
            server
            for server in mcp_servers
            if "sequential" in server.get("name", "").lower()
            or "branch-thinking" in server.get("name", "").lower()
            or "think" in server.get("name", "").lower()
        ]
        if any(server.get("status") == "connected" for server in sequential_servers):
            parts.append(
                "A sequential-thinking style MCP server is connected. For complex implementation, debugging, migration, or architectural decisions, prefer using that reasoning MCP tool before or during tool-heavy work."
            )

    if global_claude_md:
        parts.append(f"Global instructions from ~/.claude/CLAUDE.md:\n{global_claude_md}")
    if project_claude_md:
        parts.append(f"Project instructions from {cwd_path / 'CLAUDE.md'}:\n{project_claude_md}")

    return "\n\n".join(parts)
