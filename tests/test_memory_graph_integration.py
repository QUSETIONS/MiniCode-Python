"""Integration tests for graph retrieval through MemoryPipeline."""
from __future__ import annotations

from pathlib import Path

from minicode.memory import MemoryManager, MemoryScope
from minicode.memory_graph import GraphRetrieval
from minicode.memory_pipeline import MemoryPipeline


def _isolated_manager(workspace: Path) -> MemoryManager:
    manager = MemoryManager(project_root=workspace)
    for scope in MemoryScope:
        manager.memories[scope].entries.clear()
        manager.memories[scope]._rebuild_indices()
    return manager


def test_pipeline_fuses_graph_only_decision_with_lexical_file_hit(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    file_entry = manager.add_entry(
        MemoryScope.PROJECT,
        category="task_context",
        content="Authentication work is tracked in src/auth.py.",
    )
    decision_entry = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use token rotation for authentication.",
    )

    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=True,
    )
    assert pipeline.graph_store is not None

    file_fact = pipeline.graph_store.add_fact(
        memory_id=file_entry.id,
        scope=MemoryScope.PROJECT,
        subject="artifact",
        predicate="touches_file",
        value="src/auth.py",
        evidence="Authentication work is tracked in src/auth.py.",
    )
    decision_fact = pipeline.graph_store.add_fact(
        memory_id=decision_entry.id,
        scope=MemoryScope.PROJECT,
        subject="decision",
        predicate="choice",
        value="use token rotation",
        evidence="Use token rotation for authentication.",
    )
    pipeline.graph_store.add_edge(file_fact.id, decision_fact.id, "supports")
    assert pipeline.graph_store.save()

    results = pipeline.read("src/auth.py why", max_results=2)
    result_by_id = {result["id"]: result for result in results}

    assert file_entry.id in result_by_id
    assert decision_entry.id in result_by_id
    decision_result = result_by_id[decision_entry.id]
    assert decision_result["graph"] is True
    assert decision_result["evidence"]
    assert decision_result["evidence_path"]
    assert decision_result["evidence_relations"] == ["supports"]

    reloaded = MemoryPipeline(_isolated_manager(workspace))
    reloaded.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=True,
    )
    assert reloaded.graph_store.edge_count >= 1
    assert reloaded.graph_store.fact_count >= 2


def test_pipeline_can_disable_graph_without_changing_fallback_shape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use SQLite for local development.",
    )

    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=False,
    )
    results = pipeline.read("which decision should we use", max_results=3)

    assert results
    assert all(set(result) == {"id", "content", "domain", "relevance", "source"} for result in results)
    assert pipeline.stats["graph_enabled"] is False


def test_pipeline_defaults_to_lexical_only_until_graph_is_explicitly_enabled(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use SQLite for local development.",
    )

    pipeline = MemoryPipeline(manager)
    pipeline.initialize(model_adapter=None, workspace_path=str(workspace))

    assert pipeline.stats["graph_enabled"] is False
    assert pipeline.graph_store is None


def test_pipeline_read_only_mode_does_not_feedback_into_usage_counts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    entry = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use SQLite for local development.",
    )
    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=False,
    )

    results = pipeline.read("which local decision should we use", record_usage=False)

    assert results
    assert entry.usage_count == 0


def test_pipeline_routes_query_intent_to_relation_policy(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=True,
    )

    causal = pipeline._graph_query_policy("why did the authentication change")
    decision = pipeline._graph_query_policy("what is the current decision")
    temporal = pipeline._graph_query_policy("what happened before src/auth.py")

    assert causal["intent"] == "causal"
    assert decision["intent"] == "decision"
    assert temporal["intent"] == "temporal"
    assert causal["relation_weights"]["caused_by"] > causal["relation_weights"]["similar"]
    assert decision["relation_weights"]["supersedes"] > decision["relation_weights"]["same_as"]
    assert temporal["relation_weights"]["before"] > temporal["relation_weights"]["similar"]
    assert pipeline._graph_query_policy("what is the current theme color")[
        "supersedes_preference"
    ] == "newer"
    assert pipeline._graph_query_policy("what was the previous theme color")[
        "supersedes_preference"
    ] == "older"
    assert pipeline._graph_query_policy("compare the current and previous theme colors")[
        "supersedes_preference"
    ] is None


