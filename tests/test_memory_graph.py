"""Unit tests for the dependency-free HippoRAG-lite memory graph."""
from __future__ import annotations

from pathlib import Path

from minicode.memory import MemoryEntry, MemoryScope
from minicode.memory_graph import MemoryGraphStore


def test_graph_search_propagates_from_file_seed_to_decision():
    store = MemoryGraphStore()
    file_fact = store.add_fact(
        memory_id="memory-file",
        scope=MemoryScope.PROJECT,
        subject="artifact",
        predicate="touches_file",
        value="src/payments.py",
        evidence="The billing module is in src/payments.py.",
    )
    task_fact = store.add_fact(
        memory_id="memory-task",
        scope=MemoryScope.PROJECT,
        subject="task",
        predicate="context",
        value="billing refactor",
        evidence="The task refactored billing.",
    )
    decision_fact = store.add_fact(
        memory_id="memory-decision",
        scope=MemoryScope.PROJECT,
        subject="decision",
        predicate="choice",
        value="use an idempotency key",
        evidence="The decision was to use an idempotency key.",
    )
    store.add_edge(file_fact.id, task_fact.id, "depends_on")
    store.add_edge(task_fact.id, decision_fact.id, "supports")

    results = store.search("src/payments.py why", max_hops=2, limit=10)
    by_memory = {result.memory_id: result for result in results}

    assert "memory-decision" in by_memory
    decision_result = by_memory["memory-decision"]
    assert decision_result.path[0] == file_fact.id
    assert decision_result.path[-1] == decision_fact.id
    assert decision_result.relations == ("depends_on", "supports")
    assert "The decision was to use an idempotency key." in decision_result.evidence


def test_graph_search_respects_as_of_time_and_superseded_status():
    store = MemoryGraphStore()
    old_fact = store.add_fact(
        memory_id="old-memory",
        scope="project",
        subject="database",
        predicate="choice",
        value="use sqlite",
        valid_from=0,
        valid_to=150,
    )
    new_fact = store.add_fact(
        memory_id="new-memory",
        scope="project",
        subject="database",
        predicate="choice",
        value="use postgres",
        valid_from=150,
    )

    before = {result.memory_id for result in store.search("database choice", as_of=100)}
    after = {result.memory_id for result in store.search("database choice", as_of=200)}

    assert before == {old_fact.memory_id}
    assert after == {new_fact.memory_id}

    assert store.invalidate_fact(new_fact.id, valid_to=250)
    at_current = {result.memory_id for result in store.search("database choice", as_of=300)}
    assert at_current == set()


def test_graph_search_exposes_direct_prior_state_only_for_older_preference():
    store = MemoryGraphStore()
    old_fact = store.add_fact(
        memory_id="old-memory",
        scope="project",
        subject="database",
        predicate="choice",
        value="use sqlite",
        observed_at=10,
        confidence=0.9,
    )
    new_fact = store.add_fact(
        memory_id="new-memory",
        scope="project",
        subject="database",
        predicate="choice",
        value="use postgres",
        observed_at=20,
        confidence=0.9,
    )
    assert store.supersede_fact(new_fact.id, old_fact.id, observed_at=20)

    ordinary_ids = {
        result.memory_id
        for result in store.search("database choice", limit=10)
    }
    historical = {
        result.memory_id: result
        for result in store.search(
            "previous database choice",
            limit=10,
            supersedes_preference="older",
        )
    }
    explicit_point_in_time_ids = {
        result.memory_id
        for result in store.search(
            "previous database choice",
            limit=10,
            as_of=30,
            supersedes_preference="older",
        )
    }

    assert old_fact.memory_id not in ordinary_ids
    assert old_fact.memory_id in historical
    assert historical[old_fact.memory_id].path == (old_fact.id, new_fact.id)
    assert historical[old_fact.memory_id].relations == ("supersedes",)
    assert historical[old_fact.memory_id].supersedes_preference == "older"
    assert old_fact.memory_id not in explicit_point_in_time_ids


