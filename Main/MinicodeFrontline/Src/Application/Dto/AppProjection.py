from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntrySurface:
    name: str
    currentPoint: str
    observableResult: str
    appRole: str


LOGICAL_PRODUCT_APP = "product/app/minicode_frontline"
CURRENT_IMPLEMENTATION_ROOT = "minicode"


ENTRY_SURFACES = (
    EntrySurface(
        name="interactive-cli",
        currentPoint="minicode-py | python -m minicode.main",
        observableResult=(
            "terminal coding session with tools, permissions, model runtime, "
            "transcript, session commands, checkpoints, and rewind"
        ),
        appRole="product app lifecycle entry",
    ),
    EntrySurface(
        name="headless-runner",
        currentPoint="minicode-headless | python -m minicode.headless",
        observableResult="single prompt execution with optional message trace",
        appRole="product app automation entry",
    ),
    EntrySurface(
        name="readiness-checker",
        currentPoint="minicode-readiness | python -m minicode.readiness",
        observableResult="provider/runtime readiness report with risk scope and next actions",
        appRole="product app diagnostic entry",
    ),
    EntrySurface(
        name="local-command-surface",
        currentPoint="minicode/cli_commands.py",
        observableResult=(
            "/session, /session-replay, /sessions, /checkpoints, /rewind, "
            "/readiness, and /extensions"
        ),
        appRole="product app operation surface",
    ),
    EntrySurface(
        name="product-snapshot",
        currentPoint="minicode/product_surfaces.py",
        observableResult=(
            "instruction, hook, delegation, extension, readiness, and prompt "
            "bundle summaries"
        ),
        appRole="product app observability surface",
    ),
    EntrySurface(
        name="release-readiness",
        currentPoint="minicode/release_readiness.py",
        observableResult=(
            "compile, test, smoke, runtime profile, and provider diagnostics "
            "summary"
        ),
        appRole="product app quality gate evidence",
    ),
)
