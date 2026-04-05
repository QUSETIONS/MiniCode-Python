"""Logging configuration for MiniCode Python.

Provides structured logging with:
-分级日志（DEBUG/INFO/WARNING/ERROR）
- 控制台和文件输出
- 关键路径日志点（API 调用、工具执行、权限检查）
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from minicode.config import MINI_CODE_DIR

# 日志文件路径
LOG_FILE = MINI_CODE_DIR / "minicode.log"

# 日志格式
CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s %(filename)s:%(lineno)d: %(message)s"


def setup_logging(
    level: str = "WARNING",
    log_to_file: bool = True,
    log_to_console: bool = True,
) -> logging.Logger:
    """配置 MiniCode 日志系统。
    
    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        log_to_file: 是否输出到文件
        log_to_console: 是否输出到控制台
        
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
    
    # 文件 handler
    if log_to_file:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
        root_logger.addHandler(file_handler)
    
    # 控制台 handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(getattr(logging, level.upper(), logging.WARNING))
        console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        root_logger.addHandler(console_handler)
    
    # 减少第三方库的日志噪音
    for noisy_lib in ["urllib3", "httpx", "openai"]:
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)
    
    root_logger.info("Logging initialized (level=%s, file=%s, console=%s)", level, log_to_file, log_to_console)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取子模块 logger。
    
    Args:
        name: 子模块名称（如 'agent_loop', 'tools.read_file'）
        
    Returns:
        配置好的子 logger
    """
    return logging.getLogger(f"minicode.{name}")


# 预定义的关键路径日志点
def log_api_call(model: str, tokens_in: int, tokens_out: int, cost: float, duration_ms: float) -> None:
    """记录 API 调用信息。"""
    logger = get_logger("api")
    logger.info(
        "API call: model=%s, tokens_in=%d, tokens_out=%d, cost=$%.4f, duration=%dms",
        model, tokens_in, tokens_out, cost, duration_ms,
    )


def log_tool_execution(tool_name: str, success: bool, duration_ms: float, error: str | None = None) -> None:
    """记录工具执行信息。"""
    logger = get_logger("tools")
    if success:
        logger.debug("Tool %s executed successfully in %dms", tool_name, duration_ms)
    else:
        logger.warning("Tool %s failed after %dms: %s", tool_name, duration_ms, error)


def log_permission_check(kind: str, target: str, granted: bool) -> None:
    """记录权限检查信息。"""
    logger = get_logger("permissions")
    if granted:
        logger.debug("Permission granted: %s for %s", kind, target)
    else:
        logger.warning("Permission denied: %s for %s", kind, target)


def log_session_event(event: str, details: str = "") -> None:
    """记录会话事件（启动、保存、恢复）。"""
    logger = get_logger("session")
    if details:
        logger.info("Session %s: %s", event, details)
    else:
        logger.info("Session %s", event)
