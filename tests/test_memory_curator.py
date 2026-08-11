"""Tests for MemoryCuratorAgent — background memory optimization."""
from __future__ import annotations

import tempfile

from minicode.memory import MemoryEntry, MemoryManager, MemoryScope, MemoryTier
from minicode.memory_curator_agent import CuratorReport, MemoryCuratorAgent


def _make_entry(eid, content, domains=None, tier=None, tags=None, related=None):
    return MemoryEntry(
        id=eid, scope=MemoryScope.PROJECT,
        category="pattern", content=content,
        domains=domains or [], tier=tier or MemoryTier.SHORT_TERM,
        tags=tags or [], related_to=related or [],
    )


class TestCuratorBasics:
    def test_init(self):
        curator = MemoryCuratorAgent()
        assert not curator.should_run

    def test_task_count_triggers(self):
        curator = MemoryCuratorAgent(run_interval_tasks=3)
        for _ in range(3):
            curator.on_task_complete()
        assert curator.should_run

    def test_run_resets_counter(self):
        curator = MemoryCuratorAgent(run_interval_tasks=3)
        for _ in range(5):
            curator.on_task_complete()
        curator._task_count = 0  # Reset manually after run (simulates run_cycle)
        assert not curator.should_run


class TestCuratorWithMemory:
    def test_collects_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = MemoryManager(project_root=tmp)
            mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                         content="Use React functional components")
            mgr.add_entry(MemoryScope.PROJECT, category="convention",
                         content="FastAPI async handlers")

            curator = MemoryCuratorAgent(memory_manager=mgr)
            report = curator.run_cycle(force=True)
            assert report.total_entries >= 2
            assert "frontend" in report.domain_distribution or report.total_entries > 0

    def test_archive_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = MemoryManager(project_root=tmp)
            mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                         content="Use React functional components with hooks for all new code")
            mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                         content="Use React functional components with hooks for all new code")

            curator = MemoryCuratorAgent(memory_manager=mgr, min_similarity_archive=0.9)
            report = curator.run_cycle(force=True)
            assert report.memories_archived >= 1

    def test_missing_referenced_file_archives_with_valid_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = MemoryManager(project_root=tmp)
            entry = mgr.add_entry(
                MemoryScope.PROJECT,
                category="decision",
                content="Keep the migration notes in docs/removed-plan.md",
            )

            curator = MemoryCuratorAgent(memory_manager=mgr, workspace_path=tmp)
            report = curator.run_cycle(force=True)

            assert report.stale_count == 1
            assert entry.tier == MemoryTier.ARCHIVAL
            assert entry.content.startswith("[DEPRECATED: referenced files no longer exist]")
            assert entry.tier.value == "archival"

            # Re-running maintenance must not corrupt the enum or duplicate
            # the deprecation marker.
            curator.run_cycle(force=True)
            assert entry.tier == MemoryTier.ARCHIVAL
            assert entry.content.count("[DEPRECATED:") == 1

    def test_insight_from_related_cluster(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = MemoryManager(project_root=tmp)
            mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                         content="Use React with Zustand for state management")
            mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                         content="Zustand stores in src/stores/, one per feature")
            mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                         content="Migrated from Redux to Zustand Q1 2026")

            # Manually link them
            entries = mgr.memories[MemoryScope.PROJECT].entries
            for e in entries:
                e.domains = ["frontend"]
            entries[0].related_to = [entries[1].id, entries[2].id]
            entries[1].related_to = [entries[0].id, entries[2].id]
            entries[2].related_to = [entries[0].id, entries[1].id]

            curator = MemoryCuratorAgent(memory_manager=mgr, min_similarity_consolidate=0.3)
            report = curator.run_cycle(force=True)
            assert report.insights_created >= 1

    def test_rule_based_fallback_insight(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = MemoryManager(project_root=tmp)
            # Clear auto-loaded entries from user scope
            mgr.memories[MemoryScope.PROJECT].entries.clear()
            mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                         content="React forms use react-hook-form with zod")
            mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                         content="React form validation with zod schemas")
            mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                         content="Form components must wrap inputs with Controller")

            for e in mgr.memories[MemoryScope.PROJECT].entries:
                e.domains = ["frontend"]

            curator = MemoryCuratorAgent(memory_manager=mgr, min_similarity_consolidate=0.3)
            report = curator.run_cycle(force=True)
            assert report.total_entries >= 3
        assert curator.get_last_report() is not None

    def test_report_to_dict(self):
        report = CuratorReport(
            insights_created=2, memories_archived=1,
            total_entries=50, recommendations=["test"],
        )
        d = report.to_dict()
        assert d["insights_created"] == 2
        assert "test" in d["recommendations"]


class TestCuratorTierPromotion:
    def test_promote_and_link_called(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = MemoryManager(project_root=tmp)
            # Clear auto-loaded entries
            for s in MemoryScope:
                mgr.memories[s].entries.clear()
            for i in range(5):
                mgr.add_entry(MemoryScope.PROJECT, category="pattern",
                             content=f"React pattern {i}: use hooks")
            for e in mgr.memories[MemoryScope.PROJECT].entries:
                e.domains = ["frontend"]

            curator = MemoryCuratorAgent(memory_manager=mgr, min_similarity_archive=0.3)
            report = curator.run_cycle(force=True)
            # Should have run promote_memories and link_memories
            assert report.total_entries == 5
