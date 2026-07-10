# MiniCode Paper Portfolio

Date: 2026-06-19
Status: active
Decision: keep one canonical AAAI paper line, and split the old cybernetic
memory story into a second-paper reserve.

## Executive Decision

- Paper A is the current AAAI-track manuscript:
  `task-typed coding-agent evaluation` with `memory-heavy` as the headline
  result.
- Paper B is a reserve line:
  `closed-loop cybernetic memory` / `control-theoretic retrieval`.
- Do not merge Paper A and Paper B into one abstract, introduction, or
  conclusion.
- If Paper A needs to narrow further, narrow inside the task-typed line first;
  do not reopen the PID/control story inside the same submission draft.

## Why This Split Is Necessary

The repo currently contains two different paper stories:

1. a task-typed coding-agent paper whose strongest signal is durable-state
   preservation on memory-heavy tasks; and
2. an older cybernetic-memory paper centered on PID, Kalman, and Lyapunov
   framing.

These two stories ask different research questions, use different evidence
surfaces, and imply different contribution lists. Keeping both inside one paper
weakens novelty, blurs the thesis, and invites reviewer confusion about what is
actually being claimed.

The correct move is therefore:

- keep the current submission line mechanism-grounded and family-specific; and
- preserve the cybernetic material as a second-paper asset package instead of
  letting it distort the current draft.

## Paper A: Current AAAI Mainline

### Working Title Direction

Preferred title family:

- `When Memory Matters: Task-Typed Evaluation of Long-Horizon Coding Agents`
- `Memory-Backed Runtime Continuity for Long-Horizon Coding-Agent Tasks`
- `Task Families, Not One Winner: A Memory-First Study of Coding-Agent Runtime Capabilities`

### One-Sentence Thesis

Different coding-agent task families stress different runtime capabilities, and
the clearest current positive signal in our setting comes from memory-heavy
tasks where success depends on preserving durable prior state across long
horizons, interruptions, and partial context loss.

### Core Claim Budget

Allowed:

- family-specific capability claims,
- `memory-heavy` as the strongest current result line,
- memory-backed runtime continuity as the mechanism story,
- bounded secondary evidence on `search-heavy` tasks,
- bounded negative motivation from the old broad architecture study.

Not allowed:

- broad winner claims across all coding-agent tasks,
- claims that a single architecture is universally superior,
- reasoning-heavy positive claims without clean grading,
- PID, Kalman, or Lyapunov as the central novelty of the current AAAI draft.

### Section Spine

1. Introduction:
   broad winner claims are weak; task families are the right abstraction.
2. Motivation from bounded negative evidence:
   the old broad architecture line motivates the pivot, but is not the result.
3. Task taxonomy:
   `memory-heavy`, `search-heavy`, `reasoning-heavy`.
4. Runtime capability view:
   continuity, durable state, replay, rewind, verification, bounded search.
5. Memory-heavy mainline:
   benchmark package, conditions, metrics, mechanism, main results.
6. Search-heavy secondary line:
   keep only if the pilot remains clean and bounded.
7. Reasoning gate:
   explain why this family stays exploratory for now.
8. Discussion and limits:
   what the paper does and does not establish.

### Required Experiment Pack Before Draft Lock

- matched `Memory-Off`, `Weak-Session`, and `Memory-Backed Continuity`
  conditions on the same slice,
- task correctness and anchor-retention analysis,
- interruption or restart recovery evidence,
- context-loss or durable-state-drop analysis,
- search-heavy secondary evidence only if it survives bounded evaluation
  without becoming noisier than the appendix is worth.

### What Moves Out Of The Main Paper

- the old broad architecture story as a positive-result line,
- reasoning-heavy tasks without clean scoring,
- control-theoretic formalism as the paper's central novelty,
- long theoretical digressions that do not directly support the memory-heavy
  mechanism claim.

### Success Condition

Paper A is ready to write as a full AAAI manuscript when:

