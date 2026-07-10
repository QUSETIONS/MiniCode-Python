# MiniCode Lite Productization Verify

Date: 2026-06-05

## Scope

This verify report closes the `minicode-lite-productization` change and records
the P1-P3 surfaces that were added to move `minicode` toward a lightweight
Claude Code product shape.

## What shipped

### Instruction and policy layers

- structured instruction-layer metadata now travels through prompt assembly,
  live runtime state, saved sessions, inspect, and replay views
- `/instructions` exposes the effective instruction surface in local command
  flows

### Hook workflow productization

- hook health is visible through live summaries, saved-session surfaces, and
  `/hooks`
- recent hook execution status is bounded and inspectable instead of leaking
  into ordinary assistant output

### Delegated background runtime

- delegated-task records and retry/recovery status now persist in session data
- `/delegation`, live TUI summaries, and session replay expose delegated
  runtime state as a first-class product surface

### Extension packaging

- local extension manifests are now discoverable across project and global
  roots
- `/extensions`, `/extension-inspect`, `/extension-enable`, and
  `/extension-disable` are live
- the local sharing/install workflow is documented in
  `Docs/Documentation/superpowers/reports/2026-06-05-minicode-local-extension-workflow.md`

### Product readiness evaluation

- runtime profile artifacts now include provider outage diagnostics
- `benchmarks/release_readiness.py` produces a saved release gate artifact with
  full-repo verification, product smokes, and provider truth
- release-readiness outputs now distinguish local product health from upstream
  provider availability

## Verification

### Targeted checks

- `python -m py_compile minicode/product_surfaces.py minicode/cli_commands.py minicode/runtime_profile_eval.py minicode/release_readiness.py benchmarks/runtime_profile_eval.py benchmarks/release_readiness.py tests/test_cli_commands.py tests/test_runtime_profile_eval.py tests/test_release_readiness.py tests/test_session.py tests/test_tty_app.py tests/test_main.py`
- `pytest -q tests/test_cli_commands.py tests/test_runtime_profile_eval.py tests/test_release_readiness.py tests/test_session.py tests/test_tty_app.py tests/test_main.py`
  - result: `94 passed`

### Product artifacts

- `python benchmarks/runtime_profile_eval.py`
  - wrote:
    - `benchmarks/runtime_profile_eval_results.json`
    - `benchmarks/runtime_profile_eval_results.md`
- `python benchmarks/release_readiness.py`
  - wrote:
    - `benchmarks/release_readiness_results.json`
    - `benchmarks/release_readiness_results.md`

### Full verification

- `pytest -q`
  - result: `1016 passed, 2 skipped, 3 warnings`
  - the remaining warnings are the existing unregistered
    `pytest.mark.benchmark` markers in `tests/test_memory_benchmark.py`

## Release-readiness result

Current release gate status is `warning`, not `blocked`.

- core compile/test/runtime gates passed
- product smoke flows passed:
  - `--list-sessions`
  - `--inspect-session latest`
  - `--replay-session latest`
  - `--preview-rewind latest`
- provider diagnostics still show `provider_outage` for the active upstream
  model path

This is the intended outcome boundary: the local product surface is green, and
the remaining warning is upstream provider availability rather than a local
runtime/product failure.

## Positioning update

With this change, `minicode` now has a stronger claim to the "lightweight
Claude Code" position:

- session-first
- recovery-first
- runtime-observable
- replayable and inspectable
- locally extensible

It still stops short of full Claude Code parity on background orchestration,
enterprise policy, and managed provider reliability, but the P1-P3 lightweight
product surface is now implemented and verified.
