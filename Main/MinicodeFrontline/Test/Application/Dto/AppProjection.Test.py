from __future__ import annotations

from Main.MinicodeFrontline.Src.Application.Dto.AppProjection import (
    CURRENT_IMPLEMENTATION_ROOT,
    ENTRY_SURFACES,
    LOGICAL_PRODUCT_APP,
)


def test_app_projection_dto_declares_current_product_identity() -> None:
    assert LOGICAL_PRODUCT_APP == "product/app/minicode_frontline"
    assert CURRENT_IMPLEMENTATION_ROOT == "minicode"
    assert [surface.name for surface in ENTRY_SURFACES] == [
        "interactive-cli",
        "headless-runner",
        "readiness-checker",
        "local-command-surface",
        "product-snapshot",
        "release-readiness",
    ]
