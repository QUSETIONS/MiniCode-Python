from __future__ import annotations

from Main.MinicodeFrontline.Src.Application.Dto.AppProjection import (
    CURRENT_IMPLEMENTATION_ROOT,
    ENTRY_SURFACES,
    LOGICAL_PRODUCT_APP,
    EntrySurface,
)


def entry_surface_names() -> tuple[str, ...]:
    return tuple(surface.name for surface in ENTRY_SURFACES)
