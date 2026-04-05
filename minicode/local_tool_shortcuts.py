from __future__ import annotations


def parse_local_tool_shortcut(user_input: str) -> dict | None:
    if user_input.startswith("/ls"):
        directory = user_input.replace("/ls", "", 1).strip()
        return {"toolName": "list_files", "input": {"path": directory} if directory else {}}

    if user_input.startswith("/grep "):
        payload = user_input[len("/grep ") :].strip()
        pattern, _, search_path = payload.partition("::")
        if not pattern.strip():
            return None
        input_data = {"pattern": pattern.strip()}
        if search_path.strip():
            input_data["path"] = search_path.strip()
        return {"toolName": "grep_files", "input": input_data}

    if user_input.startswith("/read "):
        file_path = user_input[len("/read ") :].strip()
        return {"toolName": "read_file", "input": {"path": file_path}} if file_path else None

    if user_input.startswith("/write "):
        payload = user_input[len("/write ") :]
        target_path, separator, content = payload.partition("::")
        if not separator:
            return None
        return {
            "toolName": "write_file",
            "input": {"path": target_path.strip(), "content": content},
        }

    if user_input.startswith("/modify "):
        payload = user_input[len("/modify ") :]
        target_path, separator, content = payload.partition("::")
        if not separator:
            return None
        return {
            "toolName": "modify_file",
            "input": {"path": target_path.strip(), "content": content},
        }

    if user_input.startswith("/edit "):
        payload = user_input[len("/edit ") :]
        parts = payload.split("::")
        if len(parts) != 3:
            return None
        target_path, search, replace = parts
        return {
            "toolName": "edit_file",
            "input": {"path": target_path.strip(), "search": search, "replace": replace},
        }

    if user_input.startswith("/patch "):
        payload = user_input[len("/patch ") :]
        parts = payload.split("::")
        if len(parts) < 3 or len(parts) % 2 == 0:
            return None
        target_path, *ops = parts
        replacements = []
        for index in range(0, len(ops), 2):
            replacements.append({"search": ops[index], "replace": ops[index + 1]})
        return {
            "toolName": "patch_file",
            "input": {"path": target_path.strip(), "replacements": replacements},
        }

    if user_input.startswith("/cmd "):
        payload = user_input[len("/cmd ") :].strip()
        cwd, separator, command_text = payload.partition("::")
        text = command_text.strip() if separator else payload
        command_cwd = cwd.strip() if separator else None
        if not text:
            return None
        return {
            "toolName": "run_command",
            "input": {"command": text, "cwd": command_cwd or None},
        }

    return None
