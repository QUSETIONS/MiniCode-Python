# MiniCode Python Advanced Improvement Plan

## Goal

Make MiniCode Python feel closer to Claude Code in sustained coding sessions: reliable agent orchestration, responsive TUI, safe tools, strong context management, clean MCP integration, and measurable quality gates.

This plan is based on a local architecture review of the current branch. The `dual-codex-review` MCP was attempted first but returned `Transport closed`; rerun this plan through dual review when that MCP is healthy.

## Current Baseline

- Core agent loop exists with multi-step tool use, recoverable empty/thinking response handling, concurrent read-only tool execution, and callback hooks.
- TUI has been split into state, event flow, session flow, runtime control, renderer, transcript layout, navigation, tool lifecycle, and UI hints.
- Transcript rendering now has windowed layout, revision-aware layout caching, and renderer snapshot caching.
- MCP stdio support exists for tools, resources, and prompts, with lazy startup and basic server summaries.
- Context manager already has token estimation and layered compaction primitives.
- Sessions use incremental delta saves and metadata indexing.
- Tests are broad and currently pass locally, but CI/release automation is not yet first-class in the repository.

## Constraints

- Preserve zero-runtime-dependency positioning unless a dependency has a strong product payoff.
- Keep Python 3.11+ support.
- Keep compatibility with the existing `minicode-py`, `minicode-headless`, `minicode-gateway`, and `minicode-cron` entry points.
- Do not weaken permission behavior for write, shell, MCP, or destructive tools.
- Use failing tests first for behavior changes.
- Keep `out.txt` and other local scratch files out of commits.

## Phase P0: Reliability And Safety Foundation

### P0.1 Add CI as a merge gate

Modify:
- `.github/workflows/ci.yml`
- `pyproject.toml`

Steps:
1. Add a GitHub Actions workflow for Windows, Linux, and macOS.
2. Run `python -m compileall -q minicode tests`.
3. Run `python -m pytest`.
4. Add a lightweight import smoke test for console entry points.
5. Optionally add Python 3.11 and 3.12 matrix if runtime is stable.

Verification:
- `python -m compileall -q minicode tests`
- `python -m pytest`
- CI green on all targeted platforms.

Risk:
- Existing Windows pytest atexit cleanup warning may need isolation or temp-dir configuration before it becomes CI noise.

### P0.2 Create structured permission decision tests

Modify:
- `tests/test_permissions.py`
- `minicode/permissions.py`

Steps:
1. Add regression tests for workspace path access, external path approval, denied path persistence, command allow/deny patterns, and destructive command classification.
2. Add Windows-style path tests for case-insensitive prefix handling.
3. Add tests for `deny_with_feedback` and turn-scoped edit permissions.
4. Only then refactor permission internals if test gaps reveal ambiguity.

Verification:
- `python -m pytest tests/test_permissions.py`

Risk:
- Permission persistence touches user-level files; tests should patch `MINI_CODE_PERMISSIONS_PATH`.

### P0.3 Stabilize MCP process lifecycle

Modify:
- `minicode/mcp.py`
- `tests/test_mcp.py`

Steps:
1. Add tests for server process exit while requests are pending.
2. Add tests for timeout cleanup, payload limit handling, and repeated lazy reconnect.
3. Add tests for resource and prompt tools, not just tool calls.
4. Add explicit dispose coverage from `ToolRegistry` shutdown paths.

Verification:
- `python -m pytest tests/test_mcp.py`

Risk:
- Cross-platform process termination differs between Windows and Unix; fake MCP fixture should avoid shell-specific behavior.

## Phase P1: Claude Code-Like Agent Experience

### P1.1 Introduce an agent event stream

Create:
- `minicode/agent_events.py`
- `tests/test_agent_events.py`

Modify:
- `minicode/agent_loop.py`
- `minicode/tui/input_handler.py`
- `minicode/headless.py`

Steps:
1. Define typed events: `AssistantDelta`, `AssistantMessage`, `Progress`, `ToolStart`, `ToolResult`, `TurnDone`, `TurnError`.
2. Replace scattered callback plumbing with a single optional event sink.
3. Keep compatibility shims for existing callbacks during migration.
4. Update TUI to render from event stream while preserving current behavior.
5. Update headless mode to consume the same event stream.

