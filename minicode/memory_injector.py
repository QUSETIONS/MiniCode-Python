from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from minicode.memory import MemoryManager, MemoryScope, MemoryEntry
from minicode.logging_config import get_logger

logger = get_logger("memory_injector")


@dataclass
class InjectedMemory:
    """A memory entry prepared for injection into context."""
    content: str
    category: str
    relevance_score: float
    source: str  # "search", "tag", "category"


class MemoryInjector:
    """Injects relevant memories into agent context based on task content."""

    def __init__(
        self,
        memory_manager: MemoryManager | None = None,
        max_injected_memories: int = 5,
        min_relevance: float = 0.3,
        max_tokens_per_memory: int = 200,
    ):
        self._memory = memory_manager
        self._max_injected = max_injected_memories
        self._min_relevance = min_relevance
        self._max_tokens = max_tokens_per_memory
        self._last_query: str = ""
        self._last_injection_time: float = 0.0
        self._injection_cooldown: float = 30.0  # Seconds between injections

    def inject_for_task(
        self,
        task_description: str,
        current_files: list[str] | None = None,
    ) -> list[InjectedMemory]:
        """Search and prepare relevant memories for a task.

        Args:
            task_description: Description of the current task
            current_files: List of files currently being worked on

        Returns:
            List of injected memories sorted by relevance
        """
        if self._memory is None:
            return []

        # Cooldown check - don't inject too frequently
        if time.time() - self._last_injection_time < self._injection_cooldown:
            if task_description == self._last_query:
                return []  # Same query, skip

        self._last_query = task_description
        self._last_injection_time = time.time()

        memories: list[tuple[float, MemoryEntry, str]] = []

        # Search across all scopes
        for scope in MemoryScope:
            results = self._memory.search(
                task_description,
                scope=scope,
                limit=self._max_injected * 2,
                min_relevance=self._min_relevance,
            )
            for entry in results:
                # Calculate composite relevance
                relevance = self._calculate_relevance(entry, task_description, current_files)
                memories.append((relevance, entry, scope.value))

        # Sort by relevance and take top N
        memories.sort(key=lambda x: x[0], reverse=True)

        injected: list[InjectedMemory] = []
        seen_content: set[str] = set()

        for relevance, entry, scope_name in memories[:self._max_injected]:
            content = entry.content[:self._max_tokens * 4]  # Rough char limit
            content_key = content[:100].lower()

            if content_key in seen_content:
                continue
            seen_content.add(content_key)

            injected.append(InjectedMemory(
                content=content,
                category=entry.category,
                relevance_score=relevance,
                source=f"{scope_name}_search",
            ))

        # Also search by tags if task has code-related keywords
        tag_memories = self._inject_by_tags(task_description)
        for mem in tag_memories:
            content_key = mem.content[:100].lower()
            if content_key not in seen_content and len(injected) < self._max_injected:
                seen_content.add(content_key)
                injected.append(mem)

        logger.info(
            "Injected %d memories for task: %s",
            len(injected),
            task_description[:50],
        )

        return injected

    def inject_on_failure(
        self,
        error_message: str,
        tool_name: str,
    ) -> list[InjectedMemory]:
        """Search for similar past failures and solutions.

        Args:
            error_message: The error message from the failed tool
            tool_name: Name of the tool that failed

        Returns:
            List of relevant memories that might contain solutions
        """
        if self._memory is None:
            return []

        # Search for memories related to this error and tool
        query = f"{tool_name} {error_message[:100]}"

        memories: list[tuple[float, MemoryEntry, str]] = []

        for scope in MemoryScope:
            results = self._memory.search(
                query,
                scope=scope,
                limit=self._max_injected,
                min_relevance=0.2,  # Lower threshold for failure recovery
            )
            for entry in results:
                # Boost memories in "testing" or "decision" categories
                relevance = 0.5  # Base relevance for failure context
                if entry.category in ["testing", "decision", "code-pattern"]:
                    relevance += 0.2
                if tool_name in entry.content.lower():
                    relevance += 0.15
                memories.append((relevance, entry, scope.value))

        memories.sort(key=lambda x: x[0], reverse=True)

        injected: list[InjectedMemory] = []
        for relevance, entry, scope_name in memories[:self._max_injected]:
            injected.append(InjectedMemory(
                content=entry.content[:self._max_tokens * 4],
                category=entry.category,
                relevance_score=relevance,
                source=f"{scope_name}_failure_recovery",
            ))

        if injected:
            logger.info(
                "Injected %d recovery memories for %s failure",
                len(injected),
                tool_name,
            )

        return injected

    def format_for_prompt(self, memories: list[InjectedMemory]) -> str:
        """Format injected memories for inclusion in system prompt.

        Args:
            memories: List of memories to format

        Returns:
            Formatted string for prompt injection
        """
        if not memories:
            return ""

        lines = ["## Relevant Context from Memory", ""]

        for i, mem in enumerate(memories, 1):
            lines.append(f"{i}. [{mem.category}] {mem.content}")

        lines.append("")
        lines.append("Use the above context to inform your decisions.")

        return "\n".join(lines)

    def _calculate_relevance(
        self,
        entry: MemoryEntry,
        task_description: str,
        current_files: list[str] | None,
    ) -> float:
        """Calculate composite relevance score for a memory entry."""
        score = 0.5  # Base score

        # Boost if memory category matches task type
        task_lower = task_description.lower()
        if entry.category == "architecture" and any(kw in task_lower for kw in ["design", "structure", "api"]):
            score += 0.2
        elif entry.category == "testing" and any(kw in task_lower for kw in ["test", "assert", "verify"]):
            score += 0.2
        elif entry.category == "convention" and any(kw in task_lower for kw in ["style", "naming", "format"]):
            score += 0.2

        # Boost if memory mentions current files
        if current_files:
            entry_lower = entry.content.lower()
            for file_path in current_files:
                file_name = file_path.split("/")[-1].split("\\")[-1]
                if file_name.lower() in entry_lower:
                    score += 0.15

        # Boost recent memories
        age_hours = (time.time() - entry.updated_at) / 3600
        if age_hours < 24:
            score += 0.1
        elif age_hours < 168:  # 1 week
            score += 0.05

        return min(1.0, score)

    def _inject_by_tags(self, task_description: str) -> list[InjectedMemory]:
        """Find memories by matching tags to task keywords."""
        if self._memory is None:
            return []

        # Extract potential tags from task description
        task_lower = task_description.lower()
        keywords = []

        # Common code-related keywords
        code_keywords = [
            "api", "test", "function", "class", "database", "config",
            "security", "performance", "git", "docker", "deploy",
        ]
        for kw in code_keywords:
            if kw in task_lower:
                keywords.append(kw)

        memories: list[InjectedMemory] = []
        seen: set[str] = set()

        for keyword in keywords[:3]:  # Limit to top 3 keywords
            for scope in MemoryScope:
                tagged = self._memory.search_by_tag(scope, keyword)
                for entry in tagged:
                    content_key = entry.content[:100].lower()
                    if content_key not in seen:
                        seen.add(content_key)
                        memories.append(InjectedMemory(
                            content=entry.content[:self._max_tokens * 4],
                            category=entry.category,
                            relevance_score=0.6,  # Tag matches are fairly relevant
                            source=f"{scope.value}_tag",
                        ))

        return memories[:self._max_injected]