def test_graph_enabled_preserves_ordinary_query_results(tmp_path: Path):
    contents = [
        "Frontend service owns the profile form.",
        "Backend service exposes the authentication API.",
        "Worker service processes queued jobs.",
        "Database service runs migration checks.",
    ]

    def build_pipeline(workspace: Path, enable_graph: bool) -> MemoryPipeline:
        workspace.mkdir()
        manager = _isolated_manager(workspace)
        for content in contents:
            manager.add_entry(
                MemoryScope.PROJECT,
                category="task_context",
                content=content,
            )
        pipeline = MemoryPipeline(manager)
        pipeline.initialize(
            model_adapter=None,
            workspace_path=str(workspace),
            enable_reranker=False,
            enable_vector=False,
            enable_graph=enable_graph,
        )
        return pipeline

    graph_off = build_pipeline(tmp_path / "off", enable_graph=False)
    graph_on = build_pipeline(tmp_path / "on", enable_graph=True)
    off_results = graph_off.read("service", max_results=4)
    on_results = graph_on.read("service", max_results=4)

    # The lexical score includes time-sensitive recency/usage terms.  These
    # pipelines are built independently, so tied candidates may legitimately
    # arrive in a different order on another platform.  The graph opt-in
    # contract for an ordinary query is that it preserves the same candidates,
    # not a platform-specific ordering of equal-scoring entries.
    assert sorted(result["content"] for result in on_results) == sorted(
        result["content"] for result in off_results
    )
    assert all("graph" not in result for result in on_results)


def test_reliable_graph_path_does_not_downweight_an_unrelated_lexical_candidate(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    lexical = manager.add_entry(
        MemoryScope.PROJECT,
        category="task_context",
        content="The authentication task is tracked in src/auth.py.",
    )
    graph_only = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use token rotation for authentication.",
    )
    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=False,
    )

    merged, evidence = pipeline._merge_graph_candidates(
        [lexical, graph_only],
        [
            GraphRetrieval(
                memory_id=graph_only.id,
                score=0.2,
                relations=("supports",),
            )
        ],
        max_results=2,
        prefer_graph=True,
    )

    assert [entry.id for entry in merged] == [lexical.id, graph_only.id]
    assert set(evidence) == {graph_only.id}


def test_graph_shaped_query_preserves_its_seed_then_expands_reliable_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    seed = manager.add_entry(
        MemoryScope.PROJECT,
        category="task_context",
        content="The payment retry handler is in src/payments/retry.py.",
    )
    lexical_distractor = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="The retry queue previously used Redis.",
    )
    cause = manager.add_entry(
        MemoryScope.PROJECT,
        category="debugging",
        content="Duplicate webhook delivery caused repeated processing.",
    )
    decision = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use an idempotency key for webhook processing.",
    )
    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=False,
    )

    merged, evidence = pipeline._merge_graph_candidates(
        [seed, lexical_distractor, cause, decision],
        [
            GraphRetrieval(
                memory_id=cause.id,
                score=0.4,
                relations=("caused_by",),
            ),
            GraphRetrieval(
                memory_id=decision.id,
                score=0.2,
                relations=("caused_by", "supports"),
            ),
        ],
        max_results=4,
        prefer_graph=True,
    )

    assert [entry.id for entry in merged] == [
        seed.id,
        cause.id,
        decision.id,
        lexical_distractor.id,
    ]
    assert set(evidence) == {cause.id, decision.id}


def test_surface_only_graph_path_cannot_append_or_rerank_lexical_evidence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    lexical = manager.add_entry(
        MemoryScope.PROJECT,
        category="task_context",
        content="The authentication task is tracked in src/auth.py.",
    )
    surface_hit = manager.add_entry(
        MemoryScope.PROJECT,
        category="task_context",
        content="A session mentioned authentication in a generic status update.",
    )
    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=False,
    )

    merged, evidence = pipeline._merge_graph_candidates(
        [lexical],
        [
            GraphRetrieval(
                memory_id=surface_hit.id,
                score=0.95,
                relations=("same_as",),
            )
        ],
        max_results=2,
        prefer_graph=True,
    )

    assert [entry.id for entry in merged] == [lexical.id]
    assert evidence == {}


