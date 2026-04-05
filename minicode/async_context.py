"""Async context collector for MiniCode Python.

Parallelizes expensive I/O operations (git status, CLAUDE.md loading, etc.)
and caches results with invalidation support.

Inspired by Claude Code's memoized async context providers.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Context collector
# ---------------------------------------------------------------------------

@dataclass
class ContextCache:
    """Cache entry with TTL."""
    value: Any
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 300.0  # 5 minutes default
    
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


class AsyncContextCollector:
    """Collects and caches context information.
    
    Inspired by Claude Code's memoized async context providers:
    - getSystemContext() - git status, system info
    - getUserContext() - CLAUDE.md, user preferences
    
    Parallelizes expensive I/O and provides cache invalidation.
    """
    
    def __init__(self, cwd: str, cache_ttl: float = 300.0):
        self.cwd = Path(cwd)
        self.cache_ttl = cache_ttl
        self._cache: dict[str, ContextCache] = {}
        self._git_root: Path | None = None
    
    async def get_full_context(self) -> dict[str, str]:
        """Get complete context (parallelized).
        
        Returns:
            Dictionary with context sections (git, user, system, etc.)
        """
        # Parallel collection
        system_ctx, user_ctx = await asyncio.gather(
            self.get_system_context(),
            self.get_user_context(),
            return_exceptions=True,
        )
        
        # Merge results
        context = {}
        if isinstance(system_ctx, dict):
            context.update(system_ctx)
        if isinstance(user_ctx, dict):
            context.update(user_ctx)
        
        return context
    
    async def get_system_context(self) -> dict[str, str]:
        """Get system context (git status, etc.) with caching."""
        cache_key = "system_context"
        
        # Check cache
        if cache_key in self._cache and not self._cache[cache_key].is_expired():
            return self._cache[cache_key].value
        
        # Collect (parallelized)
        git_status = await self._get_git_status()
        
        result = {}
        if git_status:
            result["git_status"] = git_status
        
        # Cache result
        self._cache[cache_key] = ContextCache(
            value=result,
            ttl_seconds=self.cache_ttl,
        )
        
        return result
    
    async def get_user_context(self) -> dict[str, str]:
        """Get user context (CLAUDE.md, preferences) with caching."""
        cache_key = f"user_context:{self.cwd}"
        
        # Check cache
        if cache_key in self._cache and not self._cache[cache_key].is_expired():
            return self._cache[cache_key].value
        
        # Collect (parallelized)
        claude_md = await self._load_claude_md()
        
        result = {
            "current_date": self._get_current_date(),
        }
        if claude_md:
            result["claude_md"] = claude_md
        
        # Cache result
        self._cache[cache_key] = ContextCache(
            value=result,
            ttl_seconds=self.cache_ttl,
        )
        
        return result
    
    def invalidate(self, pattern: str | None = None) -> None:
        """Invalidate cache entries.
        
        Args:
            pattern: If provided, only invalidate matching keys
        """
        if pattern:
            keys_to_remove = [k for k in self._cache if pattern in k]
            for key in keys_to_remove:
                del self._cache[key]
        else:
            self._cache.clear()
    
    def invalidate_git_cache(self) -> None:
        """Invalidate only git-related cache."""
        self.invalidate("system_context")
    
    # -----------------------------------------------------------------------
    # Internal collectors
    # -----------------------------------------------------------------------
    
    async def _get_git_status(self) -> str | None:
        """Get git status (parallelized sub-operations)."""
        if not await self._is_git_repo():
            return None
        
        # Parallel collection
        branch, status, log = await asyncio.gather(
            self._get_branch(),
            self._get_status(),
            self._get_log(),
        )
        
        return f"Branch: {branch}\nStatus:\n{status}\nRecent commits:\n{log}"
    
    async def _is_git_repo(self) -> bool:
        """Check if cwd is a git repo."""
        try:
            git_dir = self.cwd / ".git"
            if git_dir.exists():
                self._git_root = self.cwd
                return True
            
            # Search parent directories
            for parent in self.cwd.parents:
                if (parent / ".git").exists():
                    self._git_root = parent
                    return True
            
            return False
        except Exception:
            return False
    
    async def _get_branch(self) -> str:
        """Get current git branch."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"
    
    async def _get_status(self) -> str:
        """Get git status output."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() or "clean"
        except Exception:
            pass
        return "unknown"
    
    async def _get_log(self) -> str:
        """Get recent git log."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"
    
    async def _load_claude_md(self) -> str | None:
        """Load CLAUDE.md file if exists."""
        claude_md_path = self.cwd / "CLAUDE.md"
        if claude_md_path.exists():
            try:
                return claude_md_path.read_text(encoding="utf-8")
            except Exception:
                pass
        return None
    
    def _get_current_date(self) -> str:
        """Get current date string."""
        from datetime import datetime
        return f"Today's date is {datetime.now().isoformat()}."
    
    # -----------------------------------------------------------------------
    # Formatting
    # -----------------------------------------------------------------------
    
    def format_context_for_prompt(self, context: dict[str, str]) -> str:
        """Format context dictionary into prompt section."""
        if not context:
            return ""
        
        lines = ["## Current Context", ""]
        
        if "git_status" in context:
            lines.extend([
                "### Git Status",
                "```",
                context["git_status"],
                "```",
                "",
            ])
        
        if "claude_md" in context:
            lines.extend([
                "### Project Instructions (CLAUDE.md)",
                "",
                context["claude_md"],
                "",
            ])
        
        if "current_date" in context:
            lines.append(context["current_date"])
        
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_collector: AsyncContextCollector | None = None


def get_collector(cwd: str) -> AsyncContextCollector:
    """Get or create global collector."""
    global _collector
    if _collector is None or _collector.cwd != Path(cwd):
        _collector = AsyncContextCollector(cwd)
    return _collector


async def collect_context(cwd: str) -> dict[str, str]:
    """Collect full context for cwd."""
    return await get_collector(cwd).get_full_context()


def invalidate_context(pattern: str | None = None) -> None:
    """Invalidate context cache."""
    if _collector:
        _collector.invalidate(pattern)
