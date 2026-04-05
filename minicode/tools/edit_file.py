from __future__ import annotations

from minicode.file_review import apply_reviewed_file_change, load_existing_file
from minicode.tooling import ToolDefinition
from minicode.workspace import resolve_tool_path


def _validate(input_data: dict) -> dict:
    path = input_data.get("path")
    search = input_data.get("search", input_data.get("old"))
    replace = input_data.get("replace", input_data.get("new"))
    replace_all = bool(input_data.get("replaceAll", input_data.get("replace_all", False)))
    if not isinstance(path, str) or not path:
        raise ValueError("path is required")
    if not isinstance(search, str) or not isinstance(replace, str):
        raise ValueError("search and replace must be strings")
    if not search:
        raise ValueError("search must be non-empty")
    return {"path": path, "search": search, "replace": replace, "replace_all": replace_all}


def _run(input_data: dict, context):
    target = resolve_tool_path(context, input_data["path"], "write")
    content = load_existing_file(target)
    if input_data["search"] not in content:
        raise ValueError(f"Text not found in {input_data['path']}")
    if input_data["replace_all"]:
        next_content = input_data["replace"].join(content.split(input_data["search"]))
    else:
        next_content = content.replace(input_data["search"], input_data["replace"], 1)
    return apply_reviewed_file_change(context, input_data["path"], target, next_content)


edit_file_tool = ToolDefinition(
    name="edit_file",
    description="Replace a substring in a file after the user reviews the diff.",
    input_schema={"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}, "replace_all": {"type": "boolean"}}, "required": ["path", "old", "new"]},
    validator=_validate,
    run=_run,
)