def test_graph_sidecar_round_trip_preserves_facts_and_edges(tmp_path: Path):
    path = tmp_path / ".mini-code-memory" / "memory_graph.json"
    first = MemoryGraphStore(storage_path=path)
    source = first.add_fact(
        memory_id="m1",
        scope="project",
        subject="build",
        predicate="uses_tool",
        value="pytest",
        evidence="The build uses pytest.",
        source_session="session-1",
        source_turn=4,
        source_files=("tests/test_app.py",),
    )
    target = first.add_fact(
        memory_id="m2",
        scope="project",
        subject="test",
        predicate="supports",
        value="integration coverage",
    )
    first.add_edge(source.id, target.id, "supports", weight=0.7)
    assert first.save()

    restored = MemoryGraphStore(storage_path=path)
    assert restored.fact_count == 2
    assert restored.edge_count == 1
    restored_source = restored.facts[source.id]
    assert restored_source.source_session == "session-1"
    assert restored_source.source_turn == 4
    assert restored_source.source_files == ("tests/test_app.py",)


def test_sync_entries_creates_stable_generic_facts_and_similarity_edges():
    first = MemoryEntry(
        id="project-one",
        scope=MemoryScope.PROJECT,
        category="decision",
        content="Use SQLite for local development.",
        related_to=["project-two"],
    )
    second = MemoryEntry(
        id="project-two",
        scope=MemoryScope.PROJECT,
        category="pattern",
        content="SQLite integration tests use an in-memory database.",
    )
    store = MemoryGraphStore()
    store.sync_entries([first, second], persist=False)

    assert "memory:project-one" in store.facts
    assert "memory:project-two" in store.facts
    assert any(edge.relation == "similar" for edge in store.edges.values())
    assert store.facts["memory:project-one"].evidence_id == "project-one"


def test_graph_search_cache_hits_and_invalidates_on_graph_mutation():
    store = MemoryGraphStore()
    source = store.add_fact(
        memory_id="source",
        scope="project",
        subject="artifact",
        predicate="touches_file",
        value="src/cache.py",
    )
    target = store.add_fact(
        memory_id="target",
        scope="project",
        subject="decision",
        predicate="choice",
        value="use bounded cache",
    )

    first = store.search("src/cache.py", max_hops=1)
    second = store.search("src/cache.py", max_hops=1)
    assert first == second
    assert store.stats()["search_cache_hits"] >= 1

    store.add_edge(source.id, target.id, "supports")
    third = store.search("src/cache.py", max_hops=1)
    assert {result.memory_id for result in third} == {"source", "target"}
    assert store.stats()["search_cache_misses"] >= 2


def test_graph_save_trim_invalidates_cached_evicted_facts(tmp_path: Path):
    store = MemoryGraphStore(
        storage_path=tmp_path / "memory-graph.json",
        max_facts=2,
    )
    evicted = store.add_fact(
        memory_id="evicted",
        scope="project",
        subject="obsolete",
        predicate="choice",
        value="evict this fact",
        confidence=0.1,
        observed_at=1,
    )
    store.add_fact(
        memory_id="kept-1",
        scope="project",
        subject="current",
        predicate="choice",
        value="keep this fact",
        confidence=0.9,
        observed_at=2,
    )
    store.add_fact(
        memory_id="kept-2",
        scope="project",
        subject="current",
        predicate="choice",
        value="keep another fact",
        confidence=0.9,
        observed_at=3,
    )

    assert [result.memory_id for result in store.search("obsolete evict")] == [
        evicted.memory_id
    ]
    assert store.stats()["search_cache_size"] == 1

    assert store.save()
    assert evicted.id not in store.facts
    assert store.search("obsolete evict") == []
    assert store.stats()["search_cache_hits"] == 0


def test_graph_relation_prioritises_support_over_similarity():
    store = MemoryGraphStore()
    source = store.add_fact(
        memory_id="source",
        scope="project",
        subject="artifact",
        predicate="touches_file",
        value="src/relation.py",
    )
    similar = store.add_fact(
        memory_id="similar",
        scope="project",
        subject="note",
        predicate="context",
        value="unrelated note",
    )
    supported = store.add_fact(
        memory_id="supported",
        scope="project",
        subject="decision",
        predicate="choice",
        value="unrelated decision",
    )
    store.add_edge(source.id, similar.id, "similar", weight=1.0)
    store.add_edge(source.id, supported.id, "supports", weight=1.0)

    results = store.search("src/relation.py", max_hops=1, limit=3)
    assert [result.memory_id for result in results].index("supported") < [
        result.memory_id for result in results
    ].index("similar")


