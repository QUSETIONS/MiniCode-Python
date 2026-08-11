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

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path


def _headless_response_exit_code(response: str) -> int:
    normalized = " ".join(str(response or "").lower().split())
    failure_prefixes = (
        "error:",
        "config error:",
        "model api error",
        "model api timeout",
        "network error",
        "provider availability failure",
        "reached the maximum tool step limit",
    )
    if any(normalized.startswith(prefix) for prefix in failure_prefixes):
        return 1
    if "empty response" in normalized:
        return 1
    return 0


def _write_headless_messages_trace(
    trace_path: str | None,
    *,
    cwd: str,
    prompt: str,
    runtime: dict | None,
    result_messages: list[dict] | None,
    response_text: str | None,
    error_text: str | None = None,
) -> None:
    if not trace_path:
        return
    readiness_report = _headless_readiness_snapshot(cwd, runtime)
    payload = {
        "cwd": cwd,
        "prompt": prompt,
        "model": (runtime or {}).get("model"),
        "exit_code": _headless_response_exit_code(response_text or error_text or ""),
        "readiness_report": readiness_report,
        "repair_plan": readiness_report.get("repair_plan", []),
        "messages": result_messages or [],
        "assistant_response": response_text,
        "error": error_text,
    }
    try:
        from minicode.release_readiness import redact_sensitive_payload

        payload = redact_sensitive_payload(payload)
    except Exception:  # noqa: BLE001
        pass
    path = Path(trace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _headless_readiness_snapshot(cwd: str, runtime: dict | None) -> dict:
    try:
        from minicode.product_surfaces import build_readiness_report

        report = build_readiness_report(cwd, runtime=runtime or {})
        if is_dataclass(report):
            return asdict(report)
        if isinstance(report, dict):
            return report
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unknown",
            "summary": f"readiness unavailable: {exc}",
            "repair_plan": [
                {
                    "step": "diagnose-local-readiness",
                    "status": "blocked",
                    "action": "Inspect local provider configuration without calling the model provider.",
                    "command": "minicode-readiness --json --fail-on blocked",
                    "safety": "read-only",
                },
                {
                    "step": "verify-release-readiness",
                    "status": "verify",
                    "action": "Run the explicit provider smoke after local configuration is ready.",
                    "command": "MINICODE_LIVE_PROVIDER_SMOKE=1 minicode-provider-smoke --run-live",
                    "safety": "explicit opt-in; may call the live provider",
                },
            ],
        }
    return {
        "status": "unknown",
        "summary": "readiness unavailable",
        "repair_plan": [],
    }


def _allow_edits_requested(cli_flag: bool = False) -> bool:
    """True if headless should auto-approve edits/commands/out-of-cwd access.

    Opt-in, non-interactive CI mode. Gated by the --allow-edits flag or the
    MINI_CODE_ALLOW_EDITS env var (1/true/yes/on)."""
    if cli_flag:
        return True
    return os.getenv("MINI_CODE_ALLOW_EDITS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _make_auto_approve_prompt():
    """Build a non-interactive permission prompt that grants every request for
    the current run. Decisions are session-scoped (no persistence to the
    permission store): edits via allow_all_turn, paths/commands via allow_once.
    """

    def _auto_approve(request: dict) -> dict:
        if request.get("kind") == "edit":
            return {"decision": "allow_all_turn"}
        return {"decision": "allow_once"}

    return _auto_approve


def run_headless(prompt: str | None = None, allow_edits: bool = False) -> str:
    """Run a single agent turn in headless mode and return the response.

    Args:
        prompt: The user message to send. If None, reads from stdin.
        allow_edits: If True (or via MINI_CODE_ALLOW_EDITS), auto-approve file
            edits, commands, and out-of-cwd access for this non-interactive run.
            Required for headless to modify files (edits otherwise need TTY
            approval).

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
    from minicode.logging_config import setup_logging, get_logger, structured_logging_requested

    setup_logging(
        level=os.environ.get("MINI_CODE_LOG_LEVEL", "WARNING"),
        structured=structured_logging_requested(),
    )
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
    trace_output_path = os.environ.get("MINI_CODE_HEADLESS_MESSAGES_OUT", "").strip() or None

    # Load config
    try:
        runtime = load_runtime_config(cwd)
    except Exception as exc:  # noqa: BLE001
        # Persist the failure to the log file (issue #5), not just stderr.
        logger.error("Config load failed: %s", exc, exc_info=True)
        _write_headless_messages_trace(
            trace_output_path,
            cwd=cwd,
            prompt=prompt,
            runtime=None,
            result_messages=[],
            response_text=f"Config error: {exc}",
            error_text=str(exc),
        )
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Initialize components
    tools = create_default_tool_registry(cwd, runtime=runtime)
    auto_approve = _allow_edits_requested(cli_flag=allow_edits)
    if auto_approve:
        logger.warning(
            "Headless --allow-edits is active: file edits, commands, and "
            "out-of-cwd access will be auto-approved for this run "
            "(non-interactive CI mode; approvals are session-scoped)."
        )
    permissions = PermissionManager(cwd, prompt=_make_auto_approve_prompt() if auto_approve else None)
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
            memory_manager=memory_mgr,
            runtime=runtime,
        )

        # Extract last assistant message
        last_assistant = next(
            (m for m in reversed(result_messages) if m["role"] == "assistant"),
            None,
        )
        response_text = last_assistant["content"] if last_assistant else "(no response)"
        _write_headless_messages_trace(
            trace_output_path,
            cwd=cwd,
            prompt=prompt,
            runtime=runtime,
            result_messages=result_messages,
            response_text=response_text,
        )
        return response_text

    except Exception as exc:  # noqa: BLE001
        logger.error("Headless error: %s", exc)
        response_text = f"Error: {exc}"
        _write_headless_messages_trace(
            trace_output_path,
            cwd=cwd,
            prompt=prompt,
            runtime=runtime,
            result_messages=[],
            response_text=response_text,
            error_text=str(exc),
        )
        return response_text
    finally:
        try:
            tools.dispose()
        except Exception:  # noqa: BLE001
            pass


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minicode-headless",
        description="Run one MiniCode agent turn without a TTY.",
    )
    parser.add_argument(
        "--allow-edits",
        action="store_true",
        help="Auto-approve edits, commands, and out-of-cwd access for this run.",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Prompt to send; reads stdin when omitted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for headless mode."""
    parser = _build_argument_parser()
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    prompt = " ".join(parsed.prompt) if parsed.prompt else None
    response = run_headless(prompt, allow_edits=parsed.allow_edits)
    print(response)
    return _headless_response_exit_code(response)


if __name__ == "__main__":
    raise SystemExit(main())
