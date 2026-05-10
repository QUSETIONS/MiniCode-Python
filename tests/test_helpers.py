"""Test helper utilities for MiniCode tests."""
import json
from pathlib import Path
from typing import Any
from minicode.memory import MemoryEntry, MemoryManager, MemoryScope


def create_memory_entries(manager: MemoryManager, count: int, scope: MemoryScope = MemoryScope.PROJECT) -> list[MemoryEntry]:
    """Create N test memory entries with varied content."""
    categories = ["architecture", "convention", "decision", "pattern", "testing"]
    entries = []
    for i in range(count):
        entry = manager.add_entry(
            scope=scope,
            category=categories[i % len(categories)],
            content=f"Test memory entry number {i}: This is about {'testing' if i % 3 == 0 else 'architecture' if i % 3 == 1 else 'convention'}",
            tags=[f"tag-{i % 5}", f"group-{i // 5}"],
        )
        entries.append(entry)
    return entries


def create_chinese_memory_entries(manager: MemoryManager, count: int, scope: MemoryScope = MemoryScope.PROJECT) -> list[MemoryEntry]:
    """Create N test memory entries with Chinese content."""
    chinese_entries = [
        "使用 FastAPI 构建 REST API 后端",
        "所有函数使用 snake_case 命名规范",
        "测试使用 pytest 框架和 fixtures",
        "数据库使用 SQLite 进行开发环境配置",
        "代码审查必须包含安全性和性能检查",
        "使用 Docker Compose 管理开发环境服务",
        "API 响应必须包含错误码和详细描述",
        "使用 Pydantic 进行数据验证和序列化",
        "日志系统使用结构化日志格式",
        "认证使用 JWT token 方案",
    ]
    entries = []
    for i in range(min(count, len(chinese_entries))):
        entry = manager.add_entry(
            scope=scope,
            category="general",
            content=chinese_entries[i],
            tags=[f"标签-{i}"],
        )
        entries.append(entry)
    return entries


def verify_memory_integrity(manager: MemoryManager) -> dict[str, Any]:
    """Verify memory system integrity and return diagnostics."""
    result = {"valid": True, "issues": []}
    for scope in MemoryScope:
        integrity = manager.check_integrity(scope)
        if not integrity["is_valid"]:
            result["valid"] = False
            result["issues"].extend(integrity["issues"])
    return result


def create_corrupted_memory_file(path: Path) -> dict:
    """Create a corrupted memory.json file for testing recovery."""
    corrupted_data = {
        "scope": "project",
        "entries": [
            {"id": "valid-1", "scope": "project", "category": "test", "content": "Valid entry"},
            {"id": "invalid-2", "scope": "invalid_scope", "category": "test", "content": "Bad scope"},
            {"id": "valid-3", "scope": "project", "category": "", "content": ""},
            "not_a_dict_entry",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(corrupted_data), encoding="utf-8")
    return corrupted_data


def assert_entries_equal(entry1: MemoryEntry, entry2: MemoryEntry, ignore_timestamps: bool = True) -> None:
    """Assert two memory entries are equal, optionally ignoring timestamps."""
    assert entry1.id == entry2.id
    assert entry1.scope == entry2.scope
    assert entry1.category == entry2.category
    assert entry1.content == entry2.content
    assert sorted(entry1.tags) == sorted(entry2.tags)
    assert entry1.usage_count == entry2.usage_count
