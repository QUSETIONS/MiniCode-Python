"""Smoke test for TUI performance optimizations."""
from minicode.tui.chrome import (
    render_banner, render_footer_bar, render_panel, render_slash_menu,
    _cached_terminal_size, string_display_width, strip_ansi, _ANSI_RE
)
from minicode.tui.transcript import render_transcript, get_transcript_window_size
from minicode.tui.markdown import render_markdownish
from minicode.tui.input_parser import parse_input_chunk
from minicode.tui.types import TranscriptEntry
from minicode.tty_app import _ThrottledRenderer, _get_terminal_size

# Test cached terminal size
cols, rows = _cached_terminal_size()
print(f"Terminal size: {cols}x{rows}")

# Test string_display_width
w = string_display_width("hello 你好")
assert w == 10, f"Expected 10, got {w}"  # 5 ascii + 1 space + 2*2 CJK = 10
print(f"Width of 'hello 你好': {w}")

# Test strip_ansi
stripped = strip_ansi("\033[31mred\033[0m text")
assert stripped == "red text", f"Expected 'red text', got {stripped!r}"
print(f"Stripped: {stripped!r}")

# Test render_markdownish
md = render_markdownish("# Title\n- item1\n- item2\n**bold** and `code`")
assert len(md) > 0
print(f"Markdown rendered OK, {len(md)} chars")

# Test parse_input_chunk
result = parse_input_chunk("hello")
assert len(result.events) == 5  # 5 TextEvent chars
print(f"Input parsed: {len(result.events)} events, rest={result.rest!r}")

# Test render_panel
panel = render_panel("test", "body text here")
assert len(panel) > 0
print(f"Panel rendered OK, {len(panel)} chars")

# Test render_footer_bar
footer = render_footer_bar(None, True, False)
assert len(footer) > 0
print(f"Footer rendered OK, {len(footer)} chars")

# Test _get_terminal_size (tty_app version)
ts = _get_terminal_size()
assert len(ts) == 2
print(f"tty_app terminal size: {ts}")

# Test ThrottledRenderer
call_count = 0
def test_render():
    global call_count
    call_count += 1
tr = _ThrottledRenderer(test_render, min_interval=0.01)
tr.force()
tr.force()
assert call_count == 2
print(f"ThrottledRenderer works, rendered {call_count} times")

# Test TranscriptEntry creation
entry = TranscriptEntry(id=1, kind="user", body="test")
print(f"TranscriptEntry: {entry}")

# Test render_transcript
entries = [
    TranscriptEntry(id=1, kind="user", body="hello"),
    TranscriptEntry(id=2, kind="assistant", body="hi there"),
]
t = render_transcript(entries, 0, 10)
assert len(t) > 0
print(f"Transcript rendered OK, {len(t)} chars")

# Test get_transcript_window_size
ws = get_transcript_window_size()
assert ws >= 8
print(f"Transcript window size: {ws}")

# Test _ANSI_RE is pre-compiled
import re
assert isinstance(_ANSI_RE, re.Pattern)
print(f"_ANSI_RE is pre-compiled: {type(_ANSI_RE)}")

# Test input_parser pre-compiled regexes
from minicode.tui.input_parser import (
    _SGR_MOUSE_RE, _CSI_CURSOR_RE, _CSI_TILDE_RE, _SS3_RE, _ESC_CHAR_RE
)
for name, pattern in [
    ("_SGR_MOUSE_RE", _SGR_MOUSE_RE),
    ("_CSI_CURSOR_RE", _CSI_CURSOR_RE),
    ("_CSI_TILDE_RE", _CSI_TILDE_RE),
    ("_SS3_RE", _SS3_RE),
    ("_ESC_CHAR_RE", _ESC_CHAR_RE),
]:
    assert isinstance(pattern, re.Pattern), f"{name} is not pre-compiled"
print("All input_parser regexes are pre-compiled")

# Test markdown pre-compiled regexes
from minicode.tui.markdown import (
    _RE_TABLE_SEP, _RE_TABLE_ROW, _RE_LIST_ITEM, _RE_INLINE_CODE, _RE_BOLD
)
for name, pattern in [
    ("_RE_TABLE_SEP", _RE_TABLE_SEP),
    ("_RE_TABLE_ROW", _RE_TABLE_ROW),
    ("_RE_LIST_ITEM", _RE_LIST_ITEM),
    ("_RE_INLINE_CODE", _RE_INLINE_CODE),
    ("_RE_BOLD", _RE_BOLD),
]:
    assert isinstance(pattern, re.Pattern), f"{name} is not pre-compiled"
print("All markdown regexes are pre-compiled")

print()
print("=" * 40)
print("ALL SMOKE TESTS PASSED")
print("=" * 40)
