"""Logging configuration for MiniCode Python.

Provides structured logging with:
- 分级日志（DEBUG/INFO/WARNING/ERROR）
- 控制台和文件输出
- 日志轮转（按大小 + 按时间，防止无限增长）
- 结构化 JSON 日志（可选，便于机器解析）
- 关键路径日志点（API 调用、工具执行、权限检查）
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path

from minicode.config import MINI_CODE_DIR

# 日志文件路径
LOG_FILE = MINI_CODE_DIR / "minicode.log"

# 日志格式
CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s %(filename)s:%(lineno)d: %(message)s"

# 轮转配置
LOG_MAX_BYTES = 10 * 1024 * 1024   # 10 MB per file
LOG_BACKUP_COUNT = 5               # Keep 5 rotated files (50 MB total max)
LOG_ROTATION_WHEN = "midnight"     # Also rotate at midnight
LOG_ROTATION_INTERVAL = 1          # Every 1 day


# ---------------------------------------------------------------------------
# Structured JSON formatter
# ---------------------------------------------------------------------------

class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter for machine-parseable logs.
    
    Outputs each log entry as a single JSON line:
    {"ts": "2025-01-15T10:30:00", "level": "INFO", "module": "api", ...}
    """
    
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
            "file": f"{record.filename}:{record.lineno}",
        }
        
        # Add structured extras if present
        for key in ("tool_name", "model", "duration_ms", "tokens_in", "tokens_out",
                     "cost", "error_category", "session_id", "workspace"):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        
        # Add exception info
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = str(record.exc_info[1])
            entry["exc_type"] = type(record.exc_info[1]).__name__
        
        return json.dumps(entry, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_logging(
    level: str = "WARNING",
    log_to_file: bool = True,
    log_to_console: bool = True,
    structured: bool = False,
) -> logging.Logger:
    """配置 MiniCode 日志系统。
    
    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        log_to_file: 是否输出到文件
        log_to_console: 是否输出到控制台
        structured: 是否使用 JSON 结构化日志格式
        
    Returns:
        配置好的根 logger
    """
    # 确保日志目录存在
    if log_to_file:
        MINI_CODE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 创建根 logger
    root_logger = logging.getLogger("minicode")
    root_logger.setLevel(getattr(logging, level.upper(), logging.WARNING))
    
    # 清除已有的 handlers（避免重复）
    root_logger.handlers.clear()
    
    # 选择格式化器
    if structured:
        file_formatter = StructuredFormatter()
        console_formatter = StructuredFormatter()
    else:
        file_formatter = logging.Formatter(FILE_FORMAT)
        console_formatter = logging.Formatter(CONSOLE_FORMAT)
    
    # 文件 handler — 使用 RotatingFileHandler 防止日志无限增长
    if log_to_file:
        # RotatingFileHandler: 按大小轮转
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # 控制台 handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(getattr(logging, level.upper(), logging.WARNING))
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # 减少第三方库的日志噪音
    for noisy_lib in ["urllib3", "httpx", "openai"]:
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)
    
    root_logger.info("Logging initialized (level=%s, file=%s, console=%s, structured=%s)",
                     level, log_to_file, log_to_console, structured)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取子模块 logger。
    
    Args:
        name: 子模块名称（如 'agent_loop', 'tools.read_file'）
        
    Returns:
        配置好的子 logger
    """
    return logging.getLogger(f"minicode.{name}")


# ---------------------------------------------------------------------------
# Structured logging helpers
# ---------------------------------------------------------------------------

def log_api_call(model: str, tokens_in: int, tokens_out: int, cost: float, duration_ms: float) -> None:
    """记录 API 调用信息（结构化）。"""
    logger = get_logger("api")
    logger.info(
        "API call: model=%s, tokens_in=%d, tokens_out=%d, cost=$%.4f, duration=%dms",
        model, tokens_in, tokens_out, cost, duration_ms,
        extra={
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": cost,
            "duration_ms": duration_ms,
        },
    )


def log_tool_execution(tool_name: str, success: bool, duration_ms: float, error: str | None = None) -> None:
    """记录工具执行信息（结构化）。"""
    logger = get_logger("tools")
    extra = {"tool_name": tool_name, "duration_ms": duration_ms}
    if success:
        logger.debug("Tool %s executed successfully in %dms", tool_name, duration_ms, extra=extra)
    else:
        extra["error_category"] = "tool_failure"
        logger.warning("Tool %s failed after %dms: %s", tool_name, duration_ms, error, extra=extra)


def log_permission_check(kind: str, target: str, granted: bool) -> None:
    """记录权限检查信息（结构化）。"""
    logger = get_logger("permissions")
    extra = {"tool_name": kind}
    if granted:
        logger.debug("Permission granted: %s for %s", kind, target, extra=extra)
    else:
        logger.warning("Permission denied: %s for %s", kind, target, extra=extra)


def log_session_event(event: str, details: str = "") -> None:
    """记录会话事件（启动、保存、恢复）。"""
    logger = get_logger("session")
    if details:
        logger.info("Session %s: %s", event, details)
    else:
        logger.info("Session %s", event)


def get_log_stats() -> dict[str, Any]:
    """获取当前日志文件统计信息（大小、轮转文件数等）。"""
    stats: dict[str, Any] = {
        "log_file": str(LOG_FILE),
        "exists": LOG_FILE.exists(),
    }
    
    if LOG_FILE.exists():
        size = LOG_FILE.stat().st_size
        stats["size_bytes"] = size
        stats["size_mb"] = round(size / (1024 * 1024), 2)
        stats["max_size_mb"] = LOG_MAX_BYTES / (1024 * 1024)
        stats["rotation_pct"] = round(size / LOG_MAX_BYTES * 100, 1)
    
    # Count rotated files
    rotated = list(LOG_FILE.parent.glob(f"{LOG_FILE.name}.*"))
    stats["rotated_files"] = len(rotated)
    stats["max_rotated"] = LOG_BACKUP_COUNT
    
    return stats
