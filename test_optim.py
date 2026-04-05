"""Quick smoke test for all TUI optimizations."""
import sys
import os
sys.stdout.reconfigure(encoding="utf-8")

from minicode.tui.chrome import string_display_width, wrap_panel_body_line, _stripped_display_width
from minicode.tui.markdown import render_markdownish
from minicode.tui.transcript import (
    TranscriptEntry, get_transcript_window_size, render_transcript,
    get_transcript_max_scroll_offset, _get_entry_lines, _compute_total_lines
)

print("=== 1. Markdown single-pass inline test ===")
md = render_markdownish("Hello **bold** and *italic* and `code` text\n# Heading\n- bullet\n> quote")
assert "bold" in md
assert "code" in md
print("  PASS")

print("=== 2. string_display_width LRU cache test ===")
w1 = string_display_width("\x1b[31mhello\x1b[0m")
assert w1 == 5
info1 = _stripped_display_width.cache_info()
w2 = string_display_width("\x1b[31mhello\x1b[0m")
info2 = _stripped_display_width.cache_info()
assert info2.hits > info1.hits, "Cache should be hit on 2nd call"
print(f"  PASS (cache hits: {info2.hits})")

print("=== 3. wrap_panel_body_line finditer test ===")
long_line = "\x1b[31m" + "a" * 200 + "\x1b[0m"
lines = wrap_panel_body_line(long_line, 80)
assert len(lines) > 1
print(f"  PASS (wrapped into {len(lines)} lines)")

print("=== 4. Windowed transcript rendering test ===")
entries = []
for i in range(100):
    entries.append(TranscriptEntry(id=i, kind="user", body=f"Message {i}"))
    entries.append(TranscriptEntry(id=i + 1000, kind="assistant", body=f"Reply {i}"))

total = _compute_total_lines(entries)
print(f"  Total lines for 200 entries: {total}")

max_scroll = get_transcript_max_scroll_offset(entries, 20)
print(f"  Max scroll offset (ws=20): {max_scroll}")

# Render at bottom
result = render_transcript(entries, 0, 20)
assert len(result.split("\n")) <= 20
print(f"  Bottom render: {len(result.split(chr(10)))} lines - PASS")

# Render at top
result2 = render_transcript(entries, max_scroll, 20)
# top render may include scroll indicator (+2 lines)
assert len(result2.split("\n")) <= 23
print(f"  Top render: {len(result2.split(chr(10)))} lines - PASS")

# Render middle
mid_offset = max_scroll // 2
result3 = render_transcript(entries, mid_offset, 20)
assert len(result3.split("\n")) <= 23
print(f"  Mid render: {len(result3.split(chr(10)))} lines - PASS")

print("=== 5. Entry cache test ===")
entry = TranscriptEntry(id=999, kind="user", body="Cache test")
lines1 = _get_entry_lines(entry)
lines2 = _get_entry_lines(entry)
assert lines1 is lines2, "Should return same cached list"
print("  PASS (cache hit returns same object)")

print("\n✅ All optimizations verified successfully!")
