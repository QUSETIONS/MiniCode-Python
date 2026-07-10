---
archived-with: 2026-06-05-minicode-lite-productization
status: final
status: final
---
## Overview

`minicode` already has a strong local runtime kernel: typed phases, verification
guards, widening, session replay, runtime summaries, and checkpoint/rewind. The
remaining gap against a lightweight Claude Code experience is no longer the core
loop. It is the missing product surface around that loop.

This design turns the next stage into five connected capability layers:

1. instruction and policy layers,
2. first-class hook workflows,
3. delegated background runtime,
4. lightweight extension packaging,
5. release-facing readiness evaluation.

The guiding constraint is to stay lightweight and local-first. We should make
the current runtime more inspectable, more recoverable, and more shareable
without adding a heavy cloud control plane.

## Product Positioning

The target is not "full Claude Code parity." The target is a lightweight local
coding agent that preserves the most valuable operator experience:

- clear instruction precedence,
- transparent async behavior,
- bounded delegation,
- recoverable file edits,
- replayable sessions,
- artifact-backed runtime health.

## Scope

### P1

- Explicit instruction-policy layers with precedence and origin metadata.
- First-class hook workflows with inspectable health and operator-facing status.
- Runtime governance UX across CLI, TUI, and saved sessions.

### P2

- Delegated/background runtime as a typed, replayable product surface.
- Lightweight local extension manifests and extension lifecycle commands.
- Shared inspection outputs for delegated work, hooks, and runtime metadata.

### P3

- Release-readiness artifacts that combine tests, runtime profiles, provider
  fallback truth, and product smoke checks.
- A minimal release gate that checks real product workflows, not just unit
  tests.

## Architectural Direction

### 1. Instruction Governance Uses Structured Layers

Instruction loading should no longer be implicit prompt text only. Each runtime
turn should know which global, user, project, and machine-managed instruction
sources were active, in what precedence order, and from which file paths.

That same structure should power:

- prompt assembly debugging,
- live `/session` inspection,
- saved session replay,
- release-readiness evidence.

### 2. Hooks, Delegation, And Runtime Events Share A Common Story

Hooks, background tasks, and delegated subagent-style runs should all publish a
bounded structured summary. The summary must answer:

- what started,
- why it started,
- what produced output,
- whether it failed or recovered,
- where the replayable artifact lives.

This avoids opaque async behavior and keeps the runtime explainable.

### 3. Extension Packaging Must Stay Local-First

The first packaging layer should be file-based, inspectable, and shareable
inside repos. We do not need a remote marketplace. We do need a durable manifest
format and operator commands for listing, enabling, disabling, and inspecting
extensions.

### 4. Release Readiness Must Reflect Real Runtime Health

Recent experience showed that full tests can pass while real provider routes are
degraded. P3 therefore needs a release artifact that combines:

- full repo test pass state,
- runtime profile benchmarks,
- provider fallback diagnostics,
- checkpoint/rewind smoke checks,
- session inspect/replay smoke checks,
- delegated runtime smoke checks.

## Sequencing

1. Land instruction-policy layers first so later surfaces share a stable
   governance model.
2. Productize hooks next because they already sit inside the runtime lifecycle.
3. Build delegated runtime and extension packaging on top of the same summary
   and session surfaces.
4. Finish with release-readiness automation once the new structured outputs
   exist.

## Risks

- Scope sprawl across P1-P3.
  Mitigation: keep one shared data model and reuse current session/runtime
  surfaces.
- New async features become opaque.
  Mitigation: require replayable summaries before declaring features complete.
- Packaging grows into a platform project.
  Mitigation: keep manifests local-first and defer remote registry work.
- Product health reporting drifts away from real usage.
  Mitigation: make real provider fallback and product workflow smoke checks part
  of the release artifact.

## Evidence Anchor

Current repo baseline before this change planning:

- `pytest -q` -> `1005 passed, 2 skipped, 3 warnings`
- The remaining warnings are existing `pytest.mark.benchmark` registration
  warnings, not functional failures.