Verification:
- `python -m pytest tests/test_agent_loop.py tests/test_tty_app.py`
- Manual mock run: `MINI_CODE_MODEL_MODE=mock python -m minicode.main`

Risk:
- This touches the highest-value path. Keep it adapter-first: add event stream without deleting old callbacks in the same commit.

### P1.2 Add plan/todo continuity as first-class state

Modify:
- `minicode/tools/todo_write.py`
- `minicode/task_tracker.py`
- `minicode/tui/renderer.py`
- `minicode/session.py`

Steps:
1. Persist todos into `SessionData`.
2. Render current todo state in the TUI footer or contextual help area.
3. Make `todo_write` output compact, deterministic summaries.
4. Add resume tests proving todos survive session reload.

Verification:
- `python -m pytest tests/test_session.py tests/test_tty_app.py`

Risk:
- If todos are duplicated into both messages and session metadata, compaction can drift. Pick one canonical store.

### P1.3 Improve sub-agent task orchestration

Modify:
- `minicode/tools/task.py`
- `minicode/agent_loop.py`
- `tests/test_tools.py`

Steps:
1. Make sub-agent result schema structured: summary, files inspected, files changed, risks, verification.
2. Add read-only enforcement tests for `explore` and `plan`.
3. Add parent trace IDs so tool output can be linked to the child run.
4. Add optional `max_turns` override with bounded limits.

Verification:
- `python -m pytest tests/test_tools.py tests/test_agent_loop.py`

Risk:
- Sub-agent recursion must be bounded to prevent runaway task spawning.

## Phase P2: Context, Memory, And Long-Session Performance

### P2.1 Replace heuristic compaction with explicit compaction artifacts

Modify:
- `minicode/context_manager.py`
- `minicode/session.py`
- `tests/test_new_features.py`

Steps:
1. Represent compaction as a structured artifact with source message range, files, decisions, tool results, and unresolved tasks.
2. Store compaction artifacts in session metadata.
3. Add tests that compaction preserves tool errors, edited file paths, and user constraints.
4. Keep the current layered summary builder as implementation detail.

Verification:
- `python -m pytest tests/test_new_features.py tests/test_session.py`

Risk:
- Over-aggressive compaction can erase user intent. Test preservation before optimizing token size.

### P2.2 Add context budget telemetry

Create:
- `minicode/context_telemetry.py`
- `tests/test_context_telemetry.py`

Modify:
- `minicode/agent_loop.py`
- `minicode/tui/ui_hints.py`

Steps:
1. Track estimated context usage before each model call.
2. Emit telemetry events when crossing 50%, 75%, 90%, and compaction threshold.
3. Show compact status in TUI hints without spamming transcript.
4. Add a debug command or log section for context budget history.

Verification:
- `python -m pytest tests/test_context_telemetry.py tests/test_agent_loop.py`

Risk:
- Token estimation is approximate. UI should say "estimated", not imply exact billing.

### P2.3 Add transcript performance benchmarks as regression checks

Modify:
- `benchmarks/performance_benchmark.py`
- `bench_optim.py`
- `tests/test_renderer_performance.py`

Steps:
1. Move ad-hoc benchmark scripts into a single benchmark entry point.
2. Add deterministic transcript fixtures for 100, 1,000, 5,000, and 20,000 entries.
3. Add a non-flaky test for algorithmic behavior, such as visible window render count not scaling with full transcript size.
4. Keep wall-clock benchmarks out of normal pytest unless behind an env flag.

Verification:
- `python -m pytest tests/test_renderer_performance.py`
- `python benchmarks/performance_benchmark.py`

Risk:
- Wall-clock tests are flaky on CI; assert structural counters in pytest and print timings separately.

## Phase P3: MCP And Tooling Upgrade

### P3.1 Promote MCP resources and prompts to first-class UX

Modify:
- `minicode/mcp.py`
- `minicode/tools/__init__.py`
- `minicode/prompt.py`
- `README.md`

