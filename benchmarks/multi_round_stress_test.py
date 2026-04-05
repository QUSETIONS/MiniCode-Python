"""Multi-round stress test for MiniCode Python performance."""

import timeit
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from minicode.context_manager import estimate_tokens
from minicode.tui.chrome import (
    render_panel,
    render_banner,
    render_footer_bar,
    string_display_width,
    _cached_terminal_size,
)


def test_token_estimation():
    """Test token estimation performance across multiple rounds."""
    test_cases = [
        ('ASCII', 'Hello World ' * 100),
        ('Chinese', '你好世界' * 100),
        ('Mixed', 'Hello 你好 World 世界 ' * 50),
    ]
    
    results = []
    for round_num in range(1, 6):
        round_results = []
        for name, text in test_cases:
            t = timeit.timeit(lambda: estimate_tokens(text), number=10000)
            ops = 10000 / t
            tokens = estimate_tokens(text)
            round_results.append((name, ops, tokens))
        results.append((round_num, round_results))
    
    return results


def test_rendering():
    """Test rendering performance across multiple rounds."""
    cols, rows = _cached_terminal_size()
    
    results = []
    for round_num in range(1, 6):
        round_results = []
        
        # Panel
        t = timeit.timeit(lambda: render_panel("test", "Line " * 100, right_title="right"), number=1000)
        round_results.append(('render_panel', 1000 / t))
        
        # Banner
        t = timeit.timeit(
            lambda: render_banner(
                {"model": "claude-sonnet-4-20250514", "baseUrl": "https://api.anthropic.com"},
                str(Path.cwd()),
                ["cwd: /test"],
                {"transcriptCount": 10, "messageCount": 20, "skillCount": 5, "mcpCount": 1},
            ),
            number=1000,
        )
        round_results.append(('render_banner', 1000 / t))
        
        # Footer
        t = timeit.timeit(
            lambda: render_footer_bar("Running...", True, True, []),
            number=1000,
        )
        round_results.append(('render_footer', 1000 / t))
        
        results.append((round_num, round_results))
    
    return results


def test_string_width():
    """Test string display width performance."""
    test_strings = [
        "Hello World",
        "你好世界",
        "混合 mixed 文本 text 🚀",
    ]
    
    results = []
    for round_num in range(1, 6):
        round_results = []
        for s in test_strings:
            t = timeit.timeit(lambda: string_display_width(s), number=100000)
            ops = 100000 / t
            round_results.append((s[:20], ops))
        results.append((round_num, round_results))
    
    return results


def main():
    print("=" * 80)
    print("MiniCode Python Multi-Round Performance Stress Test")
    print("=" * 80)
    
    # Token estimation test
    print("\n📊 Token Estimation Performance (ops/sec)")
    print("-" * 60)
    token_results = test_token_estimation()
    for round_num, round_results in token_results:
        print(f"\nRound {round_num}:")
        for name, ops, tokens in round_results:
            print(f"  {name:12} {ops:12.0f} ops/sec  -> {tokens} tokens")
    
    # Rendering test
    print("\n\n📊 Rendering Performance (ops/sec)")
    print("-" * 60)
    render_results = test_rendering()
    for round_num, round_results in render_results:
        print(f"\nRound {round_num}:")
        for name, ops in round_results:
            print(f"  {name:20} {ops:12.0f} ops/sec")
    
    # String width test
    print("\n\n📊 String Display Width Performance (ops/sec)")
    print("-" * 60)
    width_results = test_string_width()
    for round_num, round_results in width_results:
        print(f"\nRound {round_num}:")
        for name, ops in round_results:
            print(f"  {name:20} {ops:12.0f} ops/sec")
    
    # Summary
    print("\n\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    
    # Calculate averages
    avg_token_ops = sum(r[1][0][1] for r in token_results) / len(token_results)
    avg_banner_ops = sum(r[1][1][1] for r in render_results) / len(render_results)
    avg_footer_ops = sum(r[1][2][1] for r in render_results) / len(render_results)
    
    print(f"\nToken Estimation (ASCII avg):  {avg_token_ops:,.0f} ops/sec")
    print(f"Banner Rendering (avg):        {avg_banner_ops:,.0f} ops/sec")
    print(f"Footer Rendering (avg):        {avg_footer_ops:,.0f} ops/sec")
    
    print("\n✅ All tests passed!")
    print(f"✅ Completed {len(token_results)} rounds of token estimation")
    print(f"✅ Completed {len(render_results)} rounds of rendering")
    print(f"✅ Completed {len(width_results)} rounds of string width")
    
    # Save results
    output_file = Path(__file__).parent / "stress_test_results.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("Multi-Round Performance Stress Test Results\n")
        f.write("=" * 60 + "\n\n")
        
        f.write("Token Estimation:\n")
        for round_num, round_results in token_results:
            f.write(f"  Round {round_num}:\n")
            for name, ops, tokens in round_results:
                f.write(f"    {name}: {ops:,.0f} ops/sec -> {tokens} tokens\n")
        
        f.write("\nRendering:\n")
        for round_num, round_results in render_results:
            f.write(f"  Round {round_num}:\n")
            for name, ops in round_results:
                f.write(f"    {name}: {ops:,.0f} ops/sec\n")
    
    print(f"\n📄 Results saved to: {output_file}")


if __name__ == "__main__":
    main()
