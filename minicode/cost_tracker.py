"""Cost and usage tracking for API calls.

Tracks token usage, API costs, and code changes across the session.
Inspired by Claude Code's cost-tracker.ts implementation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

# ---------------------------------------------------------------------------
# Pricing (approximate, per 1M tokens)
# ---------------------------------------------------------------------------

MODEL_PRICING = {
    # Anthropic models (USD per 1M tokens)
    "claude-sonnet-4-20250514": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-opus-4-20250514": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "claude-haiku-3-20240307": {
        "input": 0.25,
        "output": 1.25,
        "cache_read": 0.03,
        "cache_write": 0.30,
    },
    # OpenAI models
    "gpt-4o": {
        "input": 2.50,
        "output": 10.0,
        "cache_read": 1.25,
        "cache_write": 2.50,
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
        "cache_read": 0.08,
        "cache_write": 0.15,
    },
    "gpt-4-turbo": {
        "input": 10.0,
        "output": 30.0,
        "cache_read": 5.0,
        "cache_write": 10.0,
    },
    # Default fallback
    "default": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ModelUsage:
    """Usage statistics for a specific model."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0
    error_count: int = 0
    total_duration_ms: int = 0
    
    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )
    
    @property
    def avg_duration_ms(self) -> float:
        """Average API call duration."""
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count


@dataclass
class CostTracker:
    """Tracks API costs and usage across the session.
    
    Inspired by Claude Code's cost-tracker.ts
    """
    # Global totals
    total_cost_usd: float = 0.0
    total_api_duration_ms: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0
    total_lines_modified: int = 0
    
    # Per-model usage
    model_usage: dict[str, ModelUsage] = field(default_factory=dict)
    
    # Session info
    session_start: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    
    def add_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Record API usage.
        
        Args:
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count
            duration_ms: API call duration
            cache_read_tokens: Cache read token count
            cache_write_tokens: Cache write token count
        
        Returns:
            Calculated cost in USD
        """
        # Get pricing
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        
        # Calculate cost
        cost = (
            (input_tokens / 1_000_000) * pricing["input"]
            + (output_tokens / 1_000_000) * pricing["output"]
            + (cache_read_tokens / 1_000_000) * pricing["cache_read"]
            + (cache_write_tokens / 1_000_000) * pricing["cache_write"]
        )
        
        # Update model usage
        if model not in self.model_usage:
            self.model_usage[model] = ModelUsage()
        
        usage = self.model_usage[model]
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.cache_read_tokens += cache_read_tokens
        usage.cache_write_tokens += cache_write_tokens
        usage.cost_usd += cost
        usage.call_count += 1
        usage.total_duration_ms += duration_ms
        
        # Update totals
        self.total_cost_usd += cost
        self.total_api_duration_ms += duration_ms
        self.last_updated = time.time()
        
        return cost
    
    def record_error(self, model: str) -> None:
        """Record an API error.
        
        Args:
            model: Model name
        """
        if model not in self.model_usage:
            self.model_usage[model] = ModelUsage()
        
        self.model_usage[model].error_count += 1
        self.last_updated = time.time()
    
    def record_code_changes(
        self,
        lines_added: int = 0,
        lines_removed: int = 0,
    ) -> None:
        """Record code changes.
        
        Args:
            lines_added: Lines added
            lines_removed: Lines removed
        """
        self.total_lines_added += lines_added
        self.total_lines_removed += lines_removed
        self.total_lines_modified += lines_added + lines_removed
        self.last_updated = time.time()
    
    def get_model_usage(self, model: str) -> ModelUsage:
        """Get usage for a specific model.
        
        Args:
            model: Model name
        
        Returns:
            ModelUsage instance
        """
        return self.model_usage.get(model, ModelUsage())
    
    def get_total_tokens(self) -> int:
        """Get total tokens across all models."""
        return sum(u.total_tokens for u in self.model_usage.values())
    
    def get_total_calls(self) -> int:
        """Get total API calls."""
        return sum(u.call_count for u in self.model_usage.values())
    
    def get_total_errors(self) -> int:
        """Get total API errors."""
        return sum(u.error_count for u in self.model_usage.values())
    
    # -----------------------------------------------------------------------
    # Formatting
    # -----------------------------------------------------------------------
    
    def format_cost_report(self, detailed: bool = False) -> str:
        """Format cost and usage report.
        
        Args:
            detailed: Include per-model breakdown
        
        Returns:
            Formatted report string
        """
        lines = [
            "Cost & Usage Report",
            "=" * 60,
            "",
            "Summary:",
            f"  Total cost: ${self.total_cost_usd:.4f}",
            f"  Total API calls: {self.get_total_calls()}",
            f"  Total API errors: {self.get_total_errors()}",
            f"  Total tokens: {self.get_total_tokens():,}",
            f"  Total API duration: {self.total_api_duration_ms / 1000:.1f}s",
            "",
            "Code Changes:",
            f"  Lines added: {self.total_lines_added:,}",
            f"  Lines removed: {self.total_lines_removed:,}",
            f"  Total modified: {self.total_lines_modified:,}",
        ]
        
        if detailed and self.model_usage:
            lines.extend([
                "",
                "Per-Model Breakdown:",
                "-" * 60,
            ])
            
            for model, usage in self.model_usage.items():
                lines.extend([
                    "",
                    f"  {model}:",
                    f"    Cost: ${usage.cost_usd:.4f}",
                    f"    Calls: {usage.call_count}",
                    f"    Errors: {usage.error_count}",
                    f"    Tokens: {usage.total_tokens:,}",
                    f"      Input: {usage.input_tokens:,}",
                    f"      Output: {usage.output_tokens:,}",
                    f"      Cache read: {usage.cache_read_tokens:,}",
                    f"      Cache write: {usage.cache_write_tokens:,}",
                    f"    Avg duration: {usage.avg_duration_ms:.0f}ms",
                ])
        
        # Session duration
        session_duration = time.time() - self.session_start
        lines.extend([
            "",
            "-" * 60,
            f"Session duration: {session_duration / 60:.1f} minutes",
            f"Cost per minute: ${self.total_cost_usd / max(1, session_duration / 60):.4f}",
        ])
        
        return "\n".join(lines)
    
    def format_short_summary(self) -> str:
        """Format a short summary for status bar.
        
        Returns:
            Short summary string
        """
        if self.total_cost_usd == 0:
            return "Cost: $0.0000"
        
        return (
            f"Cost: ${self.total_cost_usd:.4f} | "
            f"Tokens: {self.get_total_tokens():,} | "
            f"Calls: {self.get_total_calls()}"
        )