- the task-typed thesis fits in one paragraph,
- the memory-heavy claim can be stated in one sentence,
- every main figure supports the same mechanism story,
- the search-heavy line is either cleanly bounded or removed from the main
  narrative,
- no paragraph depends on the cybernetic-control story to justify the paper's
  existence.

## Paper B: Cybernetic Memory Reserve

### Working Question

Can agent-memory retrieval be framed and improved as a closed-loop control
problem with explicit feedback, adaptive retrieval pressure, and stability
analysis?

### Why It Is Not The Current AAAI Line

Paper B is not the current submission line because it requires a different
burden of proof:

- strong standalone retrieval or memory-system baselines,
- clean `PID on/off` or controller-component ablations,
- a theory-to-practice bridge that stands on its own,
- evidence that the control story explains gains better than a simpler
  engineering mechanism story.

Right now, the cleaner evidence surface in this repo is not "control theory
beats alternatives." It is "durable-state preservation matters for
memory-heavy coding-agent tasks."

### Assets To Preserve

- terminology around adaptive retrieval pressure and continuity control,
- possible controller ablations,
- theoretical notes on control framing,
- any standalone retrieval experiments that can later support a dedicated
  memory-system paper.

### Reactivation Gate

Reopen Paper B only when all of the following become true:

- a clean standalone benchmark exists for the control story,
- the controller ablation package is complete,
- there is a credible baseline set beyond the current task-typed paper,
- the contribution can stand even if the coding-agent taxonomy is removed.

Until then, Paper B stays a reserve line rather than a section inside Paper A.

## Material Routing

### Canonical Paper A Assets

- `.trae/documents/paper-a-canonical-draft.md`
- `.trae/documents/paper-a-claim-figure-package.md`
- `.trae/documents/paper-a-figure-drafts.md`
- `paper/aaai2027/minicode_paper_a_submission.tex`
- `openspec/changes/task-typed-coding-agent-paper/paper-seed.md`
- `openspec/changes/task-typed-coding-agent-paper/paper-decision-gate-after-memory-pilot-setup.md`
- `openspec/changes/task-typed-coding-agent-paper/task-taxonomy.md`
- `openspec/changes/task-typed-coding-agent-paper/tasks.md`
- `Docs/Documentation/superpowers/specs/2026-06-08-task-typed-coding-agent-paper-design.md`
- `Docs/Documentation/superpowers/plans/2026-06-08-task-typed-coding-agent-paper-build.md`
- `Docs/Documentation/superpowers/reports/2026-06-09-task-typed-coding-agent-paper-verify.md`

### Paper B Reserve Assets

- historical control-theoretic memory notes,
- any future `PID on/off` retrieval experiments,
- theory-heavy framing that is not needed to justify the current AAAI draft.

### Canonical Manuscript Package

The canonical Paper A package now lives at:

- `.trae/documents/paper-a-canonical-draft.md`
- `.trae/documents/paper-a-claim-figure-package.md`
- `.trae/documents/paper-a-figure-drafts.md`
- `paper/aaai2027/minicode_paper_a_submission.tex`

These assets now form the primary source of truth for manuscript wording, claim
control, figure planning, and anonymous AAAI-formatted paper assembly. The
figure-draft file locks the first paper-facing figure set even before the
matched suite is rerun. The planning assets listed above remain the upstream
design basis, not competing drafts.

## Immediate Next Actions

1. Freeze the abstract, introduction, and contribution list around the
   memory-heavy task-typed thesis.
2. Complete the matched same-model three-condition suite for the memory-heavy
   main result.
3. Fill the main result figure and metric table only from matched artifacts.
4. Keep search-heavy only if the bounded pilot remains worth the page budget.
5. Push all cybernetic/PID/control material into Paper B reserve notes unless a
   paragraph truly needs it as implementation background.
6. Start drafting figures and sections only after this split is respected.
