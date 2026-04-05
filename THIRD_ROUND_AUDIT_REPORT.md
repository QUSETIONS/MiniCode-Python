# Third Round Deep Code Audit Report — MiniCode Python

**Date:** 2026-04-06
**Scope:** All modules under `minicode/` and `minicode/tools/`
**Focus Areas:** Architecture, data processing, concurrency, UX, extensibility, documentation

---

## Summary

| # | File | Line(s) | Risk | Category | Description |
|---|------|---------|------|----------|-------------|
| 1 | anthropic_adapter.py | 134-139 | High | Concurrency | Blocking `time.sleep()` in model adapter |
| 2 | anthropic_adapter.py | 105-139 | Medium | Architecture | Monolithic adapter — hard to test/extend |
| 3 | context_manager.py | 51-53 | Medium | Data | Crude token estimation (4 chars/token) |
| 4 | context_manager.py | 176-214 | Medium | Data | O(n^2) compaction loop |
| 5 | cost_tracker.py | 11-56 | Low | Data | Hardcoded stale pricing |
| 6 | cost_tracker.py | 150-159 | Medium | Data | Integer division precision loss |
| 7 | memory.py | 252-274 | Medium | Architecture | Tight coupling: `get_relevant_context` imports `context_manager` |
| 8 | memory.py | 301-308 | Low | Data | `re` imported inside loop |
| 9 | sub_agents.py | 150-181 | High | Concurrency | No actual execution engine — agents are inert |
| 10 | sub_agents.py | 102-111 | Medium | Architecture | No max-turns enforcement |
| 11 | task_tracker.py | 237-261 | Low | UX | `auto_detect_tasks` regex too fragile |
| 12 | tools/load_skill.py | 1-38 | Medium | Architecture | No skill caching — repeated disk I/O |
| 13 | tools/web_fetch.py | 55-64 | Medium | Security | No redirect limit / SSRF protection |
| 14 | tools/web_search.py | 41-45 | Medium | Reliability | DuckDuckGo scraping is brittle |
| 15 | api_retry.py | 212-255 | High | Concurrency | Async retry doesn't actually detect async functions |
| 16 | async_context.py | 115-174 | Medium | Concurrency | `subprocess.run` in async methods blocks event loop |
| 17 | background_tasks.py | 22-51 | Medium | Concurrency | Module-level mutable dict, no thread safety |
| 18 | state.py | 72-78 | Low | Architecture | Mutable state updates break immutability contract |
| 19 | skills.py | 70-75 | Low | Performance | No caching on `discover_skills` |
| 20 | tooling.py | 124-129 | Medium | Architecture | `execute` swallows all exceptions |

Below is the detailed analysis for each finding.

---

## Finding 1: Blocking `time.sleep()` in Model Adapter

**File:** `D:\Desktop\minicode\py-src\minicode\anthropic_adapter.py`
**Lines:** 134-139
**Risk:** **High**

