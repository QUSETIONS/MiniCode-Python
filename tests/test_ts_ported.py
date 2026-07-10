"""Tests ported from the TypeScript parity provenance record.

These translate the TS reference scenarios into pytest so the Python port can be
checked against the same expectations. The TS suite is green (200/0); any failure
here is a real divergence / bug in the Python port.

Stable provenance:
  - Docs/Documentation/engineering/ts-parity-provenance.json

Sources ported:
  - test/input-parser.test.ts          -> parse_input_chunk multiline paste
  - test/local-tool-shortcuts.test.ts  -> parse_local_tool_shortcut
  - test/token-estimator.test.ts       -> context_manager token estimation
  - test/transcript-wrapping.test.ts   -> transcript scroll offset / wrapping
"""

from __future__ import annotations

import pytest

from minicode.context_manager import (
    compute_context_stats,
    estimate_message_tokens,
    estimate_messages_tokens,
    get_model_context_window,
    token_count_with_estimation,
)
from minicode.local_tool_shortcuts import parse_local_tool_shortcut
from minicode.tui.input_parser import parse_input_chunk
from minicode.tui.types import TranscriptEntry


# ---------------------------------------------------------------------------
# Ported from test/input-parser.test.ts
# ---------------------------------------------------------------------------


def test_parse_input_chunk_multiline_paste_does_not_submit() -> None:
    """A pasted multi-line chunk must NOT emit 'return' (submit) keys; the text
    is preserved with newlines. Mirrors TS: parseInputChunk('', pasted)."""
    pasted = "test1\r\ntest2\r\ntest3\r\ntest4\r\ntest5"
    result = parse_input_chunk(pasted, incoming_chunk=pasted)

    assert result.rest == ""
    assert not any(
        getattr(e, "name", None) == "return" for e in result.events
    ), "pasted newlines must not submit"
    joined = "".join(e.text for e in result.events if e.kind == "text")
    assert joined == "test1\ntest2\ntest3\ntest4\ntest5"


def test_parse_input_chunk_real_enter_still_submits() -> None:
    """A lone '\\r' (real Enter key, its own chunk) still emits 'return'."""
    result = parse_input_chunk("\r", incoming_chunk="\r")
    assert any(getattr(e, "name", None) == "return" for e in result.events)


def test_slash_commands_registers_help_and_exit() -> None:
    from minicode.cli_commands import SLASH_COMMANDS

    usages = {c.usage for c in SLASH_COMMANDS}
    assert "/help" in usages
    assert "/exit" in usages
    assert "/collapse" in usages  # TS parity: tool-output collapse command


# ---------------------------------------------------------------------------
# Ported from test/local-tool-shortcuts.test.ts
# ---------------------------------------------------------------------------


def test_parse_ls_with_optional_path() -> None:
    assert parse_local_tool_shortcut("/ls") == {"toolName": "list_files", "input": {}}
    assert parse_local_tool_shortcut("/ls src") == {
        "toolName": "list_files",
        "input": {"path": "src"},
    }


def test_parse_ls_does_not_match_adjacent_text() -> None:
    """'/lsfoo' is NOT a /ls shortcut (TS returns null)."""
    assert parse_local_tool_shortcut("/lsfoo") is None


def test_parse_write_modify_reject_blank_paths() -> None:
    assert parse_local_tool_shortcut("/write ::content") is None
    assert parse_local_tool_shortcut("/modify ::content") is None


def test_parse_edit_rejects_blank_path() -> None:
    assert parse_local_tool_shortcut("/edit   ::before::after") is None


# ---------------------------------------------------------------------------
# Ported from test/token-estimator.test.ts
# ---------------------------------------------------------------------------


def test_estimate_message_tokens_basic() -> None:
    assert 0 < estimate_message_tokens({"role": "system", "content": "You are a helpful assistant."}) < 100
    assert estimate_message_tokens({"role": "user", "content": "Hello, how are you?"}) > 0


def test_estimate_message_tokens_tool_result_higher_density() -> None:
    content = "a" * 100
    tool_tokens = estimate_message_tokens(
        {"role": "tool_result", "toolUseId": "1", "toolName": "read_file", "content": content, "isError": False}
    )
    assistant_tokens = estimate_message_tokens({"role": "assistant", "content": content})
    assert tool_tokens > assistant_tokens


def test_estimate_message_tokens_assistant_tool_call_and_context_summary() -> None:
    assert estimate_message_tokens(
        {"role": "assistant_tool_call", "toolUseId": "1", "toolName": "read_file", "input": {"path": "/some/long/path/to/file.ts"}}
    ) > 0
    assert estimate_message_tokens(
        {"role": "context_summary", "content": "Summary of conversation so far.", "compressedCount": 5}
    ) > 0


def test_estimate_message_tokens_empty_content() -> None:
    # Matches TS: estimateMessageTokens({role:'user',content:''}) === 0.
    # (Python keeps its CJK-aware estimator for non-empty content.)
    assert estimate_message_tokens({"role": "user", "content": ""}) == 0
    assert estimate_message_tokens({"role": "system", "content": ""}) == 0


def test_estimate_messages_tokens_sums_and_empty() -> None:
    messages = [
        {"role": "system", "content": "System prompt here."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    total = estimate_messages_tokens(messages)
    assert total == sum(estimate_message_tokens(m) for m in messages)
    assert estimate_messages_tokens([]) == 0


# ---------------------------------------------------------------------------
# Ported from test/model-context.test.ts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
])
def test_model_context_claude_4(model: str) -> None:
    cw = get_model_context_window(model)
    assert cw.context_window == 200_000
    assert cw.output_reserve == 16_000
    assert cw.effective_input == 184_000


