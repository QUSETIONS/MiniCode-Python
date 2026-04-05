from pathlib import Path

from minicode.mcp import create_mcp_backed_tools
from minicode.tooling import ToolContext


def test_create_mcp_backed_tools_supports_newline_json(tmp_path: Path) -> None:
    server_script = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"
    mcp = create_mcp_backed_tools(
        cwd=str(tmp_path),
        mcp_servers={
            "fake": {
                "command": "python",
                "args": [str(server_script)],
                "protocol": "newline-json",
            }
        },
    )

    names = [tool.name for tool in mcp["tools"]]
    assert "mcp__fake__echo" in names
    assert "list_mcp_resources" in names
    assert "list_mcp_prompts" in names

    echo_tool = next(tool for tool in mcp["tools"] if tool.name == "mcp__fake__echo")
    result = echo_tool.run({"text": "hi"}, ToolContext(cwd=str(tmp_path)))
    assert result.ok is True
    assert result.output == "echo:hi"

    resource_tool = next(tool for tool in mcp["tools"] if tool.name == "read_mcp_resource")
    resource_result = resource_tool.run({"server": "fake", "uri": "fake://hello"}, ToolContext(cwd=str(tmp_path)))
    assert "hello resource" in resource_result.output

    prompt_tool = next(tool for tool in mcp["tools"] if tool.name == "get_mcp_prompt")
    prompt_result = prompt_tool.run({"server": "fake", "name": "hello", "arguments": {"name": "cc"}}, ToolContext(cwd=str(tmp_path)))
    assert "hello cc" in prompt_result.output

    mcp["dispose"]()
