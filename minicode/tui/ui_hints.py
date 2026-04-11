from __future__ import annotations

import random

from minicode.tui.state import ScreenState, TtyAppArgs


def _get_contextual_help(state: ScreenState, args: TtyAppArgs) -> str | None:
    """Return a small context-sensitive hint for the footer area."""
    if not state.is_busy and not state.pending_approval:
        tips = [
            "💡 Tip: Use /skills to see available workflows",
            "💡 Tip: Try '帮我分析这个项目' to get started",
            "💡 Tip: Use Tab to autocomplete commands",
            "💡 Tip: Type /help for all commands",
            "💡 Tip: Use Ctrl+R to search history",
        ]
        return random.choice(tips)

    if state.is_busy and state.active_tool:
        return f"⏳ Running {state.active_tool}... Press Ctrl+C to cancel"

    if state.pending_approval:
        return "⚠️ Permission required. Use arrow keys and Enter to choose"

    return None
