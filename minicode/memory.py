"""Layered memory system for cross-session knowledge retention.

Provides three-tier memory hierarchy:
- User memory (~/.mini-code/memory/) - cross-project, persistent
- Project memory (.mini-code-memory/) - shared across sessions, can be versioned
- Local memory (.mini-code-memory-local/) - project-specific, not checked in

Memory is automatically injected into system prompts to give the agent
context about past decisions, codebase patterns, and project conventions.

Search uses TF-IDF relevance scoring for intelligent retrieval.
"""

from __future__ import annotations

import functools
import json
import logging
import math
import os
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from minicode.config import MINI_CODE_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Memory data validation
# ---------------------------------------------------------------------------


def _validate_memory_data(data: dict) -> tuple[bool, list[str]]:
    """Validate the structure of memory JSON data before loading.

    Checks for:
    - Required fields present (entries)
    - Valid enum values for scope
    - Valid data types for all entry fields

    Args:
        data: Parsed JSON data dictionary

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return False, ["Root data must be a dictionary"]

    if "entries" not in data:
        errors.append("Missing required field: 'entries'")
        return False, errors

    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("'entries' must be a list")
        return False, errors

    for idx, entry_data in enumerate(entries):
        _, entry_errors = _validate_entry(entry_data, idx)
        errors.extend(entry_errors)

    return len(errors) == 0, errors


def _validate_entry(entry: Any, index: int) -> tuple[bool, list[str]]:
    """Validate a single memory entry dictionary.

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors: list[str] = []
    prefix = f"Entry at index {index}"

    if not isinstance(entry, dict):
        return False, [f"{prefix} is not a dictionary"]

    required_fields = ["id", "content"]
    for field_name in required_fields:
        if field_name not in entry:
            errors.append(f"{prefix} missing required field: '{field_name}'")

    if "id" in entry and not isinstance(entry["id"], str):
        errors.append(f"{prefix} field 'id' must be a string")

    if "scope" in entry:
        scope_val = entry["scope"]
        if not isinstance(scope_val, str):
            errors.append(f"{prefix} field 'scope' must be a string")
        elif scope_val not in _VALID_SCOPES:
            errors.append(
                f"{prefix} has invalid scope value: '{scope_val}'. "
                f"Must be one of: {', '.join(sorted(_VALID_SCOPES))}"
            )

    if "category" in entry and not isinstance(entry["category"], str):
        errors.append(f"{prefix} field 'category' must be a string")

    if "content" in entry and not isinstance(entry["content"], str):
        errors.append(f"{prefix} field 'content' must be a string")

    if "created_at" in entry:
        val = entry["created_at"]
        if not isinstance(val, (int, float)):
            errors.append(f"{prefix} field 'created_at' must be a number")

    if "updated_at" in entry:
        val = entry["updated_at"]
        if not isinstance(val, (int, float)):
            errors.append(f"{prefix} field 'updated_at' must be a number")

    if "tags" in entry:
        val = entry["tags"]
        if not isinstance(val, list):
            errors.append(f"{prefix} field 'tags' must be a list")
        elif not all(isinstance(t, str) for t in val):
            errors.append(f"{prefix} field 'tags' must contain only strings")

    if "usage_count" in entry:
        val = entry["usage_count"]
        if not isinstance(val, int):
            errors.append(f"{prefix} field 'usage_count' must be an integer")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Corrupted data recovery
# ---------------------------------------------------------------------------

def _recover_entries(data: dict, memory_json_path: Path) -> list[dict]:
    """Attempt to recover valid entries from corrupted memory data.

    Creates a backup of the corrupted file and returns only valid entries.

    Args:
        data: Parsed JSON data (may be partially corrupted)
        memory_json_path: Path to the original memory.json file

    Returns:
        List of valid entry dictionaries
    """
    backup_path = memory_json_path.with_suffix(".json.bak")
    try:
        import shutil
        shutil.copy2(str(memory_json_path), str(backup_path))
        logger.warning(
            "Corrupted memory file backed up to %s", backup_path
        )
    except OSError as e:
        logger.error(
            "Failed to create backup of corrupted memory file: %s", e
        )

    entries = data.get("entries", [])
    valid_entries = []
    recovered_count = 0

    for idx, entry_data in enumerate(entries):
        entry_valid, _ = _validate_entry(entry_data, idx)
        if not entry_valid:
            logger.warning("Skipping corrupted entry at index %d", idx)
        else:
            valid_entries.append(entry_data)
            recovered_count += 1

    total = len(entries)
    logger.info(
        "Recovery complete: %d/%d entries recovered", recovered_count, total
    )
    return valid_entries




# ---------------------------------------------------------------------------
# TF-IDF search utilities
# ---------------------------------------------------------------------------

# Tokenize text into lowercase words, individual CJK chars, and CJK bigrams
_WORD_RE = re.compile(r'[a-zA-Z0-9]+|[\u4e00-\u9fff]')
_CJK_BIGRAM_RE = re.compile(r'[\u4e00-\u9fff]{2}')

# Query-only stopwords keep natural-language questions from matching every
# memory through terms such as "what", "is", and "the".  They are removed
# from retrieval scoring, while stored memory text remains untouched.
_SEARCH_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "this",
        "to",
        "use",
        "using",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "would",
    }
)

# Very large conversational indexes contain many filler turns with generic
# request language.  At that scale, pronouns and polite scaffolding dominate
# document frequency more easily than they do in the normal project-memory
# file, so the search path becomes stricter without changing stored content.
_LARGE_CORPUS_SEARCH_STOPWORDS = frozenset(
    {
        "also",
        "any",
        "around",
        "find",
        "get",
        "give",
        "i",
        "just",
        "like",
        "many",
        "me",
        "might",
        "mine",
        "more",
        "much",
        "my",
        "one",
        "please",
        "really",
        "some",
        "still",
        "tell",
        "thing",
        "things",
        "think",
        "thinking",
        "we",
        "would",
        "you",
        "your",
        "yours",
    }
)
_LARGE_CORPUS_THRESHOLD = 1000
_LARGE_CORPUS_QUERY_MARKERS = (
    "recommend",
    "suggest",
    "advice",
    "tips",
    "ideas",
    "what should",
    "what do you think",
    "choose",
    "choice",
    "prefer",
    "preference",
    "推荐",
    "建议",
    "偏好",
    "选择",
)


def _uses_large_corpus_stopwords(query: str) -> bool:
    """Return whether a query is broad enough to need stricter filtering."""

    lowered = query.lower()
    return any(marker in lowered for marker in _LARGE_CORPUS_QUERY_MARKERS)

# Common code terminology expansions (bidirectional)
_CODE_TERM_EXPANSIONS: dict[str, list[str]] = {
    "函数": ["function", "func", "method"],
    "function": ["函数", "func", "method"],
    "func": ["函数", "function", "method"],
    "method": ["函数", "function", "func"],
    "类": ["class", "type"],
    "class": ["类", "type"],
    "type": ["类", "class"],
    "变量": ["variable", "var"],
    "variable": ["变量", "var"],
    "var": ["变量", "variable"],
    "参数": ["parameter", "param", "argument", "arg"],
    "parameter": ["参数", "param", "argument"],
    "param": ["参数", "parameter", "arg"],
    "argument": ["参数", "parameter", "arg"],
    "属性": ["attribute", "attr", "property", "prop"],
    "attribute": ["属性", "attr", "property"],
    "property": ["属性", "attr", "prop"],
    "接口": ["interface"],
    "interface": ["接口"],
    "模块": ["module"],
    "module": ["模块"],
    "包": ["package"],
    "package": ["包"],
    "方法": ["method", "function"],
    "对象": ["object", "obj"],
    "object": ["对象", "obj"],
    "继承": ["inherit", "inheritance", "extends"],
    "inherit": ["继承"],
    "多态": ["polymorphism"],
    "封装": ["encapsulation", "encapsulate"],
    "异常": ["exception", "error"],
    "exception": ["异常"],
    "error": ["错误", "异常"],
    "错误": ["error", "bug"],
    "bug": ["错误", "bug", "缺陷"],
    "循环": ["loop", "iteration", "iterate"],
    "loop": ["循环"],
    "条件": ["condition"],
    "condition": ["条件"],
    "数组": ["array"],
    "array": ["数组"],
    "列表": ["list"],
    "list": ["列表"],
    "字典": ["dict", "dictionary", "map"],
    "dict": ["字典", "dictionary"],
    "dictionary": ["字典", "dict"],
    "map": ["字典", "映射"],
    "映射": ["map"],
    "集合": ["set"],
    "set": ["集合"],
    "字符串": ["string", "str"],
    "string": ["字符串"],
    "整数": ["int", "integer"],
    "integer": ["整数"],
    "浮点": ["float"],
    "float": ["浮点"],
    "布尔": ["bool", "boolean"],
    "boolean": ["布尔"],
    "同步": ["sync", "synchronous"],
    "异步": ["async", "asynchronous"],
    "async": ["异步"],
    "回调": ["callback"],
    "callback": ["回调"],
    "事件": ["event"],
    "event": ["事件"],
    "装饰器": ["decorator"],
    "decorator": ["装饰器"],
    "生成器": ["generator"],
    "generator": ["生成器"],
    "迭代器": ["iterator"],
    "iterator": ["迭代器"],
    "测试": ["test", "testing"],
    "test": ["测试"],
    "调试": ["debug", "debugging"],
    "debug": ["调试"],
    "配置": ["config", "configuration"],
    "config": ["配置"],
    "数据库": ["database", "db"],
    "database": ["数据库", "db"],
    "缓存": ["cache"],
    "cache": ["缓存"],
    "队列": ["queue"],
    "queue": ["队列"],
    "栈": ["stack"],
    "stack": ["栈"],
    "树": ["tree"],
    "tree": ["树"],
    "图": ["graph"],
    "graph": ["图"],
    "搜索": ["search"],
    "search": ["搜索"],
    "排序": ["sort", "sorting"],
    "sort": ["排序"],
    "文件": ["file"],
    "file": ["文件"],
    "路径": ["path"],
    "path": ["路径"],
    "网络": ["network"],
    "network": ["网络"],
    "请求": ["request"],
    "request": ["请求"],
    "响应": ["response"],
    "response": ["响应"],
}

