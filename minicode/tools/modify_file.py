from minicode.tools.write_file import _run, _validate
from minicode.tooling import ToolDefinition


modify_file_tool = ToolDefinition(
    name="modify_file",
    description="Replace a file with reviewed content so the user can approve the diff first.",
    input_schema={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    validator=_validate,
    run=_run,
)