def test_model_context_claude_3_5_sonnet() -> None:
    cw = get_model_context_window("claude-3-5-sonnet-20241022")
    assert cw.context_window == 200_000
    assert cw.output_reserve == 8_192
    assert cw.effective_input == 200_000 - 8_192


def test_model_context_gpt5() -> None:
    cw = get_model_context_window("gpt-5")
    assert cw.context_window == 128_000
    assert cw.output_reserve == 16_000


def test_model_context_gemini_25_pro() -> None:
    cw = get_model_context_window("gemini-2.5-pro")
    assert cw.context_window == 1_048_576
    assert cw.output_reserve == 16_000
    assert cw.effective_input == 1_048_576 - 16_000


def test_model_context_deepseek_chat() -> None:
    cw = get_model_context_window("deepseek-chat")
    assert cw.context_window == 128_000
    assert cw.output_reserve == 4_000


def test_model_context_unknown_default() -> None:
    cw = get_model_context_window("some-unknown-model-v1")
    assert cw.context_window == 128_000
    assert cw.output_reserve == 8_000
    assert cw.effective_input == 120_000


def test_model_context_case_insensitive() -> None:
    upper = get_model_context_window("CLAUDE-OPUS-4-6")
    lower = get_model_context_window("claude-opus-4-6")
    assert (upper.context_window, upper.output_reserve) == (lower.context_window, lower.output_reserve)


def test_model_context_partial_match() -> None:
    cw = get_model_context_window("anthropic/claude-3-5-sonnet-latest")
    assert cw.context_window == 200_000


@pytest.mark.parametrize("model", [
    "claude-opus-4-6", "gpt-4o", "deepseek-chat", "unknown-model",
])
def test_model_context_effective_input_identity(model: str) -> None:
    cw = get_model_context_window(model)
    assert cw.effective_input == cw.context_window - cw.output_reserve


# ---------------------------------------------------------------------------
# Ported from test/token-estimator.test.ts: tokenCountWithEstimation +
# computeContextStats (Python now provides 1:1 counterparts).
# ---------------------------------------------------------------------------


def test_token_count_with_estimation_estimate_only_without_provider_usage() -> None:
    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Hello"},
    ]
    result = token_count_with_estimation(messages)
    assert result["source"] == "estimate_only"
    assert result["provider_usage_tokens"] == 0
    assert result["estimated_tokens"] == estimate_messages_tokens(messages)
    assert result["total_tokens"] == result["estimated_tokens"]
    assert result["is_exact"] is False


def test_token_count_with_estimation_uses_provider_usage() -> None:
    messages = [
        {"role": "system", "content": "System"},
        {
            "role": "assistant",
            "content": "Hi",
            "providerUsage": {"inputTokens": 100, "outputTokens": 25, "totalTokens": 125, "source": "test"},
        },
    ]
    result = token_count_with_estimation(messages)
    assert result["source"] == "provider_usage"
    assert result["provider_usage_tokens"] == 125
    assert result["estimated_tokens"] == 0
    assert result["total_tokens"] == 125
    assert result["is_exact"] is True


def test_compute_context_stats_warning_levels() -> None:
    # Small -> normal
    stats = compute_context_stats(
        [{"role": "system", "content": "Hello"}, {"role": "user", "content": "Test"}],
        "claude-sonnet-4-6",
    )
    assert stats["warning_level"] == "normal"
    assert stats["context_window"] == 200_000
    assert stats["effective_input"] == 184_000
    assert stats["utilization"] < 0.01
    # Huge -> blocked/critical, utilization capped at 1
    big = compute_context_stats([{"role": "system", "content": "x" * 600_000}], "deepseek-chat")
    assert big["warning_level"] in ("blocked", "critical")
    assert big["utilization"] == 1


def test_compute_context_stats_medium_warning() -> None:
    # Sized for Python's CJK-aware estimator (ascii ~4 chars/token): two 200k-char
    # messages -> ~100k tokens -> ~0.54 of claude-sonnet-4-6's 184k effective input
    # -> warning band (>=0.50, <0.85). Verifies compute_context_stats thresholds.
    stats = compute_context_stats(
        [{"role": "system", "content": "x" * 200_000}, {"role": "user", "content": "x" * 200_000}],
        "claude-sonnet-4-6",
    )
    assert stats["warning_level"] in ("warning", "critical")
    assert stats["utilization"] >= 0.5


# ---------------------------------------------------------------------------
# Ported from test/transcript-wrapping.test.ts
# ---------------------------------------------------------------------------


def test_transcript_wrapping_counts_visual_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """A long body wraps across multiple visual rows, which the max scroll offset
    must account for. Mirrors TS: withTerminalWidth(60, getTranscriptMaxScrollOffset).

    Width 60 → inner = 56; a 172-char body wraps to 4 rows + 1 label row = 5,
    so a 4-row window yields scroll offset 1."""
    from minicode.tui import transcript as transcript_module

    monkeypatch.setattr(transcript_module, "_cached_terminal_size", lambda: (60, 24))

    entries = [
        TranscriptEntry(id=1, kind="assistant", body="a" * 166 + "BCDEFG"),
    ]
    offset = transcript_module.get_transcript_max_scroll_offset(entries, window_size=4)

    assert offset == 1
