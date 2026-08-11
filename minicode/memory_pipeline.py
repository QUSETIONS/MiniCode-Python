"""Memory Pipeline — unified facade for the complete memory lifecycle.

Design principle: ONE class, FOUR methods. All memory operations flow
through this single entry point. No scattered ad-hoc calls.

Architecture:
  MemoryPipeline
    ├── read(task, files) → DomainClassifier → BM25 → Reranker → [memories]
    ├── inject(task, files, messages) → read + append to system prompt
    ├── write(task, trace) → ReflectionEngine → TaskContext → MemoryManager
    └── maintain() → CuratorAgent → consolidate/validate/promote/link

Sub-components (internal, not exposed):
  - DomainClassifier: auto-detects active domains from files/intent
  - MemoryReranker: LLM curation of BM25 results
  - MemoryInjector: PID-controlled injection into prompt
  - MemoryCuratorAgent: background optimization during idle
  - VectorMemoryStore: optional parallel semantic search
"""
from __future__ import annotations

from copy import deepcopy
import time
from pathlib import Path
from typing import Any

from minicode.logging_config import get_logger

logger = get_logger("memory_pipeline")


class MemoryPipeline:
    """Unified memory operations facade.

    Usage:
        pipeline = MemoryPipeline(memory_manager)
        pipeline.initialize(model_adapter, workspace_path)

        # On task start
        memories = pipeline.read("Create login form", ["src/Login.tsx"])
        messages = pipeline.inject("Create login form", ["src/Login.tsx"], messages)

        # On task end
        pipeline.write("Create login form", execution_trace)

        # Background (every ~10 tasks)
        report = pipeline.maintain()
    """

    def __init__(self, memory_manager: Any | None = None):
        self._memory = memory_manager
        self._model: Any = None
        self._workspace: str | None = None

        # Subsystems (lazy init via initialize())
        self._reranker: Any = None
        self._injector: Any = None
        self._curator: Any = None
        self._reflection: Any = None
        self._vector_store: Any = None
        self._dense_store: Any = None
        self._graph_store: Any = None
        self._defer_graph_consolidation = False
        self._domain_classifier_loaded = False

        self._initialized = False
        self._read_count = 0
        self._write_count = 0
        self._maintain_count = 0
        # Read-only diagnostic sidecar for the most recent graph retrieval.
        # It deliberately keeps only routing decisions, memory IDs, and ranks
        # (not the raw query or memory content) so a caller can audit a state
        # transition re-rank without changing the retrieval result contract.
        self._last_graph_trace: dict[str, Any] | None = None

    # ── Lifecycle ──────────────────────────────────────────────────

    def initialize(
        self,
        model_adapter: Any | None = None,
        workspace_path: str | None = None,
        enable_reranker: bool = True,
        enable_vector: bool = False,
        enable_graph: bool = False,
        defer_graph_consolidation: bool = False,
    ) -> None:
        """Initialize all subsystems. Call once after MemoryManager is ready.

        The graph layer is dependency-free and remains a no-op until it has
        facts or edges.  It is opt-in because the lexical path is the
        validated default while graph construction remains experimental.
        """
        self._model = model_adapter
        self._workspace = workspace_path
        self._defer_graph_consolidation = bool(defer_graph_consolidation)

        # Reranker (LLM curation on read)
        if enable_reranker:
            from minicode.memory_reranker import MemoryReranker
            self._reranker = MemoryReranker(model_adapter=model_adapter)

        # Injector (PID-controlled injection)
        if self._memory:
            from minicode.memory_injector import MemoryInjector
            self._injector = MemoryInjector(
                memory_manager=self._memory,
                reranker=self._reranker if self._reranker and self._reranker.enabled else None,
            )

        # Curator (background optimization)
        from minicode.memory_curator_agent import MemoryCuratorAgent
        self._curator = MemoryCuratorAgent(
            memory_manager=self._memory,
            model_adapter=model_adapter,
            workspace_path=workspace_path,
        )

        # Reflection engine (write path)
        from minicode.agent_reflection import ReflectionEngine
        self._reflection = ReflectionEngine(memory_manager=self._memory)

        # Vector store — sparse TF-IDF always available, optional sentence-transformers
        if enable_vector:
            try:
                from minicode.vector_memory import SparseVectorStore, VectorMemoryStore
                self._vector_store = SparseVectorStore()  # Zero-dependency, always works
                # Also try the optional dense backend
                self._dense_store = VectorMemoryStore()
                if self._memory:
                    all_entries = []
                    from minicode.memory import MemoryScope
                    for scope in MemoryScope:
                        if scope in self._memory.memories:
                            all_entries.extend(self._memory.memories[scope].entries)
                    if all_entries:
                        n = self._vector_store.index_entries(all_entries)
                        logger.info("SparseVectorStore: indexed %d entries", n)
                        if self._dense_store.enabled:
                            self._dense_store.index_entries(all_entries)
            except Exception:
                pass

        # HippoRAG-lite graph retrieval.  Keep this sidecar independent from
        # memory.json so old memory files remain readable and graph failures
        # can always fall back to the established lexical/vector path.
        if enable_graph and self._memory:
            try:
                from minicode.memory_graph import MemoryGraphStore

                graph_path = self._graph_path(workspace_path)
                self._graph_store = MemoryGraphStore(storage_path=graph_path)
                self._refresh_graph()
            except Exception as exc:
                logger.debug("MemoryPipeline graph initialization failed: %s", exc)
                self._graph_store = None

        self._initialized = True
        logger.info(
            "MemoryPipeline initialized: reranker=%s vector=%s",
            self._reranker.enabled if self._reranker else False,
            self._vector_store is not None and self._vector_store.enabled if self._vector_store else False,
        )

        # Restore persisted state
        self._load_state()

    # ── State persistence ────────────────────────────────────────────

    def _state_path(self) -> str | None:
        """Path for pipeline state file."""
        if not self._workspace:
            return None
        import os
        return os.path.join(self._workspace, ".mini-code-memory", "pipeline_state.json")

    def save_state(self) -> None:
        """Persist pipeline state to disk (cache stats, counters, curator history)."""
        path = self._state_path()
        if not path:
            return
        try:
            import json
            import os
            os.makedirs(os.path.dirname(path), exist_ok=True)
            state = {
                "read_count": self._read_count,
                "write_count": self._write_count,
                "maintain_count": self._maintain_count,
                "reranker_cache_hits": self._reranker._cache_hits if self._reranker else 0,
                "reranker_call_count": self._reranker._call_count if self._reranker else 0,
                "curator_history": self._curator.get_history() if self._curator else [],
                "timestamp": time.time(),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.debug("MemoryPipeline save_state failed: %s", e)

    def _load_state(self) -> None:
        """Restore pipeline state from disk."""
        path = self._state_path()
        if not path:
            return
        try:
            import json
            import os
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self._read_count = state.get("read_count", 0)
            self._write_count = state.get("write_count", 0)
            self._maintain_count = state.get("maintain_count", 0)
            if self._reranker:
                self._reranker._cache_hits = state.get("reranker_cache_hits", 0)
                self._reranker._call_count = state.get("reranker_call_count", 0)
            logger.debug("MemoryPipeline: restored state (%d reads, %d writes)",
                        self._read_count, self._write_count)
        except Exception as e:
            logger.debug("MemoryPipeline _load_state failed: %s", e)

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "read_count": self._read_count,
            "write_count": self._write_count,
            "maintain_count": self._maintain_count,
            "reranker_enabled": self._reranker.enabled if self._reranker else False,
            "reranker_cache_hit_rate": self._reranker.cache_hit_rate if self._reranker else 0.0,
            "vector_enabled": self._vector_store is not None and self._vector_store.enabled if self._vector_store else False,
            "graph_enabled": self._graph_store is not None and self._graph_store.enabled if self._graph_store else False,
            "graph_facts": self._graph_store.fact_count if self._graph_store else 0,
            "graph_edges": self._graph_store.edge_count if self._graph_store else 0,
            "graph_pending_facts": (
                self._graph_store.stats().get("pending_facts", 0)
                if self._graph_store
                else 0
            ),
            "graph_deferred_consolidation": self._defer_graph_consolidation,
        }

    @property
    def graph_store(self) -> Any:
        """Expose the optional graph store for diagnostics and experiments."""

        return self._graph_store

    @property
    def last_graph_trace(self) -> dict[str, Any] | None:
        """Return an isolated audit record for the most recent ``read`` call.

        The trace is intentionally ephemeral rather than persisted.  In
        particular, ``state_path`` distinguishes a request that merely asks
        about time from one where a directly evidenced ``supersedes`` path was
        eligible and actually selected for the narrow state re-rank.
        """

        return deepcopy(self._last_graph_trace)

    def _graph_path(self, workspace_path: str | None = None) -> Path | None:
        """Return the project-local graph sidecar path when available."""

        workspace = workspace_path or getattr(self._memory, "workspace", None) or self._workspace
        if not workspace:
            return None
        return Path(workspace) / ".mini-code-memory" / "memory_graph.json"

    def _all_memory_entries(self) -> list[Any]:
        if not self._memory:
            return []
        entries: list[Any] = []
        try:
            for memory_file in self._memory.memories.values():
                entries.extend(memory_file.entries)
        except (AttributeError, TypeError):
            return []
        return entries

    def _refresh_graph(self) -> None:
        """Synchronize generic facts for entries created outside the pipeline."""

        if not self._graph_store:
            return
        try:
            self._graph_store.sync_entries(self._all_memory_entries())
        except Exception as exc:
            logger.debug("MemoryPipeline graph refresh failed: %s", exc)

    def consolidate_graph(self, max_memories: int | None = None) -> int:
        """Flush deferred graph linking without changing the memory files."""

        if not self._graph_store:
            return 0
        try:
            linked = self._graph_store.consolidate_pending(
                max_memories=max_memories,
                persist=True,
            )
            self.save_state()
            return linked
        except Exception as exc:
            logger.debug("MemoryPipeline graph consolidation failed: %s", exc)
            return 0

    # ── READ: Memory retrieval ─────────────────────────────────────

    def read(
        self,
        task_description: str,
        current_files: list[str] | None = None,
        active_domains: list[str] | None = None,
        max_results: int = 15,
        as_of: float | None = None,
        record_usage: bool = True,
    ) -> list[dict[str, Any]]:
        """Full retrieval pipeline: classify domains → BM25 → optional reranker.

        ``as_of`` is an optional point-in-time for graph-backed temporal
        retrieval.  ``record_usage=False`` exposes a stable, read-only ranking
        for evaluation and previews.  When omitted, graph facts are evaluated
        at the current time and normal retrieval feedback remains enabled.

        Returns list of {id, content, domain, relevance, source}.
        """
        graph_policy = self._graph_query_policy(task_description)
        graph_trace = self._new_graph_trace(graph_policy)
        if not self._memory:
            graph_trace["outcome"] = "memory_unavailable"
            self._last_graph_trace = graph_trace
            return []

        self._read_count += 1
        self._refresh_graph()

        # 1. Derive active domains if not provided
        if not active_domains and current_files:
            active_domains = self._get_active_domains(current_files, task_description)

        # 2. Search with query reformulation fallback (T2)
        entries = self._try_search_with_reformulation(
            task_description,
            active_domains,
            max_results,
            record_usage=record_usage,
        )

        # 2b. Parallel vector search + RRF fusion (F1)
        if self._vector_store and self._vector_store.enabled:
            try:
                vec_results = self._vector_store.search(
                    task_description, top_k=max_results,
                )
                if vec_results:
                    from minicode.vector_memory import merge_bm25_vector
                    entries = merge_bm25_vector(entries, vec_results)
            except Exception:
                pass

        # 2c. Conditional graph retrieval (HippoRAG-lite).  Graph search is
        # deliberately routed only for relational/temporal questions or when
        # lexical retrieval is sparse; ordinary queries keep the old ranking
        # path unchanged.
        graph_evidence: dict[str, Any] = {}
        graph_conflicts: dict[str, set[str]] = {}
        if self._graph_store and self._should_use_graph(task_description, entries):
            graph_trace["routed"] = True
            try:
                graph_hits = self._graph_store.search(
                    task_description,
                    limit=max(10, max_results * 2),
                    max_hops=graph_policy["max_hops"],
                    as_of=as_of,
                    relation_weights=graph_policy["relation_weights"],
                    seed_limit=graph_policy["seed_limit"],
                    supersedes_preference=graph_policy["supersedes_preference"],
                )
                graph_trace["outcome"] = "searched"
                graph_trace["graph_hit_count"] = len(graph_hits)
                if as_of is not None:
                    # A point-in-time query must also suppress lexical hits
                    # whose graph facts are known but invalid at that point.
                    # Otherwise graph retrieval would find the current fact
                    # while the legacy BM25 candidate could still reintroduce
                    # a superseded decision into the final list.
                    valid_memory_ids = self._graph_store.valid_memory_ids(
                        as_of=as_of,
                    )
                    tracked_memory_ids = self._graph_store.tracked_memory_ids
                    entries = [
                        entry
                        for entry in entries
                        if entry.id not in tracked_memory_ids
                        or entry.id in valid_memory_ids
                    ]
                if (
                    self._is_decision_query(task_description)
                    and graph_policy["supersedes_preference"] != "older"
                ):
                    superseded_memory_ids = self._graph_store.superseded_memory_ids(
                        {"decision", "choice"},
                        as_of=as_of,
                    )
                    if superseded_memory_ids:
                        entries = [
                            entry
                            for entry in entries
                            if entry.id not in superseded_memory_ids
                        ]
                        graph_hits = [
                            hit
                            for hit in graph_hits
                            if hit.memory_id not in superseded_memory_ids
                        ]
                baseline_ranks = self._ranked_memory_ids(entries)
                preferred_state_ids = [
                    str(hit.memory_id)
                    for hit in graph_hits
                    if (
                        graph_policy["supersedes_preference"] in {"newer", "older"}
                        and getattr(hit, "supersedes_preference", None)
                        == graph_policy["supersedes_preference"]
                    )
                ]
                for hit in graph_hits:
                    conflicts = self._graph_store.conflicting_memory_ids(
                        hit.memory_id,
                        as_of=as_of,
                    )
                    if conflicts:
                        graph_conflicts[hit.memory_id] = conflicts
                entries, graph_evidence = self._merge_graph_candidates(
                    entries,
                    graph_hits,
                    max_results=max_results,
                    prefer_graph=self._is_graph_shaped_query(task_description),
                    supersedes_preference=graph_policy["supersedes_preference"],
                )
                selected_state_ids = [
                    memory_id
                    for memory_id in preferred_state_ids
                    if memory_id in graph_evidence
                ]
                merged_ranks = self._ranked_memory_ids(entries)
                graph_trace["graph_evidence_count"] = len(graph_evidence)
                graph_trace["state_path"] = {
                    "eligible_memory_ids": preferred_state_ids,
                    "selected_memory_ids": selected_state_ids,
                    "baseline_ranks": {
                        memory_id: baseline_ranks[memory_id]
                        for memory_id in selected_state_ids
                        if memory_id in baseline_ranks
                    },
                    "merged_ranks": {
                        memory_id: merged_ranks[memory_id]
                        for memory_id in selected_state_ids
                        if memory_id in merged_ranks
                    },
                    "final_ranks": {},
                    "applied": bool(selected_state_ids),
                    "ranking_changed": any(
                        baseline_ranks.get(memory_id) != merged_ranks.get(memory_id)
                        for memory_id in selected_state_ids
                    ),
                }
            except Exception as exc:
                graph_trace["outcome"] = "failed"
                logger.debug("MemoryPipeline graph retrieval failed: %s", exc)
        elif self._graph_store and self._graph_store.enabled:
            graph_trace["outcome"] = "not_routed"

        # 3. Score entries with value function (T1)
        if self._reranker and self._reranker.enabled and len(entries) > 3:
            try:
                result = self._reranker.curate(
                    entries, task_description,
                    active_domains=active_domains,
                    current_files=current_files,
                )
                # Filter entries to selected IDs
                selected = set(result.selected_ids)
                entries = [e for e in entries if e.id in selected]
            except Exception:
                pass  # Fall through to BM25 results

        # 4. Spreading activation via related_to graph (T3)
        entries = self._spread_activation(entries)

        # 5. Format results
        results = []
        for e in entries[:max_results]:
            result = {
                "id": e.id,
                "content": e.content,
                "domain": getattr(e, 'domains', []),
                "relevance": getattr(e, 'usage_count', 0),
                "source": "memory_pipeline",
            }
            evidence = graph_evidence.get(e.id)
            if evidence:
                result.update(
                    {
                        "graph": True,
                        "graph_score": evidence.score,
                        "evidence": list(evidence.evidence),
                        "evidence_path": list(evidence.path),
                        "evidence_relations": list(evidence.relations),
                        "graph_intent": graph_policy["intent"],
                    }
                )
            conflicts = graph_conflicts.get(e.id)
            if conflicts:
                result["conflicts"] = sorted(conflicts)
            results.append(result)
        selected_state_ids = graph_trace["state_path"]["selected_memory_ids"]
        result_ranks = self._ranked_memory_ids(results)
        graph_trace["state_path"]["final_ranks"] = {
            memory_id: result_ranks[memory_id]
            for memory_id in selected_state_ids
            if memory_id in result_ranks
        }
        self._last_graph_trace = graph_trace
        return results

    # ── INJECT: Memory into prompt ──────────────────────────────────

    def inject(
        self,
        task_description: str,
        current_files: list[str] | None,
        messages: list[dict],
        context_usage: float = 0.5,
    ) -> list[dict]:
        """Read memories and inject into system prompt with adaptive cooldown.

        Adaptive cooldown (T1): τ_cool = τ_base × (1 - context_pressure).
        Returns modified messages with memory context appended to system message.
        """
        if not self._initialized or not self._memory:
            return messages

        # Adaptive cooldown check
        now = time.time()
        cooldown = self._adaptive_cooldown(context_usage)
        if hasattr(self, '_last_inject_time'):
            if now - self._last_inject_time < cooldown:
                return messages  # Still in cooldown
        self._last_inject_time = now

        try:
            # Use the injector for PID-controlled injection
            if self._injector:
                injected = self._injector.inject_for_task(
                    task_description,
                    current_files=current_files,
                )
                if injected:
                    memory_context = "\n## Relevant Project Memory\n" + "\n".join(
                        f"- {m.content[:200]}" for m in injected[:5]
                    )
                    for i, msg in enumerate(messages):
                        if msg.get("role") == "system":
                            messages[i] = {
                                **msg,
                                "content": msg["content"] + memory_context,
                            }
                            break
                    logger.info(
                        "MemoryPipeline: injected %d memories (mode=%s)",
                        len(injected),
                        self._injector._last_decision.mode.value if self._injector._last_decision else "?",
                    )
        except Exception:
            pass

        return messages

    # ── WRITE: Memory persistence ──────────────────────────────────

    def write(
        self,
        task_description: str,
        execution_trace: list[dict[str, Any]],
    ) -> str | None:
        """Write task reflection as structured memory.

        Uses ReflectionEngine to extract TaskContext with files, libraries,
        and domain tags. Returns the created memory entry ID or None.
        """
        if not self._reflection:
            return None

        self._write_count += 1

        try:
            # MemoryPipeline owns the single structured write.  ReflectionEngine
            # can still persist when used directly, but doing both here would
            # create duplicate memory entries and duplicate graph evidence.
            result = self._reflection.reflect(
                task_description,
                execution_trace,
                persist=False,
            )
            if result and result.confidence >= self._reflection.min_confidence:
                mem_data = result.to_memory_entry()
                from minicode.memory import MemoryScope
                entry = self._memory.add_entry(
                    scope=MemoryScope.PROJECT,
                    category=mem_data["category"],
                    content=mem_data["content"],
                    tags=mem_data["tags"],
                )
                # Post-add domain assignment
                if mem_data.get("domains"):
                    for scope in MemoryScope:
                        if scope in self._memory.memories:
                            for e in self._memory.memories[scope].entries:
                                if e.content == mem_data["content"]:
                                    e.domains = mem_data["domains"]
                                    break
                if self._graph_store:
                    self._graph_store.sync_entries(self._all_memory_entries(), persist=False)
                    self._graph_store.ingest_reflection(
                        memory_id=entry.id,
                        scope=entry.scope,
                        task_description=task_description,
                        metadata=mem_data.get("metadata", {}),
                        confidence=result.confidence,
                        execution_trace=execution_trace,
                        persist=False,
                        consolidate=not self._defer_graph_consolidation,
                    )
                    self._graph_store.save()
                logger.info(
                    "MemoryPipeline: wrote reflection success=%s confidence=%.2f",
                    result.success, result.confidence,
                )
                self.save_state()
                return getattr(entry, 'id', None)
        except Exception:
            pass

        self.save_state()
        return None

    # ── FEEDBACK: Close the quality loop (F2) ────────────────────────

    def feedback(
        self,
        task_success: bool,
        injected_memory_ids: list[str] | None = None,
    ) -> None:
        """Task outcome → memory utility. Closes the outermost learning loop.

        Success → boost injected memories (positive reinforcement).
        Failure → gentle decay (they may have misled the agent).
        """
        if not self._memory or not injected_memory_ids:
            return

        from minicode.memory import MemoryScope
        changed_scopes: set[MemoryScope] = set()
        for scope in MemoryScope:
            if scope not in self._memory.memories:
                continue
            for entry in self._memory.memories[scope].entries:
                if entry.id in injected_memory_ids:
                    if task_success:
                        entry.usage_count += 2
                    else:
                        entry.usage_count = max(0, entry.usage_count - 1)
                    entry.last_accessed = time.time()
                    changed_scopes.add(scope)

        # Feedback is part of the learning loop, so an in-memory-only update
        # would disappear on the next process restart and silently disable
        # utility-based ranking.  Persist only scopes that actually changed;
        # keep compatibility with lightweight test doubles that do not expose
        # the private scope writer.
        save_scope = getattr(self._memory, "_save_scope", None)
        if callable(save_scope):
            for scope in changed_scopes:
                try:
                    save_scope(scope)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "MemoryPipeline feedback persistence failed for %s: %s",
                        scope.value,
                        type(exc).__name__,
                    )
        if changed_scopes:
            self.save_state()

    # ── MAINTAIN: Background optimization ───────────────────────────

    def maintain(self, force: bool = False) -> dict[str, Any] | None:
        """Run background memory optimization.

        Consolidates insights, archives duplicates, validates against codebase,
        promotes/demotes tiers, and links related memories.

        Returns CuratorReport as dict, or None if not ready.
        """
        if not self._curator:
            return None

        self._curator.on_task_complete()

        if not force and not self._curator.should_run:
            return None

        self._maintain_count += 1
        try:
            # Flush the fast-path graph queue during the existing background
            # maintenance cycle, keeping online writes latency-bounded.
            self.consolidate_graph()
            report = self._curator.run_cycle(force=True)
            self.save_state()
            return report.to_dict()
        except Exception:
            return None

    # ── Internal ────────────────────────────────────────────────────

    _GRAPH_QUERY_MARKERS = (
        "why",
        "how",
        "which decision",
        "what led",
        "what changed",
        "what happened",
        "when",
        "who",
        "where",
        "current",
        "latest",
        "now",
        "as of",
        "before",
        "after",
        "depend",
        "related",
        "similar",
        "because",
        "原因",
        "为什么",
        "如何",
        "哪个决定",
        "什么变化",
        "发生了什么",
        "何时",
        "谁",
        "哪里",
        "相似",
        "相关",
        "之前",
        "之后",
        "依赖",
        "导致",
        "决策",
        "方案",
        "当前",
        "现在",
        "最新",
    )

    _GRAPH_RELATION_BONUS = {
        "supports": 0.20,
        "caused_by": 0.20,
        "depends_on": 0.18,
        "before": 0.12,
        "supersedes": 0.16,
        "contradicts": 0.14,
        "same_as": 0.10,
        "contains": 0.08,
        "mentions": 0.10,
        "occurs_at": 0.10,
        "similar": 0.03,
    }
    _DECISION_QUERY_MARKERS = (
        "decision",
        "choice",
        "哪个决定",
        "决策",
        "方案",
        "option",
    )
    _NEWER_STATE_MARKERS = (
        "current",
        "latest",
        "now",
        "as of",
        "当前",
        "现在",
        "最新",
    )
    _OLDER_STATE_MARKERS = (
        "previous",
        "prior",
        "earlier",
        "former",
        "before",
        "previously",
        "先前",
        "之前",
        "以前",
        "原先",
    )

    _GRAPH_INTENT_MARKERS = {
        "causal": (
            "why",
            "because",
            "cause",
            "reason",
            "led to",
            "what led",
            "原因",
            "为什么",
            "为何",
            "导致",
        ),
        "temporal": (
            "when",
            "before",
            "after",
            "latest",
            "current",
            "now",
            "as of",
            "history",
            "时间",
            "之前",
            "之后",
            "当前",
            "最新",
        ),
        "decision": (
            "decision",
            "choice",
            "option",
            "which approach",
            "哪个决定",
            "决策",
            "方案",
            "选择",
        ),
        "entity": (
            "who",
            "where",
            "which file",
            "which module",
            "which library",
            "谁",
            "哪里",
            "哪个文件",
            "哪个模块",
        ),
        "associative": (
            "related",
            "similar",
            "other memories",
            "关联",
            "相关",
            "相似",
        ),
    }
    _GRAPH_INTENT_POLICIES = {
        "causal": {
            "relation_weights": {
                "caused_by": 3.0,
                "supports": 1.8,
                "depends_on": 1.5,
                "before": 0.7,
                "similar": 0.35,
            },
            "max_hops": 3,
            "seed_limit": 16,
        },
        "temporal": {
            "relation_weights": {
                "before": 3.0,
                "supersedes": 2.8,
                "contradicts": 2.0,
                "contains": 1.1,
                "occurs_at": 1.8,
                "similar": 0.5,
            },
            "max_hops": 2,
            "seed_limit": 20,
        },
        "decision": {
            "relation_weights": {
                "supersedes": 3.0,
                "contradicts": 2.8,
                "supports": 1.8,
                "before": 1.5,
                "same_as": 0.6,
                "mentions": 1.4,
                "occurs_at": 0.8,
            },
            "max_hops": 2,
            "seed_limit": 16,
        },
        "entity": {
            "relation_weights": {
                "same_as": 2.5,
                "contains": 1.8,
                "mentions": 2.2,
                "similar": 1.4,
                "before": 0.5,
            },
            "max_hops": 2,
            "seed_limit": 20,
        },
        "associative": {
            "relation_weights": {
                "similar": 2.5,
                "same_as": 2.0,
                "contains": 1.2,
                "supports": 1.2,
            },
            "max_hops": 2,
            "seed_limit": 24,
        },
        "semantic": {
            "relation_weights": {
                "similar": 1.6,
                "same_as": 1.1,
                "supports": 1.2,
            },
            "max_hops": 2,
            "seed_limit": 24,
        },
    }

    def _new_graph_trace(self, graph_policy: dict[str, Any]) -> dict[str, Any]:
        """Create the stable, content-free audit shape for one read."""

        graph_enabled = bool(
            self._graph_store is not None and self._graph_store.enabled
        )
        return {
            "graph_enabled": graph_enabled,
            "routed": False,
            "outcome": "not_routed" if graph_enabled else "disabled",
            "intent": graph_policy["intent"],
            "supersedes_preference": graph_policy["supersedes_preference"],
            "graph_hit_count": 0,
            "graph_evidence_count": 0,
            "state_path": {
                "eligible_memory_ids": [],
                "selected_memory_ids": [],
                "baseline_ranks": {},
                "merged_ranks": {},
                "final_ranks": {},
                "applied": False,
                "ranking_changed": False,
            },
        }

    @staticmethod
    def _ranked_memory_ids(items: list[Any]) -> dict[str, int]:
        """Return one-based ranks for entries or formatted read results."""

        ranks: dict[str, int] = {}
        for index, item in enumerate(items, 1):
            memory_id = (
                item.get("id", "")
                if isinstance(item, dict)
                else getattr(item, "id", "")
            )
            if memory_id and memory_id not in ranks:
                ranks[str(memory_id)] = index
        return ranks

    def _should_use_graph(self, query: str, entries: list[Any]) -> bool:
        """Route only graph-shaped questions to the graph retriever."""

        if not self._graph_store or not self._graph_store.enabled:
            return False
        # Explicit current-versus-prior wording is itself a narrow graph
        # request.  In particular, historical markers such as "previous" do
        # not need to appear in the broader relational-marker list before a
        # directly evidenced state endpoint may be considered.
        if self._supersedes_preference(query) is not None:
            return True
        if self._is_graph_shaped_query(query):
            return True
        return len(entries) < 3 and self._graph_store.edge_count > 0

    def _is_graph_shaped_query(self, query: str) -> bool:
        lowered = str(query or "").casefold()
        return any(marker in lowered for marker in self._GRAPH_QUERY_MARKERS)

    def _is_decision_query(self, query: str) -> bool:
        lowered = str(query or "").casefold()
        return any(marker in lowered for marker in self._DECISION_QUERY_MARKERS)

    @classmethod
    def _supersedes_preference(cls, query: str) -> str | None:
        """Resolve an unambiguous current-versus-historical state request.

        The graph may override lexical order only when the wording clearly
        requests one endpoint of a source-backed ``supersedes`` relation.
        Mixed wording remains on the conservative lexical/graph path.
        """

        lowered = str(query or "").casefold()
        wants_newer = any(marker in lowered for marker in cls._NEWER_STATE_MARKERS)
        wants_older = any(marker in lowered for marker in cls._OLDER_STATE_MARKERS)
        if wants_newer == wants_older:
            return None
        return "newer" if wants_newer else "older"

    @classmethod
    def _graph_query_policy(cls, query: str) -> dict[str, Any]:
        """Map a query to a small MAGMA-style relation traversal policy."""

        lowered = str(query or "").casefold()
        scores = {
            intent: sum(lowered.count(marker.casefold()) for marker in markers)
            for intent, markers in cls._GRAPH_INTENT_MARKERS.items()
        }
        priority = ("causal", "decision", "temporal", "entity", "associative")
        intent = (
            max(
                scores,
                key=lambda name: (
                    scores[name],
                    -priority.index(name) if name in priority else -len(priority),
                ),
            )
            if max(scores.values(), default=0)
            else "semantic"
        )
        policy = cls._GRAPH_INTENT_POLICIES[intent]
        return {
            "intent": intent,
            "relation_weights": dict(policy["relation_weights"]),
            "max_hops": policy["max_hops"],
            "seed_limit": policy["seed_limit"],
            "supersedes_preference": cls._supersedes_preference(query),
        }

    @classmethod
    def _graph_path_bonus(cls, relations: Any) -> float:
        """Score an explanation path by relation quality and hop distance."""

        if not relations:
            return 0.0
        bonus = sum(
            cls._GRAPH_RELATION_BONUS.get(str(relation), 0.04) / (index + 1)
            for index, relation in enumerate(relations)
        )
        return min(0.20, bonus)

    def _merge_graph_candidates(
        self,
        entries: list[Any],
        graph_hits: list[Any],
        *,
        max_results: int,
        prefer_graph: bool = False,
        supersedes_preference: str | None = None,
    ) -> tuple[list[Any], dict[str, Any]]:
        """Fuse lexical candidates and graph hits before optional reranking."""

        live_entries = {entry.id: entry for entry in self._all_memory_entries()}
        base_entries = list(dict.fromkeys(entry for entry in entries if getattr(entry, "id", "")))
        base_rank = {entry.id: index for index, entry in enumerate(base_entries)}
        hit_by_id = {
            hit.memory_id: hit
            for hit in graph_hits
            if getattr(hit, "memory_id", "") in live_entries
        }
        # Surface links are useful for graph construction and diagnostics, but
        # a graph-only candidate must have a semantically meaningful path
        # before it is allowed to enter the lexical candidate set.  Otherwise
        # an arbitrary entity/time co-occurrence can perturb a bounded result
        # window without offering an explanation for the rank change.
        reliable_relations = {
            "supports",
            "caused_by",
            "depends_on",
            "supersedes",
            "contradicts",
            # Legacy reflection linking uses ``similar`` when the provenance
            # match is strong but no causal predicate exists.
            "similar",
        }
        reliable_hit_by_id = {
            entry_id: hit
            for entry_id, hit in hit_by_id.items()
            if set(getattr(hit, "relations", ())) & reliable_relations
        }
        preferred_state_ids = [
            entry_id
            for entry_id, hit in reliable_hit_by_id.items()
            if (
                supersedes_preference in {"newer", "older"}
                and getattr(hit, "supersedes_preference", None)
                == supersedes_preference
            )
        ]
        # A direct, source-backed state transition is the narrow exception to
        # preserving lexical rank 1.  For an explicit current/previous query,
        # the requested endpoint is stronger evidence than a stale wording
        # match, but both transition facts must already have been recognized
        # by graph search before this branch can run.
        if preferred_state_ids:
            preferred_set = set(preferred_state_ids)
            ordered_ids = [
                *preferred_state_ids,
                *(entry.id for entry in base_entries if entry.id not in preferred_set),
            ]
            max_candidates = max(max_results * 2, max_results)
            included_ids = set(ordered_ids[:max_candidates])
            return (
                [live_entries[entry_id] for entry_id in ordered_ids[:max_candidates]],
                {
                    entry_id: reliable_hit_by_id[entry_id]
                    for entry_id in preferred_state_ids
                    if entry_id in included_ids
                },
            )
        # A graph-shaped query has an explicit lexical anchor and asks for a
        # relation around it (for example, why a file changed).  Preserve that
        # first anchor, then expand the reliable graph paths in the store's
        # evidence order before falling back to the remaining lexical list.
        # This is a bounded seed-and-expand policy: it avoids the old global
        # blend, which could demote the anchor merely because another
        # candidate had a path, while still making a verified multi-hop chain
        # visible near the top of the result.
        if prefer_graph and reliable_hit_by_id:
            seed_ids = [entry.id for entry in base_entries[:1]]
            graph_ids = [
                entry_id
                for entry_id in reliable_hit_by_id
                if entry_id not in seed_ids
            ]
            excluded_ids = set(seed_ids) | set(graph_ids)
            remaining_ids = [
                entry.id
                for entry in base_entries
                if entry.id not in excluded_ids
            ]
            ordered_ids = [*seed_ids, *graph_ids, *remaining_ids]
            max_candidates = max(max_results * 2, max_results)
            merged = [
                live_entries[entry_id]
                for entry_id in ordered_ids[:max_candidates]
            ]
            included_ids = set(ordered_ids[:max_candidates])
            evidence = {
                entry_id: reliable_hit_by_id[entry_id]
                for entry_id in reliable_hit_by_id
                if entry_id in included_ids
            }
            return merged, evidence

        candidate_ids = set(base_rank) | set(reliable_hit_by_id)
        if not candidate_ids:
            return entries, {}

        base_count = max(1, len(base_entries))
        ranked: list[tuple[float, int, str]] = []
        for entry_id in candidate_ids:
            rank = base_rank.get(entry_id, base_count)
            base_score = (base_count - rank) / base_count if entry_id in base_rank else 0.0
            hit = reliable_hit_by_id.get(entry_id)
            graph_score = float(getattr(hit, "score", 0.0))
            # A traversed relation is stronger evidence than a generic fact
            # that merely shares a query token.  Graph-shaped questions also
            # give the graph score more weight so lexical noise cannot push a
            # two-hop explanation below unrelated high-usage memories.
            if hit is not None and getattr(hit, "relations", ()):
                graph_score = min(
                    1.0,
                    graph_score + self._graph_path_bonus(hit.relations),
                )
            # For graph-shaped questions, a traversed evidence path should
            # contribute only when it represents a semantic relation.  Surface
            # entity/event/time links can help construct and inspect a graph,
            # but are not reliable enough to re-rank lexical evidence on their
            # own.  This keeps graph retrieval precision-first.
            has_reliable_graph_path = hit is not None
            graph_weight = (
                0.95
                if prefer_graph and has_reliable_graph_path
                else 0.35
                if has_reliable_graph_path
                else 0.0
            )
            base_weight = 1.0 - graph_weight
            combined = base_weight * base_score + graph_weight * graph_score
            ranked.append((combined, -rank, entry_id))
        ranked.sort(reverse=True)

        max_candidates = max(max_results * 2, max_results)
        merged = [live_entries[entry_id] for _, _, entry_id in ranked[:max_candidates]]
        evidence = {
            entry_id: reliable_hit_by_id[entry_id]
            for entry_id in reliable_hit_by_id
            if entry_id in {entry.id for entry in merged}
        }
        return merged, evidence

    def _get_active_domains(
        self, current_files: list[str], task_description: str
    ) -> list[str]:
        try:
            from minicode.domain_classifier import get_active_domain_values
            return get_active_domain_values(
                current_files=current_files,
                intent_text=task_description,
            )
        except Exception:
            return []

    # ── T1: Memory Value Function + Adaptive Cooldown ───────────────

    # Formal definition:
    #   V(m, t, c) = relevance(m, t) × freshness(m) × utility(m, c)
    #   where:
    #     relevance(m, t) = BM25_score(m, t) ∈ [0, 1]
    #     freshness(m)    = exp(-age_days / τ) with τ = 30 days
    #     utility(m, c)   = 1 + α × I(m was used in similar context c)
    #
    # Adaptive cooldown:  τ_cool(c) = τ_base × (1 - context_pressure)
    #   High context pressure → shorter cooldown → faster injection
    #   Low context pressure → longer cooldown → less noise

    _TAU_FRESHNESS = 30.0  # days
    _ALPHA_UTILITY = 0.15

    def _memory_value(
        self, bm25_score: float, entry: Any, context_usage: float = 0.5
    ) -> float:
        """Compute V(m, t, c) for a single memory entry."""
        import math
        age_days = (time.time() - getattr(entry, 'updated_at', time.time())) / 86400.0
        freshness = math.exp(-age_days / self._TAU_FRESHNESS)
        utility = 1.0 + self._ALPHA_UTILITY * math.log1p(getattr(entry, 'usage_count', 0))
        return bm25_score * freshness * utility

    def _adaptive_cooldown(self, context_usage: float) -> float:
        """Compute adaptive injection cooldown based on context pressure.

        τ_cool = τ_base × (1 - context_pressure), clamped to [5s, 120s].
        High pressure → shorter cooldown (memory is more needed).
        """
        base = 30.0  # seconds
        return max(5.0, min(120.0, base * (1.0 - context_usage)))

    # ── T2: Query Reformulation ─────────────────────────────────────

    # When BM25 returns poor results (top score < τ_low), attempt
    # reformulation: strip stopwords, try domain synonyms, expand abbreviations.
    # Max 3 attempts. If no improvement, keep original results.

    _QUERY_STOPWORDS = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                        "to", "of", "in", "for", "on", "with", "at", "by", "from",
                        "and", "or", "but", "not", "this", "that", "it", "i", "we",
                        "add", "create", "make", "implement", "build", "set", "get"}

    _QUERY_REFORMULATIONS = [
        lambda q: " ".join(w for w in q.lower().split() if w not in MemoryPipeline._QUERY_STOPWORDS),
        lambda q: q.lower().replace("  ", " ").strip(),
    ]

    def _reformulate_query(self, query: str) -> list[str]:
        """Generate reformulated query variants."""
        variants = [query]
        for reformulate in self._QUERY_REFORMULATIONS:
            v = reformulate(query)
            if v and v != query and v not in variants:
                variants.append(v)
        return variants[:3]

    def _try_search_with_reformulation(
        self,
        task_description: str,
        active_domains: list[str] | None,
        max_results: int,
        *,
        record_usage: bool = True,
    ) -> list[Any]:
        """Search with query reformulation fallback for poor initial results."""

        entries = self._memory.search(
            task_description,
            limit=max_results,
            active_domains=active_domains,
            record_usage=record_usage,
        )

        if entries and len(entries) >= 3:
            return entries  # Good enough

        # Try reformulations
        for variant in self._reformulate_query(task_description):
            if variant == task_description:
                continue
            alt = self._memory.search(
                variant,
                limit=max_results,
                active_domains=active_domains,
                record_usage=record_usage,
            )
            if len(alt) > len(entries):
                logger.debug("Query reformulation improved: %d → %d results", len(entries), len(alt))
                return alt

        return entries

    # ── T3: Spreading Activation ────────────────────────────────────

    # When memory m is retrieved, its related_to neighbors also receive
    # activation: score_neighbor += score(m) × decay × sim(m, neighbor)
    # depth=1, decay=0.5. This surfaces related memories the user might
    # not have explicitly searched for.

    _SPREAD_DECAY = 0.5
    _SPREAD_THRESHOLD = 0.3

    def _spread_activation(
        self, entries: list[Any]
    ) -> list[Any]:
        """Enrich results via spreading activation through related_to graph.

        Concatenates directly-linked neighbors with decayed relevance.
        """
        if not self._memory or not entries:
            return entries

        seen_ids = {e.id for e in entries}
        neighbors = []

        for entry in entries[:5]:  # Only spread from top 5
            if not hasattr(entry, 'related_to') or not entry.related_to:
                continue
            for rid in entry.related_to:
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                # Find neighbor in memory
                for scope_name in ["project", "local", "user"]:
                    try:
                        from minicode.memory import MemoryScope
                        scope = MemoryScope(scope_name)
                        if scope in self._memory.memories:
                            nbr = self._memory.memories[scope]._id_index.get(rid)
                            if nbr:
                                neighbors.append(nbr)
                                break
                    except (ValueError, KeyError):
                        continue

        return entries + neighbors
