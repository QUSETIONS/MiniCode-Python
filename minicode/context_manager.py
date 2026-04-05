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
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    "claude-haiku-3-20240307": 100_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
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

def estimate_tokens(text: str) -> int:
    """Rough token estimation based on character count.
    
    Uses average of ~4 characters per token (works for English and code).
    For production, consider tiktoken or exact tokenizer.
    """
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


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
    
    def get_stats(self) -> ContextStats:
        """Calculate current context statistics."""
        if not self.messages:
            return ContextStats(
                context_window=self.context_window,
            )
        
        # Count tokens
        system_tokens = 0
        conversation_tokens = 0
        tool_calls = 0
        
        for msg in self.messages:
            msg_tokens = estimate_message_tokens(msg)
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
        """Check if auto-compaction should trigger."""
        stats = self.get_stats()
        return stats.should_compact
    
    def compact_messages(self) -> list[dict[str, Any]]:
        """Compact messages to fit within context window.
        
        Strategy:
        1. Keep system prompt (always)
        2. Keep recent messages (last N)
        3. Summarize/condense older tool calls
        4. Remove old assistant progress messages
        """
        stats = self.get_stats()
        if not stats.should_compact:
            return self.messages
        
        # Calculate target: reduce to ~70% of context window
        target_tokens = int(self.context_window * 0.70)
        
        # Always keep system prompt
        system_messages = [m for m in self.messages if m.get("role") == "system"]
        other_messages = [m for m in self.messages if m.get("role") != "system"]
        
        # Remove old progress messages first
        filtered = [
            m for m in other_messages
            if m.get("role") != "assistant_progress"
        ]
        
        # If still too large, drop oldest messages one at a time.
        # Prefer dropping tool-call/tool-result pairs first, then plain
        # assistant/user messages.  Always keep the most recent messages.
        while estimate_messages_tokens(filtered) > target_tokens and len(filtered) > MIN_MESSAGES_TO_KEEP:
            removed = False
            for i in range(len(filtered) - MIN_MESSAGES_TO_KEEP):
                role = filtered[i].get("role")
                # Drop tool-call + its result as a pair
                if role == "assistant_tool_call":
                    if (i + 1 < len(filtered) and
                            filtered[i + 1].get("role") == "tool_result"):
                        del filtered[i:i + 2]
                    else:
                        del filtered[i]
                    removed = True
                    break
                # Drop standalone tool_result (orphaned)
                if role == "tool_result":
                    del filtered[i]
                    removed = True
                    break
                # Drop plain user/assistant messages
                if role in ("user", "assistant"):
                    del filtered[i]
                    removed = True
                    break

            if not removed:
                break
        
        # Add compaction marker
        compaction_marker = {
            "role": "system",
            "content": (
                f"[Context compacted at {time.strftime('%H:%M:%S')}. "
                f"Previous {stats.messages_count - len(filtered) - len(system_messages)} messages summarized. "
                f"Token usage reduced from {stats.usage_percentage:.0f}% to "
                f"{estimate_messages_tokens(filtered) / self.context_window * 100:.0f}%]"
            ),
        }
        
        # Build final message list
        compacted = system_messages + [compaction_marker] + filtered
        
        # Record compaction
        self.compaction_history.append({
            "timestamp": time.time(),
            "before_tokens": stats.total_tokens,
            "after_tokens": estimate_messages_tokens(compacted),
            "messages_removed": stats.messages_count - len(compacted),
        })
        
        self.messages = compacted
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
    }
    
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def load_context_state() -> ContextManager | None:
    """Load context manager state from disk."""
    state_path = MINI_CODE_DIR / "context_state.json"
    if not state_path.exists():
        return None
    
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return ContextManager(
            model=state.get("model", "default"),
            context_window=state.get("context_window", 0),
            messages=state.get("messages", []),
            compaction_history=state.get("compaction_history", []),
        )
    except (json.JSONDecodeError, KeyError):
        return None


def clear_context_state() -> None:
    """Clear saved context state."""
    state_path = MINI_CODE_DIR / "context_state.json"
    if state_path.exists():
        state_path.unlink()
