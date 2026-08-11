"""Background Memory Curator Agent — proactive memory optimization.

Unlike the reactive MemoryReranker (runs at query time), the Curator runs
during idle periods to:

1. CONSOLIDATE: Merge 3-5 related memories into a synthetic "insight"
2. VALIDATE: Cross-reference memories against codebase for staleness
3. CLEAN: Archive near-duplicate memories (Jaccard > 0.9)
4. REPORT: Generate memory health metrics

Runs every N tasks or on explicit trigger. Uses lightweight LLM (Haiku) for
consolidation, rule-based methods for validation and cleaning.

Architecture:
  CyberneticOrchestrator
    └── MemoryCuratorAgent
          ├── MemoryManager (read/write)
          ├── LLM adapter (for consolidate)
          └── Workspace access (for validate)
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from minicode.logging_config import get_logger

logger = get_logger("memory_curator")


# ── Data types ─────────────────────────────────────────────────────

@dataclass
class CuratorReport:
    """Output of a curation cycle."""
    insights_created: int = 0
    memories_archived: int = 0
    memories_validated: int = 0
    stale_count: int = 0
    total_entries: int = 0
    tier_distribution: dict[str, int] = field(default_factory=dict)
    domain_distribution: dict[str, int] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "insights_created": self.insights_created,
            "memories_archived": self.memories_archived,
            "memories_validated": self.memories_validated,
            "stale_count": self.stale_count,
            "total_entries": self.total_entries,
            "tier_distribution": self.tier_distribution,
            "domain_distribution": self.domain_distribution,
            "recommendations": self.recommendations,
            "duration_ms": round(self.duration_ms, 1),
        }


# ── Consolidation prompt ───────────────────────────────────────────

CONSOLIDATE_PROMPT = """Synthesize a concise insight from these related project memories:

{memory_texts}

Create a SINGLE insight sentence that captures the common pattern, rule, or knowledge across these memories. The insight should be specific enough to guide an AI agent.

