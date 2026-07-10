# MiniCode vs Claude Code Gap Checklist

Date: 2026-06-03

## Status update (2026-06-05)

The `minicode-lite-productization` change has now shipped the planned P1-P3
lightweight product layers:

- instruction and policy-layer inspection
- hook and delegated-runtime product surfaces
- local extension packaging and control flows
- release-readiness and provider-diagnostic artifacts

Verification and rollout evidence for this update lives in:

- `D:/Desktop/minicode/Docs/Documentation/superpowers/reports/2026-06-05-minicode-lite-productization-verify.md`
- `D:/Desktop/minicode/benchmarks/release_readiness_results.md`

## Goal

Turn the current "how far are we from Claude Code?" discussion into an
execution-grade product checklist for `minicode`.

This document is intentionally practical:

- it uses verified `minicode` repo state as of 2026-06-03
- it uses current Claude Code official docs as the external product baseline
- it separates "runtime-kernel strength" from "full product-system parity"
- it names the next gaps in `P0 / P1 / P2` order

## Baseline

### External comparison baseline

Claude Code capabilities referenced here were checked against official pages on
2026-06-03:

- Memory and managed `CLAUDE.md`
  - <https://code.claude.com/docs/en/memory>
- Sessions and resume
  - <https://code.claude.com/docs/en/sessions>
  - <https://code.claude.com/docs/en/cli-usage>
- Checkpointing and rewind
  - <https://code.claude.com/docs/en/checkpointing>
- Hooks
  - <https://code.claude.com/docs/en/hooks>
- Subagents and background execution
  - <https://code.claude.com/docs/en/sub-agents>
- Plugins
  - <https://code.claude.com/docs/en/plugins>

### Verified `minicode` anchors

The current repo already has meaningful product/runtime structure:

- runtime profiles
  - `D:/Desktop/minicode/minicode/runtime_profiles.py`
- recurrent turn kernel and typed stop reasons
  - `D:/Desktop/minicode/minicode/turn_kernel.py`
- runtime events and widening transition
  - `D:/Desktop/minicode/minicode/agent_loop.py`
  - `D:/Desktop/minicode/minicode/types.py`
- live/runtime transcript visibility
  - `D:/Desktop/minicode/minicode/tui/transcript.py`
  - `D:/Desktop/minicode/minicode/tui/renderer.py`
  - `D:/Desktop/minicode/minicode/tui/input_handler.py`
- session persistence, resume, and session-level runtime summaries
  - `D:/Desktop/minicode/minicode/session.py`
- benchmarkable runtime-profile comparison
  - `D:/Desktop/minicode/minicode/runtime_profile_eval.py`
  - `D:/Desktop/minicode/benchmarks/runtime_profile_eval_results.md`
- partial hooks and background task plumbing
  - `D:/Desktop/minicode/minicode/hooks.py`
  - `D:/Desktop/minicode/minicode/background_tasks.py`
- CLAUDE.md loading and local/project instruction support
  - `D:/Desktop/minicode/minicode/prompt.py`

## Current position

### Where `minicode` is already strong

`minicode` is no longer a thin prompt shell. It already has:

- a real turn loop
- explicit runtime profiles, including `single-deep`
- typed stop reasons such as `verification_failed` and `widen_needed`
- widening as a deliberate runtime transition
- evidence-aware verification gating
- session persistence and resume
- runtime observability across live TUI, saved transcript, session metadata,
  and benchmark outputs

This means `minicode` is already competitive on the "single-agent terminal
runtime kernel" axis.

### Where `minicode` is still clearly behind Claude Code

The largest remaining product gaps are not basic looping anymore. They are:

- automatic checkpointing and rewind for code edits
- product-grade subagent/background orchestration
- layered memory and managed policy surfaces
- plugin and extensibility packaging
- session replay and artifact inspection product surfaces
- organization-grade governance and safety UX

## Gap matrix

