from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from minicode.tooling import ToolDefinition, ToolResult

# 安全常量：禁止在命令参数中出现的危险字符
DANGEROUS_SHELL_CHARS = set('|&;`$(){}<>\n\r')

# 允许的命令白名单（常见的 MCP 服务器命令）
ALLOWED_COMMANDS = {
    'node', 'npm', 'npx', 'python', 'python3', 'pip', 'pip3',
    'uv', 'deno', 'bun', 'cargo', 'go', 'java', 'javac',
    'ruby', 'gem', 'dotnet', 'curl', 'wget',
}


JsonRpcProtocol = str


@dataclass(slots=True)
class McpServerSummary:
    name: str
    command: str
    status: str
    toolCount: int
    error: str | None = None
    protocol: str | None = None
    resourceCount: int | None = None
    promptCount: int | None = None


def _sanitize_tool_segment(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() or char in {"_", "-"} else "_" for char in value)
    normalized = normalized.strip("_")
    return normalized or "tool"


def _validate_mcp_command(command: str) -> None:
    """验证 MCP 命令的合法性"""
    from pathlib import Path
    
    normalized = Path(command).resolve().as_posix()
    
    # 不允许路径遍历字符
    if '..' in normalized or '~' in normalized:
        raise RuntimeError(f"Invalid MCP command: contains path traversal characters")
    
    # 提取命令的基本名称
    base_command = Path(command).name.lower()
    # 处理 .exe 后缀
    if base_command.endswith('.exe'):
        base_command = base_command[:-4]
    
    # 如果是绝对路径，需要额外验证
    if Path(command).is_absolute():
        # 检查是否在常见的系统目录中
        allowed_system_dirs = ['/usr/bin', '/usr/local/bin', '/usr/sbin', '/opt']
        if os.name == 'nt':
            allowed_system_dirs.extend([
                'C:\\Program Files',
                'C:\\Program Files (x86)',
                'C:\\Windows\\System32',
            ])
        
        is_in_allowed_dir = any(normalized.lower().startswith(d.lower()) for d in allowed_system_dirs)
        
        # 不在允许的系统目录且不在白名单中
        if not is_in_allowed_dir and base_command not in ALLOWED_COMMANDS:
            raise RuntimeError(
                f"MCP command \"{command}\" is not in the allowed list. "
                f"Use a whitelisted command or place the executable in a standard system directory."
            )
        
        # 禁止危险的系统 shell
        dangerous_shells = ['cmd.exe', 'command.com', 'powershell.exe', 'pwsh.exe']
        if any(normalized.lower().endswith(d) for d in dangerous_shells):
            raise RuntimeError(
                f"MCP command \"{command}\" is a dangerous system shell. "
                f"Direct execution of shells is not allowed for security reasons."
            )
        return
    
    # 相对路径必须在白名单中
    if base_command not in ALLOWED_COMMANDS:
        raise RuntimeError(
            f"MCP command \"{command}\" is not in the allowed list. "
            f"Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}. "
            f"Use absolute paths for custom commands."
        )


def _validate_mcp_args(args: list[str]) -> None:
    """验证 MCP 参数不包含危险的 shell 元字符"""
    for arg in args:
        for char in arg:
            if char in DANGEROUS_SHELL_CHARS:
                raise RuntimeError(
                    f"Invalid MCP argument: contains dangerous shell character '{char}'. "
                    f"MCP server arguments cannot contain shell metacharacters for security reasons."
                )


def _normalize_input_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    return schema if isinstance(schema, dict) else {"type": "object", "additionalProperties": True}


def _format_content_block(block: Any) -> str:
    if not isinstance(block, dict):
        return json.dumps(block, indent=2, ensure_ascii=False)
    if block.get("type") == "text" and "text" in block:
        return str(block["text"])
    return json.dumps(block, indent=2, ensure_ascii=False)


