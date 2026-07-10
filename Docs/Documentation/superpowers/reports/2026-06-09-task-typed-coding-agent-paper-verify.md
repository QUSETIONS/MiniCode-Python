---
status: final
---
## Scope

Verify that `task-typed-coding-agent-paper` is now a valid, executable paper
change and that the repo contains enough artifact-backed material to begin
writing and first-round memory-heavy experimentation without returning to the
old broad architecture framing.

## Verification Checks

### 1. OpenSpec validity

- `openspec validate task-typed-coding-agent-paper --no-color`
- Result: `pass`

### 2. OpenSpec completeness

- `openspec status --change task-typed-coding-agent-paper --json`
- Result: `isComplete: true`

### 3. Required artifact set

Verified present:

- `proposal.md`
- `design.md`
- `tasks.md`
- `task-taxonomy.md`
- `memory-mainline-package.md`
- `memory-pilot-setup.md`
- `memory-condition-evidence-mapping.md`
- `paper-decision-gate-after-memory-pilot-setup.md`
- `paper-seed.md`
- `memory-results-ready-package.md`
- `specs/task-typed-coding-agent-study/spec.md`

### 4. Claim-boundary check

Pass.

The new change does not rely on a broad architecture-winner claim. The old
study is explicitly retained as precursor/bounded evidence only, while the new
paper line centers on task family and runtime capability.

### 5. Mainline executability check

Pass.

The `memory-heavy` mainline is now concrete enough to execute and write from:

- benchmark slice is frozen,
- runtime conditions are named,
- metrics are named,
- decision gate is written,
- a first results-ready package exists,
- a first condition-to-artifact evidence map exists.

### 6. Results-surface honesty check

Pass.

The change now explicitly distinguishes between:

- the **already evidenced** two-condition surface
  (`Weak-Session` vs `Memory-Backed Continuity`), and
- the **not yet cleanly reconstructed** `Memory-Off` condition.

This prevents the paper line from overstating the current artifact pool. The
repo now contains a written mapping from result files to paper conditions, plus
an explicit note that the full three-condition claim still requires a matched
`Memory-Off` rerun.

## Key Outcome

This change successfully pivots the paper from:

- "which agent architecture wins in general?"

to:

- "which runtime capability helps which task family, with memory-heavy tasks as
  the first mainline?"

This is the strongest current paper direction because it matches the most
localized evidence already present in the repo.

## Remaining Work

The remaining work is experimental and narrative, not framing repair:

1. run the explicit `memory-off / weak-session / memory-backed continuity`
   comparison,
2. add anchor-retention movement alongside answer quality,
3. expand the current two-condition comparison into the full three-condition
   main table once `Memory-Off` is matched,
4. turn the current results-ready package into the first actual Results
   subsection draft.

## Verdict

`pass`

The change is ready to leave design/build ambiguity behind. It now has:

- valid OpenSpec structure,
- bounded thesis,
- executable memory-heavy mainline,
- ready-to-write results seed,
- explicit condition-to-artifact evidence map,
- explicit limits on what may and may not be claimed.