Format: Return just the insight sentence, nothing else."""


# ── Curator Agent ───────────────────────────────────────────────────

class MemoryCuratorAgent:
    """Background agent that proactively optimizes the memory store.

    Usage:
        curator = MemoryCuratorAgent(memory_mgr, model_adapter, workspace_path)
        report = curator.run_cycle()  # Call during idle or every N tasks
    """

    def __init__(
        self,
        memory_manager: Any | None = None,
        model_adapter: Any | None = None,
        workspace_path: str | None = None,
        min_similarity_consolidate: float = 0.6,
        min_similarity_archive: float = 0.9,
        max_insights_per_cycle: int = 3,
        run_interval_tasks: int = 10,
    ):
        self._memory = memory_manager
        self._model = model_adapter
        self._workspace = workspace_path
        self._min_sim_consolidate = min_similarity_consolidate
        self._min_sim_archive = min_similarity_archive
        self._max_insights = max_insights_per_cycle
        self._run_interval = run_interval_tasks

        self._task_count = 0
        self._last_run: float = 0.0
        self._report_history: list[CuratorReport] = []

    @property
    def should_run(self) -> bool:
        """Check if curator should run based on task count."""
        return self._task_count >= self._run_interval

    def on_task_complete(self) -> None:
        """Notify curator that a task completed. Increments counter."""
        self._task_count += 1

    def run_cycle(self, force: bool = False) -> CuratorReport:
        """Execute a full curation cycle.

        Args:
            force: If True, run even if task threshold not met.

        Returns:
            CuratorReport with cycle metrics.
        """
        if not force and not self.should_run:
            return CuratorReport()

        if self._memory is None:
            return CuratorReport()

        start = time.time()
        report = CuratorReport()
        self._task_count = 0

        # 1. Collect stats
        report = self._collect_stats(report)

        # 2. Archive near-duplicates
        archived = self._archive_duplicates()
        report.memories_archived = archived

        # 3. Validate against codebase
        if self._workspace:
            stale, validated = self._validate_memories()
            report.stale_count = stale
            report.memories_validated = validated

        # 4. Consolidate related memories into insights
        insights = self._consolidate_insights()
        report.insights_created = insights

        # 5. Run tier promotion
        if hasattr(self._memory, 'promote_memories'):
            try:
                self._memory.promote_memories()
            except Exception:
                pass

        # 6. Run link creation
        if hasattr(self._memory, 'link_memories'):
            try:
                self._memory.link_memories()
            except Exception:
                pass

        report.duration_ms = (time.time() - start) * 1000
        report.timestamp = time.time()
        self._report_history.append(report)
        self._last_run = time.time()

        logger.info(
            "Curator: insights=%d archived=%d stale=%d total=%d %.0fms",
            report.insights_created, report.memories_archived,
            report.stale_count, report.total_entries, report.duration_ms,
        )
        return report

    # ── Stats collection ───────────────────────────────────────

    def _collect_stats(self, report: CuratorReport) -> CuratorReport:
        from minicode.memory import MemoryScope
        total = 0
        tiers: Counter[str] = Counter()
        domains: Counter[str] = Counter()

        for scope in MemoryScope:
            if scope not in self._memory.memories:
                continue
            for entry in self._memory.memories[scope].entries:
                total += 1
                tiers[entry.tier.value] += 1
                for d in entry.domains:
                    domains[d] += 1

        report.total_entries = total
        report.tier_distribution = dict(tiers)
        report.domain_distribution = dict(domains)

        if total > 0:
            recs = []
            archive_pct = tiers.get("archival", 0) / total
            if archive_pct > 0.5:
                recs.append(f"High archival ratio ({archive_pct:.0%}), consider purge")
            if len(domains) < 2:
                recs.append("Low domain diversity, consider broader knowledge capture")
            report.recommendations = recs

        return report

    # ── Duplicate archiving ─────────────────────────────────────

    def _archive_duplicates(self) -> int:
        from minicode.memory import MemoryScope, MemoryTier
        archived = 0
        for scope in MemoryScope:
            if scope not in self._memory.memories:
                continue
            entries = self._memory.memories[scope].entries
            to_archive: set[int] = set()
            for i, a in enumerate(entries):
                if i in to_archive:
                    continue
                for j, b in enumerate(entries):
                    if i >= j or j in to_archive:
                        continue
                    if self._memory._jaccard_similarity(a.content, b.content) >= self._min_sim_archive:
                        # Archive the older/shorter one
                        if len(a.content) >= len(b.content):
                            to_archive.add(j)
                        else:
                            to_archive.add(i)

            for idx in sorted(to_archive, reverse=True):
                entries[idx].tier = MemoryTier.ARCHIVAL
                archived += 1

        return archived

    # ── Codebase validation ────────────────────────────────────

    def _validate_memories(self) -> tuple[int, int]:
        """Check if memory-referenced files/patterns still exist in workspace."""
        if not self._workspace:
            return 0, 0

        import os
        from minicode.memory import MemoryScope, MemoryTier

        stale = 0
        validated = 0

        for scope in MemoryScope:
            if scope not in self._memory.memories:
                continue
            for entry in self._memory.memories[scope].entries:
                # Extract potential file paths from content
                words = entry.content.split()
                paths = [w.strip(".,;:()[]{}'\"") for w in words
                        if ("/" in w or "\\" in w) and "." in w and len(w) > 3]
                if not paths:
                    continue
                validated += 1
                # Check if referenced files still exist
                all_missing = True
                for p in paths[:3]:
                    full = os.path.join(self._workspace, p.lstrip("/\\"))
                    if os.path.exists(full):
                        all_missing = False
                        break
                if all_missing and paths:
                    stale += 1
                    if entry.tier != MemoryTier.ARCHIVAL:
                        entry.tier = MemoryTier.ARCHIVAL
                        # Keep the marker idempotent so repeated maintenance
                        # cycles do not grow the content indefinitely.
                        marker = "[DEPRECATED: referenced files no longer exist] "
                        if not entry.content.startswith(marker):
                            entry.content = marker + entry.content[:100]
                            entry.invalidate_tokens()

                # Curator validation can mutate content, so refresh the
                # MemoryFile indexes before later maintenance stages use them.
            self._memory.memories[scope]._rebuild_indices()

        return stale, validated

    # ── Insight consolidation ──────────────────────────────────

    def _consolidate_insights(self) -> int:
        """Find related memory clusters and synthesize insights via LLM."""
        from minicode.memory import MemoryScope

        created = 0
        for scope in MemoryScope:
            if scope not in self._memory.memories or created >= self._max_insights:
                break
            entries = self._memory.memories[scope].entries
            clusters = self._find_clusters(entries)
            for cluster in clusters[:self._max_insights - created]:
                insight = self._synthesize_insight(cluster)
                if insight:
                    from minicode.memory import MemoryEntry, MemoryTier
                    import hashlib
                    eid = "insight-" + hashlib.md5(
                        insight.encode(), usedforsecurity=False
                    ).hexdigest()[:8]
                    entry = MemoryEntry(
                        id=eid, scope=scope,
                        category="insight",
                        content=insight,
                        tier=MemoryTier.LONG_TERM,
                        domains=list(set(d for e in cluster for d in e.domains)),
                        related_to=[e.id for e in cluster],
                        tags=["curator-insight"],
                    )
                    self._memory.memories[scope].add_entry(entry)
                    created += 1

        return created

    def _find_clusters(self, entries: list) -> list[list]:
        """Find clusters of related memories using related_to + Jaccard."""
        if len(entries) < 3:
            return []

        # Use existing related_to links as seeds
        clusters: list[set[int]] = []
        seen: set[int] = set()

        for i, entry in enumerate(entries):
            if i in seen or not entry.related_to:
                continue
            cluster: set[int] = {i}
            frontier = [i]
            while frontier:
                cur = frontier.pop()
                for rid in entries[cur].related_to:
                    for j, e in enumerate(entries):
                        if e.id == rid and j not in cluster:
                            cluster.add(j)
                            frontier.append(j)
            if len(cluster) >= 3:
                clusters.append(cluster)
                seen |= cluster

        # Fallback: Jaccard-based clustering for unlinked entries
        for i, entry in enumerate(entries):
            if i in seen:
                continue
            cluster = {i}
            for j, other in enumerate(entries):
                if i == j or j in seen:
                    continue
                sim = self._memory._jaccard_similarity(entry.content, other.content)
                if sim >= self._min_sim_consolidate:
                    cluster.add(j)
            if len(cluster) >= 3:
                clusters.append(cluster)
                seen |= cluster

        return [[entries[i] for i in c] for c in clusters[:5]]

    def _synthesize_insight(self, cluster: list) -> str | None:
        """Call LLM to synthesize an insight from a memory cluster."""
        texts = "\n".join(
            f"- [{e.id}] {e.content[:150]}" for e in cluster[:5]
        )
        prompt = CONSOLIDATE_PROMPT.format(memory_texts=texts)

        try:
            if self._model and hasattr(self._model, 'generate'):
                raw = self._model.generate(prompt)
                if isinstance(raw, dict):
                    result = raw.get("content", "") or raw.get("text", "")
                else:
                    result = str(raw)
                result = result.strip()
                if 30 < len(result) < 500:
                    return result
            elif self._model and hasattr(self._model, 'next'):
                msgs = [{"role": "user", "content": prompt}]
                step = self._model.next(msgs)
                result = getattr(step, 'content', '') or ""
                result = result.strip()
                if 30 < len(result) < 500:
                    return result
        except Exception as e:
            logger.debug("Curator insight synthesis failed: %s", e)

        # Rule-based fallback
        domains = set(d for e in cluster for d in e.domains)
        common_words = self._extract_common_words([e.content for e in cluster])
        if common_words:
            return (
                f"[Auto] Memories in {', '.join(domains) or 'general'} share patterns: "
                f"{', '.join(common_words[:5])}. "
                f"({len(cluster)} related entries)"
            )
        return None

    @staticmethod
    def _extract_common_words(contents: list[str], min_len: int = 3) -> list[str]:
        """Extract common significant words across multiple texts."""
        from collections import Counter
        word_sets = []
        for c in contents:
            words = {w.lower().strip(".,;:()[]{}'\"") for w in c.split()
                    if len(w) > min_len and not w.startswith("http")}
            word_sets.append(words)
        if not word_sets:
            return []
        common = word_sets[0]
        for ws in word_sets[1:]:
            common = common & ws
        freq = Counter()
        for c in contents:
            freq.update(w.lower().strip(".,;:()[]{}'\"") for w in c.split()
                       if len(w) > min_len and w.lower().strip(".,;:()[]{}'\"") in common)
        return [w for w, _ in freq.most_common(10)]

    # ── Public API ─────────────────────────────────────────────

    def get_history(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._report_history[-10:]]

    def get_last_report(self) -> CuratorReport | None:
        return self._report_history[-1] if self._report_history else None
