"""Scheduled headless task runner for MiniCode.

Config format:

{
  "tasks": [
    {"name": "daily-check", "prompt": "Summarize the repository status"}
  ]
}

Without a config file, the runner exits cleanly with an explanatory message.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any


def _default_config_path() -> Path:
    return Path(os.environ.get("MINI_CODE_CRON_CONFIG", ".mini-code/cron.json"))


def load_cron_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else _default_config_path()
    if not config_path.exists():
        return {"tasks": []}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("cron config must be a JSON object")
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("cron config field 'tasks' must be a list")
    return {"tasks": tasks}


def run_configured_tasks(config: dict[str, Any], *, dry_run: bool = False) -> list[dict[str, Any]]:
    from minicode.headless import run_headless

    results: list[dict[str, Any]] = []
    for index, task in enumerate(config.get("tasks", [])):
        if not isinstance(task, dict):
            results.append({"index": index, "ok": False, "error": "task must be an object"})
            continue
        prompt = str(task.get("prompt", "")).strip()
        name = str(task.get("name") or f"task-{index + 1}")
        if not prompt:
            results.append({"name": name, "ok": False, "error": "prompt is required"})
            continue
        if dry_run:
            results.append({"name": name, "ok": True, "dryRun": True})
            continue
        results.append({"name": name, "ok": True, "response": run_headless(prompt)})
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run MiniCode scheduled headless tasks.")
    parser.add_argument("--config", default=None, help="Path to cron JSON config.")
    parser.add_argument("--once", action="store_true", help="Run tasks once and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Validate tasks without executing prompts.")
    parser.add_argument("--interval", type=float, default=60.0, help="Polling interval in seconds.")
    args = parser.parse_args(argv)

    while True:
        config = load_cron_config(args.config)
        if not config["tasks"]:
            print(f"No cron tasks configured in {args.config or _default_config_path()}.", flush=True)
        else:
            for result in run_configured_tasks(config, dry_run=args.dry_run):
                print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.once or not config["tasks"]:
            return
        time.sleep(max(args.interval, 1.0))


if __name__ == "__main__":
    main()
