"""Property-based tests: random byte sequences must never crash the input parser
or the transcript layout engine. Uses Hypothesis for fuzz-style testing.
"""

from __future__ import annotations

from hypothesis import given, strategies as st, settings

from minicode.tui.input_parser import parse_input_chunk
from minicode.tui.types import TranscriptEntry


# Strategy: any mix of printable + control + escape + CJK bytes
arbitrary_text = st.text(
    alphabet=st.characters(min_codepoint=0, max_codepoint=0xFFFF),
    max_size=200,
)


@given(arbitrary_text)
@settings(max_examples=500)
def test_parse_input_chunk_never_crashes(chunk: str) -> None:
    """parse_input_chunk must never raise on any arbitrary string input."""
    result = parse_input_chunk(chunk)
    assert isinstance(result.events, list)
    assert isinstance(result.rest, str)
    # Second pass with remainder (simulates chunked input)
    if result.rest:
        parse_input_chunk(result.rest)


@given(arbitrary_text)
@settings(max_examples=200)
def test_transcript_layout_never_crashes(body: str) -> None:
    """Transcript layout computation must never crash on any body text,
    including CJK, control chars, and very long lines."""
    from minicode.tui import transcript as t
    t._cached_terminal_size = lambda: (80, 24)  # type: ignore[attr-defined]
    entries = [TranscriptEntry(id=1, kind="assistant", body=body)]
    offset = t.get_transcript_max_scroll_offset(entries, window_size=4)
    assert isinstance(offset, int)
    assert offset >= 0
