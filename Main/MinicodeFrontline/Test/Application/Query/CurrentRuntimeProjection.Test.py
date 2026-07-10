from __future__ import annotations

from pathlib import Path

from Main.MinicodeFrontline.Src.Application.Query.CurrentRuntimeProjection import (
    build_current_runtime_projection,
)


def test_current_runtime_projection_reports_all_entry_evidence() -> None:
    projection = build_current_runtime_projection(Path.cwd())

    assert projection["logicalProductApp"] == "product/app/minicode_frontline"
    assert projection["currentImplementationRoot"] == "minicode"
    assert projection["entryCount"] == 6
    assert projection["missingEvidence"] == []
    assert {
        entry["evidencePath"] for entry in projection["entries"]
    } == {
        "minicode/main.py",
        "minicode/headless.py",
        "minicode/readiness.py",
        "minicode/cli_commands.py",
        "minicode/product_surfaces.py",
        "minicode/release_readiness.py",
    }
