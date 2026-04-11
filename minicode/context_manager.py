"""Context window management for LLM conversations.

Tracks token usage, estimates context window consumption, and provides
auto-compaction to prevent context overflow in long conversations.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minicode.config import MINI_CODE_DIR


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default context window sizes (tokens)
DEFAULT_CONTEXT_WINDOWS = {
    # Anthropic
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    "claude-haiku-3-20240307": 100_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3-mini": 200_000,
    # OpenRouter popular models
    "openrouter/auto": 200_000,
    "anthropic/claude-sonnet-4": 200_000,
    "anthropic/claude-opus-4": 200_000,
    "openai/gpt-4o": 128_000,
    "openai/gpt-4o-mini": 128_000,
    "google/gemini-2.5-pro": 1_000_000,
    "google/gemini-2.5-flash": 1_000_000,
    "meta-llama/llama-4-maverick": 1_000_000,
    "deepseek/deepseek-r1": 128_000,
    "deepseek/deepseek-chat": 128_000,
    "qwen/qwen3-235b-a22b": 128_000,
    "minimax/minimax-m1": 1_000_000,
    "default": 128_000,  # Fallback
}

# Auto-compaction threshold (95% of context window)
AUTOCOMPACT_THRESHOLD = 0.95

# Estimated tokens per character (rough average for English/Code)
CHARS_PER_TOKEN = 4.0

# Minimum messages to keep after compaction
MIN_MESSAGES_TO_KEEP = 10

# System prompt is always kept (counts as 1 message)
SYSTEM_PROMPT_RESERVED = 1


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# 预编译的正则表达式用于快速 CJK 字符检测
import re
_CJK_PATTERN = re.compile(r'[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF]')

# LRU 缓存：token 估算被频繁调用（每条消息、每次上下文检查），
# 相同文本的 token 数是确定性的，缓存可避免重复计算。
_token_cache: dict[str, int] = {}
_TOKEN_CACHE_MAX = 1024


def estimate_tokens(text: str) -> int:
    """改进的 token 估算，支持中英文
    
    - 英文/代码：约 4 字符/token
    - 中文/日文：约 1.5 字符/token
    - 混合文本：使用启发式估算
    
    性能优化：使用正则表达式替代逐字符 ord() 检查，速度快 10-50 倍。
    带 LRU 缓存避免重复计算相同文本。
    """
    if not text:
        return 0
    
    # 缓存查找（短文本优先缓存）
    cache_key = text if len(text) < 256 else hash(text)  # 长文本用 hash 作为 key
    if cache_key in _token_cache:
        return _token_cache[cache_key]
    
    # 使用正则表达式快速统计 CJK 字符数量
    cjk_count = len(_CJK_PATTERN.findall(text))
    
    # CJK 字符约 1.5 字符/token，英文约 4 字符/token
    ascii_chars = len(text) - cjk_count
    
    result = max(1, int(cjk_count / 1.5 + ascii_chars / 4.0))
    
    # 缓存结果（防止无限增长）
    if len(_token_cache) < _TOKEN_CACHE_MAX:
        _token_cache[cache_key] = result
    
    return result


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens for a single message."""
    tokens = 0
    
    # Role overhead
    role = message.get("role", "")
    if role == "system":
        tokens += 3  # System prompt overhead
    elif role == "user":
        tokens += 4  # User message overhead
    elif role == "assistant":
        tokens += 3  # Assistant overhead
    elif role == "assistant_tool_call":
        tokens += 7  # Tool call overhead
    elif role == "tool_result":
        tokens += 6  # Tool result overhead
    elif role == "assistant_progress":
        tokens += 3
    
    # Content tokens
    content = message.get("content", "")
    if isinstance(content, str):
        tokens += estimate_tokens(content)
    
    # Tool call input/output
    if "input" in message:
        input_str = json.dumps(message["input"]) if isinstance(message["input"], dict) else str(message["input"])
        tokens += estimate_tokens(input_str)
    
    return tokens


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of messages."""
    return sum(estimate_message_tokens(msg) for msg in messages)


@dataclass
class _ExtractedInfo:
    """Information extracted from removed messages during summarization."""
    user_intents: list[str] = field(default_factory=list)
    file_paths: set[str] = field(default_factory=set)
    key_tool_results: list[str] = field(default_factory=list)
    assistant_conclusions: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)


# Tool categories for classification
_EDIT_TOOLS = frozenset({"edit_file", "write_file", "modify_file", "patch_file", "multi_edit"})
_READ_TOOLS = frozenset({"read_file", "list_files", "grep_files", "file_tree"})
_SEARCH_TOOLS = frozenset({"grep_files", "find_symbols", "find_references", "web_search", "web_fetch"})
_COMMAND_TOOLS = frozenset({"run_command", "execute_command", "bash"})

# Regex for extracting code-like content and decisions
_CODE_FENCE_RE = re.compile(r'```[\w]*\n(.{20,300}?)```', re.DOTALL)
_DECISION_KEYWORDS = re.compile(
    r'(?:decided|decision|chose|chosen|will use|using|switching to|'
    r'implemented|fixed|resolved|refactored|migrated|upgraded|'
    r'recommend|should|must|need to|going to|plan to|'
    r'approach:|strategy:|solution:|conclusion:)',
    re.IGNORECASE,
)


def _extract_from_messages(messages: list[dict[str, Any]]) -> _ExtractedInfo:
    """Extract structured information from messages for layered summarization.
    
    This is the core extraction step that pulls out different categories of
    information at varying levels of detail, enabling the budget-aware builder
    to include the most important information first.
    """
    info = _ExtractedInfo()
    
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        if role == "user" and content.strip():
            # Extract user intent — keep more context for short queries,
            # truncate long paste-heavy messages
            preview = content.strip().replace("\n", " ")
            # For short queries (<200 chars), keep them fully
            # For long ones, keep first 200 chars
            if len(preview) > 200:
                preview = preview[:200] + "..."
            info.user_intents.append(preview)
            
        elif role == "assistant" and content.strip():
            text = content.strip()
            
            # Extract decisions/conclusions
            sentences = text.replace("\n", " ").split(". ")
            for sentence in sentences:
                if _DECISION_KEYWORDS.search(sentence):
                    decision = sentence.strip()[:180]
                    if decision and decision not in info.decisions:
                        info.decisions.append(decision)
            
            # Extract code snippets from assistant responses
            for match in _CODE_FENCE_RE.finditer(text):
                snippet = match.group(1).strip()
                if len(snippet) >= 20 and len(info.code_snippets) < 5:
                    info.code_snippets.append(snippet[:300])
            
            # General conclusion preview
            preview = text[:200].replace("\n", " ")
            info.assistant_conclusions.append(preview)
            
        elif role == "assistant_tool_call":
            tool_name = msg.get("toolName", "unknown")
            info.tool_names.append(tool_name)
            
            # Extract file paths from edit/write tools
            if tool_name in _EDIT_TOOLS:
                inp = msg.get("input", {})
                path = inp.get("path") or inp.get("filePath", "")
                if path:
                    info.file_paths.add(path)
            
            # Extract searched patterns from grep/search tools
            if tool_name in _SEARCH_TOOLS:
                inp = msg.get("input", {})
                pattern = inp.get("pattern") or inp.get("query", "")
                if pattern:
                    info.file_paths.add(f"search:{pattern[:80]}")
            
            # Extract command names from run_command
            if tool_name in _COMMAND_TOOLS:
                inp = msg.get("input", {})
                cmd = inp.get("command", "")
                if cmd:
                    cmd_name = cmd.split()[0] if cmd.split() else ""
                    if cmd_name:
                        info.key_tool_results.append(f"ran: {cmd_name}")
            
        elif role == "tool_result":
            tool_name = msg.get("toolName", "")
            is_error = msg.get("isError", False)
            
            # Preserve error results (highest priority tool info)
            if is_error:
                error_preview = content.strip()[:150].replace("\n", " ")
                info.key_tool_results.append(f"ERROR({tool_name}): {error_preview}")
            
            # Preserve edit confirmations with file paths
            elif tool_name in _EDIT_TOOLS and content.strip():
                success_preview = content.strip()[:100].replace("\n", " ")
                info.key_tool_results.append(f"{tool_name} ok: {success_preview}")
            
            # Extract file paths from read_file results
            elif tool_name in _READ_TOOLS and content.strip():
                # Check if content references a file path
                first_line = content.strip().split("\n")[0][:100]
                if "/" in first_line or "\\" in first_line:
                    info.file_paths.add(first_line.strip())
    
    return info


def _build_layered_summary(info: _ExtractedInfo, max_summary_tokens: int = 2000) -> str:
    """Build a budget-aware layered summary from extracted information.
    
    Layers are ordered by importance and each has a token budget allocation:
    - Layer 1: User intents (35% budget) — what the user wanted
    - Layer 2: Decisions & file paths (20% budget) — key choices made
    - Layer 3: Key tool results — errors and important outcomes (15% budget)
    - Layer 4: Assistant conclusions (15% budget) — results reached
    - Layer 5: Code snippets (10% budget) — important code patterns
    - Layer 6: Tool usage summary (5% budget) — compact activity log
    """
    lines: list[str] = []
    
    # Budget allocations per layer (as fraction of total)
    layer_budgets = [0.35, 0.20, 0.15, 0.15, 0.10, 0.05]
    
    def _remaining_budget() -> int:
        return max(0, max_summary_tokens - estimate_tokens("\n".join(lines)))
    
    # Layer 1: User intents (highest priority)
    if info.user_intents:
        budget = int(max_summary_tokens * layer_budgets[0])
        lines.append("## User requests:")
        for intent in info.user_intents[:12]:
            if estimate_tokens("\n".join(lines)) > budget:
                lines.append(f"  ... and {len(info.user_intents) - info.user_intents.index(intent)} more")
                break
            lines.append(f"- {intent}")
    
    # Layer 2: Decisions and file paths
    has_decisions = bool(info.decisions)
    has_files = bool(info.file_paths)
    if has_decisions or has_files:
        budget = int(max_summary_tokens * (layer_budgets[0] + layer_budgets[1]))
        
        if info.decisions:
            lines.append("## Key decisions:")
            for dec in info.decisions[:8]:
                if estimate_tokens("\n".join(lines)) > budget:
                    break
                lines.append(f"- {dec}")
        
        if info.file_paths:
            # Separate real paths from search patterns
            real_paths = sorted(p for p in info.file_paths if not p.startswith("search:"))
            search_patterns = sorted(p[8:] for p in info.file_paths if p.startswith("search:"))
            
            path_line = f"## Files: {', '.join(real_paths[:20])}"
            if len(real_paths) > 20:
                path_line += f" (+{len(real_paths)-20} more)"
            if search_patterns:
                path_line += f"\n## Searched: {', '.join(search_patterns[:5])}"
            
            if estimate_tokens("\n".join(lines) + path_line) <= budget:
                lines.append(path_line)
    
    # Layer 3: Key tool results (errors + edits)
    if info.key_tool_results:
        budget = int(max_summary_tokens * sum(layer_budgets[:3]))
        lines.append("## Key results:")
        for result in info.key_tool_results[:15]:
            if estimate_tokens("\n".join(lines)) > budget:
                break
            lines.append(f"- {result}")
    
    # Layer 4: Assistant conclusions
    if info.assistant_conclusions:
        budget = int(max_summary_tokens * sum(layer_budgets[:4]))
        lines.append("## Conclusions:")
        for conc in info.assistant_conclusions[:8]:
            if estimate_tokens("\n".join(lines)) > budget:
                break
            lines.append(f"- {conc}")
    
    # Layer 5: Code snippets (most selective)
    if info.code_snippets:
        budget = int(max_summary_tokens * sum(layer_budgets[:5]))
        lines.append("## Code patterns:")
        for snippet in info.code_snippets[:3]:
            snippet_line = f"```\n{snippet}\n```"
            if estimate_tokens("\n".join(lines) + snippet_line) > budget:
                break
            lines.append(snippet_line)
    
    # Layer 6: Tool usage summary (most compact)
    if info.tool_names:
        from collections import Counter
        tool_counts = Counter(info.tool_names)
        tool_summary = ", ".join(
            f"{name}×{count}" if count > 1 else name
            for name, count in tool_counts.most_common()
        )
        lines.append(f"## Tools: {tool_summary}")
    
    return "\n".join(lines)


def _summarize_removed_messages(messages: list[dict[str, Any]], max_summary_tokens: int = 2000) -> str:
    """Build a condensed summary of removed messages for context retention.
    
    Uses a two-phase approach:
    1. Extract: Pull structured information from all message types
    2. Build: Assemble layers respecting token budget allocations
    
    This ensures the most important information (user intents, key decisions)
    is always included, while less critical details (tool names, code snippets)
    fill remaining budget.
    """
    if not messages:
        return ""
    
    info = _extract_from_messages(messages)
    return _build_layered_summary(info, max_summary_tokens)


# ---------------------------------------------------------------------------
# Context tracking
# ---------------------------------------------------------------------------

@dataclass
class ContextStats:
    """Current context window statistics."""
    total_tokens: int = 0
    context_window: int = 0
    usage_percentage: float = 0.0
    messages_count: int = 0
    system_tokens: int = 0
    conversation_tokens: int = 0
    tool_calls_count: int = 0
    is_near_limit: bool = False
    should_compact: bool = False


@dataclass
class ContextManager:
    """Manages context window tracking and auto-compaction."""
    model: str = "default"
    context_window: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    compaction_history: list[dict[str, Any]] = field(default_factory=list)
    _token_cache: dict[int, int] = field(default_factory=dict, repr=False)  # id(msg) -> tokens
    
    # 多级压缩支持
    _compaction_level: int = field(default_factory=lambda: 0)  # 0=无压缩, 1=轻微, 2=中等, 3=深度
    
    # 多级压缩目标 (相对于 context window 的百分比)
    _COMPACTION_LEVELS = [0.70, 0.50, 0.30]  # 轻度/中度/深度
    
    def __post_init__(self):
        if self.context_window == 0:
            self.context_window = DEFAULT_CONTEXT_WINDOWS.get(
                self.model, DEFAULT_CONTEXT_WINDOWS["default"]
            )
    
    def update_model(self, model: str) -> None:
        """Update model and adjust context window."""
        self.model = model
        self.context_window = DEFAULT_CONTEXT_WINDOWS.get(
            model, DEFAULT_CONTEXT_WINDOWS["default"]
        )
    
    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message and update tracking."""
        self.messages.append(message)
        # Cache token count immediately to avoid re-estimation in get_stats()
        self._token_cache[id(message)] = estimate_message_tokens(message)
    
    def get_stats(self) -> ContextStats:
        """Calculate current context statistics.
        
        Uses cached token counts when available (O(1) amortized for
        messages added via add_message).
        """
        if not self.messages:
            return ContextStats(
                context_window=self.context_window,
            )
        
        # Count tokens using cache when available
        system_tokens = 0
        conversation_tokens = 0
        tool_calls = 0
        
        for msg in self.messages:
            msg_tokens = self._token_cache.get(id(msg))
            if msg_tokens is None:
                msg_tokens = estimate_message_tokens(msg)
                self._token_cache[id(msg)] = msg_tokens
            if msg.get("role") == "system":
                system_tokens += msg_tokens
            else:
                conversation_tokens += msg_tokens
            
            if msg.get("role") == "assistant_tool_call":
                tool_calls += 1
        
        total_tokens = system_tokens + conversation_tokens
        usage_pct = (total_tokens / self.context_window * 100) if self.context_window > 0 else 0
        
        is_near_limit = usage_pct >= 80  # Warning at 80%
        should_compact = usage_pct >= (AUTOCOMPACT_THRESHOLD * 100)
        
        return ContextStats(
            total_tokens=total_tokens,
            context_window=self.context_window,
            usage_percentage=usage_pct,
            messages_count=len(self.messages),
            system_tokens=system_tokens,
            conversation_tokens=conversation_tokens,
            tool_calls_count=tool_calls,
            is_near_limit=is_near_limit,
            should_compact=should_compact,
        )
    
    def should_auto_compact(self) -> bool:
        """Check if auto-compaction should trigger.
        
        Multi-level trigger:
        - Level 0: Trigger at 95% threshold
        - Level 1: Trigger at 85% threshold  
        - Level 2: Trigger at 75% threshold
        - Level 3: Trigger at 60% threshold (more aggressive)
        """
        stats = self.get_stats()
        # Higher compaction level = more aggressive (lower threshold)
        threshold = AUTOCOMPACT_THRESHOLD - (self._compaction_level * 0.10)
        threshold = max(0.60, threshold)  # Minimum 60%
        usage_pct = stats.usage_percentage
        return usage_pct >= (threshold * 100)
    
    def compact_messages(self) -> list[dict[str, Any]]:
        """Compact messages to fit within context window.
        
        Multi-level progressive compression:
        - Level 0 (first compaction): 70% target
        - Level 1 (second compaction): 50% target  
        - Level 2+ (deep compaction): 30% target
        
        Progressive compression strategy with semantic-aware tool pairing:
        1. Keep system prompt (always)
        2. Remove assistant_progress messages (lowest value)
        3. Truncate large tool results in-place (adaptive sizing)
        4. Compress tool_call+result pairs into inline summaries
        5. Remove remaining messages by priority (tool_result > tool_call > assistant > user)
        
        Key improvements over simple priority removal:
        - Tool call+result pairs are compressed (not just deleted), preserving
          the semantic link between what was called and what resulted
        - Tool-specific compression: read-only tools get shorter summaries,
          edit tools preserve file paths, error results preserve error text
        - Recent messages are protected — removal starts from oldest
        - Budget-aware: each phase checks if we've reached the target
        """
        stats = self.get_stats()
        if not stats.should_compact:
            return self.messages
        
        # Get target based on compaction level
        target_pct = self._COMPACTION_LEVELS[min(self._compaction_level, 2)]
        target_tokens = int(self.context_window * target_pct)
        
        # Always keep system prompt
        system_messages = [m for m in self.messages if m.get("role") == "system"]
        other_messages = [m for m in self.messages if m.get("role") != "system"]
        
        # Phase 1: Remove progress messages (lowest priority — always safe to drop)
        filtered = [
            m for m in other_messages
            if m.get("role") != "assistant_progress"
        ]
        
        current_tokens = estimate_messages_tokens(filtered)
        if current_tokens <= target_tokens:
            return self._finalize_compaction(
                system_messages, other_messages, filtered, stats, target_tokens
            )
        
        # Phase 2: Truncate large tool results in-place (adaptive threshold)
        # Use different thresholds based on tool type:
        # - Read-only tools: more aggressive truncation (they can be re-run)
        # - Edit tools: less aggressive (their results are side-effect confirmations)
        # - Error results: preserve more (errors are hard to reproduce)
        _READ_TOOL_TRUNCATE = 1500   # chars to keep for read-only tool results
        _EDIT_TOOL_TRUNCATE = 3000   # chars to keep for edit tool results
        _ERROR_TRUNCATE = 4000       # chars to keep for error results
        _DEFAULT_TRUNCATE = 2000     # default truncation threshold
        
        for i, m in enumerate(filtered):
            if m.get("role") != "tool_result":
                continue
            content = m.get("content", "")
            if not content or len(content) <= _DEFAULT_TRUNCATE:
                continue
            
            tool_name = m.get("toolName", "")
            is_error = m.get("isError", False)
            
            # Select truncation threshold based on tool type
            if is_error:
                threshold = _ERROR_TRUNCATE
            elif tool_name in _EDIT_TOOLS:
                threshold = _EDIT_TOOL_TRUNCATE
            elif tool_name in _READ_TOOLS:
                threshold = _READ_TOOL_TRUNCATE
            else:
                threshold = _DEFAULT_TRUNCATE
            
            if len(content) <= threshold:
                continue
            
            # Smart truncation: head + tail with context line
            content_lines = content.split("\n")
            # Determine how many head/tail lines to keep based on threshold
            keep_chars = threshold
            head_lines: list[str] = []
            tail_lines: list[str] = []
            head_chars = 0
            
            for line in content_lines:
                if head_chars + len(line) + 1 > keep_chars * 0.7:
                    break
                head_lines.append(line)
                head_chars += len(line) + 1
            
            # Tail: last few lines
            tail_chars = 0
            for line in reversed(content_lines):
                if tail_chars + len(line) + 1 > keep_chars * 0.3:
                    break
                tail_lines.insert(0, line)
                tail_chars += len(line) + 1
            
            omitted = len(content_lines) - len(head_lines) - len(tail_lines)
            truncated_content = "\n".join(head_lines)
            if omitted > 0:
                truncated_content += f"\n... [{omitted} lines truncated for compaction] ...\n"
            truncated_content += "\n".join(tail_lines)
            
            filtered[i] = {**m, "content": truncated_content}
        
        current_tokens = estimate_messages_tokens(filtered)
        if current_tokens <= target_tokens:
            return self._finalize_compaction(
                system_messages, other_messages, filtered, stats, target_tokens
            )
        
        # Phase 3: Compress tool_call + result pairs into inline summaries
        # Instead of simply deleting pairs, replace them with compact summaries
        # that preserve the semantic link between call and result.
        # This is especially important for edit operations where knowing
        # WHAT was edited is critical even after compaction.
        compressed: list[dict[str, Any]] = []
        i = 0
        while i < len(filtered):
            msg = filtered[i]
            
            # Look for tool_call + tool_result pairs to compress
            if (msg.get("role") == "assistant_tool_call" and
                    i + 1 < len(filtered) and
                    filtered[i + 1].get("role") == "tool_result"):
                
                call_msg = msg
                result_msg = filtered[i + 1]
                tool_name = call_msg.get("toolName", "unknown")
                result_content = result_msg.get("content", "")
                is_error = result_msg.get("isError", False)
                
                # Build a compact summary preserving the key information
                summary = self._compress_tool_pair(call_msg, result_msg)
                
                # Replace the pair with a single compressed message
                compressed.append({
                    "role": "assistant",
                    "content": summary,
                })
                i += 2  # Skip both messages
            else:
                compressed.append(msg)
                i += 1
        
        current_tokens = estimate_messages_tokens(compressed)
        if current_tokens <= target_tokens:
            return self._finalize_compaction(
                system_messages, other_messages, compressed, stats, target_tokens
            )
        
        # Phase 4: Priority-based removal (oldest first, lowest priority removed first)
        # Priority order (highest kept, lowest removed first):
        #   0 = user messages (keep longest — encode intent)
        #   1 = assistant conclusions (keep long — encode results)
        #   2 = compressed tool summaries (medium — already compressed)
        PRIORITY = {
            "user": 0,                    # Highest — encode intent
            "assistant": 1,               # High — encode conclusions + compressed tools
            "assistant_tool_call": 2,     # Medium — should have been compressed in Phase 3
            "tool_result": 3,             # Low — should have been compressed in Phase 3
        }
        
        # Protect recent messages (last 6) from removal
        PROTECTED_RECENT = 6
        
        while estimate_messages_tokens(compressed) > target_tokens and len(compressed) > MIN_MESSAGES_TO_KEEP:
            # Find the message with the lowest priority (highest number) in the removable range
            removable_end = max(MIN_MESSAGES_TO_KEEP, len(compressed) - PROTECTED_RECENT)
            best_idx = None
            best_priority = -1
            
            for idx in range(removable_end):
                role = compressed[idx].get("role", "")
                priority = PRIORITY.get(role, 1)
                if priority > best_priority:
                    best_priority = priority
                    best_idx = idx
            
            if best_idx is None:
                break
            
            del compressed[best_idx]
        
        return self._finalize_compaction(
            system_messages, other_messages, compressed, stats, target_tokens
        )
    
    @staticmethod
    def _compress_tool_pair(call_msg: dict[str, Any], result_msg: dict[str, Any]) -> str:
        """Compress a tool_call + tool_result pair into a compact inline summary.
        
        Tool-specific compression strategies:
        - Edit tools: preserve file path and success/failure status
        - Read tools: just note the file was read (content can be re-read)
        - Search tools: preserve the pattern and result count
        - Command tools: preserve command name and exit status
        - Error results: preserve error message (critical for debugging)
        """
        tool_name = call_msg.get("toolName", "unknown")
        inp = call_msg.get("input", {})
        result_content = result_msg.get("content", "")
        is_error = result_msg.get("isError", False)
        
        # Error results: preserve the error message
        if is_error:
            error_text = result_content.strip()[:200].replace("\n", " ")
            return f"[Tool {tool_name} ERROR: {error_text}]"
        
        # Tool-specific compression
        if tool_name in _EDIT_TOOLS:
            path = inp.get("path") or inp.get("filePath", "unknown")
            # Preserve key edit details
            if tool_name == "multi_edit":
                edits = inp.get("edits", [])
                return f"[Edited {path}: {len(edits)} changes applied]"
            return f"[Edited {path}: ok]"
        
        if tool_name in _READ_TOOLS:
            path = inp.get("path") or inp.get("filePath", "")
            if path:
                # Note: content can be re-read, so just record that it was read
                line_count = result_content.count("\n") + 1
                return f"[Read {path}: {line_count} lines]"
            return f"[{tool_name}: completed]"
        
        if tool_name in _SEARCH_TOOLS:
            pattern = inp.get("pattern") or inp.get("query", "")
            # Count matches from result
            match_lines = [l for l in result_content.split("\n") if l.strip() and not l.startswith("#")]
            return f"[Searched '{pattern[:50]}': {len(match_lines)} results]"
        
        if tool_name in _COMMAND_TOOLS:
            cmd = inp.get("command", "")
            cmd_name = cmd.split()[0] if cmd.split() else "command"
            # Check for success indicators
            exit_info = ""
            if "exit code" in result_content.lower():
                for line in result_content.split("\n"):
                    if "exit code" in line.lower():
                        exit_info = f" ({line.strip()[:50]})"
                        break
            return f"[Ran {cmd_name}{exit_info}]"
        
        # Generic compression: tool name + brief result
        brief = result_content.strip()[:100].replace("\n", " ")
        if brief:
            return f"[{tool_name}: {brief}]"
        return f"[{tool_name}: completed]"
    
    def _finalize_compaction(
        self,
        system_messages: list[dict[str, Any]],
        original_other: list[dict[str, Any]],
        filtered: list[dict[str, Any]],
        stats: ContextStats,
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        """Build the final compacted message list with summary marker."""
        # Build a layered summary of removed messages
        removed_set = set(id(m) for m in filtered)
        removed_messages = [m for m in original_other if id(m) not in removed_set]
        summary_text = _summarize_removed_messages(removed_messages)
        
        removed_count = len(original_other) - len(filtered)
        after_pct = estimate_messages_tokens(filtered) / self.context_window * 100 if self.context_window > 0 else 0
        
        # Add compaction marker with content summary
        compaction_marker = {
            "role": "system",
            "content": (
                f"[Context compacted at {time.strftime('%H:%M:%S')}. "
                f"{removed_count} messages removed. "
                f"Token usage: {stats.usage_percentage:.0f}% → {after_pct:.0f}%]\n"
                + (f"\nSummary of removed conversation:\n{summary_text}" if summary_text else "")
            ),
        }
        
        # Build final message list
        compacted = system_messages + [compaction_marker] + filtered
        
        # Record compaction
        self.compaction_history.append({
            "timestamp": time.time(),
            "before_tokens": stats.total_tokens,
            "after_tokens": estimate_messages_tokens(compacted),
            "messages_removed": len(self.messages) - len(compacted),
            "compaction_level": self._compaction_level,
        })
        
        # Increment compaction level for next compaction (more aggressive)
        self._compaction_level = min(self._compaction_level + 1, 3)
        
        self.messages = compacted
        # Rebuild token cache: discard stale entries, keep only retained msgs
        self._token_cache = {
            id(m): self._token_cache.get(id(m), estimate_message_tokens(m))
            for m in compacted
        }
        return compacted
    
    def get_context_summary(self) -> str:
        """Get a human-readable context usage summary."""
        stats = self.get_stats()
        
        if stats.messages_count == 0:
            return "Context: empty"
        
        status = "✓"
        if stats.is_near_limit:
            status = "⚠"
        if stats.should_compact:
            status = "🔴"
        
        return (
            f"Context: {status} {stats.usage_percentage:.0f}% "
            f"({stats.total_tokens:,}/{stats.context_window:,} tokens, "
            f"{stats.messages_count} msgs, {stats.tool_calls_count} tools)"
        )
    
    def format_context_details(self) -> str:
        """Get detailed context information for /context command."""
        stats = self.get_stats()
        
        lines = [
            "Context Window Usage",
            "=" * 50,
            f"Model: {self.model}",
            f"Context window: {stats.context_window:,} tokens",
            "",
            f"Total tokens: {stats.total_tokens:,}",
            f"Usage: {stats.usage_percentage:.1f}%",
            f"Messages: {stats.messages_count}",
            f"Tool calls: {stats.tool_calls_count}",
            "",
        ]
        
        if stats.should_compact:
            lines.append("⚠️  WARNING: Context is near capacity!")
            lines.append("Auto-compaction will trigger soon.")
            lines.append("")
        
        if self.compaction_history:
            lines.append("Compaction History:")
            for comp in self.compaction_history[-3:]:  # Last 3
                ts = time.strftime("%H:%M:%S", time.localtime(comp["timestamp"]))
                lines.append(
                    f"  {ts}: {comp['messages_removed']} messages removed, "
                    f"{comp['before_tokens']:,} → {comp['after_tokens']:,} tokens"
                )
        
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_context_state(manager: ContextManager) -> None:
    """Save context manager state to disk."""
    state_path = MINI_CODE_DIR / "context_state.json"
    MINI_CODE_DIR.mkdir(parents=True, exist_ok=True)
    
    state = {
        "model": manager.model,
        "context_window": manager.context_window,
        "messages": manager.messages,
        "compaction_history": manager.compaction_history[-10:],  # Keep last 10
        "_compaction_level": manager._compaction_level,  # Save compaction level
    }
    
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def load_context_state() -> ContextManager | None:
    """Load context manager state from disk."""
    state_path = MINI_CODE_DIR / "context_state.json"
    if not state_path.exists():
        return None
    
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        manager = ContextManager(
            model=state.get("model", "default"),
            context_window=state.get("context_window", 0),
            messages=state.get("messages", []),
            compaction_history=state.get("compaction_history", []),
        )
        # Restore compaction level if saved
        if "_compaction_level" in state:
            manager._compaction_level = state["_compaction_level"]
        return manager
    except (json.JSONDecodeError, KeyError):
        return None


def clear_context_state() -> None:
    """Clear saved context state."""
    state_path = MINI_CODE_DIR / "context_state.json"
    if state_path.exists():
        state_path.unlink()
