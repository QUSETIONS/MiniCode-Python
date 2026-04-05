"""Benchmark: scaling behavior with increasing session size."""
import sys
import time
sys.stdout.reconfigure(encoding="utf-8")

from minicode.tui.transcript import (
    TranscriptEntry, render_transcript, _render_transcript_lines,
    _compute_total_lines, _entry_cache, _line_count_cache
)

for size in [100, 500, 2000, 5000]:
    entries = []
    for i in range(size):
        if i % 3 == 0:
            entries.append(TranscriptEntry(id=i, kind="user", body=f"User message {i} with typical content"))
        elif i % 3 == 1:
            entries.append(TranscriptEntry(
                id=i, kind="assistant",
                body=f"Here is a **response** with `code` and some longer text.\n- point 1\n- point 2\n- point 3"
            ))
        else:
            entries.append(TranscriptEntry(
                id=i, kind="tool", body=f"file content line 1\nline 2\nline 3\nline 4\nline 5",
                toolName="read_file", status="success"
            ))

    # Warm cache
    _entry_cache.clear()
    _line_count_cache.clear()
    render_transcript(entries, 0, 30)

    N = 200

    # Old: render all then slice
    t0 = time.perf_counter()
    for _ in range(N):
        all_lines = _render_transcript_lines(entries)
        end_idx = len(all_lines)
        start_idx = max(0, end_idx - 30)
        _ = "\n".join(all_lines[start_idx:end_idx])
    ms_old = (time.perf_counter() - t0) / N * 1000

    # New: windowed
    t0 = time.perf_counter()
    for _ in range(N):
        _ = render_transcript(entries, 0, 30)
    ms_new = (time.perf_counter() - t0) / N * 1000

    total_lines = _compute_total_lines(entries)
    speedup = ms_old / ms_new if ms_new > 0 else 0
    print(f"  {size:5d} entries ({total_lines:6d} lines): OLD {ms_old:6.2f}ms  NEW {ms_new:6.2f}ms  => {speedup:.1f}x")
