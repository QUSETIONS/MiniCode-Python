from pathlib import Path

import pytest

import minicode.mcp as mcp_module
from minicode.mcp import StdioMcpClient, create_mcp_backed_tools
from minicode.tooling import ToolContext


def _fake_server_script() -> Path:
    return Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def _client(tmp_path: Path, *, mode: str = "normal") -> StdioMcpClient:
    return StdioMcpClient(
        "fake",
        {
            "command": "python",
            "args": [str(_fake_server_script())],
            "protocol": "newline-json",
            "env": {"FAKE_MCP_MODE": mode},
        },
        str(tmp_path),
    )


def test_create_mcp_backed_tools_supports_newline_json(tmp_path: Path) -> None:
    mcp = create_mcp_backed_tools(
        cwd=str(tmp_path),
        mcp_servers={
            "fake": {
                "command": "python",
                "args": [str(_fake_server_script())],
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


def test_pending_request_fails_when_server_exits(tmp_path: Path) -> None:
    client = _client(tmp_path, mode="exit_on_call")
    client.start()

    with pytest.raises(RuntimeError, match="process exited"):
        client.request("tools/call", {"name": "echo", "arguments": {"text": "hi"}}, timeout_seconds=1.0)

    assert client._pending == {}
    client.close()


def test_timed_out_request_is_removed_from_pending(tmp_path: Path) -> None:
    client = _client(tmp_path, mode="hang_on_call")
    client.start()

    with pytest.raises(RuntimeError, match="request timed out"):
        client.request("tools/call", {"name": "echo", "arguments": {"text": "hi"}}, timeout_seconds=0.1)

    assert client._pending == {}
    client.close()


def test_oversized_payload_is_rejected_without_leaking_pending_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, mode="oversized_payload")
    client.start()
    monkeypatch.setattr(mcp_module, "MAX_MCP_PAYLOAD_BYTES", 64)

    with pytest.raises(RuntimeError, match="request timed out"):
        client.request("tools/call", {"name": "echo", "arguments": {"text": "hi"}}, timeout_seconds=0.1)

    assert client._pending == {}
    assert any("payload too large" in line for line in client.stderr_lines)
    client.close()


def test_client_reconnects_after_process_exit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.start()
    original_pid = client.process.pid if client.process is not None else None
    assert original_pid is not None

    client.process.kill()
    client.process.wait(timeout=5)

    result = client.call_tool("echo", {"text": "again"})

    assert result.ok is True
    assert result.output == "echo:again"
    assert client.process is not None
    assert client.process.pid != original_pid
    client.close()
