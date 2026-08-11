from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from benchmarks.runtime_profile_eval import collect_provider_diagnostics
from minicode import provider_smoke
from minicode.model_registry import Provider


def _valid_runtime() -> dict[str, object]:
    return {
        "model": "gpt-4o",
        "openaiApiKey": "sk-test-secret",
        "openaiBaseUrl": "http://127.0.0.1:9999/v1",
    }


def _patch_valid_runtime(monkeypatch) -> None:
    runtime = _valid_runtime()
    monkeypatch.setattr(provider_smoke, "load_runtime_config", lambda cwd: runtime)
    monkeypatch.setattr(provider_smoke, "validate_provider_runtime", lambda runtime, **kwargs: [])
    monkeypatch.setattr(
        provider_smoke,
        "detect_provider",
        lambda model, runtime, **kwargs: Provider.OPENAI,
    )
    monkeypatch.setattr(
        provider_smoke,
        "build_readiness_report",
        lambda cwd, runtime=None: {
            "status": "ready",
            "fallback_ready": True,
            "fallback_candidates": ["gpt-4o-mini"],
            "viable_fallbacks": ["gpt-4o-mini"],
            "risk_scope": "none",
        },
    )


def test_provider_smoke_is_offline_by_default(monkeypatch) -> None:
    monkeypatch.delenv(provider_smoke.LIVE_PROVIDER_SMOKE_ENV, raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("default provider smoke must not start a subprocess")

    result = provider_smoke.run_provider_smoke(runner=fail_if_called)

    assert result["status"] == "skipped"
    assert result["outcome"] == "skipped"
    assert result["live_provider_claim"] is False
    assert result["attempted"] is False


def test_provider_smoke_requires_environment_gate(monkeypatch) -> None:
    monkeypatch.delenv(provider_smoke.LIVE_PROVIDER_SMOKE_ENV, raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("missing environment gate must not start a subprocess")

    result = provider_smoke.run_provider_smoke(run_live=True, runner=fail_if_called)

    assert result["status"] == "blocked"
    assert result["outcome"] == "blocked"
    assert result["live_provider_claim"] is False
    assert provider_smoke.LIVE_PROVIDER_SMOKE_ENV in result["summary"]


def test_provider_smoke_blocks_invalid_runtime_before_subprocess(monkeypatch) -> None:
    monkeypatch.setenv(provider_smoke.LIVE_PROVIDER_SMOKE_ENV, "1")
    monkeypatch.setattr(
        provider_smoke,
        "load_runtime_config",
        lambda cwd: (_ for _ in ()).throw(RuntimeError("No auth configured.")),
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid runtime must not start a subprocess")

    result = provider_smoke.run_provider_smoke(run_live=True, runner=fail_if_called)

    assert result["status"] == "blocked"
    assert result["outcome"] == "blocked"
    assert result["live_provider_claim"] is False
    assert "No auth configured." in result["summary"]


def test_provider_smoke_returns_redacted_success_evidence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(provider_smoke.LIVE_PROVIDER_SMOKE_ENV, "true")
    _patch_valid_runtime(monkeypatch)

    def fake_run(command, **kwargs):
        trace_path = Path(kwargs["env"]["MINI_CODE_HEADLESS_MESSAGES_OUT"])
        trace_path.write_text(
            json.dumps(
                {
                    "readiness_report": {"status": "ready"},
                    "repair_plan": [{"step": "keep-fallback-gate"}],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="OK\n", stderr="")

    result = provider_smoke.run_provider_smoke(
        tmp_path,
        run_live=True,
        timeout=7,
        runner=fake_run,
    )

    rendered = json.dumps(result)
    assert result["status"] == "passed"
    assert result["outcome"] == "answered"
    assert result["live_provider_claim"] is True
    assert result["attempted"] is True
    assert result["provider"] == "openai"
    assert result["trace"] == {
        "available": True,
        "readiness_status": "ready",
        "repair_step_count": 1,
    }
    assert result["timeout_seconds"] == 7
    assert "sk-test-secret" not in rendered


def test_provider_smoke_reaches_local_openai_compatible_server(
    monkeypatch,
    tmp_path: Path,
) -> None:
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            requests.append(json.loads(self.rfile.read(length).decode("utf-8")))
            body = json.dumps(
                {
                    "id": "chatcmpl-local-smoke",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "OK"},
                            "finish_reason": "stop",
                        }
                    ],
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv(provider_smoke.LIVE_PROVIDER_SMOKE_ENV, "1")
        monkeypatch.setenv("MINI_CODE_MODEL", "gpt-4o")
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-key")
        monkeypatch.setenv(
            "OPENAI_BASE_URL",
            f"http://127.0.0.1:{server.server_port}",
        )
        _patch_valid_runtime(monkeypatch)
        result = provider_smoke.run_provider_smoke(
            tmp_path,
            run_live=True,
            timeout=10,
            runner=subprocess.run,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result["status"] == "passed"
    assert result["outcome"] == "answered"
    assert result["live_provider_claim"] is True
    assert len(requests) == 1
    assert requests[0]["model"] == "gpt-4o"
    assert "local-test-key" not in json.dumps(result)


def test_provider_smoke_classifies_api_error_without_returning_raw_output(monkeypatch) -> None:
    monkeypatch.setenv(provider_smoke.LIVE_PROVIDER_SMOKE_ENV, "1")
    _patch_valid_runtime(monkeypatch)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=(
                "Model API error: error code: 401 request id: req-123 "
                "Bearer sk-test-secret"
            ),
        )

    result = provider_smoke.run_provider_smoke(run_live=True, runner=fake_run)

    assert result["status"] == "failed"
    assert result["outcome"] == "provider_api_error"
    assert result["failure_category"] == "authentication"
    assert result["error_code"] == "401"
    assert result["request_id"] == "req-123"
    assert "sk-test-secret" not in json.dumps(result)
    assert "Bearer [REDACTED]" in result["summary"]


def test_provider_smoke_classifies_timeout(monkeypatch) -> None:
    monkeypatch.setenv(provider_smoke.LIVE_PROVIDER_SMOKE_ENV, "1")
    _patch_valid_runtime(monkeypatch)

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="partial")

    result = provider_smoke.run_provider_smoke(run_live=True, runner=fake_run)

    assert result["status"] == "failed"
    assert result["outcome"] == "timeout"
    assert result["failure_category"] == "timeout"
    assert result["retryable"] is True
    assert result["live_provider_claim"] is True


def test_runtime_profile_default_cannot_inherit_provider_credentials(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("MINICODE_LIVE_PROVIDER_SMOKE", "1")
    captured: dict[str, str] = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Config error: No auth configured.",
        )

    monkeypatch.setattr("benchmarks.runtime_profile_eval.subprocess.run", fake_run)

    diagnostics = collect_provider_diagnostics()

    assert diagnostics[0].outcome == "provider_channel_unavailable"
    assert "OPENAI_API_KEY" not in captured
    assert "MINICODE_LIVE_PROVIDER_SMOKE" not in captured
    assert captured["HOME"] != str(Path.home())
