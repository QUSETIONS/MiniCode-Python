from __future__ import annotations

import time

from minicode.types import AgentStep


def _last_user_message(messages):
    return next((message["content"] for message in reversed(messages) if message["role"] == "user"), "")


def _last_tool_message(messages):
    return next((message for message in reversed(messages) if message["role"] == "tool_result"), None)


def _latest_assistant_call(messages):
    call = next((message for message in reversed(messages) if message["role"] == "assistant_tool_call"), None)
    return call["toolName"] if call else None


class MockModelAdapter:
    def next(self, messages, on_stream_chunk=None):
        tool_message = _last_tool_message(messages)
        if tool_message and tool_message["role"] == "tool_result":
            last_call = _latest_assistant_call(messages)
            if last_call == "list_files":
                return AgentStep(type="assistant", content=f"Directory contents:\n\n{tool_message['content']}")
            if last_call == "read_file":
                return AgentStep(type="assistant", content=f"File contents:\n\n{tool_message['content']}")
            if last_call in {"write_file", "edit_file", "modify_file", "patch_file"}:
                return AgentStep(type="assistant", content=tool_message["content"])
            return AgentStep(type="assistant", content=f"I received the tool result:\n\n{tool_message['content']}")

        user_text = _last_user_message(messages).strip()
        tool_id = f"mock-{int(time.time() * 1000)}"

        if user_text == "/tools":
            return AgentStep(
                type="assistant",
                content="Available tools: ask_user, list_files, grep_files, read_file, write_file, edit_file, patch_file, run_command",
            )

        if user_text.startswith("/ls"):
            directory = user_text.replace("/ls", "", 1).strip()
            return AgentStep(
                type="tool_calls",
                calls=[{"id": tool_id, "toolName": "list_files", "input": {"path": directory} if directory else {}}],
            )

        if user_text.startswith("/grep "):
            payload = user_text[len("/grep ") :].strip()
            pattern, _, search_path = payload.partition("::")
            return AgentStep(
                type="tool_calls",
                calls=[
                    {
                        "id": tool_id,
                        "toolName": "grep_files",
                        "input": {"pattern": pattern.strip(), "path": search_path.strip() or None},
                    }
                ],
            )

        if user_text.startswith("/read "):
            return AgentStep(
                type="tool_calls",
                calls=[{"id": tool_id, "toolName": "read_file", "input": {"path": user_text[len('/read ') :].strip()}}],
            )

        if user_text.startswith("/cmd "):
            payload = user_text[len("/cmd ") :].strip()
            return AgentStep(type="tool_calls", calls=[{"id": tool_id, "toolName": "run_command", "input": {"command": payload}}])

        if user_text.startswith("/write "):
            payload = user_text[len("/write ") :]
            target_path, separator, content = payload.partition("::")
            if not separator:
                return AgentStep(type="assistant", content="Usage: /write <path>::<content>")
            return AgentStep(
                type="tool_calls",
                calls=[{"id": tool_id, "toolName": "write_file", "input": {"path": target_path.strip(), "content": content}}],
            )

        if user_text.startswith("/edit "):
            payload = user_text[len("/edit ") :]
            parts = payload.split("::")
            if len(parts) != 3:
                return AgentStep(type="assistant", content="Usage: /edit <path>::<search>::<replace>")
            target_path, search, replace = parts
            return AgentStep(
                type="tool_calls",
                calls=[{"id": tool_id, "toolName": "edit_file", "input": {"path": target_path.strip(), "search": search, "replace": replace}}],
            )

        if user_text.startswith("/patch "):
            payload = user_text[len("/patch ") :]
            parts = payload.split("::")
            if len(parts) < 3 or len(parts) % 2 == 0:
                return AgentStep(type="assistant", content="Usage: /patch <path>::<search1>::<replace1>::<search2>::<replace2> ...")
            target_path, *ops = parts
            replacements = []
            for index in range(0, len(ops), 2):
                replacements.append({"search": ops[index], "replace": ops[index + 1]})
            return AgentStep(
                type="tool_calls",
                calls=[{"id": tool_id, "toolName": "patch_file", "input": {"path": target_path.strip(), "replacements": replacements}}],
            )

        return AgentStep(
            type="assistant",
            content="\n".join(
                [
                    "This is a minimal MiniCode Python shell.",
                    "You can try:",
                    "/tools",
                    "/ls",
                    "/grep pattern::src",
                    "/read README.md",
                    "/cmd pwd",
                    "/write notes.txt::hello",
                    "/edit notes.txt::hello::hello world",
                ]
            ),
        )