def _format_tool_call_result(result: Any) -> ToolResult:
    if not isinstance(result, dict):
        return ToolResult(ok=True, output=json.dumps(result, indent=2, ensure_ascii=False))
    parts: list[str] = []
    content = result.get("content")
    if isinstance(content, list) and content:
        parts.append("\n\n".join(_format_content_block(block) for block in content))
    if "structuredContent" in result:
        parts.append("STRUCTURED_CONTENT:\n" + json.dumps(result["structuredContent"], indent=2, ensure_ascii=False))
    if not parts:
        parts.append(json.dumps(result, indent=2, ensure_ascii=False))
    return ToolResult(ok=not bool(result.get("isError")), output="\n\n".join(parts).strip())


def _format_read_resource_result(result: Any) -> ToolResult:
    if not isinstance(result, dict):
        return ToolResult(ok=False, output=json.dumps(result, indent=2, ensure_ascii=False))
    contents = result.get("contents", [])
    if not contents:
        return ToolResult(ok=True, output="No resource contents returned.")
    rendered = []
    for item in contents:
        header_lines = [f"URI: {item.get('uri', '(unknown)')}"]
        if item.get("mimeType"):
            header_lines.append(f"MIME: {item['mimeType']}")
        header = "\n".join(header_lines) + "\n\n"
        if isinstance(item.get("text"), str):
            rendered.append(header + item["text"])
        elif isinstance(item.get("blob"), str):
            rendered.append(header + "BLOB:\n" + item["blob"])
        else:
            rendered.append(header + json.dumps(item, indent=2, ensure_ascii=False))
    return ToolResult(ok=True, output="\n\n".join(rendered))


def _format_prompt_result(result: Any) -> ToolResult:
    if not isinstance(result, dict):
        return ToolResult(ok=False, output=json.dumps(result, indent=2, ensure_ascii=False))
    header = f"DESCRIPTION: {result['description']}\n\n" if result.get("description") else ""
    body_parts = []
    for message in result.get("messages", []):
        role = message.get("role", "unknown")
        content = message.get("content")
        if isinstance(content, str):
            rendered = content
        elif isinstance(content, list):
            rendered = "\n".join(
                str(part["text"]) if isinstance(part, dict) and "text" in part else json.dumps(part, indent=2, ensure_ascii=False)
                for part in content
            )
        else:
            rendered = json.dumps(content, indent=2, ensure_ascii=False)
        body_parts.append(f"[{role}]\n{rendered}")
    output = (header + "\n\n".join(body_parts)).strip()
    return ToolResult(ok=True, output=output or json.dumps(result, indent=2, ensure_ascii=False))


