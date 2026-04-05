import json
import sys


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    message_id = message.get("id")

    if method == "initialize":
        send({"jsonrpc": "2.0", "id": message_id, "result": {"serverInfo": {"name": "fake"}}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        send(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo text",
                            "inputSchema": {"type": "object"},
                        }
                    ]
                },
            }
        )
    elif method == "resources/list":
        send(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {"resources": [{"uri": "fake://hello", "name": "Hello"}]},
            }
        )
    elif method == "resources/read":
        send(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {"contents": [{"uri": "fake://hello", "text": "hello resource"}]},
            }
        )
    elif method == "prompts/list":
        send(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {"prompts": [{"name": "hello", "arguments": [{"name": "name", "required": True}]}]},
            }
        )
    elif method == "prompts/get":
        arguments = message.get("params", {}).get("arguments", {})
        name = arguments.get("name", "world")
        send(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {"messages": [{"role": "user", "content": f"hello {name}"}]},
            }
        )
    elif method == "tools/call":
        arguments = message.get("params", {}).get("arguments", {})
        send(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {"content": [{"type": "text", "text": f"echo:{arguments.get('text', '')}"}]},
            }
        )

