---
status: draft
---
## Goal

Turn the paper from a broad architecture-selection study into a task-typed
coding-agent paper with a memory-heavy mainline, a search-heavy secondary line,
and a reasoning-heavy exploratory gate.

## Build Mode

- Recommended isolation: `branch`
- Recommended build mode: `subagent-driven-development`

## Workstreams

### 1. Freeze The Old Broad Claim

- Extract the exact claim boundary from the closed architecture study.
- Reposition that work as precursor evidence and motivation, not the main paper
  contribution.
- Write one short transition note that explains the pivot cleanly.

### 2. Build The Task Taxonomy

- Define operational rules for memory-heavy, search-heavy, and reasoning-heavy
  tasks.
- Map current benchmark candidates into the taxonomy.
- Reject candidates that blur the family definition too much.

### 3. Land The Memory Mainline

- Choose the first benchmark or local task package.
- Define baseline and ablation settings.
- Finalize metrics for correctness, consistency, and interruption recovery.
- Draft the mechanism story and paper figures for this line first.

### 4. Build The Search Secondary Line

- Choose one bounded search-heavy package.
- Define the comparison between plain single-loop and bounded search assistance.
- Pilot the line only enough to decide whether it belongs in the main paper or
  appendix.

### 5. Gate Reasoning

- Survey candidate reasoning-heavy tasks.
- Admit only tasks with clean grading and bounded cost.
- Default outcome: exploratory/future-work status unless the pilot is unusually
  clean and strong.

### 6. Paper Packaging

- Write a task-typed title set, abstract seed, and contribution list.
- Produce the figure plan and section outline.
- Add explicit result-to-claim gates for abstract, intro, and conclusion.

## Verification

Required verification before closing this change:

- task taxonomy table exists and is internally consistent,
- memory-heavy mainline benchmark choice is concrete,
- search-heavy secondary line is concretely bounded,
- reasoning gate has a written admit/reject rule,
- paper title/abstract/contribution draft exists,
- the final framing does not make unsupported broad architecture claims.

## Exit Criteria

The change is done when:

- the paper's new thesis is written clearly,
- the main result line is memory-heavy and executable,
- the search line is bounded and secondary,
- the reasoning line is explicitly gated,
- the repo contains the artifact set needed to start experiments and writing
  without revisiting the old broad framing.