Steps:
1. Ensure resource and prompt gateway tools are discoverable in `/tools`.
2. Add prompt text that teaches when to use MCP resources/prompts.
3. Add compact server status in startup banner and session metadata.
4. Add tests for `mcp__server__read_resource` and `mcp__server__get_prompt` naming and execution.

Verification:
- `python -m pytest tests/test_mcp.py tests/test_prompt.py`

Risk:
- MCP prompts can inject instructions. Treat them as external content and label them in the prompt.

### P3.2 Add tool result channels

Modify:
- `minicode/tooling.py`
- `minicode/agent_loop.py`
- Tool modules under `minicode/tools/`

Steps:
1. Extend `ToolResult` with optional `summary`, `metadata`, and `artifacts`.
2. Keep `output` for backward compatibility.
3. Update high-volume tools (`read_file`, `grep_files`, `run_command`, `test_runner`) first.
4. Use `summary` for transcript preview and `output` for model context only when necessary.

Verification:
- `python -m pytest tests/test_tools.py tests/test_agent_loop.py tests/test_tui.py`

Risk:
- Adapter expectations may assume text-only tool results. Keep wire format unchanged until adapters are updated.

### P3.3 Tool permission preflight

Modify:
- `minicode/tooling.py`
- `minicode/tools/run_command.py`
- `minicode/tools/write_file.py`
- `minicode/tools/edit_file.py`
- `minicode/tools/patch_file.py`

Steps:
1. Add optional `permission_preview(input, context)` to tool definitions.
2. Let TUI show a more specific approval prompt before execution.
3. Include command risk category, target paths, and persistence scope.
4. Add tests for preview content.

Verification:
- `python -m pytest tests/test_tools.py tests/test_permissions.py`

Risk:
- Do not trust preview alone; execution must still enforce permission checks.

## Phase P4: Packaging, Docs, And Release Quality

### P4.1 Package metadata and install polish

Modify:
- `pyproject.toml`
- `README.md`
- `minicode/install.py`

Steps:
1. Add project authors, license file reference, classifiers, keywords, and URLs.
2. Verify console scripts after editable install.
3. Add install docs for mock mode and real provider mode.
4. Add `python -m pip install -e ".[dev]"` to CI.

Verification:
- `python -m pip install -e ".[dev]"`
- `minicode-py --validate-config`

Risk:
- Console scripts behave differently on Windows PowerShell vs cmd; document both.

### P4.2 Replace report sprawl with curated docs

Modify:
- `README.md`
- `docs/`

Steps:
1. Move historical audit/progress reports into `docs/archive/` or remove them from default user path if not needed.
2. Add one canonical architecture doc.
3. Add one contributor guide with test commands and branch workflow.
4. Keep README focused on quick start, capabilities, and examples.

Verification:
- Manual README review.
- Link check if a link checker is added later.

Risk:
- Some reports may contain useful migration context; archive before deletion.

### P4.3 Release checklist

Create:
- `docs/RELEASE_CHECKLIST.md`

Steps:
1. Define pre-release checks: full pytest, compileall, mock-mode smoke, TUI smoke, MCP fake server test, packaging install.
2. Define version bump and changelog rules.
3. Define GitHub PR and tag flow.

Verification:
- Execute checklist once before tagging.

Risk:
- Avoid over-formal process until the project has regular releases.

## Recommended Execution Order

1. P0.1 CI workflow.
2. P0.2 permission tests.
3. P0.3 MCP lifecycle tests.
4. P1.1 agent event stream.
5. P2.1 structured compaction artifacts.
6. P3.1 first-class MCP resources/prompts.
7. P4.1 packaging polish.

## Parallelizable Work

- CI/package docs can run independently of agent event stream.
- Permission tests can run independently of transcript performance work.
- MCP lifecycle tests can run independently of context compaction.
- Documentation cleanup can happen after any implementation phase without blocking code.

## Definition Of Done

- Full test suite passes locally and in CI.
- Mock-mode smoke run works.
- A long transcript fixture renders with stable latency characteristics.
- Permission prompts remain conservative for writes, shell commands, and MCP.
- Session resume preserves messages, transcript, history, todos, and compaction artifacts.
- README accurately reflects the implemented behavior, not aspirational features.