| Surface | Claude Code baseline | Current `minicode` status | Gap judgement |
| --- | --- | --- | --- |
| Core runtime loop | Deep single-agent runtime, session resume, explicit workflows | Strong and improving; `single-deep`, widening, verification, runtime traces all exist | `minicode` is in the game |
| Checkpoint / rewind | Automatic checkpoints before edits, cross-session rewind | No first-class file-edit checkpoint ledger or rewind command | Major gap |
| Subagents | Named subagents, forked subagents, background execution, panel UX | Partial ingredients exist: hooks, context isolation, background tasks, prompt hints | Major gap |
| Memory / policy | Project/user/org `CLAUDE.md`, auto memory, managed settings | `CLAUDE.md` loading exists; broader layered memory/policy product is partial | Medium gap |
| Sessions | Resume, naming, session management, persistent checkpoints | Resume/session metadata are good; replay/inspect is still thin | Medium gap |
| Hooks / automation | Rich hook lifecycle, async/background hook patterns | Hook types exist, but productized workflows are still narrow | Medium gap |
| Plugins / packaging | Plugin directories, reusable commands, team sharing | No comparable end-user plugin product surface yet | Major gap |
| Product observability | Legible session status and operational views | Runtime trace is now strong; artifact-side replay still limited | Small to medium gap |
| Enterprise / governance | Managed organization settings and policy delivery | Only partial building blocks | Major gap |

## Priority rule

If a candidate feature does not improve one of these three outcomes, it should
not outrank the current backlog:

1. safer autonomous execution
2. easier recovery and replay
3. more scalable delegation without losing context hygiene

## P0: Product gaps to close next

These are the closest things to "Claude Code parity blockers."

### 1. Automatic checkpointing and rewind

Why this matters:

- Claude Code's checkpointing changes the user's risk tolerance
- it is the most obvious missing safety net in `minicode`
- it turns ambitious edits from "trust me" into "recoverable"

Checklist:

- [ ] Capture a file-change checkpoint before every write/edit tool mutation
- [ ] Persist checkpoint metadata into the session record, not only RAM
- [ ] Add a first-class rewind surface:
  - CLI: `--rewind` or equivalent
  - TUI: session-local restore action
  - transcript/session metadata: show checkpoint count and latest restore point
- [ ] Support "rewind files only" without forcing full conversation rollback
- [ ] Make checkpointing boundaries explicit for shell edits versus structured
      tool edits

Acceptance:

- a user can restore the workspace to a prior agent edit point within the same
  session
- checkpoints survive resume
- logs/transcript can explain what was restored

Likely implementation homes:

- `D:/Desktop/minicode/minicode/session.py`
- `D:/Desktop/minicode/minicode/agent_loop.py`
- `D:/Desktop/minicode/minicode/tooling.py`
- `D:/Desktop/minicode/minicode/tools/`
- `D:/Desktop/minicode/minicode/tui/`

### 2. Product-grade subagent runtime

Why this matters:

- Claude Code now treats subagents as a normal working mode, not an exotic path
- `minicode` already has some primitives, but not a coherent user-facing
  delegation system

Checklist:

- [ ] Define one typed subagent launch API for the runtime
- [ ] Support at least two modes:
  - fresh-context subagent
  - inherited-context fork
- [ ] Persist subagent summaries/results separately from the main transcript
- [ ] Show active subagents in TUI and session metadata
- [ ] Keep tool chatter isolated; only final result flows back by default
- [ ] Make subagent failure/retry reasons visible

Acceptance:

- a main run can delegate a side task without polluting its primary context
- subagent status is inspectable while running
- subagent output can be replayed after the session

Likely implementation homes:

- `D:/Desktop/minicode/minicode/context_isolation.py`
- `D:/Desktop/minicode/minicode/background_tasks.py`
- `D:/Desktop/minicode/minicode/agent_loop.py`
- `D:/Desktop/minicode/minicode/hooks.py`
- `D:/Desktop/minicode/minicode/tui/`

### 3. Session replay / inspect view

Why this matters:

- `minicode` already has runtime summaries and trace tokens
- the next step is to make historical sessions truly inspectable, not just
  resumable

Checklist:

- [ ] Add a replay/inspect mode for saved sessions
- [ ] Show:
  - runtime timeline
  - key checkpoints
  - major tool results
  - stop reason
  - any widening/subagent transitions
- [ ] Keep transcript, runtime-summary, and session metadata in one view
- [ ] Let users inspect without resuming execution

