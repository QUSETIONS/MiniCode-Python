from __future__ import annotations

import math

import minicode.memory as memory_module
from minicode.memory import (
    MemoryEntry,
    MemoryFile,
    MemoryScope,
    _LARGE_CORPUS_SEARCH_STOPWORDS,
    _SEARCH_STOPWORDS,
    _bm25_score,
    _expand_query_terms,
    _search_tokens,
    _uses_large_corpus_stopwords,
)


def test_bm25_uses_raw_document_term_frequency():
    tokens = ["needle"] + ["noise"] * 99

    score = _bm25_score(["needle"], tokens, {"needle": 1.0}, avgdl=100.0)

    # k1=1.5 and b=0.75 give a denominator of 2.5 at average length;
    # raw tf=1 therefore produces a score of exactly 1.0.
    assert math.isclose(score, 1.0)


def test_memory_file_search_reuses_the_validated_idf_snapshot(monkeypatch):
    memory = MemoryFile(scope=MemoryScope.LOCAL, max_size_bytes=10_000)
    memory.add_entry(
        MemoryEntry(
            id="entry-1",
            scope=MemoryScope.LOCAL,
            category="general",
            content="needle fact",
        )
    )

    assert memory.search("needle")

    def fail_if_rebuilt(_documents):
        raise AssertionError("search should reuse the existing IDF snapshot")

    monkeypatch.setattr(memory_module, "_compute_idf", fail_if_rebuilt)

    assert memory.search("needle")


def test_conversational_query_expansion_bridges_common_paraphrases():
    expanded = _expand_query_terms(["preferred", "publications"])

    assert "preference" in expanded
    assert "prefer" in expanded
    assert "paper" in expanded
    assert "article" in expanded


def test_large_corpus_search_removes_filler_query_terms():
    query = "Can you recommend some resources for me?"

    normal = _search_tokens(query, stopwords=_SEARCH_STOPWORDS)
    large = _search_tokens(
        query,
        stopwords=_SEARCH_STOPWORDS | _LARGE_CORPUS_SEARCH_STOPWORDS,
    )

    assert "recommend" in normal
    assert "recommend" in large
    assert "you" in normal
    assert "you" not in large
    assert "some" not in large


def test_large_corpus_filtering_is_limited_to_broad_preference_queries():
    assert _uses_large_corpus_stopwords("Can you suggest a hotel?")
    assert _uses_large_corpus_stopwords("What is my preferred framework?")
    assert not _uses_large_corpus_stopwords("Which event happened first?")


def test_conversational_expansion_improves_preference_and_publication_lookup():
    memory = MemoryFile(scope=MemoryScope.LOCAL, max_size_bytes=10_000)
    target = MemoryEntry(
        id="target",
        scope=MemoryScope.LOCAL,
        category="general",
        content="The user would rather read research papers and articles.",
    )
    distractor = MemoryEntry(
        id="distractor",
        scope=MemoryScope.LOCAL,
        category="general",
        content="The user asked for hotel recommendations.",
    )
    memory.add_entry(target)
    memory.add_entry(distractor)

    results = memory.search("What is the user's preferred publication choice?")

    assert results
    assert results[0].id == "target"