def test_graph_accepts_typed_entity_and_time_relations():
    store = MemoryGraphStore()
    event = store.add_fact(
        memory_id="event",
        scope="project",
        subject="session-1",
        predicate="event",
        value="deployed the billing service",
    )
    entity = store.add_fact(
        memory_id="event",
        scope="project",
        subject="billing",
        predicate="entity",
        value="billing",
    )
    moment = store.add_fact(
        memory_id="event",
        scope="project",
        subject="session-1",
        predicate="time",
        value="2025-01-01",
    )

    mentions = store.add_edge(event.id, entity.id, "mentions")
    occurs_at = store.add_edge(event.id, moment.id, "occurs_at")

    assert mentions is not None and mentions.relation == "mentions"
    assert occurs_at is not None and occurs_at.relation == "occurs_at"


def test_query_relation_policy_can_change_traversal_priority():
    store = MemoryGraphStore()
    source = store.add_fact(
        memory_id="source",
        scope="project",
        subject="artifact",
        predicate="touches_file",
        value="src/policy.py",
    )
    cause = store.add_fact(
        memory_id="cause",
        scope="project",
        subject="cause",
        predicate="lesson",
        value="the failing fixture caused the retry change",
    )
    similar = store.add_fact(
        memory_id="similar",
        scope="project",
        subject="note",
        predicate="lesson",
        value="the retry change is similar to another fix",
    )
    store.add_edge(source.id, cause.id, "caused_by", weight=1.0)
    store.add_edge(source.id, similar.id, "similar", weight=1.0)

    results = store.search(
        "src/policy.py",
        max_hops=1,
        limit=3,
        relation_weights={"caused_by": 0.1, "similar": 5.0},
    )
    result_ids = [result.memory_id for result in results]
    assert result_ids.index("similar") < result_ids.index("cause")


def test_reflection_creates_temporal_edges_for_shared_context():
    store = MemoryGraphStore()
    common = {"task_context": {"files": ["src/auth.py"]}}
    store.ingest_reflection(
        memory_id="earlier",
        scope=MemoryScope.PROJECT,
        task_description="repair authentication tests",
        metadata=common,
        execution_trace=[{"session_id": "session-1", "turn_index": 1}],
        observed_at=10.0,
        persist=False,
    )
    store.ingest_reflection(
        memory_id="later",
        scope=MemoryScope.PROJECT,
        task_description="extend authentication tests",
        metadata=common,
        execution_trace=[{"session_id": "session-1", "turn_index": 2}],
        observed_at=20.0,
        persist=False,
    )

    earlier_task = store.facts["reflection:earlier:task"]
    later_task = store.facts["reflection:later:task"]
    edge_id = f"edge-{earlier_task.id}-{later_task.id}-before"
    assert edge_id in store.edges
    assert store.edges[edge_id].relation == "before"


def test_deferred_consolidation_flushes_cross_memory_links():
    store = MemoryGraphStore()
    store.ingest_reflection(
        memory_id="old-note",
        scope=MemoryScope.PROJECT,
        task_description="choose authentication strategy",
        metadata={"key_decisions": ["use token rotation"]},
        observed_at=10.0,
        persist=False,
    )
    store.ingest_reflection(
        memory_id="new-note",
        scope=MemoryScope.PROJECT,
        task_description="review authentication strategy",
        metadata={"key_decisions": ["adopt token rotation"]},
        observed_at=20.0,
        persist=False,
        consolidate=False,
    )

    assert store.stats()["pending_facts"] > 0
    assert not any(
        store.facts[edge.source_fact_id].memory_id != store.facts[edge.target_fact_id].memory_id
        for edge in store.edges.values()
    )

    linked = store.consolidate_pending(persist=False)
    assert linked > 0
    assert store.stats()["pending_facts"] == 0
    assert any(
        store.facts[edge.source_fact_id].memory_id != store.facts[edge.target_fact_id].memory_id
        for edge in store.edges.values()
    )


def test_ingest_reflection_preserves_provenance_and_builds_typed_subgraph():
    store = MemoryGraphStore()
    created = store.ingest_reflection(
        memory_id="reflection-1",
        scope=MemoryScope.PROJECT,
        task_description="repair authentication tests",
        metadata={
            "key_decisions": ["use token rotation"],
            "errors": ["old fixture expired"],
            "task_context": {
                "files": ["src/auth.py"],
                "libraries": ["pytest"],
                "tools": ["run_tests"],
            },
        },
        confidence=0.9,
        execution_trace=[{"session_id": "session-7", "turn_index": 3}],
        persist=False,
    )

    assert created >= 4
    facts = list(store.facts.values())
    decision = next(fact for fact in facts if fact.predicate == "decision")
    assert decision.evidence_id == "reflection-1"
    assert decision.source_session == "session-7"
    assert decision.source_turn == 3
    assert decision.source_files == ("src/auth.py",)
    assert any(edge.relation == "contains" for edge in store.edges.values())