class StdioMcpClient:
    def __init__(self, server_name: str, config: dict[str, Any], cwd: str) -> None:
        self.server_name = server_name
        self.config = config
        self.cwd = cwd
        self.process: subprocess.Popen[str] | None = None
        self.protocol: JsonRpcProtocol | None = None
        self.next_id = 1
        self.pending: dict[int, Queue[Any]] = {}
        self.stderr_lines: list[str] = []
        self._stderr_thread: threading.Thread | None = None
        self._stdout_thread: threading.Thread | None = None

    def _protocol_candidates(self) -> list[JsonRpcProtocol]:
        configured = self.config.get("protocol")
        if configured == "content-length":
            return ["content-length"]
        if configured == "newline-json":
            return ["newline-json"]
        return ["content-length", "newline-json"]

    def start(self) -> None:
        if self.process is not None:
            return
        last_error: Exception | None = None
        for protocol in self._protocol_candidates():
            try:
                self._spawn_process()
                self.protocol = protocol
                self.request(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "mini-code", "version": "0.1.0"},
                    },
                    timeout_seconds=2.0,
                )
                self.notify("notifications/initialized", {})
                return
            except Exception as error:  # noqa: BLE001
                last_error = error
                self.close()
        raise RuntimeError(str(last_error or f'Failed to connect MCP server "{self.server_name}".'))

    def _spawn_process(self) -> None:
        command = str(self.config.get("command", "")).strip()
        if not command:
            raise RuntimeError(f'MCP server "{self.server_name}" has no command configured.')

        # 安全验证：检查命令和参数的合法性
        _validate_mcp_command(command)
        _validate_mcp_args(list(self.config.get("args", []) or []))

        process_cwd = Path(self.cwd)
        if self.config.get("cwd"):
            process_cwd = (process_cwd / str(self.config["cwd"])).resolve()
        env = os.environ.copy()
        for key, value in dict(self.config.get("env", {}) or {}).items():
            env[str(key)] = str(value)

        popen_kwargs: dict = {}
        if os.name == "nt":
            # Prevent a console window from popping up for the child process
            CREATE_NO_WINDOW = 0x08000000
            popen_kwargs["creationflags"] = CREATE_NO_WINDOW
        try:
            self.process = subprocess.Popen(  # noqa: S603
                [command, *list(self.config.get("args", []) or [])],
                cwd=str(process_cwd),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                **popen_kwargs,
            )
        except FileNotFoundError:
            raise RuntimeError(f"Command not found: {command}. Install it first and ensure it is available in PATH.") from None

        self.stderr_lines = []
        self.pending = {}
        self._stderr_thread = threading.Thread(target=self._consume_stderr, daemon=True)
        self._stderr_thread.start()

    def _consume_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        for line in self.process.stderr:
            text = line.strip()
            if text:
                self.stderr_lines.append(text)
                self.stderr_lines = self.stderr_lines[-8:]

    def _ensure_stdout_thread(self) -> None:
        if self._stdout_thread is not None:
            return
        self._stdout_thread = threading.Thread(target=self._consume_stdout, daemon=True)
        self._stdout_thread.start()

    def _consume_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None

        while True:
            line = self.process.stdout.readline()
            if not line:
                break

            stripped = line.strip()
            if not stripped:
                continue

            # Auto-detect protocol if not determined yet
            if self.protocol is None:
                if line.lower().startswith("content-length:"):
                    self.protocol = "content-length"
                else:
                    self.protocol = "newline-json"

            if self.protocol == "newline-json":
                try:
                    self._handle_message(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
            else:
                # Content-length protocol
                # The current 'line' is the first header line
                header_lines = [line.rstrip("\r\n")]
                while True:
                    next_line = self.process.stdout.readline()
                    if not next_line:
                        return
                    h_stripped = next_line.rstrip("\r\n")
                    if h_stripped == "":
                        break
                    header_lines.append(h_stripped)

                content_length = 0
                for header in header_lines:
                    if header.lower().startswith("content-length:"):
                        try:
                            content_length = int(header.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                        break

                if content_length > 0:
                    body = self.process.stdout.read(content_length)
                    if not body:
                        return
                    try:
                        self._handle_message(json.loads(body))
                    except json.JSONDecodeError:
                        pass

    def _handle_message(self, message: dict[str, Any]) -> None:
        message_id = message.get("id")
        if not isinstance(message_id, int):
            return
        queue = self.pending.pop(message_id, None)
        if queue is not None:
            queue.put(message)

    def send(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError(f'MCP server "{self.server_name}" is not running.')
        payload = json.dumps(message, ensure_ascii=False)
        if self.protocol == "newline-json":
            self.process.stdin.write(payload + "\n")
            self.process.stdin.flush()
            self._ensure_stdout_thread()
            return
        header = f"Content-Length: {len(payload.encode('utf-8'))}\r\n\r\n"
        self.process.stdin.write(header + payload)
        self.process.stdin.flush()
        self._ensure_stdout_thread()

    def notify(self, method: str, params: Any) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: Any, timeout_seconds: float = 5.0) -> Any:
        message_id = self.next_id
        self.next_id += 1
        response_queue: Queue[Any] = Queue(maxsize=1)
        self.pending[message_id] = response_queue
        self.send({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params})
        try:
            message = response_queue.get(timeout=timeout_seconds)
        except Empty as error:
            self.pending.pop(message_id, None)
            stderr = "\n".join(self.stderr_lines)
            raise RuntimeError(
                f"MCP {self.server_name}: request timed out for {method}" + (f"\n{stderr}" if stderr else "")
            ) from error
        if message.get("error"):
            details = message["error"].get("data")
            suffix = f"\n{json.dumps(details, indent=2, ensure_ascii=False)}" if details else ""
            raise RuntimeError(f"MCP {self.server_name}: {message['error']['message']}{suffix}")
        return message.get("result")

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        return list(result.get("tools", []) if isinstance(result, dict) else [])

    def list_resources(self) -> list[dict[str, Any]]:
        result = self.request("resources/list", {}, timeout_seconds=3.0)
        return list(result.get("resources", []) if isinstance(result, dict) else [])

    def read_resource(self, uri: str) -> ToolResult:
        return _format_read_resource_result(self.request("resources/read", {"uri": uri}, timeout_seconds=5.0))

    def list_prompts(self) -> list[dict[str, Any]]:
        result = self.request("prompts/list", {}, timeout_seconds=3.0)
        return list(result.get("prompts", []) if isinstance(result, dict) else [])

    def get_prompt(self, name: str, args: dict[str, str] | None = None) -> ToolResult:
        return _format_prompt_result(
            self.request("prompts/get", {"name": name, "arguments": args or {}}, timeout_seconds=5.0)
        )

    def call_tool(self, name: str, input_data: Any) -> ToolResult:
        return _format_tool_call_result(self.request("tools/call", {"name": name, "arguments": input_data or {}}))

    def close(self) -> None:
        pending = list(self.pending.values())
        self.pending.clear()
        for queue in pending:
            queue.put({"error": {"message": f'MCP server "{self.server_name}" closed before completing the request.'}})
        
        if self.process is not None:
            try:
                # 跨平台进程终止
                if os.name == "nt":
                    # Windows: 使用 taskkill 终止进程树
                    try:
                        subprocess.run(
                            ["taskkill", "/T", "/F", "/PID", str(self.process.pid)],
                            capture_output=True,
                            timeout=5
                        )
                    except subprocess.TimeoutExpired:
                        # taskkill 本身超时，强制 kill
                        try:
                            self.process.kill()
                        except OSError:
                            pass
                    except Exception:
                        try:
                            self.process.kill()
                        except OSError:
                            pass
                else:
                    # Unix: 先 SIGTERM，超时后 SIGKILL
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            self.process.kill()
                        except OSError:
                            pass

                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
            except OSError:
                pass  # 进程可能已经退出
            finally:
                self.process = None
        
        self.protocol = None
        self._stdout_thread = None
        self._stderr_thread = None


def create_mcp_backed_tools(*, cwd: str, mcp_servers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    clients: list[StdioMcpClient] = []
    tools: list[ToolDefinition] = []
    servers: list[dict[str, Any]] = []
    resource_index: dict[str, dict[str, Any]] = {}
    prompt_index: dict[str, dict[str, Any]] = {}

    try:
        for server_name, config in mcp_servers.items():
            if config.get("enabled") is False:
                servers.append(asdict(McpServerSummary(name=server_name, command=config.get("command", ""), status="disabled", toolCount=0, protocol=config.get("protocol"))))
                continue

            client = StdioMcpClient(server_name, config, cwd)
            try:
                client.start()
                descriptors = client.list_tools()
                try:
                    resources = client.list_resources()
                except Exception:  # noqa: BLE001
                    resources = []
                try:
                    prompts = client.list_prompts()
                except Exception:  # noqa: BLE001
                    prompts = []
                clients.append(client)

                for resource in resources:
                    resource_index[f"{server_name}:{resource.get('uri')}"] = {"serverName": server_name, "resource": resource}
                for prompt in prompts:
                    prompt_index[f"{server_name}:{prompt.get('name')}"] = {"serverName": server_name, "prompt": prompt}

                for descriptor in descriptors:
                    wrapped_name = f"mcp__{_sanitize_tool_segment(server_name)}__{_sanitize_tool_segment(str(descriptor.get('name', 'tool')))}"
                    descriptor_name = str(descriptor.get("name", "tool"))
                    input_schema = _normalize_input_schema(descriptor.get("inputSchema"))

                    def _validator(value: Any) -> Any:
                        return value

                    def _run(input_data: Any, _context, *, _client=client, _descriptor_name=descriptor_name):
                        return _client.call_tool(_descriptor_name, input_data)

                    tools.append(
                        ToolDefinition(
                            name=wrapped_name,
                            description=str(descriptor.get("description") or f"Call MCP tool {descriptor_name} from server {server_name}."),
                            input_schema=input_schema,
                            validator=_validator,
                            run=_run,
                        )
                    )

                servers.append(
                    asdict(
                        McpServerSummary(
                            name=server_name,
                            command=config.get("command", ""),
                            status="connected",
                            toolCount=len(descriptors),
                            protocol=client.protocol,
                            resourceCount=len(resources),
                            promptCount=len(prompts),
                        )
                    )
                )
            except Exception as error:  # noqa: BLE001
                client.close()
                servers.append(
                    asdict(
                        McpServerSummary(
                            name=server_name,
                            command=config.get("command", ""),
                            status="error",
                            toolCount=0,
                            error=str(error),
                            protocol=config.get("protocol"),
                        )
                    )
                )
    except Exception:
        # 清理所有已连接的客户端，防止资源泄漏
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
        raise

    if resource_index:
        tools.append(
            ToolDefinition(
                name="list_mcp_resources",
                description="List available MCP resources exposed by connected MCP servers.",
                input_schema={"type": "object", "properties": {"server": {"type": "string"}}},
                validator=lambda value: {"server": value.get("server")} if isinstance(value, dict) else {"server": None},
                run=lambda input_data, _context: ToolResult(
                    ok=True,
                    output="\n".join(
                        f"{entry['serverName']}: {entry['resource'].get('uri')}"
                        + (f" ({entry['resource'].get('name')})" if entry["resource"].get("name") else "")
                        + (f" - {entry['resource'].get('description')}" if entry["resource"].get("description") else "")
                        for entry in resource_index.values()
                        if not input_data.get("server") or entry["serverName"] == input_data["server"]
                    )
                    or "No MCP resources available.",
                ),
            )
        )

        def _read_resource(input_data: dict, _context) -> ToolResult:
            client = next((item for item in clients if item.server_name == input_data["server"]), None)
            if client is None:
                return ToolResult(ok=False, output=f"Unknown MCP server: {input_data['server']}")
            return client.read_resource(input_data["uri"])

        tools.append(
            ToolDefinition(
                name="read_mcp_resource",
                description="Read a specific MCP resource by server and URI.",
                input_schema={"type": "object", "properties": {"server": {"type": "string"}, "uri": {"type": "string"}}, "required": ["server", "uri"]},
                validator=lambda value: value,
                run=_read_resource,
            )
        )

    if prompt_index:
        tools.append(
            ToolDefinition(
                name="list_mcp_prompts",
                description="List available MCP prompts exposed by connected MCP servers.",
                input_schema={"type": "object", "properties": {"server": {"type": "string"}}},
                validator=lambda value: {"server": value.get("server")} if isinstance(value, dict) else {"server": None},
                run=lambda input_data, _context: ToolResult(
                    ok=True,
                    output="\n".join(
                        f"{entry['serverName']}: {entry['prompt'].get('name')}"
                        + (
                            " args=["
                            + ", ".join(
                                f"{arg.get('name')}{'*' if arg.get('required') else ''}"
                                for arg in entry["prompt"].get("arguments", [])
                            )
                            + "]"
                            if entry["prompt"].get("arguments")
                            else ""
                        )
                        + (f" - {entry['prompt'].get('description')}" if entry["prompt"].get("description") else "")
                        for entry in prompt_index.values()
                        if not input_data.get("server") or entry["serverName"] == input_data["server"]
                    )
                    or "No MCP prompts available.",
                ),
            )
        )

        def _get_prompt(input_data: dict, _context) -> ToolResult:
            client = next((item for item in clients if item.server_name == input_data["server"]), None)
            if client is None:
                return ToolResult(ok=False, output=f"Unknown MCP server: {input_data['server']}")
            return client.get_prompt(input_data["name"], input_data.get("arguments"))

        tools.append(
            ToolDefinition(
                name="get_mcp_prompt",
                description="Fetch a rendered MCP prompt by server, prompt name, and optional arguments.",
                input_schema={"type": "object", "properties": {"server": {"type": "string"}, "name": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["server", "name"]},
                validator=lambda value: value,
                run=_get_prompt,
            )
        )

    return {
        "tools": tools,
        "servers": servers,
        "dispose": lambda: [client.close() for client in clients],
    }