def test_pipeline_write_persists_once_and_creates_cross_memory_edge(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    historical = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use token rotation for authentication.",
    )

    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=True,
    )
    historical_fact = pipeline.graph_store.add_fact(
        memory_id=historical.id,
        scope=MemoryScope.PROJECT,
        subject="historical decision",
        predicate="decision",
        value="use token rotation",
        evidence=historical.content,
        source_files=("src/auth.py",),
        observed_at=10.0,
        valid_from=0.0,
        confidence=0.9,
    )
    before_count = len(manager.memories[MemoryScope.PROJECT].entries)

    written_id = pipeline.write(
        "repair authentication",
        [
            {"type": "tool_call", "name": "read_file", "path": "src/auth.py"},
            {"type": "assistant", "content": "We will use refresh tokens."},
        ],
    )

    assert written_id
    assert len(manager.memories[MemoryScope.PROJECT].entries) == before_count + 1
    cross_edges = [
        edge
        for edge in pipeline.graph_store.edges.values()
        if pipeline.graph_store.facts[edge.source_fact_id].memory_id != historical.id
        and pipeline.graph_store.facts[edge.target_fact_id].memory_id == historical.id
        and historical_fact.id in {
            edge.source_fact_id,
            edge.target_fact_id,
        }
    ]
    assert cross_edges


def test_pipeline_can_defer_graph_consolidation_until_background_flush(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    historical = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use token rotation for authentication.",
    )
    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=True,
        defer_graph_consolidation=True,
    )
    pipeline.graph_store.ingest_reflection(
        memory_id=historical.id,
        scope=MemoryScope.PROJECT,
        task_description="choose authentication strategy",
        metadata={
            "task_context": {"files": ["src/auth.py"]},
            "key_decisions": ["use token rotation"],
        },
        observed_at=10.0,
        persist=False,
    )

    written_id = pipeline.write(
        "replace authentication strategy",
        [
            {"type": "tool_call", "name": "read_file", "path": "src/auth.py"},
            {"type": "assistant", "content": "We will use refresh tokens instead."},
        ],
    )

    assert written_id
    assert pipeline.stats["graph_deferred_consolidation"] is True
    assert pipeline.stats["graph_pending_facts"] > 0
    linked = pipeline.consolidate_graph()
    assert linked > 0
    assert pipeline.stats["graph_pending_facts"] == 0


def test_pipeline_filters_superseded_decision_memory_from_current_query(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    old_entry = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use token rotation for authentication.",
    )
    new_entry = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use refresh tokens for authentication.",
    )
    manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use service accounts for batch jobs.",
    )
    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=True,
    )
    old_fact = pipeline.graph_store.add_fact(
        memory_id=old_entry.id,
        scope=MemoryScope.PROJECT,
        subject="historical decision",
        predicate="decision",
        value="use token rotation",
        source_files=("src/auth.py",),
        observed_at=10.0,
        valid_from=0.0,
        confidence=0.9,
    )
    new_fact = pipeline.graph_store.add_fact(
        memory_id=new_entry.id,
        scope=MemoryScope.PROJECT,
        subject="current decision",
        predicate="decision",
        value="use refresh tokens",
        source_files=("src/auth.py",),
        observed_at=20.0,
        valid_from=20.0,
        confidence=0.9,
    )
    assert pipeline.graph_store.supersede_fact(
        new_fact.id,
        old_fact.id,
        observed_at=20.0,
    )
    results = pipeline.read("current decision src/auth.py", max_results=5)
    historical = pipeline.read(
        "previous decision src/auth.py",
        max_results=5,
        record_usage=False,
    )
    historical_trace = pipeline.last_graph_trace
    result_ids = {result["id"] for result in results}
    assert new_entry.id in result_ids
    assert old_entry.id not in result_ids
    assert historical[0]["id"] == old_entry.id
    assert historical[0]["evidence_relations"] == ["supersedes"]
    assert historical_trace is not None
    assert historical_trace["supersedes_preference"] == "older"
    assert historical_trace["state_path"]["selected_memory_ids"] == [old_entry.id]
    assert historical_trace["state_path"]["applied"] is True


