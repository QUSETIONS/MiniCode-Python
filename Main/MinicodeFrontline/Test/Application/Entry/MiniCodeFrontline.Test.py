from __future__ import annotations

from Main.MinicodeFrontline.Src.Application.Entry.MiniCodeFrontline import (
    entry_surface_names,
)
from Main.MinicodeFrontline.Src.Application.Dto.AppProjection import (
    CURRENT_IMPLEMENTATION_ROOT,
    ENTRY_SURFACES,
    LOGICAL_PRODUCT_APP,
)


def test_minicode_frontline_entry_contract_tracks_current_runtime_root() -> None:
    assert LOGICAL_PRODUCT_APP == "product/app/minicode_frontline"
    assert CURRENT_IMPLEMENTATION_ROOT == "minicode"


def test_minicode_frontline_entry_contract_names_observable_surfaces() -> None:
    assert entry_surface_names() == (
        "interactive-cli",
        "headless-runner",
        "readiness-checker",
        "local-command-surface",
        "product-snapshot",
        "release-readiness",
    )
    assert all(surface.currentPoint for surface in ENTRY_SURFACES)
    assert all(surface.observableResult for surface in ENTRY_SURFACES)