# Lightweight conversational expansions for natural-language memory queries.
#
# Long-term memory questions often paraphrase the wording used when a memory
# was written ("recommend" vs. "suggest", "publication" vs. "paper", or
# "prefer" vs. "favorite").  These aliases stay query-side only: they do not
# mutate stored memories and they do not replace the exact lexical signal.
# This is the deterministic counterpart of an index-expansion pass, so it is
# safe to use when no LLM reranker or embedding model is available.
_CONVERSATIONAL_TERM_EXPANSIONS: dict[str, list[str]] = {
    "recommend": ["suggest", "recommendation", "advice", "advise"],
    "suggest": ["recommend", "recommendation", "advice"],
    "recommendation": ["recommend", "suggest", "advice"],
    "publication": ["paper", "article", "research"],
    "publications": ["publication", "paper", "article", "research"],
    "conference": ["symposium", "event", "meeting"],
    "movie": ["film", "show", "series"],
    "film": ["movie", "show", "series"],
    "show": ["movie", "film", "series", "program"],
    "activity": ["activities", "things", "entertainment", "recreation"],
    "activities": ["activity", "things", "entertainment", "recreation"],
    "dinner": ["meal", "dish", "recipe", "food"],
    "meal": ["dinner", "dish", "recipe", "food"],
    "hotel": ["lodging", "accommodation", "room", "stay"],
    "trip": ["travel", "vacation", "journey"],
    "preference": ["prefer", "favorite", "like", "choice"],
    "preferences": ["preference", "prefer", "favorite", "like", "choice"],
    "prefer": ["preference", "favorite", "like", "choose", "choice"],
    "preferred": ["preference", "prefer", "favorite", "choice"],
    "favorite": ["preference", "prefer", "like"],
    "choose": ["choice", "select", "pick", "prefer"],
    "choice": ["choose", "select", "pick", "prefer"],
    "said": ["say", "mention", "tell", "explain"],
    "say": ["said", "mention", "tell", "explain"],
    "previously": ["before", "earlier", "prior"],
    "remember": ["recall", "previously", "before"],
}


def _expand_query_terms(terms: list[str], active_domains: list[str] | None = None) -> list[str]:
    """Expand query terms using code terminology + domain-specific dictionaries."""
    expanded = list(terms)
    for term in terms:
        if term in _CODE_TERM_EXPANSIONS:
            expanded.extend(_CODE_TERM_EXPANSIONS[term])
        if term in _CONVERSATIONAL_TERM_EXPANSIONS:
            expanded.extend(_CONVERSATIONAL_TERM_EXPANSIONS[term])
    # Domain-specific expansions
    if active_domains:
        for domain in active_domains:
            domain_dict = _DOMAIN_TERM_EXPANSIONS.get(domain, {})
            for term in terms:
                if term in domain_dict:
                    expanded.extend(domain_dict[term])
    return expanded


# ── Domain-specific term expansions ─────────────────────────────────

_DOMAIN_TERM_EXPANSIONS: dict[str, dict[str, list[str]]] = {
    "frontend": {
        "component": ["组件", "widget", "control", "element"],
        "组件": ["component", "widget", "control"],
        "form": ["表单", "input", "field"],
        "表单": ["form", "input", "field"],
        "style": ["样式", "css", "theme", "design"],
        "样式": ["style", "css", "theme"],
        "css": ["样式", "style", "theme", "tailwind"],
        "render": ["渲染", "display", "paint"],
        "渲染": ["render", "display"],
        "state": ["状态", "store", "context"],
        "状态": ["state", "store"],
        "hook": ["hooks", "钩子"],
        "router": ["路由", "navigation"],
        "路由": ["router", "navigation", "route"],
        "button": ["按钮", "btn"],
        "modal": ["弹窗", "dialog", "popup"],
        "layout": ["布局", "grid", "flex"],
        "布局": ["layout", "grid", "flexbox"],
        "animation": ["动画", "transition", "motion"],
        "event": ["事件", "handler", "listener"],
        "props": ["属性", "properties", "parameters"],
        "dom": ["文档", "document", "node", "element"],
        "responsive": ["响应式", "adaptive", "mobile"],
        "typescript": ["ts", "type"],
    },
    "backend": {
        "api": ["端点", "endpoint", "路由", "route", "handler"],
        "endpoint": ["端点", "api", "路由"],
        "route": ["路由", "path", "endpoint", "api"],
        "auth": ["认证", "鉴权", "login", "token", "jwt", "oauth"],
        "认证": ["auth", "authentication", "login"],
        "middleware": ["中间件", "interceptor", "filter"],
        "中间件": ["middleware", "interceptor"],
        "request": ["请求", "req"],
        "response": ["响应", "res", "reply"],
        "server": ["服务器", "服务端", "host"],
        "服务器": ["server", "host"],
        "queue": ["队列", "message", "mq", "worker"],
        "队列": ["queue", "message", "worker"],
        "cache": ["缓存", "redis", "memcache"],
        "缓存": ["cache", "redis"],
        "cron": ["定时", "schedule", "job", "task"],
        "定时": ["cron", "schedule", "timer"],
        "log": ["日志", "logging", "trace"],
        "日志": ["log", "logging"],
        "validate": ["校验", "验证", "sanitize", "check"],
        "校验": ["validate", "validation", "check"],
        "rate limit": ["限流", "throttle", "quota"],
        "限流": ["rate limit", "throttle"],
        "serialize": ["序列化", "marshal", "json"],
        "序列化": ["serialize", "marshal"],
    },
    "database": {
        "migration": ["迁移", "schema change", "ddl", "alembic", "flyway"],
        "迁移": ["migration", "schema change"],
        "schema": ["模式", "结构", "ddl", "table def"],
        "query": ["查询", "select", "sql"],
        "查询": ["query", "select", "read"],
        "index": ["索引", "btree", "hash"],
        "索引": ["index", "lookup"],
        "transaction": ["事务", "commit", "rollback", "acid"],
        "事务": ["transaction", "commit"],
        "connection": ["连接", "pool", "session"],
        "连接": ["connection", "pool"],
        "postgres": ["postgresql", "pg"],
        "orm": ["prisma", "typeorm", "sequelize", "drizzle", "sqlalchemy"],
        "backup": ["备份", "dump", "restore"],
        "备份": ["backup", "dump"],
        "replica": ["副本", "standby", "slave"],
        "partition": ["分区", "shard", "split"],
    },
    "devops": {
        "deploy": ["部署", "release", "ship"],
        "部署": ["deploy", "release"],
        "docker": ["容器", "container", "image"],
        "容器": ["docker", "container"],
        "ci": ["持续集成", "pipeline", "build"],
        "pipeline": ["流水线", "ci/cd", "workflow"],
        "monitor": ["监控", "alert", "observe", "metrics"],
        "监控": ["monitor", "alert", "metrics"],
        "secret": ["密钥", "credentials", "env"],
        "密钥": ["secret", "credentials", "token"],
        "kubernetes": ["k8s", "pod", "cluster"],
        "k8s": ["kubernetes", "cluster"],
        "nginx": ["反向代理", "proxy", "gateway"],
        "terraform": ["基础设施", "infrastructure", "iac"],
        "log": ["日志", "logging", "收集", "aggregate"],
        "backup": ["备份", "snapshot", "restore"],
    },
    "testing": {
        "test": ["测试", "spec", "assert"],
        "mock": ["模拟", "stub", "fake", "spy"],
        "模拟": ["mock", "stub", "fake"],
        "assert": ["断言", "expect", "should"],
        "断言": ["assert", "expect"],
        "coverage": ["覆盖率", "cover"],
        "e2e": ["端到端", "end-to-end", "integration"],
        "unit": ["单元", "unit test"],
        "fixture": ["夹具", "setup", "teardown"],
        "regression": ["回归", "replay"],
    },
}


