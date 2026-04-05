from __future__ import annotations

from minicode.file_review import apply_reviewed_file_change, load_existing_file
from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path


def _validate(input_data: dict) -> dict:
    path = input_data.get("path")
    replacements = input_data.get("replacements")
    patch = input_data.get("patch")
    if not isinstance(path, str) or not path:
        raise ValueError("path is required")
    if replacements is None:
        if not isinstance(patch, str) or not patch:
            raise ValueError("patch must be a string")
        replacements = [{"search": patch, "replace": ""}]
    if not isinstance(replacements, list) or not replacements:
        raise ValueError("replacements must be a non-empty list")
    normalized = []
    for replacement in replacements:
        if not isinstance(replacement, dict):
            raise ValueError("replacement entries must be objects")
        search = replacement.get("search")
        replace = replacement.get("replace")
        replace_all = bool(replacement.get("replaceAll", replacement.get("replace_all", False)))
        if not isinstance(search, str) or not search:
            raise ValueError("replacement search must be a non-empty string")
        if not isinstance(replace, str):
            raise ValueError("replacement replace must be a string")
        # Normalize \r\n → \n so search/replace strings always match
        # file content (read_text uses universal newlines).
        search = search.replace("\r\n", "\n")
        replace = replace.replace("\r\n", "\n")
        normalized.append({"search": search, "replace": replace, "replace_all": replace_all})
    return {"path": path, "replacements": normalized}


def _run(input_data: dict, context):
    target = resolve_tool_path(context, input_data["path"], "write")
    content = load_existing_file(target)
    applied: list[str] = []
    for index, replacement in enumerate(input_data["replacements"], start=1):
        if replacement["search"] not in content:
            return ToolResult(ok=False, output=f"Replacement {index} not found in {input_data['path']}")
        replace_all = bool(replacement.get("replace_all", replacement.get("replaceAll", False)))
        if replace_all:
            content = replacement["replace"].join(content.split(replacement["search"]))
            applied.append(f"#{index} replaceAll")
        else:
            content = content.replace(replacement["search"], replacement["replace"], 1)
            applied.append(f"#{index} replaceOnce")
    result = apply_reviewed_file_change(context, input_data["path"], target, content)
    if not result.ok:
        return result
    return ToolResult(
        ok=True,
        output=f"Patched {input_data['path']} with {len(applied)} replacement(s): {', '.join(applied)}",
    )


patch_file_tool = ToolDefinition(
    name="patch_file",
    description="Apply multiple exact-text replacements to one file in a single operation.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "replacements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "search": {"type": "string"},
                        "replace": {"type": "string"},
                        "replaceAll": {"type": "boolean"},
                    },
                    "required": ["search", "replace"],
                },
            },
        },
        "required": ["path", "replacements"],
    },
    validator=_validate,
    run=_run,
)