**Problem:** The `next()` method uses `_sleep()` (which wraps `time.sleep()`) inside retry loops. If this adapter is ever called from an async context (e.g., via `api_retry.py`'s async retry wrapper), the entire event loop blocks.

**Impact:** In TUI or any async-driven UI, all rendering freezes during retry waits (up to 8 seconds per attempt × 5 attempts = 40s max freeze).

**Fix:** Provide an async variant of the adapter:

```python
# anthropic_adapter.py — add async variant
async def next_async(self, messages: list[dict[str, Any]]) -> AgentStep:
    # ... same logic but replace _sleep() with asyncio.sleep()
    import asyncio
    # In the retry loop:
    await asyncio.sleep(_get_retry_delay_ms(...) / 1000)
```

**Expected Benefit:** UI responsiveness during API retries; enables proper async integration.

---

## Finding 2: Monolithic Adapter — Hard to Test/Extend

**File:** `D:\Desktop\minicode\py-src\minicode\anthropic_adapter.py`
**Lines:** 105-139 (the entire `next()` method)
**Risk:** **Medium**

**Problem:** The `next()` method does everything: message conversion, HTTP request, retry logic, response parsing, and step construction. This makes unit testing difficult — you cannot test retry logic without mocking the entire HTTP stack, and you cannot test response parsing without constructing full HTTP responses.

**Impact:** Low test coverage for critical retry and parsing logic; high cognitive complexity.

**Fix:** Extract into composable pieces:

```python
class AnthropicModelAdapter:
    def __init__(self, runtime, tools):
        self.runtime = runtime
        self.tools = tools
        self._http_client = self._make_http_client()

    def _make_http_client(self):
        """Factory for HTTP client — override for testing."""
        return urllib.request

    def _send_request(self, request) -> tuple[Any, int]:
        """Send HTTP request with retry. Returns (parsed_body, status)."""
        # Extract retry loop here
        ...

    def _parse_response(self, data: Any, status: int) -> AgentStep:
        """Parse JSON response into AgentStep."""
        # Extract parsing logic here
        ...

    def next(self, messages: list[dict[str, Any]]) -> AgentStep:
        system, converted = _to_anthropic_messages(messages)
        request = self._build_request(system, converted)
        data, status = self._send_request(request)
        return self._parse_response(data, status)
```

**Expected Benefit:** Each piece independently testable; easier to swap HTTP libraries (e.g., httpx).

---

## Finding 3: Crude Token Estimation

**File:** `D:\Desktop\minicode\py-src\minicode\context_manager.py`
**Lines:** 51-53
**Risk:** **Medium**

**Problem:** `estimate_tokens()` uses a flat `CHARS_PER_TOKEN = 4.0` ratio. This is wildly inaccurate for Chinese text (where 1 character ≈ 1-2 tokens) and code (where identifiers and keywords compress differently). A 10,000-character Chinese document could be estimated as 2,500 tokens when it's actually 5,000-8,000.

**Impact:** Context compaction triggers too late for non-English content, risking context overflow.

**Fix:** Add language-aware estimation or use a configurable tokenizer:

```python
def estimate_tokens(text: str, model: str = "default") -> int:
    if not text:
        return 0
    # Chinese/CJK characters use ~1.5 tokens per char on average
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    ascii_count = len(text) - cjk_count
    # CJK: ~1.5 chars/token, ASCII: ~4 chars/token
    tokens = int(cjk_count / 1.5) + int(ascii_count / 4.0)
    return max(1, tokens)
```

**Expected Benefit:** 2-3x more accurate token estimation for multilingual content.

---

## Finding 4: O(n²) Compaction Loop

**File:** `D:\Desktop\minicode\py-src\minicode\context_manager.py`
**Lines:** 176-214
**Risk:** **Medium**

**Problem:** The `while` loop calls `estimate_messages_tokens(filtered)` on every iteration, which itself iterates over all messages (O(n)). Combined with the outer loop that removes one message at a time, this becomes O(n²) in the number of messages.

**Impact:** For conversations with 500+ messages, compaction takes noticeably long.

**Fix:** Track running token total instead of recalculating:

```python
def compact_messages(self) -> list[dict[str, Any]]:
    # ... setup code ...
    current_tokens = estimate_messages_tokens(filtered)

    while current_tokens > target_tokens and len(filtered) > MIN_MESSAGES_TO_KEEP:
        # Find message to remove
        removed_tokens = estimate_message_tokens(filtered[i])
        del filtered[i]
        current_tokens -= removed_tokens  # O(1) update
```

**Expected Benefit:** O(n) instead of O(n²) compaction — 10-50x faster for long conversations.

---

## Finding 5: Hardcoded Stale Pricing

**File:** `D:\Desktop\minicode\py-src\minicode\cost_tracker.py`
**Lines:** 11-56
**Risk:** **Low**

**Problem:** `MODEL_PRICING` dictionary is hardcoded with approximate prices. Model prices change frequently, and cache pricing varies by provider.

**Impact:** Cost estimates drift from reality over time.

**Fix:** Allow pricing to be loaded from a config file with hardcoded defaults as fallback:

```python
def _load_pricing() -> dict[str, dict[str, float]]:
    pricing_file = MINI_CODE_DIR / "model_pricing.json"
    if pricing_file.exists():
        try:
            return json.loads(pricing_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return MODEL_PRICING  # hardcoded fallback
```

**Expected Benefit:** Accurate cost tracking without code changes.

---

## Finding 6: Integer Division Precision Loss

**File:** `D:\Desktop\minicode\py-src\minicode\cost_tracker.py`
**Lines:** 150-159
**Risk:** **Medium**

**Problem:** The cost calculation uses integer division `input_tokens / 1_000_000` which in Python 3 is float division, but for small token counts (e.g., 500 tokens), the result is `0.0005`, which when multiplied by price ($3.00) gives $0.0015 — effectively zero for most practical purposes. The per-call cost is so small it accumulates rounding errors.

**Impact:** Minor cost underestimation for short interactions.

**Fix:** Use `Decimal` for precise arithmetic or accumulate at a finer granularity:

```python
from decimal import Decimal, ROUND_HALF_UP

def _calculate_cost(pricing: dict, input_tokens: int, output_tokens: int,
                    cache_read: int, cache_write: int) -> float:
    cost = (
        Decimal(input_tokens) * Decimal(pricing["input"]) / Decimal(1_000_000)
        + Decimal(output_tokens) * Decimal(pricing["output"]) / Decimal(1_000_000)
        + Decimal(cache_read) * Decimal(pricing["cache_read"]) / Decimal(1_000_000)
        + Decimal(cache_write) * Decimal(pricing["cache_write"]) / Decimal(1_000_000)
    )
    return float(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
```

**Expected Benefit:** 10-100x more accurate per-call cost tracking.

---

## Finding 7: Tight Coupling Between Memory and Context Manager

**File:** `D:\Desktop\minicode\py-src\minicode\memory.py`
**Lines:** 252-274 (`get_relevant_context` method)
**Risk:** **Medium**

**Problem:** `memory.py` imports `estimate_tokens` from `context_manager.py` inside the method. This creates a circular dependency risk and couples two modules that should be independent.

**Impact:** If `context_manager.py` changes its token estimation API, `memory.py` breaks. Makes testing and refactoring harder.

**Fix:** Move `estimate_tokens` to a shared utility module or define an interface:

```python
# minicode/utils/tokens.py (new module)
def estimate_tokens(text: str) -> int:
    ...

# memory.py
from minicode.utils.tokens import estimate_tokens

# context_manager.py
from minicode.utils.tokens import estimate_tokens
```

**Expected Benefit:** Cleaner module boundaries, easier to swap token estimation strategy.

---

## Finding 8: `re` Imported Inside Loop

**File:** `D:\Desktop\minicode\py-src\minicode\memory.py`
**Lines:** 301-308
**Risk:** **Low**

**Problem:** `import re` is inside the `_parse_memory_md` method, and `re.findall`/`re.sub` are called for every list item. While Python caches module imports, this is still poor style and makes the code look like the import was forgotten at module level.

**Fix:** Move `import re` to the top of the file.

**Expected Benefit:** Cleaner code, follows PEP 8 conventions.

---

## Finding 9: No Actual Execution Engine for Sub-Agents

**File:** `D:\Desktop\minicode\py-src\minicode\sub_agents.py`
**Lines:** 150-181 (`spawn_agent` and related methods)
**Risk:** **High**

**Problem:** The `SubAgentManager` can spawn agent instances and add messages, but there is no `run()` or `execute()` method that actually drives the agent loop. The agents sit inert — messages are added but the model is never called.

**Impact:** Sub-agent system is a skeleton with no muscle. Users who expect delegated execution will be confused.

**Fix:** Add an execution method:

```python
def run_agent_sync(self, agent_id: str, model: ModelAdapter,
                   tools: ToolRegistry, cwd: str) -> AgentInstance:
    """Execute the agent's agent loop synchronously."""
    instance = self.agents.get(agent_id)
    if not instance or instance.status != "running":
        return instance

    from minicode.agent_loop import run_agent_turn

    try:
        messages = run_agent_turn(
            model=model,
            tools=tools,
            messages=instance.messages,
            cwd=cwd,
            max_steps=instance.definition.max_turns,
        )
        instance.messages = messages
        instance.turn_count = len(messages) - 1  # minus system prompt
        instance.status = "completed"
        instance.result = messages[-1].get("content", "") if messages else ""
    except Exception as e:
        instance.status = "failed"
        instance.error = str(e)

    instance.completed_at = time.time()
    return instance
```

**Expected Benefit:** Sub-agents become functional rather than decorative.

---

## Finding 10: No Max-Turns Enforcement

**File:** `D:\Desktop\minicode\py-src\minicode\sub_agents.py`
**Lines:** 102-111
**Risk:** **Medium**

**Problem:** `AgentDefinition` has `max_turns` field, but `add_message()` never checks against it. An agent can accumulate unlimited turns.

**Impact:** Potential infinite conversation in sub-agents, wasting tokens and cost.

**Fix:** Enforce in `add_message`:

```python
def add_message(self, agent_id: str, message: dict[str, Any]) -> bool:
    instance = self.agents.get(agent_id)
    if not instance or instance.status != "running":
        return False

    if instance.turn_count >= instance.definition.max_turns:
        instance.status = "failed"
        instance.error = f"Exceeded max turns ({instance.definition.max_turns})"
        instance.completed_at = time.time()
        return False

    # ... rest of method
```

**Expected Benefit:** Prevents runaway sub-agent conversations and unexpected costs.

---

## Finding 11: Fragile Task Auto-Detection Regex

**File:** `D:\Desktop\minicode\py-src\minicode\task_tracker.py`
**Lines:** 237-261
**Risk:** **Low**

**Problem:** `auto_detect_tasks` splits on commas and checks for sequential words. This produces many false positives (e.g., "I want to fix the bug, improve the docs, and add tests" could be valid but "The code has imports, classes, and functions" would be a false positive).

**Impact:** Annoying false task list creation; user experience degradation.

**Fix:** Require stronger signals (explicit numbering, bullet points, or "first/second/third" patterns):

```python
def auto_detect_tasks(self, user_input: str) -> list[str] | None:
    # Only detect explicit numbered/bulleted lists with >= 3 items
    # Remove comma-splitting heuristic entirely — too noisy
    ...
```

**Expected Benefit:** Fewer false positives, more trustworthy task detection.

---

## Finding 12: No Skill Caching — Repeated Disk I/O

**File:** `D:\Desktop\minicode\py-src\minicode\tools\load_skill.py`
**Lines:** 1-38 (entire file)
**Risk:** **Medium**

**Problem:** Every `load_skill()` call reads from disk. `discover_skills()` walks the entire skills directory tree. These operations are repeated every turn when building system prompts.

**Impact:** Unnecessary disk I/O on every agent turn. Skills rarely change during a session.

**Fix:** Add an LRU cache with TTL:

```python
import functools
import time

@functools.lru_cache(maxsize=64)
def _cached_discover_skills(cwd: str, cache_version: int) -> list[SkillSummary]:
    return discover_skills.__wrapped__(cwd)

def discover_skills_cached(cwd: str | Path, ttl_seconds: int = 60) -> list[SkillSummary]:
    cache_key = int(time.time() / ttl_seconds)
    return _cached_discover_skills(str(cwd), cache_key)
```

**Expected Benefit:** 50-100ms saved per turn from avoiding repeated disk scans.

---

## Finding 13: No Redirect Limit / SSRF Protection in web_fetch

**File:** `D:\Desktop\minicode\py-src\minicode\tools\web_fetch.py`
**Lines:** 55-64
**Risk:** **Medium**

**Problem:** `urllib.request.urlopen` follows redirects automatically with no limit control. An attacker controlling a URL could redirect to internal services (SSRF attack).

**Impact:** Potential access to internal network resources, metadata endpoints (e.g., `http://169.254.169.254/` on AWS), or local services.

**Fix:** Add redirect limiting and URL validation:

```python
import ipaddress
from urllib.parse import urlparse

BLOCKED_HOSTS = {"169.254.169.254", "localhost", "127.0.0.1", "0.0.0.0", "::1"}

def _is_safe_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.hostname in BLOCKED_HOSTS:
        return False, f"Blocked host: {parsed.hostname}"
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False, f"Private/internal IP: {parsed.hostname}"
    except ValueError:
        pass  # Not an IP — hostname, resolve later
    return True, ""

# In _run():
    safe, reason = _is_safe_url(url)
    if not safe:
        return ToolResult(ok=False, output=f"URL blocked: {reason}")

    # Limit redirects
    class LimitedRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if len(getattr(req, '_redirect_count', 0)) > 5:
                raise urllib.error.HTTPError(req.full_url, 302, "Too many redirects", None, None)
            req._redirect_count = getattr(req, '_redirect_count', 0) + 1
            return urllib.request.Request(newurl, ...)

    opener = urllib.request.build_opener(LimitedRedirect())
```

**Expected Benefit:** Prevents SSRF attacks and redirect loops.

---

## Finding 14: Brittle DuckDuckGo Scraping

**File:** `D:\Desktop\minicode\py-src\minicode\tools\web_search.py`
**Lines:** 41-45
**Risk:** **Medium**

**Problem:** The web search tool scrapes DuckDuckGo's HTML interface, which is subject to frequent changes. The regex patterns (`class="result__a"`, `class="result__snippet"`) are fragile and break when DuckDuckGo updates their HTML.

**Impact:** Search functionality silently fails when DuckDuckGo changes their HTML structure.

**Fix:** Add fallback parsing and graceful degradation:

```python
def _parse_duckduckgo_results(html: str, max_results: int) -> list[dict[str, str]]:
    """Parse DuckDingGo HTML search results with multiple fallback strategies."""
    import re

    # Try primary patterns first
    results = _parse_primary_patterns(html, max_results)

    if not results:
        # Fallback: extract any href + adjacent text
        results = _parse_fallback_patterns(html, max_results)

    return results
```

Also add `User-Agent` rotation and rate limiting to avoid being blocked.

**Expected Benefit:** More resilient search; graceful degradation instead of silent failure.

---

## Finding 15: Async Retry Doesn't Actually Detect Async Functions

**File:** `D:\Desktop\minicode\py-src\minicode\api_retry.py`
**Lines:** 212-255
**Risk:** **High**

**Problem:** `hasattr(func, "__await__")` is not a reliable way to detect async functions. A regular function that returns a coroutine (like `async def outer(): return inner_async()`) would pass this check incorrectly. Additionally, this function is marked `async` but catches `HTTPError` from the sync retry module — if the wrapped function raises a urllib HTTPError, it won't match the custom `HTTPError` class defined in this module.

**Impact:** Async retry may fail to retry async functions correctly, or may retry sync functions incorrectly.

**Fix:** Use `asyncio.iscoroutinefunction()` for detection and handle both error types:

```python
async def retry_with_backoff_async(func, *args, max_retries=MAX_RETRIES, **kwargs):
    import asyncio

    is_async = asyncio.iscoroutinefunction(func)

    for attempt in range(max_retries + 1):
        try:
            if is_async:
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            return result
        except (HTTPError, urllib.error.HTTPError) as e:
            status_code = getattr(e, "status_code", getattr(e, "code", None))
            if status_code not in RETRYABLE_STATUS:
                raise
            # ... rest of retry logic
```

**Expected Benefit:** Reliable async retry behavior.

---

## Finding 16: `subprocess.run` in Async Methods Blocks Event Loop

**File:** `D:\Desktop\minicode\py-src\minicode\async_context.py`
**Lines:** 115-174
**Risk:** **Medium**

**Problem:** `_get_branch()`, `_get_status()`, `_get_log()` are `async def` methods but use `subprocess.run()` (synchronous) internally. The `asyncio.gather()` calls in `get_full_context()` appear parallel but actually run sequentially because `subprocess.run` blocks the thread.

**Impact:** False sense of parallelism. Users expecting speedup from async gathering get none.

**Fix:** Use `asyncio.create_subprocess_exec()`:

```python
async def _get_branch(self) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--abbrev-ref", "HEAD",
            cwd=str(self.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip()
    except Exception:
        pass
    return "unknown"
```

**Expected Benefit:** True parallelism for context collection; 2-3x faster for I/O-bound context gathering.

---

## Finding 17: Module-Level Mutable Dict — No Thread Safety

**File:** `D:\Desktop\minicode\py-src\minicode\background_tasks.py`
**Lines:** 22-51
**Risk:** **Medium**

**Problem:** `_background_tasks` is a module-level dict accessed without any locking. If multiple threads register/check tasks simultaneously, race conditions can occur (e.g., two tasks getting the same ID, or a task being checked while being registered).

**Impact:** Potential data corruption in multi-threaded scenarios (e.g., if the TUI runs background task checks on a separate thread).

**Fix:** Add threading.Lock:

```python
import threading

_background_tasks: dict[str, dict[str, Any]] = {}
_tasks_lock = threading.Lock()

def register_background_shell_task(command, pid, cwd):
    with _tasks_lock:
        # ... existing logic

def list_background_tasks():
    with _tasks_lock:
        return [_refresh_record(dict(record)) for record in _background_tasks.values()]
```

**Expected Benefit:** Thread-safe background task management.

---

## Finding 18: Mutable State Updates Break Immutability Contract

**File:** `D:\Desktop\minicode\py-src\minicode\state.py`
**Lines:** 72-78
**Risk:** **Low**

**Problem:** The `Store.set_state()` method claims to provide "immutable updates" but the updaters mutate the state in place (`state.message_count = count`). The check `if next_state is prev` will always be False since the same object is returned.

**Impact:** Subscribers get notified but cannot do "before vs after" comparison since it's the same object. Breaks time-travel debugging and undo features.

**Fix:** Either enforce true immutability with `dataclasses.replace()` or rename the contract:

```python
def set_state(self, updater: Callable[[T], T]) -> None:
    prev = self._state
    next_state = updater(prev)

    # For dataclass states, use replace for true immutability
    if hasattr(prev, "__dataclass_fields__"):
        import dataclasses
        next_state = dataclasses.replace(prev, **{
            k: getattr(next_state, k) for k in prev.__dataclass_fields__
            if getattr(next_state, k) != getattr(prev, k)
        })

    if next_state is prev:
        return
    # ... rest
```

Or more practically, document that this is a mutable store (like Zustand with mutable pattern):

```python
# Rename class docstring:
"""Zustand-style state management with mutable updates.
Subscribers are notified on state changes, but the state
object itself is mutated in place."""
```

**Expected Benefit:** Accurate documentation; predictable behavior for subscribers.

---

## Finding 19: No Caching on `discover_skills`

**File:** `D:\Desktop\minicode\py-src\minicode\skills.py`
**Lines:** 70-75
**Risk:** **Low**

**Problem:** `discover_skills()` walks 4 directory trees and reads every `SKILL.md` file. This is called every time system prompt is rebuilt (every turn).

**Impact:** Repeated disk traversal on every turn — wasteful when skills rarely change.

**Fix:** Same as Finding 12 — add caching with invalidation when skills are installed/removed.

**Expected Benefit:** Eliminates redundant disk I/O.

---

## Finding 20: `execute()` Swallows All Exceptions

**File:** `D:\Desktop\minicode\py-src\minicode\tooling.py`
**Lines:** 124-129
**Risk:** **Medium**

**Problem:** `ToolRegistry.execute()` catches `Exception` (bare except with `BLE001` noqa) and converts all errors to string output. This means `KeyboardInterrupt`, `SystemExit`, and `MemoryError` are also caught and suppressed.

**Impact:** Critical system exceptions are hidden from users and logs. `Ctrl+C` during tool execution would be swallowed.

**Fix:** Re-raise critical exceptions:

```python
def execute(self, tool_name: str, input_data: Any, context: ToolContext) -> ToolResult:
    tool = self.find(tool_name)
    if tool is None:
        return ToolResult(ok=False, output=f"Unknown tool: {tool_name}")

    try:
        parsed = tool.validator(input_data)
        return tool.run(parsed, context)
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise  # Re-raise critical exceptions
    except Exception as error:
        return ToolResult(ok=False, output=f"Tool error: {type(error).__name__}: {error}")
```

**Expected Benefit:** Proper signal-to-noise in error handling; Ctrl+C works during tool execution.

---

## Recommendations by Priority

### Immediate (High Risk)
1. **Finding 1:** Add async sleep variant in anthropic_adapter.py
2. **Finding 9:** Implement actual sub-agent execution engine
3. **Finding 15:** Fix async retry detection logic
4. **Finding 13:** Add SSRF protection to web_fetch

### Short-term (Medium Risk)
5. **Finding 2:** Refactor monolithic adapter into composable pieces
6. **Finding 3:** Language-aware token estimation
7. **Finding 4:** O(n) compaction via running token total
8. **Finding 7:** Extract shared token utility module
9. **Finding 10:** Enforce max-turns in sub-agents
10. **Finding 16:** True async subprocess in context collector
11. **Finding 17:** Thread-safe background task registry
12. **Finding 20:** Re-raise critical exceptions in tool executor

### Medium-term (Low Risk / Nice-to-Have)
13. **Finding 5:** Externalize model pricing to config file
14. **Finding 6:** Use Decimal for precise cost calculation
15. **Finding 8:** Move `import re` to module level
16. **Finding 11:** Strengthen task auto-detection
17. **Finding 12/19:** Add skill caching with TTL
18. **Finding 14:** Add fallback parsing for web search
19. **Finding 18:** Clarify or fix state immutability contract
20. **Finding 14:** Add DuckDuckGo parsing fallback

---

## Overall Architecture Assessment

**Strengths:**
- Well-organized module structure with clear separation of concerns
- Good use of TypedDict and dataclasses for type safety
- Hooks system enables extensibility
- Auto-mode permission system is thoughtful

**Weaknesses:**
- Missing actual execution engine for sub-agent system
- Async code is inconsistently applied (some methods claim async but use sync I/O)
- No caching layer for frequently-accessed but rarely-changing data (skills, config)
- Error handling is inconsistent (some places re-raise, some swallow)

**Technical Debt Estimate:**
- ~40 hours to address High-risk findings
- ~80 hours to address Medium-risk findings
- ~40 hours to address Low-risk findings
- **Total: ~160 hours** for comprehensive remediation
