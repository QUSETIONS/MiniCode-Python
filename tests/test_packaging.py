from __future__ import annotations

import importlib
import json
import subprocess
import sys
import threading
import tomllib
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_console_script_entry_points_import() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    failures = []
    for name, target in pyproject["project"]["scripts"].items():
        module_name, _, attr_name = target.partition(":")
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: cannot import {module_name}: {exc}")
            continue
        if not hasattr(module, attr_name):
            failures.append(f"{name}: {module_name}.{attr_name} does not exist")

    assert failures == []


def test_legacy_root_smoke_scripts_are_not_pytest_collected() -> None:
    import conftest

    root_smoke_scripts = {
        path.name
        for pattern in ("test_*.py", "*_test.py")
        for path in ROOT.glob(pattern)
    }

    assert root_smoke_scripts
    assert root_smoke_scripts.issubset(set(conftest.collect_ignore))
    assert "benchmarks/*.py" in conftest.collect_ignore_glob


def test_ci_workflow_runs_release_quality_gates() -> None:
    workflow = ROOT / ".github" / "workflows" / "ci.yml"

    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")
    assert "python -m compileall -q minicode tests" in content
    assert "python -m pytest -q" in content
    assert "tests/test_packaging.py" in content


def test_cron_runner_empty_config_exits_cleanly(tmp_path: Path) -> None:
    missing_config = tmp_path / "missing-cron.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "minicode.cron_runner",
            "--once",
            "--dry-run",
            "--config",
            str(missing_config),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "No cron tasks configured" in completed.stdout


def test_gateway_health_endpoint_responds() -> None:
    from http.server import ThreadingHTTPServer

    from minicode.gateway import MiniCodeGatewayHandler

    server = ThreadingHTTPServer(("127.0.0.1", 0), MiniCodeGatewayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload == {"ok": True, "service": "minicode-gateway"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
