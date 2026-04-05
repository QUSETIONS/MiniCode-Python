from __future__ import annotations

from minicode.tooling import ToolDefinition, ToolResult


def _validate(input_data: dict) -> dict:
    question = input_data.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question is required")
    return {"question": question.strip()}


def _run(input_data: dict, _context) -> ToolResult:
    return ToolResult(ok=True, output=input_data["question"], awaitUser=True)


ask_user_tool = ToolDefinition(
    name="ask_user",
    description="Pause the turn and ask the user a clarifying question.",
    input_schema={"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
    validator=_validate,
    run=_run,
)

