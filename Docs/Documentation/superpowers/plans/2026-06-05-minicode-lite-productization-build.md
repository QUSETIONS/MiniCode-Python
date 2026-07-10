---
archived-with: 2026-06-05-minicode-lite-productization
status: final
---
## Goal

Turn `minicode` into a lightweight Claude Code-style product surface by
completing the planned P1-P3 capability layers on top of the existing runtime
kernel.

## Build Mode

- Recommended isolation: `branch`
- Recommended build mode: `subagent-driven-development`

## Workstreams

### 1. Instruction And Policy Layers

- Define canonical precedence across global, user, project, and managed policy
  sources.
- Add structured instruction layer metadata to prompt/runtime/session outputs.
- Expose inspection commands and live TUI/session visibility.

### 2. Hook Workflow Productization

- Add hook registry inspection and recent execution health.
- Persist async hook completion/failure summaries into transcript/session state.
- Productize at least one validation workflow and one delegated completion
  workflow.

### 3. Delegated Background Runtime

- Introduce a typed delegated runtime record for background/subagent-style work.
- Surface live status and replayable summaries.
- Add bounded retry, recovery, and failure reporting.

### 4. Extension Packaging

- Add a local manifest format for extension bundles.
- Implement list, enable, disable, and inspect flows.
- Document repo-local sharing and install workflow.

### 5. Product Readiness Evaluation

- Expand runtime evaluation outputs with provider fallback and outage truth.
- Generate a release-readiness artifact that summarizes product health.
- Automate a minimal release gate around live product workflows.

## Verification

Required verification before closing the change:

- targeted tests for each new capability layer,
- full repo `pytest -q`,
- product-style smoke checks for:
  - `/session`, `/sessions`, `/session-replay`,
  - checkpoint/rewind preview and replay,
  - hook workflow visibility,
  - delegated runtime visibility,
  - provider fallback/outage diagnostics,
- saved artifact-backed release-readiness report.

## Exit Criteria

The change is done when:

- instruction sources are inspectable,
- hooks feel like first-class product workflows,
- delegated background work is bounded and replayable,
- extension packaging is usable locally,
- release readiness reflects real runtime truth rather than tests alone.