Acceptance:

- saved sessions are useful forensic artifacts, not just restart blobs
- postmortems and debugging become much easier

Likely implementation homes:

- `D:/Desktop/minicode/minicode/session.py`
- `D:/Desktop/minicode/minicode/tui/session_flow.py`
- `D:/Desktop/minicode/minicode/tui/transcript.py`
- `D:/Desktop/minicode/minicode/tui/renderer.py`

## P1: High-value productization after P0

### 4. Managed memory and policy layers

Why this matters:

- Claude Code has clearer separation between project, user, and org guidance
- `minicode` already reads `CLAUDE.md`, so the next move is product discipline,
  not invention from scratch

Checklist:

- [ ] Make instruction sources explicit in product UX:
  - global
  - user
  - project
  - machine-managed
- [ ] Add a readable inspect surface for what policy was loaded this turn
- [ ] Add a managed policy file path and precedence rule
- [ ] Separate durable auto-learned memory from hand-authored policy

Acceptance:

- users and admins can tell which instructions were active
- policy precedence is stable and explainable

Likely implementation homes:

- `D:/Desktop/minicode/minicode/prompt.py`
- `D:/Desktop/minicode/minicode/prompt_pipeline.py`
- `D:/Desktop/minicode/minicode/config.py`
- `D:/Desktop/minicode/minicode/tui/`

### 5. Hook workflows that feel first-class

Checklist:

- [ ] Turn hook events into user-facing workflows, not only internal types
- [ ] Support common async patterns:
  - run tests after edit
  - aggregate background task completion
  - inject verification context on next turn
- [ ] Add structured hook result visibility in transcript/session replay

Acceptance:

- hooks become a real extension and automation surface
- users can understand what hooks ran and what they changed

Likely implementation homes:

- `D:/Desktop/minicode/minicode/hooks.py`
- `D:/Desktop/minicode/minicode/agent_loop.py`
- `D:/Desktop/minicode/minicode/tui/`

### 6. Better runtime governance UX

Checklist:

- [ ] Make permission/risk mode explicit in the terminal
- [ ] Distinguish:
  - autonomous run
  - ask-before-edit
  - verification-held finalization
  - widened search
- [ ] Add clearer operator controls for pause, inspect, and recover

Acceptance:

- long autonomous runs feel governed, not mysterious

## P2: Worth doing after the main product gaps close

### 7. Plugin packaging and sharing model

Checklist:

- [ ] Define a stable plugin manifest for reusable skills/tool bundles
- [ ] Add install/list/disable surfaces
- [ ] Make project-scoped and user-scoped plugins explicit

Acceptance:

- a team can share reusable `minicode` capabilities without hand-copying repo
  internals

### 8. Enterprise policy and fleet management

Checklist:

- [ ] Add managed machine/org settings
- [ ] Support org-delivered instruction files and policy bundles
- [ ] Provide audit-friendly runtime/session metadata

Acceptance:

- `minicode` can be administered beyond a single power user machine

### 9. Broader apples-to-apples evaluation harness

Checklist:

- [ ] Extend runtime profile eval beyond `single` vs `single-deep`
- [ ] Add scenarios for:
  - checkpoint restore effectiveness
  - subagent delegation quality
  - replay/debuggability
- [ ] Keep budgets comparable across modes

Acceptance:

- product tradeoffs become measurable, not only intuitive

## Do not over-rotate on the wrong gaps

These should stay lower priority than the product blockers above:

- cosmetic CLI command proliferation
- speculative multi-agent complexity before replay/checkpointing exists
- exotic runtime strategies that weaken the current recurrent-core clarity
- copying Claude Code nouns without equivalent user value

## Recommended build order

If we only take one sane path from here:

1. ship automatic checkpointing and rewind
2. ship session replay / inspect
3. ship typed subagent runtime with background visibility
4. harden managed memory/policy layers
5. turn hooks into first-class workflows
6. add plugin packaging and organization-grade governance

## One-sentence verdict

`minicode` is already credible on runtime-kernel quality, but it will not feel
close to Claude Code as a product until it becomes dramatically better at
recovery, delegation, and inspectability.
