from __future__ import annotations

from minicode.skills import load_skill
from minicode.tooling import ToolDefinition, ToolResult


def _validate(input_data: dict) -> dict:
    name = input_data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required")
    return {"name": name.strip()}


def create_load_skill_tool(cwd: str) -> ToolDefinition:
    def _run(input_data: dict, _context) -> ToolResult:
        skill = load_skill(cwd, input_data["name"])
        if skill is None:
            return ToolResult(ok=False, output=f"Unknown skill: {input_data['name']}")
        return ToolResult(
            ok=True,
            output="\n".join(
                [
                    f"SKILL: {skill.name}",
                    f"SOURCE: {skill.source}",
                    f"PATH: {skill.path}",
                    "",
                    skill.content,
                ]
            ),
        )

    return ToolDefinition(
        name="load_skill",
        description="Load a local SKILL.md by name.",
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        validator=_validate,
        run=_run,
    )
