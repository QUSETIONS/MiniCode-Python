from __future__ import annotations

import json
from minicode.tooling import ToolDefinition, ToolResult
from minicode.workspace import resolve_tool_path


def _validate(input_data: dict) -> dict:
    path = input_data.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("path is required")
    cells = input_data.get("cells")
    if not isinstance(cells, list):
        raise ValueError("cells must be a list")
    for i, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise ValueError(f"cells[{i}] must be an object")
        if "source" not in cell:
            raise ValueError(f"cells[{i}] must have a 'source' field")
        cell_type = cell.get("cell_type", "code")
        if cell_type not in ("code", "markdown"):
            raise ValueError(f"cells[{i}] cell_type must be 'code' or 'markdown'")
    return {"path": path, "cells": cells}


def _run(input_data: dict, context) -> ToolResult:
    target = resolve_tool_path(context, input_data["path"], "write")

    new_cells = input_data["cells"]

    # Load existing notebook if exists
    existing_cells = []
    if target.exists():
        try:
            existing_nb = json.loads(target.read_text(encoding="utf-8"))
            existing_cells = existing_nb.get("cells", [])
        except (json.JSONDecodeError, KeyError):
            pass

    # Build output notebook
    notebook = {
        "cells": [],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.11.0",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    # Apply new cells or update existing
    cell_ids_seen = set()
    for new_cell in new_cells:
        cell_id = new_cell.get("id")
        cell_type = new_cell.get("cell_type", "code")
        source = new_cell["source"]
        if isinstance(source, list):
            source = "\n".join(source)

        # Try to find existing cell by id or content
        found = False
        for i, existing_cell in enumerate(existing_cells):
            existing_id = existing_cell.get("id")
            existing_source = "".join(existing_cell.get("source", [])) if isinstance(existing_cell.get("source"), list) else existing_cell.get("source", "")

            if (cell_id and existing_id and cell_id == existing_id) or \
               (not cell_id and existing_source == source):
                # Update existing cell
                updated_cell = dict(existing_cell)
                updated_cell["cell_type"] = cell_type
                updated_cell["source"] = source if "\n" not in source else source.split("\n")
                updated_cell.setdefault("outputs", [])
                updated_cell.setdefault("execution_count", None)
                if cell_id:
                    updated_cell["id"] = cell_id
                notebook["cells"].append(updated_cell)
                if cell_id:
                    cell_ids_seen.add(cell_id)
                found = True
                break

        if not found:
            # Add new cell
            import uuid
            new_cell_id = cell_id or str(uuid.uuid4())[:8]
            notebook["cells"].append({
                "id": new_cell_id,
                "cell_type": cell_type,
                "source": source if "\n" not in source else source.split("\n"),
                "metadata": {},
                "outputs": [],
                "execution_count": None,
            })

    # Add remaining existing cells that weren't updated
    for existing_cell in existing_cells:
        existing_id = existing_cell.get("id")
        if existing_id and existing_id not in cell_ids_seen:
            notebook["cells"].append(existing_cell)
        elif not existing_id:
            # Check if content matches any new cell
            existing_source = "".join(existing_cell.get("source", [])) if isinstance(existing_cell.get("source"), list) else existing_cell.get("source", "")
            if not any(nc["source"] == existing_source for nc in new_cells):
                notebook["cells"].append(existing_cell)

    # Write notebook
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Format output
    code_cells = sum(1 for c in notebook["cells"] if c["cell_type"] == "code")
    markdown_cells = sum(1 for c in notebook["cells"] if c["cell_type"] == "markdown")

    lines = [
        f"Notebook updated: {input_data['path']}",
        f"Total cells: {len(notebook['cells'])}",
        f"  Code cells: {code_cells}",
        f"  Markdown cells: {markdown_cells}",
        "",
        "Cells:",
    ]

    for i, cell in enumerate(notebook["cells"], 1):
        source = cell["source"]
        if isinstance(source, list):
            source = "\n".join(source)
        preview = source[:60].replace("\n", " ")
        icon = "💻" if cell["cell_type"] == "code" else "📝"
        lines.append(f"  {icon} [{i}] {cell['cell_type']}: {preview}...")

    return ToolResult(ok=True, output="\n".join(lines))


notebook_edit_tool = ToolDefinition(
    name="notebook_edit",
    description="Edit a Jupyter Notebook (.ipynb). Pass the complete list of cells to update. Each cell needs 'source' (string) and optionally 'cell_type' (code/markdown, default: code) and 'id' to match existing cells. Cells not matched will be added; existing cells not matched will be preserved.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the .ipynb file"},
            "cells": {
                "type": "array",
                "description": "Complete list of cells. Each cell: {source, cell_type?, id?}",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Cell ID (to match existing)"},
                        "cell_type": {"type": "string", "enum": ["code", "markdown"], "description": "Cell type (default: code)"},
                        "source": {"type": "string", "description": "Cell content"},
                    },
                    "required": ["source"],
                },
            },
        },
        "required": ["path", "cells"],
    },
    validator=_validate,
    run=_run,
)
