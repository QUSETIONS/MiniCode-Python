from __future__ import annotations

from pathlib import Path

from Main.MinicodeFrontline.Src.Application.Query.RuntimeCapabilityInventory import (
    build_runtime_capability_inventory,
)


def test_runtime_capability_inventory_covers_core_current_app_files() -> None:
    inventory = build_runtime_capability_inventory(Path.cwd())

    assert inventory["logicalProductApp"] == "product/app/minicode_frontline"
    assert inventory["currentImplementationRoot"] == "minicode"
    assert inventory["missingEvidence"] == []
    assert inventory["sliceCount"] >= 9
    assert {
        item["currentPath"] for item in inventory["slices"]
    } >= {
        "minicode/main.py",
        "minicode/headless.py",
        "minicode/readiness.py",
        "minicode/cli_commands.py",
        "minicode/session.py",
        "minicode/config.py",
        "minicode/product_surfaces.py",
        "minicode/release_readiness.py",
    }


def test_runtime_capability_inventory_names_next_migration_candidates() -> None:
    inventory = build_runtime_capability_inventory(Path.cwd())
    candidates = inventory["nextMigrationCandidates"]

    assert [item["currentPath"] for item in candidates] == [
        "minicode/main.py",
        "minicode/headless.py",
        "minicode/readiness.py",
    ]
    assert candidates[0]["migrationCandidate"] == "Main/MinicodeFrontline/Src/Boot"
    assert "entry" in inventory["capabilityKindCounts"]
