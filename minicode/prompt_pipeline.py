"""Dynamic prompt assembly pipeline for MiniCode Python.

Implements paragraph-level assembly with cache boundaries and conditional
sections, following the Learn Claude Code best practices.

Key concepts:
- SYSTEM_PROMPT_DYNAMIC_BOUNDARY: Separates static prefix (cacheable) from
  dynamic suffix (session-specific). Enables cross-session API prompt caching.
- PromptSection: Declarative paragraph registration with name, condition,
  and builder attributes.
- Paragraph-level cache: Avoids re-reading CLAUDE.md, skills, etc. every turn.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Sentinel string marking the boundary between static and dynamic prompt parts.
# API providers (Anthropic, OpenAI) use this to implement prompt caching.
SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"


@dataclass
class PromptSection:
    """Declarative prompt paragraph with conditional inclusion and caching."""

    name: str
    builder: Callable[[], str]
    condition: Callable[[], bool] | None = None
    cache_ttl: float = 300.0  # 5 minutes default
    _cached_value: str | None = field(default=None, repr=False)
    _cached_at: float = field(default=0.0, repr=False)

    def evaluate(self) -> str | None:
        """Return the paragraph text if condition is met, else None."""
        if self.condition is not None and not self.condition():
            return None

        # Check cache
        now = time.monotonic()
        if self._cached_value is not None and (now - self._cached_at) < self.cache_ttl:
            return self._cached_value

        # Build and cache
        text = self.builder()
        self._cached_value = text
        self._cached_at = now
        return text


class PromptPipeline:
    """Manages the lifecycle of prompt sections with cache boundaries.

    Usage:
        pipeline = PromptPipeline()
        pipeline.register_static("role", "You are an AI assistant...")
        pipeline.register_dynamic(
            "skills",
            lambda: get_skills_text(skills),
            condition=lambda: len(skills) > 0,
        )
        prompt = pipeline.build()
    """

    def __init__(self) -> None:
        self._static_sections: list[PromptSection] = []
        self._dynamic_sections: list[PromptSection] = []

    def register_static(self, name: str, text: str) -> None:
        """Register a paragraph that never changes (fully cacheable)."""
        self._static_sections.append(
            PromptSection(
                name=name,
                builder=lambda: text,
                cache_ttl=float("inf"),  # Never expires
            )
        )

    def register_dynamic(
        self,
        name: str,
        builder: Callable[[], str],
        condition: Callable[[], bool] | None = None,
        cache_ttl: float = 300.0,
    ) -> None:
        """Register a paragraph that may change between turns."""
        self._dynamic_sections.append(
            PromptSection(
                name=name,
                builder=builder,
                condition=condition,
                cache_ttl=cache_ttl,
            )
        )

    def build(self) -> str:
        """Assemble the full system prompt with cache boundary marker."""
        parts: list[str] = []

        # Static prefix (cacheable across turns/sessions)
        for section in self._static_sections:
            text = section.evaluate()
            if text:
                parts.append(text)

        # Dynamic boundary marker
        parts.append(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)

        # Dynamic suffix (re-evaluated per turn)
        for section in self._dynamic_sections:
            text = section.evaluate()
            if text:
                parts.append(text)

        return "\n\n".join(p for p in parts if p)

    def clear_cache(self) -> None:
        """Clear all paragraph caches (force rebuild on next build())."""
        for section in self._static_sections + self._dynamic_sections:
            section._cached_value = None
            section._cached_at = 0.0


# ---------------------------------------------------------------------------
# File-based cache for expensive paragraph builders (CLAUDE.md, etc.)
# ---------------------------------------------------------------------------

_file_cache: dict[str, tuple[str, float, float]] = {}


def read_file_cached(path: Path, ttl: float = 300.0) -> str | None:
    """Read a file with mtime-based caching.

    Returns None if file doesn't exist.
    """
    key = str(path.resolve())
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None

    if key in _file_cache:
        cached_text, cached_mtime, cached_at = _file_cache[key]
        if mtime == cached_mtime and (time.monotonic() - cached_at) < ttl:
            return cached_text

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    _file_cache[key] = (text, mtime, time.monotonic())
    return text


def content_hash(text: str) -> str:
    """Compute a short content hash for cache invalidation."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]