def test_pipeline_prefers_requested_endpoint_of_explicit_state_transition(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    old_entry = manager.add_entry(
        MemoryScope.PROJECT,
        category="task_context",
        content="Alice's current theme color was red.",
    )
    new_entry = manager.add_entry(
        MemoryScope.PROJECT,
        category="task_context",
        content="Alice selected blue for the theme color.",
    )
    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=True,
    )
    old_fact = pipeline.graph_store.add_fact(
        memory_id=old_entry.id,
        scope=MemoryScope.PROJECT,
        subject="Alice",
        predicate="state",
        value="red",
        evidence="Alice's theme color was red.",
        observed_at=10.0,
        confidence=0.95,
    )
    new_fact = pipeline.graph_store.add_fact(
        memory_id=new_entry.id,
        scope=MemoryScope.PROJECT,
        subject="Alice",
        predicate="state",
        value="blue",
        evidence="Alice selected blue for the theme color.",
        observed_at=20.0,
        confidence=0.95,
    )
    assert pipeline.graph_store.add_edge(
        new_fact.id,
        old_fact.id,
        "supersedes",
        weight=0.9,
    )

    current = pipeline.read(
        "What is Alice's current theme color?",
        max_results=2,
        record_usage=False,
    )
    current_trace = pipeline.last_graph_trace
    trace_probe = pipeline.last_graph_trace
    assert trace_probe is not None
    trace_probe["state_path"]["selected_memory_ids"].clear()
    assert pipeline.last_graph_trace is not None
    assert pipeline.last_graph_trace["state_path"]["selected_memory_ids"] == [new_entry.id]
    historical = pipeline.read(
        "What was Alice's previous theme color?",
        max_results=2,
        record_usage=False,
    )
    historical_trace = pipeline.last_graph_trace
    pipeline.read(
        "Compare Alice's current and previous theme colors.",
        max_results=2,
        record_usage=False,
    )
    ambiguous_trace = pipeline.last_graph_trace

    assert current[0]["id"] == new_entry.id
    assert current[0]["graph"] is True
    assert current[0]["evidence_relations"] == ["supersedes"]
    assert current_trace is not None
    assert current_trace["routed"] is True
    assert current_trace["outcome"] == "searched"
    assert current_trace["supersedes_preference"] == "newer"
    assert current_trace["state_path"] == {
        "eligible_memory_ids": [new_entry.id],
        "selected_memory_ids": [new_entry.id],
        "baseline_ranks": {new_entry.id: 2},
        "merged_ranks": {new_entry.id: 1},
        "final_ranks": {new_entry.id: 1},
        "applied": True,
        "ranking_changed": True,
    }
    assert historical[0]["id"] == old_entry.id
    assert historical[0]["graph"] is True
    assert historical[0]["evidence_relations"] == ["supersedes"]
    assert historical_trace is not None
    assert historical_trace["supersedes_preference"] == "older"
    assert historical_trace["state_path"]["eligible_memory_ids"] == [old_entry.id]
    assert historical_trace["state_path"]["selected_memory_ids"] == [old_entry.id]
    assert historical_trace["state_path"]["applied"] is True
    assert historical_trace["state_path"]["final_ranks"] == {old_entry.id: 1}
    assert ambiguous_trace is not None
    assert ambiguous_trace["supersedes_preference"] is None
    assert ambiguous_trace["state_path"]["eligible_memory_ids"] == []
    assert ambiguous_trace["state_path"]["selected_memory_ids"] == []
    assert ambiguous_trace["state_path"]["applied"] is False


def test_pipeline_surfaces_active_decision_conflicts(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _isolated_manager(workspace)
    old_entry = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use token rotation for authentication.",
    )
    new_entry = manager.add_entry(
        MemoryScope.PROJECT,
        category="decision",
        content="Use refresh tokens for authentication.",
    )
    pipeline = MemoryPipeline(manager)
    pipeline.initialize(
        model_adapter=None,
        workspace_path=str(workspace),
        enable_reranker=False,
        enable_vector=False,
        enable_graph=True,
    )
    context = {"task_context": {"files": ["src/auth.py"]}}
    pipeline.graph_store.ingest_reflection(
        memory_id=old_entry.id,
        scope=MemoryScope.PROJECT,
        task_description="choose authentication strategy",
        metadata={**context, "key_decisions": ["use token rotation"]},
        observed_at=10.0,
        persist=False,
    )
    pipeline.graph_store.ingest_reflection(
        memory_id=new_entry.id,
        scope=MemoryScope.PROJECT,
        task_description="review authentication strategy",
        metadata={**context, "key_decisions": ["use refresh tokens"]},
        observed_at=20.0,
        persist=False,
    )
    results = pipeline.read("which decision src/auth.py", max_results=5)
    by_id = {result["id"]: result for result in results}

    assert old_entry.id in by_id
    assert new_entry.id in by_id
    assert new_entry.id in by_id[old_entry.id]["conflicts"]
    assert old_entry.id in by_id[new_entry.id]["conflicts"]