@functools.lru_cache(maxsize=1024)
def _tokenize(text: str) -> list[str]:
    """Tokenize text into words for TF-IDF scoring.

    Handles alphanumeric words, individual CJK characters, and CJK bigrams
    for better Chinese text semantic matching.
    """
    tokens = [w.lower() for w in _WORD_RE.findall(text)]
    cjk_bigrams = [match.lower() for match in _CJK_BIGRAM_RE.findall(text)]
    return tokens + cjk_bigrams


def _search_tokens(
    text: str,
    *,
    stopwords: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Tokenize a query and remove generic question/function words."""

    blocked = _SEARCH_STOPWORDS if stopwords is None else stopwords
    return [token for token in _tokenize(text) if token not in blocked]


# BM25 parameters
_BM25_K1 = 1.5  # Term frequency scaling
_BM25_B = 0.75  # Document length normalization


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    """Compute term frequency for a list of tokens."""
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {term: count / total for term, count in counts.items()}


def _compute_idf(documents: list[list[str]]) -> dict[str, float]:
    """Compute inverse document frequency across documents.

    Uses smoothed IDF formula: log((N + 1) / (df + 1)) + 1
    """
    n = len(documents)
    if n == 0:
        return {}
    doc_freq: dict[str, int] = {}
    for doc_tokens in documents:
        seen = set(doc_tokens)
        for term in seen:
            doc_freq[term] = doc_freq.get(term, 0) + 1
    return {
        term: math.log((n + 1) / (df + 1)) + 1
        for term, df in doc_freq.items()
    }


def _compute_avgdl(documents: list[list[str]]) -> float:
    """Compute average document length."""
    if not documents:
        return 0.0
    return sum(len(doc) for doc in documents) / len(documents)


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    idf: dict[str, float],
    avgdl: float,
    *,
    k1: float = _BM25_K1,
    b: float = _BM25_B,
) -> float:
    """Compute Okapi BM25 score between query and document.

    Formula:
        score(q,d) = sum(IDF(qi) * (tf(qi,d) * (k1 + 1)) /
                         (tf(qi,d) + k1 * (1 - b + b * |d|/avgdl)))
    """
    if not query_tokens or not doc_tokens or avgdl == 0:
        return 0.0

    doc_len = len(doc_tokens)
    # Okapi BM25 uses the raw document term frequency.  Normalising by the
    # document length here double-counts length normalisation and heavily
    # suppresses relevant terms in long-session memories.
    tf_doc = Counter(doc_tokens)
    total_tokens = doc_len

    score = 0.0
    for term in set(query_tokens):
        if term not in idf:
            continue
        tf = float(tf_doc.get(term, 0))
        if tf == 0:
            continue
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * (total_tokens / avgdl))
        score += idf[term] * (numerator / denominator)

    return score


def _tfidf_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    idf: dict[str, float],
    avgdl: float = 0.0,
) -> float:
    """Compute BM25 score between query and document.

    Note: This function name is kept for backward compatibility but now
    uses BM25 scoring internally for better short-text ranking.
    """
    return _bm25_score(query_tokens, doc_tokens, idf, avgdl)


def get_tfidf_keywords(text: str, top_n: int = 10) -> list[tuple[str, float]]:
    """Extract top N most important terms from text using TF scores.

    Useful for auto-categorization and understanding key topics in text.

    Args:
        text: Input text to analyze
        top_n: Number of top keywords to return

    Returns:
        List of (term, tf_score) tuples sorted by importance
    """
    tokens = _tokenize(text)
    if not tokens:
        return []
    tf = _compute_tf(tokens)
    sorted_terms = sorted(tf.items(), key=lambda x: x[1], reverse=True)
    return sorted_terms[:top_n]


# ---------------------------------------------------------------------------
# Auto-classification heuristics
# ---------------------------------------------------------------------------

_CLASSIFICATION_RULES: list[tuple[str, list[str], list[str]]] = [
    ("architecture", ["architecture", "design", "pattern", "api", "rest", "backend", "service", "架构", "设计", "模式"]),
    ("code-pattern", ["function", "method", "def", "class", "函数", "方法", "类"]),
    ("testing", ["test", "assert", "pytest", "unit", "测试", "断言"]),
    ("configuration", ["config", "settings", "env", "配置", "设置", "环境"]),
    ("workflow", ["git", "commit", "branch", "merge", "工作流", "分支", "合并"]),
    ("security", ["security", "auth", "permission", "安全", "认证", "权限"]),
    ("performance", ["performance", "optimization", "benchmark", "性能", "优化", "基准"]),
    ("convention", ["convention", "style", "naming", "规范", "风格", "命名"]),
]


def _auto_classify_content(content: str) -> tuple[str, list[str]]:
    """Analyze content and return (category, tags) using keyword heuristics.

    Supports both English and Chinese keywords. Returns "general" category
    with empty tags if no classification rules match.

    Args:
        content: Text content to classify

    Returns:
        Tuple of (category, tags) - e.g., ("architecture", ["design-pattern"])
    """
    content_lower = content.lower()
    category_scores: dict[str, int] = {}
    matched_tags: list[str] = []

    category_to_tags = {
        "architecture": ["design-pattern"],
        "code-pattern": ["function"],
        "testing": ["test"],
        "configuration": ["config"],
        "workflow": ["git"],
        "security": ["security"],
        "performance": ["optimization"],
        "convention": ["style"],
    }

    for category, keywords in (
        (rule[0], rule[1]) for rule in _CLASSIFICATION_RULES
    ):
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            category_scores[category] = score
            matched_tags.extend(category_to_tags.get(category, []))

    if not category_scores:
        return "general", []

    best_category = max(category_scores, key=category_scores.get)
    return best_category, matched_tags


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class MemoryScope(str, Enum):
    """Memory scope levels."""
    USER = "user"       # Cross-project, ~/.mini-code/memory/
    PROJECT = "project" # Project-shared, .mini-code-memory/
    LOCAL = "local"     # Project-local, .mini-code-memory-local/


class MemoryTier(str, Enum):
    """Memory tier for multi-level storage architecture.

    Inspired by human memory models (Atkinson-Shiffrin) and Letta/MemGPT:
      WORKING    → current session, full detail, fast access
      SHORT_TERM → recent (< 7 days), full detail
      LONG_TERM  → consolidated (< 30 days), compressed
      ARCHIVAL   → permanent, heavily summarized
    """
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    ARCHIVAL = "archival"


_VALID_SCOPES = {m.value for m in MemoryScope}


@dataclass
class MemoryEntry:
    """A single memory entry (fact, pattern, decision, etc.)."""
    id: str
    scope: MemoryScope
    category: str  # e.g., "architecture", "convention", "decision", "pattern"
    content: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    usage_count: int = 0  # How often this was referenced
    domains: list[str] = field(default_factory=list)  # Domain classification
    # Multi-tier memory architecture
    tier: MemoryTier = MemoryTier.SHORT_TERM
    last_accessed: float = field(default_factory=time.time)
    related_to: list[str] = field(default_factory=list)  # Related memory IDs
    _cached_tokens: list[str] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # `content` is accessed as a str throughout search/scoring/formatting
        # (8+ sites use .lower()/.strip()/[:N]); coerce None/non-str at
        # construction so a malformed entry can't crash a memory search, which
        # is injected into every system prompt.
        if not isinstance(self.content, str):
            self.content = "" if self.content is None else str(self.content)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MemoryEntry):
            return NotImplemented
        return self.id == other.id

    def get_tokens(self) -> list[str]:
        if self._cached_tokens is None:
            text = f"{self.content} {self.category} {' '.join(self.tags)}"
            self._cached_tokens = _tokenize(text)
        return self._cached_tokens

    def invalidate_tokens(self) -> None:
        self._cached_tokens = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "scope": self.scope.value,
            "category": self.category,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "usage_count": self.usage_count,
            "domains": self.domains,
            "tier": self.tier.value,
            "last_accessed": self.last_accessed,
            "related_to": self.related_to,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEntry":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            scope=MemoryScope(data.get("scope", "user")),
            category=data.get("category", "general"),
            content=data["content"],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            tags=data.get("tags", []),
            usage_count=data.get("usage_count", 0),
            domains=data.get("domains", []),
            tier=MemoryTier(data.get("tier", "short_term")),
            last_accessed=data.get("last_accessed", time.time()),
            related_to=data.get("related_to", []),
        )


@dataclass
class MemoryFile:
    """Represents a MEMORY.md file content with indexed lookups."""
    scope: MemoryScope
    entries: list[MemoryEntry] = field(default_factory=list)
    max_entries: int = 200  # Claude Code limit
    max_size_bytes: int = 25 * 1024  # 25KB limit
    _id_index: dict[str, MemoryEntry] = field(default_factory=dict, repr=False)
    _tag_index: dict[str, set[MemoryEntry]] = field(default_factory=dict, repr=False)
    _category_index: dict[str, list[MemoryEntry]] = field(default_factory=dict, repr=False)
    _tokens_cache: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _idf_cache: dict[str, float] | None = field(default=None, repr=False)
    _avgdl_cache: float | None = field(default=None, repr=False)
    _cache_dirty: bool = field(default=True, repr=False)
    _index_signature: tuple[tuple[str, str, tuple[str, ...], str], ...] = field(
        default_factory=tuple, repr=False
    )

    def _current_index_signature(self) -> tuple[tuple[str, str, tuple[str, ...], str], ...]:
        """Return the fields used by the secondary indexes.

        ``entries`` is intentionally a public list for backwards compatibility,
        so callers can mutate it directly.  The signature lets the manager
        detect those mutations before serving an indexed lookup.
        """
        return tuple(
            (entry.id, entry.category, tuple(entry.tags), entry.content)
            for entry in self.entries
        )

    def _rebuild_indices(self) -> None:
        self._id_index.clear()
        self._tag_index.clear()
        self._category_index.clear()
        self._tokens_cache.clear()
        self._idf_cache = None
        self._avgdl_cache = None
        for entry in self.entries:
            self._id_index[entry.id] = entry
            for tag in entry.tags:
                if tag not in self._tag_index:
                    self._tag_index[tag] = set()
                self._tag_index[tag].add(entry)
            cat = entry.category
            if cat not in self._category_index:
                self._category_index[cat] = []
            self._category_index[cat].append(entry)
            self._tokens_cache[entry.id] = entry.get_tokens()
        # Precompute IDF and avgdl
        if self._tokens_cache:
            all_tokens = list(self._tokens_cache.values())
            self._idf_cache = _compute_idf(all_tokens)
            self._avgdl_cache = _compute_avgdl(all_tokens)
        self._cache_dirty = False
        self._index_signature = self._current_index_signature()

    def _ensure_cache_valid(self) -> None:
        if self._cache_dirty or self._index_signature != self._current_index_signature():
            self._rebuild_indices()

    def _invalidate_cache(self) -> None:
        self._cache_dirty = True
        self._idf_cache = None
        self._avgdl_cache = None

    def _invalidate_search_cache(self) -> None:
        """Invalidate ranking caches without discarding maintained indexes."""
        self._idf_cache = None
        self._avgdl_cache = None

    def _remove_from_indices(self, entry: MemoryEntry) -> None:
        """Remove one entry from every maintained index.

        The identity check on ``_id_index`` matters for legacy files that may
        contain duplicate IDs: removing an older duplicate must not delete the
        newer entry that currently owns the ID lookup slot.
        """
        indexed = self._id_index.get(entry.id)
        if indexed is entry:
            self._id_index.pop(entry.id, None)
            self._tokens_cache.pop(entry.id, None)

        for tag in entry.tags:
            tagged = self._tag_index.get(tag)
            if tagged is None:
                continue
            tagged.discard(entry)
            if not tagged:
                self._tag_index.pop(tag, None)

        category_entries = self._category_index.get(entry.category)
        if category_entries is not None:
            self._category_index[entry.category] = [
                candidate for candidate in category_entries if candidate is not entry
            ]
            if not self._category_index[entry.category]:
                self._category_index.pop(entry.category, None)

    @property
    def size_bytes(self) -> int:
        """Estimate size in bytes."""
        return sum(len(e.content) for e in self.entries)
    
    def add_entry(self, entry: MemoryEntry) -> None:
        """Add entry, respecting limits. Maintains indices incrementally."""
        self._ensure_cache_valid()
        self.entries.append(entry)
        self._id_index[entry.id] = entry
        for tag in entry.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(entry)
        cat = entry.category
        if cat not in self._category_index:
            self._category_index[cat] = []
        self._category_index[cat].append(entry)
        self._tokens_cache[entry.id] = entry.get_tokens()
        self._enforce_limits()
        self._invalidate_search_cache()
        self._index_signature = self._current_index_signature()
    
    def update_entry(self, entry_id: str, content: str) -> bool:
        """Update existing entry using index."""
        self._ensure_cache_valid()
        entry = self._id_index.get(entry_id)
        if entry is None:
            return False
        entry.content = content
        entry.updated_at = time.time()
        entry.invalidate_tokens()
        self._tokens_cache[entry.id] = entry.get_tokens()
        self._invalidate_search_cache()
        self._index_signature = self._current_index_signature()
        return True
    
    def delete_entry(self, entry_id: str) -> bool:
        """Delete entry using index."""
        self._ensure_cache_valid()
        entry = self._id_index.get(entry_id)
        if entry is None:
            return False
        if not any(candidate is entry for candidate in self.entries):
            # Be defensive when loading a legacy file or after a caller has
            # mutated the public entries list directly.
            self._rebuild_indices()
            entry = self._id_index.get(entry_id)
            if entry is None or not any(candidate is entry for candidate in self.entries):
                return False
        for index, candidate in enumerate(self.entries):
            if candidate is entry:
                del self.entries[index]
                break
        else:
            return False
        self._remove_from_indices(entry)
        self._invalidate_search_cache()
        self._index_signature = self._current_index_signature()
        return True

    def add_tag(self, entry_id: str, tag: str) -> bool:
        """Add a tag while keeping tag and token indexes synchronized."""
        self._ensure_cache_valid()
        entry = self._id_index.get(entry_id)
        if entry is None or not tag or tag in entry.tags:
            return entry is not None
        entry.tags.append(tag)
        self._tag_index.setdefault(tag, set()).add(entry)
        entry.invalidate_tokens()
        self._tokens_cache[entry.id] = entry.get_tokens()
        self._invalidate_search_cache()
        self._index_signature = self._current_index_signature()
        return True

    def remove_tag(self, entry_id: str, tag: str) -> bool:
        """Remove a tag while keeping tag and token indexes synchronized."""
        self._ensure_cache_valid()
        entry = self._id_index.get(entry_id)
        if entry is None or tag not in entry.tags:
            return entry is not None
        entry.tags.remove(tag)
        tagged = self._tag_index.get(tag)
        if tagged is not None:
            tagged.discard(entry)
            if not tagged:
                self._tag_index.pop(tag, None)
        entry.invalidate_tokens()
        self._tokens_cache[entry.id] = entry.get_tokens()
        self._invalidate_search_cache()
        self._index_signature = self._current_index_signature()
        return True
    
    def get_entries_by_category(self, category: str) -> list[MemoryEntry]:
        """Get entries filtered by category using index."""
        self._ensure_cache_valid()
        return list(self._category_index.get(category, []))
    
    def search(
        self,
        query: str,
        active_domains: list[str] | None = None,
        *,
        record_usage: bool = True,
    ) -> list[MemoryEntry]:
        """Search entries by keyword with BM25 + domain relevance scoring.

        Combines BM25 semantic relevance with usage frequency and optional
        domain-based boosting (soft blend, not hard filtering).
        Domain score uses Jaccard similarity between entry domains and active domains.
        """
        if not self.entries:
            return []

        self._ensure_cache_valid()

        # Snapshot entries so concurrent add_entry/_enforce_limits can't shift
        # indices between the two loops below (was: "list index out of range"
        # when another thread appended between building entry_tokens and the
        # scoring loop).
        entries = list(self.entries)

        search_stopwords = _SEARCH_STOPWORDS
        if (
            len(entries) >= _LARGE_CORPUS_THRESHOLD
            and _uses_large_corpus_stopwords(query)
        ):
            search_stopwords = _SEARCH_STOPWORDS | _LARGE_CORPUS_SEARCH_STOPWORDS

        query_tokens = _search_tokens(query, stopwords=search_stopwords)
        query_tokens = _expand_query_terms(query_tokens, active_domains=active_domains)
        if not query_tokens:
            return []

        query_lower = query.lower()
        query_terms = _search_tokens(query, stopwords=search_stopwords)

        # _rebuild_indices() already prepares the stable token/IDF snapshot;
        # reuse it across repeated reads instead of re-tokenising the whole
        # memory file for every query.  MemoryEntry.get_tokens() also keeps the
        # per-entry fallback cache for legacy callers that mutate entries
        # directly.
        if self._idf_cache is None or self._avgdl_cache is None:
            self._rebuild_indices()
        entry_tokens = [entry.get_tokens() for entry in entries]
        idf = self._idf_cache or {}
        avgdl = self._avgdl_cache or 0.0

        scored: list[tuple[float, MemoryEntry]] = []
        for i, entry in enumerate(entries):
            bm25 = _bm25_score(query_tokens, entry_tokens[i], idf, avgdl)

            substring_score = 0.0
            content_lower = entry.content.lower()
            if query_lower in content_lower:
                substring_score = 2.0
            elif any(q in content_lower for q in query_terms):
                substring_score = 1.0

            tag_score = 0.0
            exact_tag_match = any(
                tag.lower() == query_lower for tag in entry.tags
            )
            partial_tag_match = any(
                query_lower in tag.lower() for tag in entry.tags
            )
            if exact_tag_match:
                tag_score = 5.0
            elif partial_tag_match:
                tag_score = 1.5
            if query_lower in entry.category.lower():
                tag_score += 1.0

            match_score = bm25 + substring_score + tag_score
            if match_score <= 0:
                continue

            # Domain score: Jaccard similarity between entry.domains and active_domains
            domain_score = 0.0
            if active_domains and entry.domains:
                entry_set = set(entry.domains)
                active_set = set(active_domains)
                intersection = entry_set & active_set
                union = entry_set | active_set
                domain_score = len(intersection) / len(union) if union else 0.0

            # Soft blend: BM25 dominates, domain provides light steering
            final_relevance = match_score * 0.7 + domain_score * 0.3

            usage_bonus = math.log1p(entry.usage_count) * 0.3
            age_hours = (time.time() - entry.updated_at) / 3600
            recency_bonus = 1.0 / (1.0 + age_hours / 24.0) * 0.5

            total_score = final_relevance + usage_bonus + recency_bonus
            scored.append((total_score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        # Retrieval callers that compare rankings or run previews need a
        # stable, read-only view.  Production remains feedback-enabled by
        # default, while benchmarks can opt out explicitly.
        if record_usage:
            for _, entry in scored[:10]:
                entry.usage_count += 1
        return [entry for _, entry in scored]
    
    def _enforce_limits(self) -> None:
        """Remove oldest entries if exceeding limits."""
        removed = False
        # Check entry count
        while len(self.entries) > self.max_entries:
            removed_entry = self.entries.pop(0)
            self._remove_from_indices(removed_entry)
            removed = True
        
        # Check size
        while self.size_bytes > self.max_size_bytes and self.entries:
            removed_entry = self.entries.pop(0)
            self._remove_from_indices(removed_entry)
            removed = True
        if removed:
            self._invalidate_search_cache()
    
    def format_as_markdown(self, include_header: bool = True) -> str:
        """Format as MEMORY.md content."""
        lines = []
        
        if include_header:
            scope_names = {
                MemoryScope.USER: "User Memory",
                MemoryScope.PROJECT: "Project Memory",
                MemoryScope.LOCAL: "Local Memory",
            }
            lines.append(f"# {scope_names[self.scope]}")
            lines.append("")
            lines.append(f"*Last updated: {time.strftime('%Y-%m-%d %H:%M')}*")
            lines.append("")
        
        # Group by category
        categories: dict[str, list[MemoryEntry]] = {}
        for entry in self.entries:
            if entry.category not in categories:
                categories[entry.category] = []
            categories[entry.category].append(entry)
        
        for category, entries in categories.items():
            lines.append(f"## {category.title()}")
            lines.append("")
            for entry in entries:
                tags_str = f" `{' '.join(entry.tags)}`" if entry.tags else ""
                lines.append(f"- {entry.content}{tags_str}")
            lines.append("")
        
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Memory Manager
# ---------------------------------------------------------------------------

@dataclass
class MemoryPaths:
    """Paths for memory files at different scopes."""
    user_memory: Path
    project_memory: Path
    local_memory: Path
    
    @classmethod
    def for_workspace(cls, workspace: str) -> "MemoryPaths":
        """Create memory paths for a workspace."""
        workspace_path = Path(workspace)
        
        return cls(
            user_memory=MINI_CODE_DIR / "memory",
            project_memory=workspace_path / ".mini-code-memory",
            local_memory=workspace_path / ".mini-code-memory-local",
        )


class MemoryManager:
    """Manages layered memory system."""
    
    def __init__(
        self,
        workspace: str | Path | None = None,
        *,
        project_root: str | Path | None = None,
    ):
        # Backward compatibility: older call sites pass `project_root=...`.
        resolved_workspace = workspace if workspace is not None else project_root
        if resolved_workspace is None:
            resolved_workspace = Path.cwd()

        self.workspace = str(resolved_workspace)
        self.paths = MemoryPaths.for_workspace(self.workspace)
        self.memories: dict[MemoryScope, MemoryFile] = {
            MemoryScope.USER: MemoryFile(scope=MemoryScope.USER),
            MemoryScope.PROJECT: MemoryFile(scope=MemoryScope.PROJECT),
            MemoryScope.LOCAL: MemoryFile(scope=MemoryScope.LOCAL),
        }
        self._load_all()
    
    def _load_all(self) -> None:
        """Load all memory files."""
        for scope in MemoryScope:
            self._load_scope(scope)
            self._auto_recover_scope(scope)
    
    def _auto_recover_scope(self, scope: MemoryScope) -> None:
        """Check integrity and auto-recover if issues are found.

        After loading, validates the memory state. If integrity issues
        are detected, attempts to recover by removing invalid entries
        and deduplicating IDs.

        Args:
            scope: Memory scope to check and recover
        """
        result = self.check_integrity(scope)
        if not result["is_valid"]:
            logger.warning(
                "Integrity check failed for scope %s: %d issues found. "
                "Attempting auto-recovery...",
                scope.value,
                len(result["issues"]),
            )
            self._recover_scope(scope)
    
    def _recover_scope(self, scope: MemoryScope) -> None:
        """Attempt to recover a scope with integrity issues.

        Removes entries with invalid IDs, deduplicates IDs (keeps first),
        and fixes entries with empty content or category.

        Args:
            scope: Memory scope to recover
        """
        entries = self.memories[scope].entries
        seen_ids: set[str] = set()
        recovered: list[MemoryEntry] = []
        removed_count = 0
        fixed_count = 0

        for entry in entries:
            if not entry.id or not isinstance(entry.id, str):
                logger.warning(
                    "Removing entry with invalid ID during recovery"
                )
                removed_count += 1
                continue

            if entry.id in seen_ids:
                logger.warning(
                    "Removing duplicate entry with ID '%s'", entry.id
                )
                removed_count += 1
                continue

            if not entry.category or not isinstance(entry.category, str):
                entry.category = "general"
                fixed_count += 1

            if not entry.content or not isinstance(entry.content, str):
                logger.warning(
                    "Removing entry '%s' with empty content", entry.id
                )
                removed_count += 1
                continue

            seen_ids.add(entry.id)
            recovered.append(entry)

        self.memories[scope].entries = recovered
        self.memories[scope]._rebuild_indices()
        self._save_scope(scope)

        logger.info(
            "Recovery complete for scope %s: %d entries recovered, "
            "%d removed, %d fixed",
            scope.value,
            len(recovered),
            removed_count,
            fixed_count,
        )
    
    def _load_scope(self, scope: MemoryScope) -> None:
        """Load memory file for a scope."""
        path = self._get_scope_path(scope)
        memory_md = path / "MEMORY.md"
        memory_json = path / "memory.json"
        
        if not memory_md.exists() and not memory_json.exists():
            return
        
        # Load JSON metadata if exists
        if memory_json.exists():
            try:
                raw_text = memory_json.read_text(encoding="utf-8")
                data = json.loads(raw_text)
                
                is_valid, errors = _validate_memory_data(data)
                if is_valid:
                    for entry_data in data.get("entries", []):
                        entry = MemoryEntry.from_dict(entry_data)
                        self.memories[scope].entries.append(entry)
                    self.memories[scope]._rebuild_indices()
                    return
                else:
                    logger.warning(
                        "Memory data validation failed for scope %s: %s",
                        scope.value,
                        "; ".join(errors[:5]),
                    )
                    valid_entries = _recover_entries(data, memory_json)
                    for entry_data in valid_entries:
                        entry = MemoryEntry.from_dict(entry_data)
                        self.memories[scope].entries.append(entry)
                    if valid_entries:
                        self._save_scope(scope)
                    self.memories[scope]._rebuild_indices()
                    return
            except json.JSONDecodeError as e:
                logger.error(
                    "JSON decode error in scope %s: %s", scope.value, e
                )
            except KeyError as e:
                logger.error(
                    "Missing key in scope %s data: %s", scope.value, e
                )
        
        # Load from MEMORY.md
        if memory_md.exists():
            content = memory_md.read_text(encoding="utf-8")
            self._parse_memory_md(content, scope)
    
    def _parse_memory_md(self, content: str, scope: MemoryScope) -> None:
        """Parse MEMORY.md file into entries."""
        lines = content.split("\n")
        current_category = "general"
        entry_counter = 0
        
        for line in lines:
            line = line.strip()
            
            # Skip headers and metadata
            if line.startswith("#") or line.startswith("*") or not line:
                if line.startswith("## "):
                    current_category = line[3:].strip().lower()
                continue
            
            # Parse list items
            if line.startswith("- "):
                entry_content = line[2:]
                
                # Extract tags
                tags = []
                if "`" in entry_content:
                    import re
                    tag_matches = re.findall(r"`([^`]+)`", entry_content)
                    for tag_match in tag_matches:
                        tags.extend(tag_match.split())
                    entry_content = re.sub(r"`[^`]+`", "", entry_content).strip()
                
                entry_counter += 1
                entry = MemoryEntry(
                    id=f"{scope.value}-{entry_counter}",
                    scope=scope,
                    category=current_category,
                    content=entry_content,
                    tags=tags,
                )
                self.memories[scope].entries.append(entry)
        # Rebuild indices after Markdown-based loading
        if self.memories[scope].entries:
            self.memories[scope]._rebuild_indices()
    
    def _get_scope_path(self, scope: MemoryScope) -> Path:
        """Get path for memory scope."""
        if scope == MemoryScope.USER:
            return self.paths.user_memory
        elif scope == MemoryScope.PROJECT:
            return self.paths.project_memory
        else:
            return self.paths.local_memory
    
    def _ensure_scope_path(self, scope: MemoryScope) -> None:
        """Ensure directory exists for scope."""
        path = self._get_scope_path(scope)
        path.mkdir(parents=True, exist_ok=True)
    
    def add_entry(
        self,
        scope: MemoryScope,
        category: str = "auto",
        content: str = "",
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        """Add a new memory entry.

        If category is 'auto' or not provided, content will be automatically
        classified using keyword heuristics.

        Args:
            scope: Memory scope level
            category: Category for the entry, or 'auto' for auto-classification
            content: Content of the memory entry
            tags: Optional list of tags

        Returns:
            The created MemoryEntry
        """
        self._ensure_scope_path(scope)

        final_category = category
        final_tags = tags or []

        if category == "auto" and content:
            auto_category, auto_tags = _auto_classify_content(content)
            final_category = auto_category
            final_tags = list(dict.fromkeys(final_tags + auto_tags))

        # ``time.time() + len(entries)`` reused IDs once a scope reached its
        # capacity: every new entry had the same list length after eviction.
        # UUIDs keep references stable even during burst writes and across
        # process restarts.
        entry_id = f"{scope.value}-{uuid.uuid4().hex}"
        entry = MemoryEntry(
            id=entry_id,
            scope=scope,
            category=final_category,
            content=content,
            tags=final_tags,
        )

        self.memories[scope].add_entry(entry)
        self._save_scope(scope)
        return entry
    
    def update_entry(self, scope: MemoryScope, entry_id: str, content: str) -> bool:
        """Update an existing entry."""
        if self.memories[scope].update_entry(entry_id, content):
            self._save_scope(scope)
            return True
        return False
    
    def delete_entry(self, scope: MemoryScope, entry_id: str) -> bool:
        """Delete an entry."""
        if self.memories[scope].delete_entry(entry_id):
            self._save_scope(scope)
            return True
        return False

    def add_tag(self, scope: MemoryScope, entry_id: str, tag: str) -> bool:
        """Add a tag to an entry."""
        memory = self.memories[scope]
        had_tag = any(entry.id == entry_id and tag in entry.tags for entry in memory.entries)
        changed = memory.add_tag(entry_id, tag)
        if changed and not had_tag:
            self._save_scope(scope)
        return changed

    def remove_tag(self, scope: MemoryScope, entry_id: str, tag: str) -> bool:
        """Remove a tag from an entry."""
        memory = self.memories[scope]
        had_tag = any(entry.id == entry_id and tag in entry.tags for entry in memory.entries)
        changed = memory.remove_tag(entry_id, tag)
        if changed and had_tag:
            self._save_scope(scope)
        return changed

    def search_by_tag(self, scope: MemoryScope, tag: str) -> list[MemoryEntry]:
        """Search entries by tag."""
        return [
            entry for entry in self.memories[scope].entries
            if tag in entry.tags
        ]

    def get_all_tags(self, scope: MemoryScope) -> set[str]:
        """Get all unique tags in a scope."""
        tags: set[str] = set()
        for entry in self.memories[scope].entries:
            tags.update(entry.tags)
        return tags

    def get_tags_by_category(self, scope: MemoryScope) -> dict[str, list[str]]:
        """Get tags grouped by category."""
        category_tags: dict[str, set[str]] = {}
        for entry in self.memories[scope].entries:
            if entry.category not in category_tags:
                category_tags[entry.category] = set()
            category_tags[entry.category].update(entry.tags)
        return {cat: sorted(list(tags)) for cat, tags in category_tags.items()}

    def search(
        self,
        query: str,
        scope: MemoryScope | None = None,
        limit: int = 20,
        min_relevance: float = 0.1,
        active_domains: list[str] | None = None,
        *,
        record_usage: bool = True,
    ) -> list[MemoryEntry]:
        """Search across memory scopes with TF-IDF + domain relevance.

        Args:
            query: Search query string
            scope: Optional scope to limit search to
            limit: Maximum results to return
            min_relevance: Minimum relevance score threshold (0.0-1.0)
            active_domains: Current domain context for soft boosting

        Returns:
            Entries ranked by relevance (TF-IDF + domain + usage + recency)
        """
        results = []

        scopes_to_search = [scope] if scope else list(MemoryScope)

        if scope is None:
            # A per-scope search computes IDF independently and concatenating
            # those ranked lists lets a weak user-memory hit hide a stronger
            # project/local hit merely because USER is visited first.  Build a
            # read-only aggregate view so BM25 compares all scopes in one
            # corpus; the original scope order remains the stable tie-breaker.
            aggregate_entries = [
                entry
                for current_scope in scopes_to_search
                for entry in self.memories[current_scope].entries
            ]
            if aggregate_entries:
                aggregate_memory = MemoryFile(
                    scope=MemoryScope.PROJECT,
                    entries=aggregate_entries,
                )
                results = aggregate_memory.search(
                    query,
                    active_domains=active_domains,
                    record_usage=record_usage,
                )
        else:
            results.extend(
                self.memories[scope].search(
                    query,
                    active_domains=active_domains,
                    record_usage=record_usage,
                )
            )

        # Apply minimum relevance threshold
        # (entries are already scored by MemoryFile.search)
        if min_relevance > 0:
            # Normalize scores to 0-1 range for threshold comparison
            if results:
                max_score = max(
                    self._score_entry(e, _tokenize(query)) for e in results
                )
                if max_score > 0:
                    results = [
                        e for e in results
                        if self._score_entry(e, _tokenize(query)) / max_score >= min_relevance
                    ]

        # Results are already ranked by MemoryFile.search()
        # Deduplicate by content (keep highest-scored)
        seen_content: set[str] = set()
        deduped = []
        for entry in results:
            content_key = entry.content[:100].strip().lower()
            if content_key not in seen_content:
                seen_content.add(content_key)
                deduped.append(entry)

        return deduped[:limit]

    def _score_entry(self, entry: MemoryEntry, query_tokens: list[str]) -> float:
        """Compute relevance score for a memory entry."""
        if not query_tokens:
            return 0.0

        query_tokens_expanded = _expand_query_terms(query_tokens)
        entry_tokens = _tokenize(
            f"{entry.content} {entry.category} {' '.join(entry.tags)}"
        )
        idf = _compute_idf([entry_tokens])
        avgdl = len(entry_tokens)
        bm25 = _bm25_score(query_tokens_expanded, entry_tokens, idf, avgdl)

        query_lower = " ".join(query_tokens).lower()
        content_lower = entry.content.lower()
        substring_score = 0.0
        if query_lower in content_lower:
            substring_score = 2.0
        elif any(q in content_lower for q in query_tokens):
            substring_score = 1.0

        tag_score = 0.0
        exact_tag_match = any(tag.lower() == query_lower for tag in entry.tags)
        partial_tag_match = any(query_lower in tag.lower() for tag in entry.tags)
        if exact_tag_match:
            tag_score = 5.0
        elif partial_tag_match:
            tag_score = 1.5
        if query_lower in entry.category.lower():
            tag_score += 1.0

        usage_bonus = math.log1p(entry.usage_count) * 0.3

        age_hours = (time.time() - entry.updated_at) / 3600
        recency_bonus = 1.0 / (1.0 + age_hours / 24.0) * 0.5

        return bm25 + substring_score + tag_score + usage_bonus + recency_bonus
    
    def get_relevant_context(
        self,
        max_entries: int = 20,
        max_tokens: int = 8000,
        query: str | None = None,
    ) -> str:
        """Get relevant memory context for system prompt injection.
        
        Returns formatted MEMORY.md content from all scopes,
        respecting token limits.
        """
        from minicode.context_manager import estimate_tokens

        query = (query or "").strip()
        if query:
            scoped_parts = []
            total_tokens = 0
            for scope in [MemoryScope.LOCAL, MemoryScope.PROJECT, MemoryScope.USER]:
                entries = self.search(query, scope=scope, limit=max_entries, min_relevance=0.0)
                if not entries:
                    continue
                accepted_entries: list[MemoryEntry] = []
                for entry in entries[:max_entries]:
                    candidate_memory = MemoryFile(scope=scope, entries=[*accepted_entries, entry])
                    candidate = candidate_memory.format_as_markdown(include_header=True)
                    candidate_tokens = estimate_tokens(candidate)
                    if total_tokens + candidate_tokens <= max_tokens:
                        accepted_entries.append(entry)
                        continue
                    if not accepted_entries:
                        # Skip an oversized match instead of blocking lower-priority
                        # scopes that may have compact, relevant context.
                        continue
                    break
                if not accepted_entries:
                    continue
                formatted = MemoryFile(scope=scope, entries=accepted_entries).format_as_markdown(include_header=True)
                scoped_parts.append(formatted)
                total_tokens += estimate_tokens(formatted)
            if scoped_parts:
                return "\n\n".join(scoped_parts)
            return ""
        
        parts = []
        total_tokens = 0
        
        # Priority order: LOCAL > PROJECT > USER
        for scope in [MemoryScope.LOCAL, MemoryScope.PROJECT, MemoryScope.USER]:
            memory = self.memories[scope]
            if not memory.entries:
                continue
            
            formatted = memory.format_as_markdown(include_header=True)
            tokens = estimate_tokens(formatted)
            
            if total_tokens + tokens <= max_tokens:
                parts.append(formatted)
                total_tokens += tokens
            else:
                # Partial: include only recent entries
                remaining_tokens = max_tokens - total_tokens
                partial_entries = memory.entries[-max_entries:]
                partial_memory = MemoryFile(scope=scope, entries=partial_entries)
                formatted = partial_memory.format_as_markdown(include_header=True)
                
                if estimate_tokens(formatted) <= remaining_tokens:
                    parts.append(formatted)
                break
        
        if not parts:
            return ""
        
        return "\n\n".join(parts)
    
    def _save_scope(self, scope: MemoryScope) -> None:
        """Save memory to disk (atomic write to prevent corruption)."""
        path = self._get_scope_path(scope)
        self._ensure_scope_path(scope)
        
        # Save JSON metadata (atomic: write to temp, then replace)
        memory_json = path / "memory.json"
        data = {
            "scope": scope.value,
            "last_updated": time.time(),
            "entries": [e.to_dict() for e in self.memories[scope].entries],
        }
        self._atomic_write(memory_json, json.dumps(data, indent=2, ensure_ascii=False))
        
        # Also update MEMORY.md for human readability (atomic)
        memory_md = path / "MEMORY.md"
        self._atomic_write(memory_md, self.memories[scope].format_as_markdown())
    
    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        """Write content atomically: write to temp file, then os.replace().
        
        This prevents data corruption if the process is killed mid-write
        or if multiple instances write to the same file concurrently.
        """
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(target))
        except BaseException:
            # Clean up temp file on any failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    
    def get_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        return {
            scope.value: {
                "entries": len(memory.entries),
                "size_bytes": memory.size_bytes,
                "categories": list(set(e.category for e in memory.entries)),
            }
            for scope, memory in self.memories.items()
        }
    
    def format_stats(self) -> str:
        """Format memory stats for display with tier and domain breakdown."""
        from collections import Counter

        lines = ["Memory System Status", "=" * 50, ""]
        tiers: Counter[str] = Counter()
        domains: Counter[str] = Counter()
        total_entries = 0
        total_size = 0
        insight_count = 0

        for scope_name, scope_stats in self.get_stats().items():
            lines.append(f"{scope_name.title()}: {scope_stats['entries']} entries, "
                        f"{scope_stats['size_bytes'] / 1024:.1f} KB")
            total_entries += scope_stats["entries"]
            total_size += scope_stats["size_bytes"]

            # Collect tier and domain stats
            scope = MemoryScope(scope_name)
            if scope in self.memories:
                for e in self.memories[scope].entries:
                    tiers[e.tier.value] += 1
                    for d in e.domains:
                        domains[d] += 1
                    if e.category == "insight":
                        insight_count += 1

        lines.append("")
        lines.append(f"Total: {total_entries} entries ({total_size / 1024:.1f} KB)")
        lines.append("")

        if tiers:
            lines.append("Tier Distribution:")
            for tier_name in ["working", "short_term", "long_term", "archival"]:
                count = tiers.get(tier_name, 0)
                bar = "#" * (count // max(1, total_entries // 20))
                lines.append(f"  {tier_name:<12} {count:>4} {bar}")
            lines.append("")

        if domains:
            lines.append("Domain Distribution:")
            for domain, count in domains.most_common(6):
                lines.append(f"  {domain:<15} {count:>3}")
            lines.append("")

        if insight_count:
            lines.append(f"Curator Insights: {insight_count} synthesized")

        return "\n".join(lines)
    
    def clear_scope(self, scope: MemoryScope) -> None:
        """Clear all entries in a scope."""
        self.memories[scope] = MemoryFile(scope=scope)
        self._save_scope(scope)

    def handle_user_memory_input(self, user_input: str) -> str | None:
        """Handle explicit memory inputs from the main chat path.

        Supported forms:
        - "# remember this project convention"
        - "/memory add remember this project convention"
        - "/memory add project: remember this shared project convention"
        - "/memory add local: remember this local-only note"
        - "/memory add user: remember this cross-project preference"
        """
        raw = user_input.strip()
        if not raw:
            return None

        content = ""
        scope = MemoryScope.PROJECT
        category = "note"

        if raw.startswith("#"):
            content = raw[1:].strip()
            category = "directive"
        elif raw.startswith("/memory add "):
            content = raw[len("/memory add ") :].strip()
            scope_match = re.match(r"^(user|project|local)\s*:\s*(.+)$", content, flags=re.I)
            if scope_match:
                scope = MemoryScope(scope_match.group(1).lower())
                content = scope_match.group(2).strip()
        else:
            return None

        if not content:
            return "Usage: # <memory> or /memory add [user|project|local:] <memory>"

        entry = self.add_entry(scope, category, content, tags=["chat"])
        return f"Saved memory ({entry.scope.value}): {entry.content}"

    def check_integrity(self, scope: MemoryScope) -> dict[str, Any]:
        """Validate all entries in a scope for integrity.

        Checks:
        - Valid IDs (non-empty strings)
        - Valid categories (non-empty strings)
        - Non-empty content
        - No duplicate IDs

        Args:
            scope: Memory scope to check

        Returns:
            Dictionary with {is_valid: bool, issues: list[str]}
        """
        issues: list[str] = []
        seen_ids: set[str] = set()
        entries = self.memories[scope].entries

        for idx, entry in enumerate(entries):
            if not entry.id or not isinstance(entry.id, str):
                issues.append(
                    f"Entry at index {idx} has invalid or empty ID"
                )

            if entry.id in seen_ids:
                issues.append(
                    f"Duplicate ID found: '{entry.id}' "
                    f"(entries {list(self._find_entry_indices(scope, entry.id))})"
                )
            else:
                seen_ids.add(entry.id)

            if not entry.category or not isinstance(entry.category, str):
                issues.append(
                    f"Entry '{entry.id}' has invalid or empty category"
                )

            if not entry.content or not isinstance(entry.content, str):
                issues.append(
                    f"Entry '{entry.id}' has empty or invalid content"
                )

        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
        }

    def compress_scope(
        self, scope: MemoryScope, similarity_threshold: float = 0.8
    ) -> dict[str, int]:
        """Compress memory entries by merging similar content.

        Merges entries with content similarity above the threshold.
        Removes duplicate entries (exact content matches).
        Updates timestamps and preserves usage counts.

        Args:
            scope: Memory scope to compress
            similarity_threshold: Jaccard similarity threshold for merging
                (default 0.8 = 80%)

        Returns:
            Stats dictionary with {merged_count, removed_count, remaining_count}
        """
        entries = self.memories[scope].entries
        if len(entries) <= 1:
            return {"merged_count": 0, "removed_count": 0, "remaining_count": len(entries)}

        seen_content: dict[str, int] = {}
        duplicates_removed = 0

        unique_entries = []
        for entry in entries:
            content_key = entry.content.strip().lower()
            if content_key in seen_content:
                master_idx = seen_content[content_key]
                master = unique_entries[master_idx]
                master.usage_count += entry.usage_count
                master.updated_at = max(master.updated_at, entry.updated_at)
                master.tags = sorted(
                    list(set(master.tags + entry.tags))
                )
                duplicates_removed += 1
            else:
                seen_content[content_key] = len(unique_entries)
                unique_entries.append(entry)

        merged_count = 0
        final_entries: list[MemoryEntry] = []
        merged_indices: set[int] = set()

        for i, entry_a in enumerate(unique_entries):
            if i in merged_indices:
                continue

            best_match_idx = None
            best_similarity = 0.0

            for j, entry_b in enumerate(unique_entries):
                if i == j or j in merged_indices:
                    continue

                similarity = self._jaccard_similarity(
                    entry_a.content, entry_b.content
                )
                if similarity >= similarity_threshold and similarity > best_similarity:
                    best_similarity = similarity
                    best_match_idx = j

            if best_match_idx is not None:
                entry_b = unique_entries[best_match_idx]
                merged_content = self._merge_entry_content(
                    entry_a.content, entry_b.content
                )
                entry_a.content = merged_content
                entry_a.usage_count += entry_b.usage_count
                entry_a.updated_at = max(
                    entry_a.updated_at, entry_b.updated_at
                )
                entry_a.tags = sorted(
                    list(set(entry_a.tags + entry_b.tags))
                )
                merged_indices.add(best_match_idx)
                merged_count += 1

            final_entries.append(entry_a)

        self.memories[scope].entries = final_entries
        self.memories[scope]._rebuild_indices()
        self._save_scope(scope)

        return {
            "merged_count": merged_count,
            "removed_count": duplicates_removed,
            "remaining_count": len(final_entries),
        }

    @staticmethod
    def _jaccard_similarity(text_a: str, text_b: str) -> float:
        """Compute Jaccard similarity between two text strings.

        Uses token-based Jaccard similarity: |A ∩ B| / |A ∪ B|

        Args:
            text_a: First text string
            text_b: Second text string

        Returns:
            Similarity score between 0.0 and 1.0
        """
        tokens_a = set(_tokenize(text_a))
        tokens_b = set(_tokenize(text_b))

        if not tokens_a and not tokens_b:
            return 1.0
        if not tokens_a or not tokens_b:
            return 0.0

        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b

        return len(intersection) / len(union)

    @staticmethod
    def _merge_entry_content(content_a: str, content_b: str) -> str:
        """Merge two similar content strings.

        Keeps the longer version, appends unique parts from the shorter.

        Args:
            content_a: First content string
            content_b: Second content string

        Returns:
            Merged content string
        """
        if len(content_a) >= len(content_b):
            return content_a
        return content_b

    def detect_conflicts(self, content: str, scope: MemoryScope | None = None, threshold: float = 0.6) -> list[tuple[MemoryEntry, float]]:
        """Detect potential conflicts between new content and existing memories.

        Uses Jaccard similarity on token sets to identify entries that may
        contradict or overlap with the proposed new memory content.

        Args:
            content: New memory content to check for conflicts
            scope: Scope to check (None = all scopes)
            threshold: Similarity threshold for conflict flagging (0.0-1.0)

        Returns:
            List of (entry, similarity) tuples sorted by similarity descending
        """
        new_tokens = set(_tokenize(content))
        if not new_tokens:
            return []

        conflicts: list[tuple[MemoryEntry, float]] = []
        scopes = [scope] if scope else list(MemoryScope)

        for s in scopes:
            if s not in self.memories:
                continue
            for entry in self.memories[s].entries:
                old_tokens = set(entry.get_tokens())
                if not old_tokens:
                    continue
                intersection = new_tokens & old_tokens
                union = new_tokens | old_tokens
                similarity = len(intersection) / len(union) if union else 0.0
                if similarity >= threshold:
                    conflicts.append((entry, similarity))

        conflicts.sort(key=lambda x: x[1], reverse=True)
        return conflicts

    def decay_memories(self, max_age_days: float = 30.0, decay_factor: float = 0.5) -> int:
        """Apply time-based decay to memory usage_count.

        Entries older than max_age_days have their usage_count halved
        (multiplied by decay_factor), reducing their search ranking.
        Returns number of entries decayed.
        """
        now = time.time()
        decayed = 0
        for scope in MemoryScope:
            if scope not in self.memories:
                continue
            for entry in self.memories[scope].entries:
                age_days = (now - entry.updated_at) / 86400.0
                if age_days > max_age_days and entry.usage_count > 0:
                    entry.usage_count = max(0, int(entry.usage_count * decay_factor))
                    decayed += 1
        if decayed:
            for scope in MemoryScope:
                self._save_scope(scope)
        return decayed

    def promote_memories(self) -> dict[str, int]:
        """Promote/demote memories across tiers based on usage and age.

        WORKING → SHORT_TERM → LONG_TERM → ARCHIVAL
        Returns counts per operation.
        """
        now = time.time()
        stats = {"promoted_to_long": 0, "demoted_to_archival": 0, "reactivated": 0}
        changed_scopes: set[MemoryScope] = set()
        for scope in MemoryScope:
            if scope not in self.memories:
                continue
            for entry in self.memories[scope].entries:
                age_days = (now - entry.updated_at) / 86400.0
                accessed_days = (now - entry.last_accessed) / 86400.0
                if entry.tier == MemoryTier.SHORT_TERM and entry.usage_count >= 5 and age_days > 7:
                    entry.tier = MemoryTier.LONG_TERM
                    stats["promoted_to_long"] += 1
                if entry.tier == MemoryTier.LONG_TERM and accessed_days > 30:
                    entry.tier = MemoryTier.ARCHIVAL
                    entry.content = self._summarize_content(entry.content)
                    entry.invalidate_tokens()
                    changed_scopes.add(scope)
                    stats["demoted_to_archival"] += 1
                # A newly archived entry has a recent ``last_accessed`` value
                # because that field defaults to creation time.  Reactivating
                # every such entry immediately made archival and stale-memory
                # cleanup ineffective.  Require actual prior use and keep
                # curator-marked deprecated memories archived.
                is_deprecated = entry.content.startswith("[DEPRECATED:")
                if (
                    entry.tier in (MemoryTier.LONG_TERM, MemoryTier.ARCHIVAL)
                    and accessed_days < 7
                    and entry.usage_count > 0
                    and not is_deprecated
                ):
                    entry.tier = MemoryTier.SHORT_TERM
                    changed_scopes.add(scope)
                    stats["reactivated"] += 1
        if any(stats.values()):
            for scope in MemoryScope:
                if scope in changed_scopes:
                    self.memories[scope]._rebuild_indices()
                self._save_scope(scope)
        return stats

    def link_memories(self, similarity_threshold: float = 0.4) -> int:
        """Auto-link related memories by content similarity. Returns link count."""
        links = 0
        for scope in MemoryScope:
            if scope not in self.memories:
                continue
            entries = self.memories[scope].entries
            for i, a in enumerate(entries):
                for j, b in enumerate(entries):
                    if i >= j:
                        continue
                    if b.id in a.related_to:
                        continue
                    if self._jaccard_similarity(a.content, b.content) >= similarity_threshold:
                        a.related_to.append(b.id)
                        b.related_to.append(a.id)
                        links += 2
        if links:
            for scope in MemoryScope:
                self._save_scope(scope)
        return links

    def get_linked_memories(self, entry_id: str, depth: int = 1) -> list[MemoryEntry]:
        """Get memories linked to entry_id via related_to graph (BFS up to depth)."""
        entry = None
        found_scope = None
        for s in MemoryScope:
            if s in self.memories:
                self.memories[s]._ensure_cache_valid()
                entry = self.memories[s]._id_index.get(entry_id)
                if entry:
                    found_scope = s
                    break
        if not entry or not entry.related_to or not found_scope:
            return []
        visited = {entry_id}
        frontier = list(entry.related_to)
        results = []
        for _ in range(depth):
            nxt = []
            for rid in frontier:
                if rid in visited:
                    continue
                visited.add(rid)
                linked = self.memories[found_scope]._id_index.get(rid)
                if linked:
                    results.append(linked)
                    nxt.extend(linked.related_to)
            frontier = nxt
            if not frontier:
                break
        return results

    @staticmethod
    def _summarize_content(content: str, max_len: int = 150) -> str:
        if len(content) <= max_len:
            return content
        for sep in [". ", ".\n", "; ", ";\n", "\n"]:
            idx = content.find(sep)
            if 20 < idx < max_len:
                return content[:idx + 1]
        return content[:max_len] + "..."

    def _find_entry_indices(self, scope: MemoryScope, entry_id: str) -> list[int]:
        """Find all indices of entries with a given ID."""
        indices = []
        for idx, entry in enumerate(self.memories[scope].entries):
            if entry.id == entry_id:
                indices.append(idx)
        return indices


# ---------------------------------------------------------------------------
# System prompt integration
# ---------------------------------------------------------------------------

def inject_memory_into_prompt(
    system_prompt: str,
    memory_manager: MemoryManager,
    max_tokens: int = 8000,
) -> str:
    """Inject memory context into system prompt."""
    memory_context = memory_manager.get_relevant_context(max_tokens=max_tokens)
    
    if not memory_context:
        return system_prompt
    
    return f"""{system_prompt}

## Project Memory & Context

The following information has been accumulated from previous sessions:

{memory_context}

Use this context to inform your decisions and follow established patterns."""


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def format_memory_list(memory_manager=None, scope: MemoryScope | None = None, category: str | None = None) -> str:
    """Format memory entries for CLI display."""
    if memory_manager is None:
        return "No MemoryManager available."

    # Collect entries from specified scope(s)
    scopes = [scope] if scope else list(MemoryScope)
    all_entries: list[MemoryEntry] = []
    for s in scopes:
        if s in memory_manager.memories:
            entries = memory_manager.memories[s].entries
            if category:
                entries = [e for e in entries if e.category == category]
            all_entries.extend(entries)

    if not all_entries:
        return "No memories found."

    lines = [f"{'=' * 60}"]
    for entry in all_entries[:20]:  # Limit to 20 entries
        scope_tag = f"[{entry.scope.value if hasattr(entry, 'scope') else '?'}]"
        cat_tag = f"[{entry.category}]"
        content_preview = entry.content[:100].replace('\n', ' ')
        lines.append(f"{scope_tag} {cat_tag} {content_preview}")
        if entry.tags:
            lines.append(f"     Tags: {', '.join(entry.tags[:5])}")
        lines.append(f"     Used: {entry.usage_count}x | Updated: {time.strftime('%Y-%m-%d %H:%M', time.localtime(entry.updated_at))}")
        lines.append("")
    lines.append(f"{'=' * 60}")
    lines.append(f"Total: {len(all_entries)} entries")
    return "\n".join(lines)
