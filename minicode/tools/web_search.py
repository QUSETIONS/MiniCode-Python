from __future__ import annotations

import json
import urllib.request
import urllib.parse
from minicode.tooling import ToolDefinition, ToolResult

MAX_RESULTS = 10


def _validate(input_data: dict) -> dict:
    query = input_data.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query is required and must be non-empty")
    num_results = int(input_data.get("num_results", 5))
    if num_results < 1 or num_results > MAX_RESULTS:
        raise ValueError(f"num_results must be between 1 and {MAX_RESULTS}")
    return {"query": query.strip(), "num_results": num_results}


def _run(input_data: dict, context) -> ToolResult:
    query = input_data["query"]
    num_results = input_data["num_results"]

    try:
        # Use DuckDuckGo HTML search (no API key required)
        search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"

        req = urllib.request.Request(
            search_url,
            headers={
                "User-Agent": "MiniCode-Python/0.5.0 (Terminal Coding Assistant)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
        )

        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8", errors="replace")

        results = _parse_duckduckgo_results(html, num_results)

        if not results:
            return ToolResult(
                ok=False,
                output=f"No search results found for: {query}\n\nTry a different query or check your internet connection.",
            )

        # Format results
        lines = [f"Search results for: {query}", "=" * 60, ""]

        for i, result in enumerate(results, 1):
            lines.extend([
                f"{i}. {result['title']}",
                f"   URL: {result['url']}",
                f"   {result['snippet']}",
                "",
            ])

        lines.append(f"Total results: {len(results)}")

        return ToolResult(ok=True, output="\n".join(lines))

    except urllib.error.URLError as e:
        return ToolResult(
            ok=False,
            output=f"Search failed: {e.reason}\nQuery: {query}\n\nCheck your internet connection.",
        )
    except Exception as e:
        return ToolResult(
            ok=False,
            output=f"Search error: {e}\nQuery: {query}",
        )


def _parse_duckduckgo_results(html: str, max_results: int) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML search results."""
    import re

    results = []

    # Find all result blocks
    result_pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    for match in result_pattern.finditer(html):
        if len(results) >= max_results:
            break

        url = match.group(1)
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        snippet = re.sub(r"<[^>]+>", "", match.group(3)).strip()

        # Clean up entities
        title = title.replace("&amp;", "&").replace("&quot;", '"').replace("&#x27;", "'")
        snippet = snippet.replace("&amp;", "&").replace("&quot;", '"').replace("&#x27;", "'")

        if url and title:
            results.append({
                "title": title,
                "url": url,
                "snippet": snippet[:200],
            })

    return results


web_search_tool = ToolDefinition(
    name="web_search",
    description="Search the web for information. Returns search results with titles, URLs, and snippets. No API key required.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "num_results": {"type": "number", "description": "Number of results to return (1-10, default: 5)"},
        },
        "required": ["query"],
    },
    validator=_validate,
    run=_run,
)
