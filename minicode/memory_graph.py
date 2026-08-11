"""Lightweight, evidence-aware graph retrieval for long-term memory.

This module deliberately keeps the first graph-memory iteration small and
dependency-free.  It borrows the useful part of HippoRAG -- seed retrieval
followed by graph propagation -- without requiring a graph database or an
LLM-powered offline indexer.

The graph is a sidecar to the existing memory files.  ``MemoryFact`` records
what was observed, when it was valid, and which memory entry supports it.
``MemoryEdge`` records a typed relation between facts.  Search uses lexical
seed matching followed by a bounded Personalized PageRank pass over the
reachable component.  The result keeps an evidence path so callers can audit
why a memory was surfaced.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from minicode.memory import _SEARCH_STOPWORDS, _search_tokens


_RELATIONS = frozenset(
    {
        "supports",
        "contradicts",
        "supersedes",
        "depends_on",
        "caused_by",
        "before",
        "same_as",
        "contains",
        "mentions",
        "occurs_at",
        "similar",
    }
)
# Relation priors keep weak associative links from competing with explicit
# explanatory links when callers use the same nominal edge weight.  The
# caller-provided weight still matters; this is only a semantic multiplier.
_RELATION_PRIORS: dict[str, float] = {
    "supports": 1.00,
    "caused_by": 1.00,
    "before": 0.80,
    "depends_on": 0.95,
    "supersedes": 0.90,
    "contradicts": 0.85,
    "same_as": 0.75,
    "contains": 0.65,
    "mentions": 0.85,
    "occurs_at": 0.90,
    "similar": 0.35,
}
_DECISION_PREDICATES = frozenset({"decision", "choice"})
_REPLACEMENT_MARKERS = (
    "replace",
    "replaced",
    "supersede",
    "migrat",
    "switch",
    "instead",
    "move to",
    "改用",
    "替换",
    "迁移",
    "改为",
    "取代",
)
_ACTIVE_STATUSES = frozenset({"active", "disputed"})
_DEFAULT_MAX_FACTS = 5_000
_DEFAULT_MAX_EDGES = 15_000
_TOKEN_RE = re.compile(r"[^\w./:-]+", flags=re.UNICODE)
_LINK_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "use",
        "using",
        "with",
        "this",
        "that",
    }
)


def _clean_text(value: Any) -> str:
    """Return a bounded, stable text representation for graph fields."""

    if value is None:
        return ""
    return str(value).strip()


def _normalise_scope(scope: Any) -> str:
    value = getattr(scope, "value", scope)
    return _clean_text(value).lower() or "project"


def _normalise_status(status: Any) -> str:
    value = _clean_text(status).lower()
    return value if value in {"active", "superseded", "disputed", "deprecated"} else "active"


def _coerce_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _tokens(text: str) -> set[str]:
    """Tokenise graph text while preserving common code/path separators."""

    # The memory subsystem's tokenizer knows the project's code vocabulary.
    # Add path/code fragments as a fallback because graph facts often contain
    # filenames such as ``src/auth/token_store.py``.
    base = set(_search_tokens(text))
    for fragment in _TOKEN_RE.split(text.casefold()):
        if fragment and fragment not in _SEARCH_STOPWORDS:
            base.add(fragment)
            base.update(
                part
                for part in re.split(r"[/.:_-]+", fragment)
                if part and part not in _SEARCH_STOPWORDS
            )
    return base


@dataclass
class MemoryFact:
    """A typed claim backed by one existing memory entry."""

    id: str
    memory_id: str
    scope: str
    subject: str
    predicate: str
    value: str
    evidence: str = ""
    evidence_id: str = ""
    source_session: str = ""
    source_turn: int | None = None
    source_files: tuple[str, ...] = ()
    observed_at: float = field(default_factory=time.time)
    valid_from: float | None = None
    valid_to: float | None = None
    confidence: float = 0.5
    status: str = "active"

    def __post_init__(self) -> None:
        self.scope = _normalise_scope(self.scope)
        self.subject = _clean_text(self.subject)
        self.predicate = _clean_text(self.predicate).lower() or "related_to"
        self.value = _clean_text(self.value)
        self.evidence = _clean_text(self.evidence)
        self.evidence_id = _clean_text(self.evidence_id)
        self.source_session = _clean_text(self.source_session)
        self.source_files = tuple(_clean_text(item) for item in self.source_files if _clean_text(item))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.status = _normalise_status(self.status)

    @property
    def searchable_text(self) -> str:
        # ``source_files`` is provenance, not an independent semantic claim.
        # Reflection emits a dedicated ``touches_file`` fact when a file
        # should be searchable; excluding provenance here prevents every
        # historical decision that merely mentions a file in metadata from
        # becoming a lexical seed and masking cross-memory traversal.
        return " ".join(
            [
                self.subject,
                self.predicate,
                self.value,
                self.evidence,
            ]
        )

    def is_valid(self, as_of: float | None = None) -> bool:
        """Whether this fact is usable at ``as_of``.

        ``None`` means current time.  Superseded and deprecated facts stay in
        the sidecar for auditability but are not returned for current queries.
        """

        if self.status == "superseded":
            # Keep historical validity before the supersession event so
            # point-in-time queries remain reproducible.  A current query
            # (``as_of=None``) must still hide the superseded fact.
            if as_of is None or self.valid_to is None:
                return False
        elif self.status not in _ACTIVE_STATUSES:
            return False
        point = time.time() if as_of is None else float(as_of)
        if self.valid_from is not None and point < self.valid_from:
            return False
        if self.valid_to is not None and point >= self.valid_to:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "memory_id": self.memory_id,
            "scope": self.scope,
            "subject": self.subject,
            "predicate": self.predicate,
            "value": self.value,
            "evidence": self.evidence,
            "evidence_id": self.evidence_id,
            "source_session": self.source_session,
            "source_turn": self.source_turn,
            "source_files": list(self.source_files),
            "observed_at": self.observed_at,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "confidence": self.confidence,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryFact":
        confidence = _coerce_float(data.get("confidence"), 0.5)
        observed_at = _coerce_float(data.get("observed_at"), time.time())
        return cls(
            id=_clean_text(data.get("id")) or f"fact-{uuid.uuid4().hex}",
            memory_id=_clean_text(data.get("memory_id")),
            scope=data.get("scope", "project"),
            subject=data.get("subject", ""),
            predicate=data.get("predicate", "related_to"),
            value=data.get("value", ""),
            evidence=data.get("evidence", ""),
            evidence_id=data.get("evidence_id", ""),
            source_session=data.get("source_session", ""),
            source_turn=_coerce_int(data.get("source_turn")),
            source_files=tuple(data.get("source_files", ()) or ()),
            observed_at=observed_at if observed_at is not None else time.time(),
            valid_from=_coerce_float(data.get("valid_from")),
            valid_to=_coerce_float(data.get("valid_to")),
            confidence=confidence if confidence is not None else 0.5,
            status=data.get("status", "active"),
        )


@dataclass
class MemoryEdge:
    """A typed relation between two facts."""

    id: str
    source_fact_id: str
    target_fact_id: str
    relation: str
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)
    valid_from: float | None = None
    valid_to: float | None = None
    status: str = "active"

    def __post_init__(self) -> None:
        self.relation = _clean_text(self.relation).lower() or "similar"
        self.weight = max(0.0, min(10.0, float(self.weight)))
        self.status = _normalise_status(self.status)

    def is_valid(self, as_of: float | None = None) -> bool:
        if self.status not in _ACTIVE_STATUSES:
            return False
        point = time.time() if as_of is None else float(as_of)
        if self.valid_from is not None and point < self.valid_from:
            return False
        if self.valid_to is not None and point >= self.valid_to:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_fact_id": self.source_fact_id,
            "target_fact_id": self.target_fact_id,
            "relation": self.relation,
            "weight": self.weight,
            "created_at": self.created_at,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEdge":
        weight = _coerce_float(data.get("weight"), 1.0)
        created_at = _coerce_float(data.get("created_at"), time.time())
        return cls(
            id=_clean_text(data.get("id")) or f"edge-{uuid.uuid4().hex}",
            source_fact_id=_clean_text(data.get("source_fact_id")),
            target_fact_id=_clean_text(data.get("target_fact_id")),
            relation=data.get("relation", "similar"),
            weight=weight if weight is not None else 1.0,
            created_at=created_at if created_at is not None else time.time(),
            valid_from=_coerce_float(data.get("valid_from")),
            valid_to=_coerce_float(data.get("valid_to")),
            status=data.get("status", "active"),
        )


@dataclass(frozen=True)
class GraphRetrieval:
    """A memory hit plus the graph evidence used to reach it."""

    memory_id: str
    score: float
    fact_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    path: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    # Set only when a query explicitly asks for the newer or older endpoint
    # of a directly evidenced ``supersedes`` relation.  Keeping this separate
    # from ``relations`` lets callers make the narrow state-selection decision
    # without treating an arbitrary temporal traversal as an override.
    supersedes_preference: str | None = None


class MemoryGraphStore:
    """Dependency-free typed fact graph with bounded PPR retrieval."""

    VERSION = 1
    SEARCH_CACHE_TTL_SECONDS = 2.0
    SEARCH_CACHE_MAX_ENTRIES = 128
    MAX_CROSS_MEMORY_LINKS_PER_FACT = 8
    MAX_TEMPORAL_LINKS_PER_FACT = 4
    DEFAULT_RECOGNITION_SEED_LIMIT = 24

    def __init__(
        self,
        storage_path: str | Path | None = None,
        *,
        alpha: float = 0.85,
        max_facts: int = _DEFAULT_MAX_FACTS,
        max_edges: int = _DEFAULT_MAX_EDGES,
    ) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        self.alpha = max(0.1, min(0.95, float(alpha)))
        self.max_facts = max(1, int(max_facts))
        self.max_edges = max(1, int(max_edges))
        self.facts: dict[str, MemoryFact] = {}
        self.edges: dict[str, MemoryEdge] = {}
        self._facts_by_memory: dict[str, set[str]] = defaultdict(set)
        self._pending_fact_ids: set[str] = set()
        self._dirty = False
        self._search_cache: dict[
            tuple[
                str,
                int,
                int,
                float | None,
                tuple[str, ...] | None,
                tuple[tuple[str, float], ...],
                int,
                str,
            ],
            tuple[float, tuple[GraphRetrieval, ...]],
        ] = {}
        self._search_cache_hits = 0
        self._search_cache_misses = 0
        self._load()

    @property
    def fact_count(self) -> int:
        return len(self.facts)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def enabled(self) -> bool:
        return bool(self.facts)

    def _load(self) -> None:
        if self.storage_path is None or not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != self.VERSION:
                return
            facts = payload.get("facts", [])
            edges = payload.get("edges", [])
            pending_fact_ids = payload.get("pending_fact_ids", [])
            if isinstance(facts, list):
                for item in facts:
                    if isinstance(item, dict):
                        fact = MemoryFact.from_dict(item)
                        if fact.id and fact.value:
                            self.facts[fact.id] = fact
            if isinstance(edges, list):
                for item in edges:
                    if isinstance(item, dict):
                        edge = MemoryEdge.from_dict(item)
                        if edge.source_fact_id in self.facts and edge.target_fact_id in self.facts:
                            self.edges[edge.id] = edge
            if isinstance(pending_fact_ids, list):
                self._pending_fact_ids = {
                    _clean_text(fact_id)
                    for fact_id in pending_fact_ids
                    if _clean_text(fact_id) in self.facts
                }
            self._rebuild_indexes()
            self._trim()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # A graph sidecar is an optimization.  A malformed sidecar must
            # never make the primary memory store unavailable.
            self.facts.clear()
            self.edges.clear()
            self._pending_fact_ids.clear()
            self._rebuild_indexes()

    def _rebuild_indexes(self) -> None:
        self._facts_by_memory = defaultdict(set)
        for fact in self.facts.values():
            if fact.memory_id:
                self._facts_by_memory[fact.memory_id].add(fact.id)

    def _invalidate_search_cache(self) -> None:
        self._search_cache.clear()

    def _trim(self) -> None:
        trimmed = False
        if len(self.facts) > self.max_facts:
            keep = sorted(
                self.facts.values(),
                key=lambda fact: (fact.confidence, fact.observed_at),
                reverse=True,
            )[: self.max_facts]
            keep_ids = {fact.id for fact in keep}
            self.facts = {fact_id: fact for fact_id, fact in self.facts.items() if fact_id in keep_ids}
            self.edges = {
                edge_id: edge
                for edge_id, edge in self.edges.items()
                if edge.source_fact_id in keep_ids and edge.target_fact_id in keep_ids
            }
            self._rebuild_indexes()
            self._pending_fact_ids.intersection_update(keep_ids)
            trimmed = True
        if len(self.edges) > self.max_edges:
            keep_edges = sorted(
                self.edges.values(),
                key=lambda edge: (edge.weight, edge.created_at),
                reverse=True,
            )[: self.max_edges]
            self.edges = {edge.id: edge for edge in keep_edges}
            trimmed = True
        if trimmed:
            # Trimming can happen during save after a search has populated the
            # cache.  Any cached result may reference a fact or edge that was
            # just evicted, so it must not survive the capacity bound.
            self._dirty = True
            self._invalidate_search_cache()

    def save(self) -> bool:
        """Persist the sidecar atomically; return whether the write succeeded."""

        if self.storage_path is None:
            self._dirty = False
            return True
        try:
            self._trim()
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": self.VERSION,
                "facts": [fact.to_dict() for fact in self.facts.values()],
                "edges": [edge.to_dict() for edge in self.edges.values()],
                "pending_fact_ids": sorted(self._pending_fact_ids),
            }
            temp_path = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temp_path.replace(self.storage_path)
            self._dirty = False
            return True
        except OSError:
            return False

    def add_fact(
        self,
        *,
        memory_id: str,
        scope: Any,
        subject: str,
        predicate: str,
        value: str,
        evidence: str = "",
        evidence_id: str = "",
        source_session: str = "",
        source_turn: int | None = None,
        source_files: Iterable[str] = (),
        observed_at: float | None = None,
        valid_from: float | None = None,
        valid_to: float | None = None,
        confidence: float = 0.5,
        status: str = "active",
        fact_id: str | None = None,
    ) -> MemoryFact:
        fact = MemoryFact(
            id=fact_id or f"fact-{uuid.uuid4().hex}",
            memory_id=_clean_text(memory_id),
            scope=_normalise_scope(scope),
            subject=subject,
            predicate=predicate,
            value=value,
            evidence=evidence,
            evidence_id=evidence_id,
            source_session=source_session,
            source_turn=source_turn,
            source_files=tuple(source_files),
            observed_at=observed_at if observed_at is not None else time.time(),
            valid_from=valid_from,
            valid_to=valid_to,
            confidence=confidence,
            status=status,
        )
        previous = self.facts.get(fact.id)
        if previous != fact:
            self.facts[fact.id] = fact
            self._rebuild_indexes()
            self._dirty = True
            self._invalidate_search_cache()
        return fact

    def add_edge(
        self,
        source_fact_id: str,
        target_fact_id: str,
        relation: str,
        *,
        weight: float = 1.0,
        valid_from: float | None = None,
        valid_to: float | None = None,
        status: str = "active",
        edge_id: str | None = None,
    ) -> MemoryEdge | None:
        """Add or update a typed edge when both endpoint facts exist."""

        if source_fact_id not in self.facts or target_fact_id not in self.facts:
            return None
        relation_value = _clean_text(relation).lower() or "similar"
        if relation_value not in _RELATIONS:
            relation_value = "similar"
        stable_id = edge_id or f"edge-{source_fact_id}-{target_fact_id}-{relation_value}"
        existing = self.edges.get(stable_id)
        edge = MemoryEdge(
            id=stable_id,
            source_fact_id=source_fact_id,
            target_fact_id=target_fact_id,
            relation=relation_value,
            weight=weight,
            created_at=existing.created_at if existing else time.time(),
            valid_from=valid_from,
            valid_to=valid_to,
            status=status,
        )
        if self.edges.get(edge.id) != edge:
            self.edges[edge.id] = edge
            self._dirty = True
            self._invalidate_search_cache()
        return edge

    def invalidate_fact(
        self,
        fact_id: str,
        *,
        valid_to: float | None = None,
        status: str = "superseded",
    ) -> bool:
        """Retain a fact for audit but stop it from current retrieval."""

        fact = self.facts.get(fact_id)
        if fact is None:
            return False
        fact.valid_to = valid_to if valid_to is not None else time.time()
        fact.status = _normalise_status(status)
        self._dirty = True
        self._invalidate_search_cache()
        return True

    def supersede_fact(
        self,
        new_fact_id: str,
        old_fact_id: str,
        *,
        observed_at: float | None = None,
        weight: float = 0.8,
    ) -> MemoryEdge | None:
        """Close an older fact and record an auditable supersedes edge."""

        new_fact = self.facts.get(new_fact_id)
        old_fact = self.facts.get(old_fact_id)
        if new_fact is None or old_fact is None or new_fact_id == old_fact_id:
            return None
        event_time = (
            float(observed_at)
            if observed_at is not None
            else float(new_fact.observed_at)
        )
        if event_time <= old_fact.observed_at:
            return None
        edge_id = f"edge-{new_fact_id}-{old_fact_id}-supersedes"
        edge = self.add_edge(
            new_fact_id,
            old_fact_id,
            "supersedes",
            weight=weight,
            valid_from=event_time,
            edge_id=edge_id,
        )
        if edge is None:
            return None
        if old_fact.status in _ACTIVE_STATUSES or old_fact.valid_to is None:
            old_fact.valid_to = event_time
            old_fact.status = "superseded"
            self._dirty = True
            self._invalidate_search_cache()
        return edge

    def sync_entries(self, entries: Iterable[Any], *, persist: bool = True) -> bool:
        """Create stable generic facts for existing memory entries.

        This gives old memories a graph seed without inventing semantic
        relations.  Existing ``related_to`` IDs become low-weight ``similar``
        edges.  Typed facts added by reflection are left untouched.
        """

        entry_list = [entry for entry in entries if getattr(entry, "id", "")]
        changed = False
        for entry in entry_list:
            fact_id = f"memory:{entry.id}"
            self.add_fact(
                fact_id=fact_id,
                memory_id=entry.id,
                scope=getattr(entry, "scope", "project"),
                subject=getattr(entry, "category", "memory"),
                predicate="memory",
                value=getattr(entry, "content", ""),
                evidence=getattr(entry, "content", ""),
                evidence_id=entry.id,
                observed_at=getattr(entry, "updated_at", time.time()),
                confidence=0.5,
            )
            changed = changed or self._dirty

        # Build links in a second pass so a ``related_to`` reference may point
        # to an entry that appears later in the input list.
        for entry in entry_list:
            fact_id = f"memory:{entry.id}"
            for related_id in getattr(entry, "related_to", ()) or ():
                related_fact_id = f"memory:{related_id}"
                if related_fact_id in self.facts:
                    edge = self.add_edge(fact_id, related_fact_id, "similar", weight=0.35)
                    changed = changed or edge is not None
        if persist and self._dirty:
            self.save()
        return changed

    @staticmethod
    def _match_key(value: Any) -> str:
        """Build a conservative key for exact context matching."""

        text = _clean_text(value).replace("\\", "/").casefold()
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _fact_context_files(cls, fact: MemoryFact) -> set[str]:
        files = {
            cls._match_key(source_file)
            for source_file in fact.source_files
            if cls._match_key(source_file)
        }
        if fact.predicate == "touches_file" and fact.value:
            files.add(cls._match_key(fact.value))
        return files

    @classmethod
    def _decision_relation(
        cls,
        current: MemoryFact,
        candidate: MemoryFact,
    ) -> tuple[str, float] | None:
        """Return a conflict relation for two competing decision facts."""

        if current.predicate != candidate.predicate:
            return None
        if current.predicate not in _DECISION_PREDICATES:
            return None
        if cls._match_key(current.value) == cls._match_key(candidate.value):
            return None
        if candidate.status not in _ACTIVE_STATUSES:
            return None
        confidence_factor = 0.25 + 0.75 * min(
            current.confidence,
            candidate.confidence,
        )
        combined_text = cls._match_key(f"{current.value} {current.evidence}")
        explicit_marker = any(marker in combined_text for marker in _REPLACEMENT_MARKERS)
        ordered_trace = (
            bool(current.source_session)
            and current.source_session == candidate.source_session
            and current.source_turn is not None
            and candidate.source_turn is not None
            and current.source_turn > candidate.source_turn
        )
        if (
            current.observed_at > candidate.observed_at
            and current.confidence >= 0.65
            and (ordered_trace or explicit_marker)
        ):
            return "supersedes", 0.80 * confidence_factor
        return "contradicts", 0.45 * confidence_factor

    @classmethod
    def _fact_link_tokens(cls, fact: MemoryFact) -> set[str]:
        """Return conservative note tokens for A-MEM-style dynamic linking."""

        return {
            token
            for token in _tokens(f"{fact.predicate} {fact.value}")
            if len(token) >= 3 and token not in _LINK_STOPWORDS
        }

    def _link_temporal_context(self, new_fact_ids: Iterable[str]) -> int:
        """Link nearby reflection events with an explicit ``before`` edge.

        This is the small, dependency-free equivalent of MAGMA/Zep's temporal
        view: only task/event facts are linked, and only when they share a
        source session or an exact file context.  It avoids turning every
        historical fact into a dense chronological chain.
        """

        new_ids = {fact_id for fact_id in new_fact_ids if fact_id in self.facts}
        new_events = [
            self.facts[fact_id]
            for fact_id in new_ids
            if self.facts[fact_id].predicate == "task"
        ]
        if not new_events:
            return 0
        existing_events = [
            fact
            for fact in self.facts.values()
            if fact.predicate == "task" and fact.id not in new_ids
        ]
        linked = 0
        for current in new_events:
            current_files = self._fact_context_files(current)
            candidates: list[tuple[int, int, float, MemoryFact]] = []
            for candidate in existing_events:
                if candidate.memory_id == current.memory_id:
                    continue
                if candidate.observed_at >= current.observed_at:
                    continue
                shared_files = bool(current_files & self._fact_context_files(candidate))
                same_session = bool(
                    current.source_session
                    and current.source_session == candidate.source_session
                )
                if not shared_files and not same_session:
                    continue
                candidates.append(
                    (
                        int(same_session),
                        int(shared_files),
                        candidate.observed_at,
                        candidate,
                    )
                )
            candidates.sort(key=lambda item: item[:3], reverse=True)
            for same_session, shared_files, _observed_at, candidate in candidates[
                : self.MAX_TEMPORAL_LINKS_PER_FACT
            ]:
                edge_id = f"edge-{candidate.id}-{current.id}-before"
                existed = edge_id in self.edges
                self.add_edge(
                    candidate.id,
                    current.id,
                    "before",
                    weight=0.75 + 0.10 * same_session + 0.05 * shared_files,
                    edge_id=edge_id,
                )
                if not existed:
                    linked += 1
        return linked

    def _link_reflection_context(self, new_fact_ids: Iterable[str]) -> int:
        """Link a new reflection subgraph to older facts using exact signals.

        Cross-memory links are deliberately conservative: identical
        predicate/value pairs become ``same_as``; shared source files become
        low-weight ``similar``; lexical overlap can add an A-MEM-style note
        link when at least two meaningful tokens agree.  Generic compatibility
        facts are excluded so free-form text cannot create a dense, noisy
        graph.
        """

        new_facts = [
            self.facts[fact_id]
            for fact_id in new_fact_ids
            if fact_id in self.facts
        ]
        if not new_facts:
            return 0
        new_fact_ids_set = {fact.id for fact in new_facts}

        existing_facts = [
            fact
            for fact in self.facts.values()
            if fact.predicate != "memory"
            and fact.memory_id
            and fact.id not in new_fact_ids_set
        ]
        by_exact: dict[tuple[str, str], list[MemoryFact]] = defaultdict(list)
        by_file: dict[str, list[MemoryFact]] = defaultdict(list)
        by_token: dict[str, set[str]] = defaultdict(set)
        token_index: dict[str, set[str]] = {}
        for fact in existing_facts:
            by_exact[(fact.predicate, self._match_key(fact.value))].append(fact)
            for source_file in self._fact_context_files(fact):
                by_file[source_file].append(fact)
            fact_tokens = self._fact_link_tokens(fact)
            token_index[fact.id] = fact_tokens
            for token in fact_tokens:
                by_token[token].add(fact.id)

        linked = 0
        for fact in new_facts:
            if not fact.value:
                continue
            candidates: dict[str, tuple[str, float, int]] = {}
            exact_key = (fact.predicate, self._match_key(fact.value))
            for candidate in by_exact.get(exact_key, ()):
                if candidate.memory_id == fact.memory_id:
                    continue
                candidates[candidate.id] = ("same_as", 0.85, 2)

            for source_file in self._fact_context_files(fact):
                for candidate in by_file.get(source_file, ()):
                    if candidate.memory_id == fact.memory_id:
                        continue
                    decision_relation = self._decision_relation(fact, candidate)
                    if decision_relation is not None:
                        candidates[candidate.id] = (
                            decision_relation[0],
                            decision_relation[1],
                            3,
                        )
                        continue
                    if candidate.id not in candidates:
                        confidence_factor = 0.25 + 0.75 * candidate.confidence
                        candidates[candidate.id] = (
                            "similar",
                            0.35 * confidence_factor,
                            1,
                        )

            fact_tokens = self._fact_link_tokens(fact)
            token_candidates = {
                candidate_id
                for token in fact_tokens
                for candidate_id in by_token.get(token, ())
            }
            for candidate_id in token_candidates:
                candidate = self.facts[candidate_id]
                if candidate.memory_id == fact.memory_id or candidate_id in candidates:
                    continue
                candidate_tokens = token_index.get(candidate_id, set())
                overlap = fact_tokens & candidate_tokens
                union = fact_tokens | candidate_tokens
                similarity = len(overlap) / max(1, len(union))
                if len(overlap) >= 2 and similarity >= 0.25:
                    candidates[candidate_id] = (
                        "similar",
                        min(0.35, 0.12 + 0.5 * similarity),
                        len(overlap),
                    )

            ranked_candidates = [
                (relation, weight, overlap, self.facts[candidate_id])
                for candidate_id, (relation, weight, overlap) in candidates.items()
            ]
            ranked_candidates.sort(
                key=lambda item: (
                    item[2],
                    item[1],
                    item[3].confidence,
                    item[3].observed_at,
                ),
                reverse=True,
            )
            for relation, weight, _overlap, candidate in ranked_candidates[
                : self.MAX_CROSS_MEMORY_LINKS_PER_FACT
            ]:
                edge_id = f"edge-{fact.id}-{candidate.id}-{relation}"
                existed = edge_id in self.edges
                if relation == "supersedes":
                    self.supersede_fact(
                        fact.id,
                        candidate.id,
                        observed_at=fact.observed_at,
                        weight=weight,
                    )
                else:
                    self.add_edge(
                        fact.id,
                        candidate.id,
                        relation,
                        weight=weight,
                        edge_id=edge_id,
                    )
                if not existed:
                    linked += 1
        return linked

    def consolidate_pending(
        self,
        *,
        max_memories: int | None = None,
        persist: bool = True,
    ) -> int:
        """Run deferred cross-memory linking and temporal consolidation.

        The fast write path can persist facts and local ``contains`` edges
        first, then enqueue the expensive cross-memory work here.  This is the
        dual-stream boundary used by MAGMA and the sleep-time update idea from
        LightMem, while remaining deterministic and dependency-free.
        """

        pending = [fact_id for fact_id in self._pending_fact_ids if fact_id in self.facts]
        if not pending:
            return 0
        grouped: dict[str, list[str]] = defaultdict(list)
        for fact_id in pending:
            grouped[self.facts[fact_id].memory_id].append(fact_id)
        selected_groups = sorted(grouped.items())
        if max_memories is not None:
            selected_groups = selected_groups[: max(0, int(max_memories))]

        linked = 0
        processed: set[str] = set()
        for _memory_id, fact_ids in selected_groups:
            linked += self._link_reflection_context(fact_ids)
            linked += self._link_temporal_context(fact_ids)
            processed.update(fact_ids)
        self._pending_fact_ids.difference_update(processed)
        self._dirty = self._dirty or bool(processed)
        if persist and self._dirty:
            self.save()
        return linked

    def ingest_reflection(
        self,
        *,
        memory_id: str,
        scope: Any,
        task_description: str,
        metadata: dict[str, Any] | None = None,
        confidence: float = 0.5,
        execution_trace: Iterable[dict[str, Any]] = (),
        observed_at: float | None = None,
        persist: bool = True,
        consolidate: bool = True,
    ) -> int:
        """Turn a reflection result into a small, auditable fact subgraph."""

        metadata = metadata or {}
        now = observed_at if observed_at is not None else time.time()
        context_value = metadata.get("task_context") or {}
        context = context_value if isinstance(context_value, dict) else {}
        raw_files = context.get("files", ())
        if isinstance(raw_files, str):
            raw_files = (raw_files,)
        files = tuple(_clean_text(item) for item in raw_files if _clean_text(item))
        session_id, turn_index = self._trace_source(execution_trace)
        task_key = f"task:{memory_id}"
        task_fact = self.add_fact(
            fact_id=f"reflection:{memory_id}:task",
            memory_id=memory_id,
            scope=scope,
            subject=task_key,
            predicate="task",
            value=_clean_text(task_description),
            evidence=_clean_text(task_description),
            evidence_id=memory_id,
            source_session=session_id,
            source_turn=turn_index,
            source_files=files,
            observed_at=now,
            valid_from=now,
            confidence=confidence,
        )
        created = 1
        new_fact_ids = [task_fact.id]

        groups: list[tuple[str, Any]] = [
            ("decision", metadata.get("key_decisions", ())),
            ("encountered_error", metadata.get("errors", ())),
            ("lesson", metadata.get("lessons_learned", ())),
            ("suggested_improvement", metadata.get("improvements", ())),
            ("touches_file", context.get("files", ())),
            ("uses_library", context.get("libraries", ())),
            ("uses_tool", context.get("tools", ())),
        ]
        if context.get("project_state"):
            groups.append(("project_state", (context["project_state"],)))

        for predicate, values in groups:
            if isinstance(values, str):
                values = (values,)
            for value in values or ():
                value_text = _clean_text(value)
                if not value_text:
                    continue
                fact = self.add_fact(
                    memory_id=memory_id,
                    scope=scope,
                    subject=task_key,
                    predicate=predicate,
                    value=value_text,
                    evidence=value_text,
                    evidence_id=memory_id,
                    source_session=session_id,
                    source_turn=turn_index,
                    source_files=files,
                    observed_at=now,
                    valid_from=now,
                    confidence=confidence,
                )
                self.add_edge(task_fact.id, fact.id, "contains", weight=1.0)
                new_fact_ids.append(fact.id)
                created += 1

        if consolidate:
            self._link_reflection_context(new_fact_ids)
            self._link_temporal_context(new_fact_ids)
            self._pending_fact_ids.difference_update(new_fact_ids)
        else:
            self._pending_fact_ids.update(new_fact_ids)
            self._dirty = True

        if persist and self._dirty:
            self.save()
        return created

    @staticmethod
    def _trace_source(trace: Iterable[dict[str, Any]]) -> tuple[str, int | None]:
        session_id = ""
        turn_index: int | None = None
        for item in trace:
            if not isinstance(item, dict):
                continue
            session_id = session_id or _clean_text(
                item.get("session_id", item.get("sessionId", item.get("session", "")))
            )
            if turn_index is None:
                turn_index = _coerce_int(item.get("turn_index", item.get("turn", item.get("index"))))
            if session_id and turn_index is not None:
                break
        return session_id, turn_index

    def _valid_facts(
        self,
        *,
        as_of: float | None,
        scopes: set[str] | None,
    ) -> dict[str, MemoryFact]:
        # Generic ``memory:<entry-id>`` facts are a compatibility seed for
        # entries that have no typed graph representation.  Once an entry has
        # typed facts, keeping that generic copy in the candidate set would
        # let an un-timestamped stale text record bypass temporal filtering.
        # Prefer the typed facts for those entries while retaining the generic
        # fallback for legacy/unannotated memories.
        typed_memory_ids = {
            fact.memory_id
            for fact in self.facts.values()
            if fact.memory_id and fact.predicate != "memory"
        }
        return {
            fact_id: fact
            for fact_id, fact in self.facts.items()
            if fact.is_valid(as_of)
            and (scopes is None or fact.scope in scopes)
            and fact.value
            and not (
                fact.predicate == "memory"
                and fact.memory_id in typed_memory_ids
            )
        }

    def _historical_supersedes_targets(
        self,
        valid_facts: dict[str, MemoryFact],
        *,
        scopes: set[str] | None,
    ) -> dict[str, MemoryFact]:
        """Expose only directly evidenced prior states for an explicit request.

        A superseded fact normally stays out of the current valid set.  The
        ``older`` query policy is the one narrow exception: it may inspect the
        target of a currently valid direct ``supersedes`` edge, provided the
        newer source remains valid and the target is a real superseded fact.
        This helper deliberately does not make the old fact a general current
        candidate or expand through additional historical edges.
        """

        historical = dict(valid_facts)
        for edge in self.edges.values():
            if edge.relation != "supersedes" or not edge.is_valid(None):
                continue
            if edge.source_fact_id not in valid_facts:
                continue
            target = self.facts.get(edge.target_fact_id)
            if (
                target is None
                or target.status != "superseded"
                or target.valid_to is None
                or not target.memory_id
                or not target.value
                or (scopes is not None and target.scope not in scopes)
            ):
                continue
            historical[target.id] = target
        return historical

    def _valid_adjacency(
        self,
        valid_facts: dict[str, MemoryFact],
        *,
        as_of: float | None,
    ) -> dict[str, list[tuple[str, MemoryEdge]]]:
        adjacency: dict[str, list[tuple[str, MemoryEdge]]] = defaultdict(list)
        for edge in self.edges.values():
            if not edge.is_valid(as_of):
                continue
            if edge.source_fact_id not in valid_facts or edge.target_fact_id not in valid_facts:
                continue
            # Retrieval treats the graph as navigable in both directions while
            # retaining the stored direction and relation in the explanation.
            adjacency[edge.source_fact_id].append((edge.target_fact_id, edge))
            adjacency[edge.target_fact_id].append((edge.source_fact_id, edge))
        return adjacency

    @staticmethod
    def _effective_edge_weight(
        edge: MemoryEdge,
        relation_weights: Mapping[str, float] | None = None,
    ) -> float:
        """Apply base and query-specific relation priors to an edge."""

        prior = _RELATION_PRIORS.get(edge.relation, 0.5)
        policy_weight = 1.0
        if relation_weights is not None:
            policy_weight = max(0.05, float(relation_weights.get(edge.relation, 1.0)))
        return max(0.01, edge.weight * prior * policy_weight)

    @staticmethod
    def _lexical_score(query_tokens: set[str], fact: MemoryFact) -> float:
        fact_tokens = _tokens(fact.searchable_text)
        if not query_tokens or not fact_tokens:
            return 0.0
        overlap = len(query_tokens & fact_tokens)
        if not overlap:
            return 0.0
        coverage = overlap / max(1, len(query_tokens))
        exact_bonus = 0.15 if " ".join(sorted(query_tokens)) in fact.searchable_text.casefold() else 0.0
        predicate_bonus = 0.1 if fact.predicate in query_tokens else 0.0
        return min(1.0, coverage + exact_bonus + predicate_bonus)

    @staticmethod
    def _reachable(
        seeds: set[str],
        adjacency: dict[str, list[tuple[str, MemoryEdge]]],
        max_hops: int,
    ) -> set[str]:
        reachable = set(seeds)
        frontier = set(seeds)
        for _ in range(max(0, max_hops)):
            next_frontier: set[str] = set()
            for node in frontier:
                for neighbour, _ in adjacency.get(node, ()):
                    if neighbour not in reachable:
                        reachable.add(neighbour)
                        next_frontier.add(neighbour)
            frontier = next_frontier
            if not frontier:
                break
        return reachable

    @staticmethod
    def _path_to_seed(
        target: str,
        seeds: set[str],
        adjacency: dict[str, list[tuple[str, MemoryEdge]]],
        max_hops: int,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if target in seeds:
            return (target,), ()
        queue: deque[str] = deque([target])
        previous: dict[str, tuple[str, MemoryEdge] | None] = {target: None}
        distance: dict[str, int] = {target: 0}
        found: str | None = None
        while queue:
            current = queue.popleft()
            if current in seeds:
                found = current
                break
            if distance[current] >= max_hops:
                continue
            for neighbour, edge in adjacency.get(current, ()):
                if neighbour in previous:
                    continue
                previous[neighbour] = (current, edge)
                distance[neighbour] = distance[current] + 1
                queue.append(neighbour)
        if found is None:
            return (target,), ()

        nodes = [found]
        relations: list[str] = []
        current = found
        while current != target:
            parent_edge = previous[current]
            if parent_edge is None:
                break
            parent, edge = parent_edge
            nodes.append(parent)
            relations.append(edge.relation)
            current = parent
        return tuple(nodes), tuple(relations)

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        max_hops: int = 2,
        as_of: float | None = None,
        scopes: Iterable[Any] | None = None,
        relation_weights: Mapping[str, float] | None = None,
        seed_limit: int | None = None,
        supersedes_preference: str | None = None,
    ) -> list[GraphRetrieval]:
        """Return memory IDs reached from recognized lexical seeds through PPR.

        ``relation_weights`` is the query policy hook used by MAGMA-style
        intent routing.  ``seed_limit`` is a deterministic recognition-memory
        gate inspired by HippoRAG 2: weak lexical matches are not allowed to
        seed the whole graph before propagation. ``supersedes_preference`` is
        intentionally narrower: ``newer`` or ``older`` can mark only the
        requested endpoint of a directly evidenced, query-recognized state
        transition.
        """

        if not self.facts or limit <= 0:
            return []
        scope_key = (
            tuple(sorted(_normalise_scope(scope) for scope in scopes))
            if scopes is not None
            else None
        )
        policy_key = tuple(
            sorted(
                (
                    _clean_text(relation),
                    round(max(0.05, float(weight)), 6),
                )
                for relation, weight in (relation_weights or {}).items()
                if _clean_text(relation)
            )
        )
        effective_seed_limit = max(
            1,
            int(seed_limit)
            if seed_limit is not None
            else self.DEFAULT_RECOGNITION_SEED_LIMIT,
        )
        normalized_supersedes_preference = _clean_text(supersedes_preference).lower()
        if normalized_supersedes_preference not in {"newer", "older"}:
            normalized_supersedes_preference = ""
        cache_key = (
            _clean_text(query).casefold(),
            int(limit),
            int(max_hops),
            None if as_of is None else float(as_of),
            scope_key,
            policy_key,
            effective_seed_limit,
            normalized_supersedes_preference,
        )
        cached = self._search_cache.get(cache_key)
        now = time.monotonic()
        if cached is not None:
            cached_at, cached_results = cached
            if now - cached_at <= self.SEARCH_CACHE_TTL_SECONDS:
                self._search_cache_hits += 1
                return list(cached_results)
            self._search_cache.pop(cache_key, None)
        self._search_cache_misses += 1
        query_tokens = _tokens(_clean_text(query))
        valid_facts = self._valid_facts(
            as_of=as_of,
            scopes=set(scope_key) if scope_key is not None else None,
        )
        if normalized_supersedes_preference == "older" and as_of is None:
            valid_facts = self._historical_supersedes_targets(
                valid_facts,
                scopes=set(scope_key) if scope_key is not None else None,
            )
        if not query_tokens or not valid_facts:
            return []
        adjacency = self._valid_adjacency(valid_facts, as_of=as_of)
        lexical = {
            fact_id: self._lexical_score(query_tokens, fact)
            for fact_id, fact in valid_facts.items()
        }
        lexical = {fact_id: score for fact_id, score in lexical.items() if score > 0.0}
        if not lexical:
            return []

        recognized = sorted(
            lexical.items(),
            key=lambda item: (
                item[1] * (0.5 + 0.5 * valid_facts[item[0]].confidence),
                valid_facts[item[0]].confidence,
                valid_facts[item[0]].observed_at,
            ),
            reverse=True,
        )
        # Recognition memory keeps strong enough candidates but drops weak
        # lexical accidents (for example a generic "retry" token in an
        # unrelated decision) before they can become PPR teleport seeds.
        if recognized:
            recognition_floor = max(0.08, recognized[0][1] * 0.25)
            recognized = [
                item for item in recognized
                if item[1] >= recognition_floor
            ][:effective_seed_limit]
        seeds = {fact_id for fact_id, _score in recognized}
        preferred_supersedes_paths: dict[str, tuple[str, ...]] = {}
        if normalized_supersedes_preference:
            for edge in self.edges.values():
                if (
                    edge.relation != "supersedes"
                    or not edge.is_valid(as_of)
                    or edge.source_fact_id not in seeds
                    or edge.target_fact_id not in seeds
                ):
                    continue
                preferred_fact_id = (
                    edge.source_fact_id
                    if normalized_supersedes_preference == "newer"
                    else edge.target_fact_id
                )
                counterpart_fact_id = (
                    edge.target_fact_id
                    if normalized_supersedes_preference == "newer"
                    else edge.source_fact_id
                )
                existing = preferred_supersedes_paths.get(preferred_fact_id)
                candidate = (preferred_fact_id, counterpart_fact_id)
                if existing is None or candidate < existing:
                    preferred_supersedes_paths[preferred_fact_id] = candidate
        reachable = self._reachable(seeds, adjacency, max_hops=max_hops)
        seed_scores = {fact_id: lexical[fact_id] for fact_id in seeds}
        teleport_total = sum(seed_scores.values()) or 1.0
        teleport = {
            fact_id: seed_scores.get(fact_id, 0.0) / teleport_total
            for fact_id in seeds
        }
        rank = dict(teleport)
        for _ in range(12):
            next_rank = {
                fact_id: (1.0 - self.alpha) * teleport.get(fact_id, 0.0)
                for fact_id in reachable
            }
            for fact_id, value in rank.items():
                neighbours = [
                    (neighbour, edge)
                    for neighbour, edge in adjacency.get(fact_id, ())
                    if neighbour in reachable
                ]
                if not neighbours:
                    next_rank[fact_id] = next_rank.get(fact_id, 0.0) + self.alpha * value
                    continue
                total_weight = sum(
                    self._effective_edge_weight(edge, relation_weights=relation_weights)
                    for _, edge in neighbours
                )
                for neighbour, edge in neighbours:
                    edge_weight = self._effective_edge_weight(
                        edge,
                        relation_weights=relation_weights,
                    )
                    next_rank[neighbour] += (
                        self.alpha * value * edge_weight / total_weight
                    )
            rank = next_rank

        max_rank = max(rank.values(), default=1.0)
        by_memory: dict[str, list[tuple[float, MemoryFact]]] = defaultdict(list)
        for fact_id, fact in valid_facts.items():
            if fact_id not in reachable or not fact.memory_id:
                continue
            graph_score = 0.55 * (rank.get(fact_id, 0.0) / max_rank)
            graph_score += 0.45 * lexical.get(fact_id, 0.0)
            by_memory[fact.memory_id].append((graph_score, fact))

        results: list[GraphRetrieval] = []
        for memory_id, candidates in by_memory.items():
            candidates.sort(key=lambda item: (item[0], item[1].confidence), reverse=True)
            best_score, best_fact = candidates[0]
            preferred_candidates = [
                (score, fact)
                for score, fact in candidates
                if fact.id in preferred_supersedes_paths
            ]
            preferred_path: tuple[str, ...] = ()
            if preferred_candidates:
                best_score, best_fact = preferred_candidates[0]
                preferred_path = preferred_supersedes_paths[best_fact.id]
            # Recognition memory should prefer a well-supported fact over a
            # low-confidence lexical distractor when both share the same
            # graph path.
            best_score *= 0.5 + 0.5 * best_fact.confidence
            if preferred_path:
                path = preferred_path
                relations = ("supersedes",)
                evidence_facts = [best_fact]
                counterpart = valid_facts.get(preferred_path[-1])
                if counterpart is not None:
                    evidence_facts.append(counterpart)
            else:
                path, relations = self._path_to_seed(
                    best_fact.id,
                    seeds,
                    adjacency,
                    max_hops=max_hops,
                )
                evidence_facts = [fact for _, fact in candidates[:3]]
            evidence = tuple(
                fact.evidence or f"{fact.subject} {fact.predicate} {fact.value}"
                for fact in evidence_facts
            )
            results.append(
                GraphRetrieval(
                    memory_id=memory_id,
                    score=max(0.0, min(1.0, best_score)),
                    fact_ids=tuple(fact.id for _, fact in candidates[:3]),
                    evidence=evidence,
                    path=path,
                    relations=relations,
                    supersedes_preference=(
                        normalized_supersedes_preference if preferred_path else None
                    ),
                )
            )
        results.sort(key=lambda result: result.score, reverse=True)
        limited_results = tuple(results[:limit])
        if len(self._search_cache) >= self.SEARCH_CACHE_MAX_ENTRIES:
            oldest_key = min(
                self._search_cache,
                key=lambda key: self._search_cache[key][0],
            )
            self._search_cache.pop(oldest_key, None)
        self._search_cache[cache_key] = (now, limited_results)
        return list(limited_results)

    def stats(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "facts": self.fact_count,
            "edges": self.edge_count,
            "pending_facts": len(self._pending_fact_ids),
            "enabled": self.enabled,
            "storage_path": str(self.storage_path) if self.storage_path else None,
            "search_cache_hits": self._search_cache_hits,
            "search_cache_misses": self._search_cache_misses,
            "search_cache_size": len(self._search_cache),
        }

    @property
    def tracked_memory_ids(self) -> set[str]:
        """Return memory entries represented by at least one graph fact."""

        return {
            fact.memory_id
            for fact in self.facts.values()
            if fact.memory_id
        }

    def valid_memory_ids(
        self,
        *,
        as_of: float | None = None,
        scopes: Iterable[Any] | None = None,
    ) -> set[str]:
        """Return memory IDs with at least one usable fact at ``as_of``."""

        valid_facts = self._valid_facts(
            as_of=as_of,
            scopes={_normalise_scope(scope) for scope in scopes} if scopes is not None else None,
        )
        return {
            fact.memory_id
            for fact in valid_facts.values()
            if fact.memory_id
        }

    def superseded_memory_ids(
        self,
        predicates: Iterable[str],
        *,
        as_of: float | None = None,
    ) -> set[str]:
        """Return memories whose facts for ``predicates`` are all superseded."""

        predicate_set = {
            _clean_text(predicate).lower()
            for predicate in predicates
            if _clean_text(predicate)
        }
        valid_by_memory: set[str] = set()
        superseded_by_memory: set[str] = set()
        for fact in self.facts.values():
            if not fact.memory_id or fact.predicate not in predicate_set:
                continue
            if fact.is_valid(as_of):
                valid_by_memory.add(fact.memory_id)
            elif fact.status == "superseded":
                superseded_by_memory.add(fact.memory_id)
        return superseded_by_memory - valid_by_memory

    def conflicting_memory_ids(
        self,
        memory_id: str,
        *,
        as_of: float | None = None,
    ) -> set[str]:
        """Return memory IDs connected by currently valid ``contradicts`` edges."""

        valid_facts = self._valid_facts(as_of=as_of, scopes=None)
        conflicts: set[str] = set()
        for edge in self.edges.values():
            if edge.relation != "contradicts" or not edge.is_valid(as_of):
                continue
            source = valid_facts.get(edge.source_fact_id)
            target = valid_facts.get(edge.target_fact_id)
            if source is None or target is None:
                continue
            if source.memory_id == memory_id and target.memory_id != memory_id:
                conflicts.add(target.memory_id)
            elif target.memory_id == memory_id and source.memory_id != memory_id:
                conflicts.add(source.memory_id)
        return conflicts
