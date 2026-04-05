from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class TranscriptEntry:
    id: int
    kind: Literal["user", "assistant", "progress", "tool"]
    body: str
    toolName: str | None = None
    status: Literal["running", "success", "error"] | None = None
    collapsed: bool = False
    collapsedSummary: str | None = None
    collapsePhase: Literal[1, 2, 3] | None = None

