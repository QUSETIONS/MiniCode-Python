---
status: draft
---
## Overview

The current paper direction should stop trying to prove a broad architecture
winner. The stronger and more defensible paper is a task-typed systems study:
which coding-agent runtime capabilities matter on which task families.

The mainline should be intentionally asymmetric:

1. `memory-heavy` tasks are the primary result line,
2. `search-heavy` tasks are the secondary bounded comparison line,
3. `reasoning-heavy` tasks are exploratory unless we can benchmark them cleanly.

This is not a retreat. It is a claim-quality upgrade. The old
`study-code-mas-architecture` work already established the boundary that broad
positive architecture-selection claims are weak under current evidence. The new
paper converts that boundary into a stronger thesis centered on task family and
runtime mechanism.

## Positioning

The paper should be positioned as a systems/runtime study, not a generic agent
leaderboard paper.

The central move is:

- from: "Which architecture wins?"
- to: "Which runtime capability helps which task family?"

This framing matches MiniCode's strongest real advantages:

- memory-backed continuity,
- session replay and inspectability,
- rewind/recovery,
- verifier-backed execution,
- bounded diagnostic/readiness surfaces.

## Main Thesis

Recommended paper thesis:

> Memory-backed runtime continuity materially improves long-horizon,
> history-sensitive coding-agent tasks, while broader search assistance helps a
> narrower class of high-branching repository tasks. Task family, not generic
> agent count, is the right axis for evaluating coding-agent system design.

## Research Questions

### RQ1

Does memory-backed runtime continuity improve `memory-heavy` coding-agent tasks
in correctness, consistency, and recovery?

### RQ2

Do bounded search aids improve `search-heavy` tasks without the coherence costs
of unconstrained multi-writer delegation?

### RQ3

Which task families are dominated by runtime/system capability, and which are
still mostly dominated by underlying model reasoning quality?

## Task Families

### 1. Memory-Heavy

Definition:

- the task depends on preserving user constraints, prior attempts, session
  state, or cross-turn evidence over time,
- interruption or context loss causes failure,
- success depends on remembering what has already been established.

Representative task shapes:

- long-horizon preference or continuity tasks,
- resume-after-interruption coding tasks,
- history-sensitive user requirement tracking,
- multi-turn stateful repair flows.

Why this is the mainline:

- strongest existing repo evidence,
- strongest MiniCode product differentiation,
- clearest systems contribution.

### 2. Search-Heavy

Definition:

- the task depends on exploring many candidate files, interfaces, hypotheses, or
  evidence sources,
- the search space branches more than the implementation state evolves,
- bounded scout-style help may improve evidence acquisition.

Representative task shapes:

- repo localization,
- interface discovery,
- evidence-gathering diagnosis,
- repository construction and codebase exploration tasks.

Why this is secondary:

- promising, but not as clearly aligned with current strongest proof surface as
  memory-heavy tasks.

### 3. Reasoning-Heavy

Definition:

- the task depends mainly on multi-step inference, deep synthesis, or complex
  decision chains that are not primarily about state continuity or repo search.

Representative task shapes:

- experimental design,
- algorithmic derivation,
- research-style synthesis tasks.

Why this is exploratory:

- hardest to benchmark cleanly,
- easiest to confound with pure model quality,
- most likely to dilute the paper if forced too early.

## Experimental Direction

### Memory Mainline

Compare:

- memory-off or weak-session baseline,
- memory-backed continuity runtime,
- optionally a resume/recovery ablation.

Primary metrics:

- correctness,
- consistency across turns,
- recovery success after interruption,
- context-loss rate.

Expected contribution:

- a clean systems claim that memory and continuity mechanisms improve long-
  horizon coding tasks.

### Search Secondary

Compare:

- plain single-loop search,
- bounded read-only scout/search assistance,
- optional over-delegated or noisy-search ablation.

Primary metrics:

- localization success,
- evidence quality,
- wasted edits,
- cost overhead.

Expected contribution:

- bounded evidence that search assistance helps some high-branching tasks but
  does not justify broad MAS claims.

### Reasoning Gate

Only proceed if the benchmark has:

- reliable scoring,
- bounded runtime,
- low contamination from vague subjective grading,
- enough instances for a real pilot.

Otherwise, report reasoning as future work.

## Claim Boundaries

This design should explicitly avoid:

- universal agent-architecture superiority claims,
- "MAS is better" headlines,
- claims that reasoning-heavy gains are established if they are not.

The abstract and conclusion should instead say:

- task family matters,
- memory is the strongest current positive line,
- search help is conditional,
- reasoning is unresolved or exploratory.

## Figure Plan

1. Task-family taxonomy figure:
   memory-heavy vs search-heavy vs reasoning-heavy.
2. Runtime-capability map:
   memory, replay, rewind, verifier, bounded search.
3. Main result figure:
   memory-heavy benchmark performance and recovery curves.
4. Secondary figure:
   search-heavy bounded-gain comparison.
5. Optional appendix figure:
   reasoning exploratory outcomes or rejection gate.

## Evidence Anchor

The old architecture study is not wasted work. It becomes the pivot evidence:

- it shows why broad architecture-selection claims are too weak right now,
- it motivates task family as the right abstraction level,
- it justifies a narrower but stronger paper.
