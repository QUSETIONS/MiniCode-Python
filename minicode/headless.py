"""MiniCode Headless Runner — non-interactive, one-shot execution.

Inspired by Hermes Agent's headless mode for CI/CD pipelines and
automated workflows.

Usage:
  # Run a single prompt and exit
  python -m minicode.headless "帮我分析这个项目的结构"

  # Pipe input
  echo "解释这段代码" | python -m minicode.headless

  # In Docker
  docker compose run --rm headless "修复这个 bug"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def run_headless(prompt: str | None = None) -> str:
    """Run a single agent turn in headless mode and return the response.

    Args:
        prompt: The user message to send. If None, reads from stdin.

    Returns:
        The assistant's response text.
    """
    from minicode.agent_loop import run_agent_turn
    from minicode.config import load_runtime_config
    from minicode.memory import MemoryManager
    from minicode.model_registry import create_model_adapter
    from minicode.permissions import PermissionManager
    from minicode.prompt import build_system_prompt
    from minicode.tools import create_default_tool_registry
    from minicode.tooling import ToolContext
    from minicode.logging_config import setup_logging, get_logger

    setup_logging(level=os.environ.get("MINI_CODE_LOG_LEVEL", "WARNING"))
    logger = get_logger("headless")

    # Read prompt from stdin if not provided
    if prompt is None:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        else:
            print("Usage: python -m minicode.headless <prompt>", file=sys.stderr)
            sys.exit(1)

    if not prompt:
        print("Error: empty prompt", file=sys.stderr)
        sys.exit(1)

    cwd = str(Path.cwd())

    # Load config
    try:
        runtime = load_runtime_config(cwd)
    except Exception as exc:  # noqa: BLE001
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Initialize components
    tools = create_default_tool_registry(cwd, runtime=runtime)
    permissions = PermissionManager(cwd, prompt=None)
    memory_mgr = MemoryManager(project_root=Path(cwd))

    model = create_model_adapter(
        model=runtime.get("model", ""),
        tools=tools,
        runtime=runtime,
    )

    messages = [
        {
            "role": "system",
            "content": build_system_prompt(
                cwd,
                permissions.get_summary(),
                {
                    "skills": tools.get_skills(),
                    "mcpServers": tools.get_mcp_servers(),
                    "memory_context": memory_mgr.get_relevant_context(),
                },
            ),
        },
        {"role": "user", "content": prompt},
    ]

    logger.info("Headless run: %s", prompt[:80])

    try:
        result_messages = run_agent_turn(
            model=model,
            tools=tools,
            messages=messages,
            cwd=cwd,
            permissions=permissions,
        )

        # Extract last assistant message
        last_assistant = next(
            (m for m in reversed(result_messages) if m["role"] == "assistant"),
            None,
        )
        return last_assistant["content"] if last_assistant else "(no response)"

    except Exception as exc:  # noqa: BLE001
        logger.error("Headless error: %s", exc)
        return f"Error: {exc}"
    finally:
        try:
            tools.dispose()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    """CLI entry point for headless mode."""
    # Get prompt from command line args or stdin
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    response = run_headless(prompt)
    print(response)


if __name__ == "__main__":
    main()
