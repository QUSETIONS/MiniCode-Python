from __future__ import annotations

from Main.MinicodeFrontline.Src.Application.Entry.RuntimeLifecycleSurface import (
    RUNTIME_LIFECYCLE_ENTRIES,
    lifecycle_contract_payload,
    lifecycle_script_targets,
)


def test_runtime_lifecycle_surface_declares_console_entries() -> None:
    assert lifecycle_script_targets() == {
        "minicode-py": "minicode.main:main",
        "minicode-headless": "minicode.headless:main",
        "minicode-readiness": "minicode.readiness:main",
    }


def test_runtime_lifecycle_surface_payload_tracks_product_identity() -> None:
    payload = lifecycle_contract_payload()

    assert payload["logicalProductApp"] == "product/app/minicode_frontline"
    assert payload["entryCount"] == 3
    assert all(entry.lifecycleRole for entry in RUNTIME_LIFECYCLE_ENTRIES)