def test_reflection_links_shared_context_across_memories_conservatively():
    store = MemoryGraphStore()
    metadata = {
        "task_context": {
            "files": ["src/auth.py"],
            "libraries": ["pytest"],
        },
        "key_decisions": ["use token rotation"],
    }
    store.ingest_reflection(
        memory_id="old-reflection",
        scope=MemoryScope.PROJECT,
        task_description="repair authentication tests",
        metadata=metadata,
        observed_at=10.0,
        persist=False,
    )
    store.ingest_reflection(
        memory_id="new-reflection",
        scope=MemoryScope.PROJECT,
        task_description="extend authentication tests",
        metadata={
            "task_context": {"files": ["src/auth.py"]},
            "key_decisions": ["use refresh tokens"],
        },
        observed_at=20.0,
        persist=False,
    )

    old_decision = next(
        fact
        for fact in store.facts.values()
        if fact.memory_id == "old-reflection" and fact.predicate == "decision"
    )
    new_decision = next(
        fact
        for fact in store.facts.values()
        if fact.memory_id == "new-reflection" and fact.predicate == "decision"
    )
    decision_edge_id = f"edge-{new_decision.id}-{old_decision.id}-contradicts"
    assert decision_edge_id in store.edges
    assert 0.0 < store.edges[decision_edge_id].weight < 0.45
    assert old_decision.status == "active"

    old_file = next(
        fact
        for fact in store.facts.values()
        if fact.memory_id == "old-reflection" and fact.predicate == "touches_file"
    )
    new_file = next(
        fact
        for fact in store.facts.values()
        if fact.memory_id == "new-reflection" and fact.predicate == "touches_file"
    )
    assert f"edge-{new_file.id}-{old_file.id}-same_as" in store.edges

    generic_edges = [
        edge
        for edge in store.edges.values()
        if store.facts[edge.source_fact_id].predicate == "memory"
        or store.facts[edge.target_fact_id].predicate == "memory"
    ]
    assert generic_edges == []


def test_reflection_supersedes_decision_when_trace_order_is_explicit():
    store = MemoryGraphStore()
    common_context = {"task_context": {"files": ["src/auth.py"]}}
    store.ingest_reflection(
        memory_id="old-decision",
        scope=MemoryScope.PROJECT,
        task_description="choose authentication strategy",
        metadata={**common_context, "key_decisions": ["use token rotation"]},
        confidence=0.9,
        execution_trace=[{"session_id": "session-1", "turn_index": 1}],
        observed_at=10.0,
        persist=False,
    )
    store.ingest_reflection(
        memory_id="new-decision",
        scope=MemoryScope.PROJECT,
        task_description="replace authentication strategy",
        metadata={**common_context, "key_decisions": ["use refresh tokens"]},
        confidence=0.9,
        execution_trace=[{"session_id": "session-1", "turn_index": 2}],
        observed_at=20.0,
        persist=False,
    )

    old_fact = next(
        fact
        for fact in store.facts.values()
        if fact.memory_id == "old-decision" and fact.predicate == "decision"
    )
    new_fact = next(
        fact
        for fact in store.facts.values()
        if fact.memory_id == "new-decision" and fact.predicate == "decision"
    )
    edge = store.edges[f"edge-{new_fact.id}-{old_fact.id}-supersedes"]
    assert edge.relation == "supersedes"
    assert edge.valid_from == 20.0
    assert old_fact.status == "superseded"
    assert old_fact.valid_to == 20.0

    before_facts = store._valid_facts(as_of=15, scopes=None)
    after_facts = store._valid_facts(as_of=30, scopes=None)
    assert old_fact.id in before_facts
    assert old_fact.id not in after_facts
    assert new_fact.id in after_facts

    after_decision = {
        result.memory_id
        for result in store.search("decision src/auth.py", as_of=30)
    }
    assert "new-decision" in after_decision
