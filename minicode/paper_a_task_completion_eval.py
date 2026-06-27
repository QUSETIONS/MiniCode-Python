from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from minicode.session import create_file_checkpoint, create_new_session, save_session


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "paper_a_task_completion_eval"
ABLATION_OUTPUT_ROOT = REPO_ROOT / "outputs" / "paper_a_task_completion_ablation_eval"

DEFAULT_TASK_COMPLETION_TITLE = "Paper A Task Completion Eval"
ABLATION_TASK_COMPLETION_TITLE = "Paper A Task Completion Causal Ladder"
DEFAULT_TASK_COMPLETION_METRIC = (
    "exact task completion plus goal recall after black-box CLI continuity recovery"
)
DEFAULT_TASK_COMPLETION_INTERPRETATION: tuple[str, ...] = (
    "Weak session access completes transcript-only tasks, but it still fails when the resumed task depends on checkpoint restoration or readiness state.",
    "Memory-backed continuity is the only condition that completes every matched long-track task in the suite end to end.",
    "The completion gap appears after answer support, not before it: answer-facing summaries are not enough when the resumed task also depends on durable operational state.",
)
ABLATION_TASK_COMPLETION_INTERPRETATION: tuple[str, ...] = (
    "`Session+Checkpoint` selectively rescues checkpoint-dependent work, but it still fails on readiness-dependent recovery.",
    "`Session+Readiness` selectively rescues readiness-dependent work, but it still fails when the resumed task requires file restoration.",
    "`Stale-Continuity-Package` underperforms the fresh package, showing that packaging continuity state is not enough if the packaged state is outdated.",
    "`Memory-Backed Continuity` is the only condition that completes transcript, checkpoint, readiness, and cross-surface tasks together.",
)
STALE_READINESS_ISSUE = "ISSUE: archived readiness report is stale"
STALE_READINESS_GUIDANCE = "Archived guidance detected; refresh readiness before resuming."
STALE_CHECKPOINT_CONTENT = "state=stale\norigin=archived\n"


@dataclass(frozen=True, slots=True)
class TaskGoal:
    id: str
    label: str
    kind: str
    target_relative_path: str
    expected_content: str
    seed_content: str
    replay_phrases: tuple[str, ...] = ()
    inspect_phrases: tuple[str, ...] = ()
    preview_phrases: tuple[str, ...] = ()
    restored_relative_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskScenario:
    slug: str
    title: str
    family: str
    task_anchor: str
    durable_anchor: str
    transcript_anchor: str
    readiness_issue: str = ""
    readiness_guidance: str = ""
    goals: tuple[TaskGoal, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskCondition:
    key: str
    label: str
    include_history: bool
    include_transcript: bool
    include_checkpoint: bool
    include_readiness: bool
    stale_checkpoint: bool = False
    stale_readiness: bool = False


@dataclass(frozen=True, slots=True)
class TaskCompletionSummaryRow:
    condition: str
    condition_label: str
    family: str
    exact_completion_rate: float
    goal_recall: float
    scenario_count: int
    goal_hits: int
    goal_total: int


TASK_COMPLETION_SCENARIOS: tuple[TaskScenario, ...] = (
    TaskScenario(
        slug="readme-hero",
        title="README hero surface recovery",
        family="transcript",
        task_anchor="TASK: refresh the repository hero section for the real product surface",
        durable_anchor="STATE: first screen must foreground memory / session / rewind / readiness",
        transcript_anchor="TRACE: README hero now uses the real terminal surface instead of a placeholder",
        goals=(
            TaskGoal(
                id="hero-surface",
                label="Write the README hero surface note",
                kind="transcript_write",
                target_relative_path="docs/readme-hero.txt",
                expected_content=(
                    "hero=real-terminal\n"
                    "pillars=memory,session,rewind,readiness\n"
                ),
                seed_content="hero=placeholder\npillars=missing\n",
                replay_phrases=(
                    "TASK: refresh the repository hero section for the real product surface",
                    "STATE: first screen must foreground memory / session / rewind / readiness",
                    "TRACE: README hero now uses the real terminal surface instead of a placeholder",
                ),
            ),
            TaskGoal(
                id="product-positioning",
                label="Write the product positioning note",
                kind="transcript_write",
                target_relative_path="docs/product-positioning.txt",
                expected_content=(
                    "position=minicode-lite continuity-first coding agent\n"
                    "proof=real-terminal product surface\n"
                ),
                seed_content="position=undecided\nproof=missing\n",
                replay_phrases=(
                    "TASK: refresh the repository hero section for the real product surface",
                    "TRACE: README hero now uses the real terminal surface instead of a placeholder",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="frontend-demo",
        title="Frontend demo handoff recovery",
        family="transcript",
        task_anchor="TASK: recover the frontend demo handoff for the live MiniCode surface",
        durable_anchor="STATE: demo handoff must preserve terminal and app continuity anchors",
        transcript_anchor="TRACE: wired frontend demo copy to the real MiniCode runtime surfaces",
        goals=(
            TaskGoal(
                id="demo-surface",
                label="Write the demo surface handoff",
                kind="transcript_write",
                target_relative_path="demo/frontend-surface.txt",
                expected_content=(
                    "surface=live-minicode-frontline\n"
                    "anchors=terminal,app,continuity\n"
                ),
                seed_content="surface=unknown\nanchors=lost\n",
                replay_phrases=(
                    "TASK: recover the frontend demo handoff for the live MiniCode surface",
                    "STATE: demo handoff must preserve terminal and app continuity anchors",
                    "TRACE: wired frontend demo copy to the real MiniCode runtime surfaces",
                ),
            ),
            TaskGoal(
                id="demo-script",
                label="Write the demo script outline",
                kind="transcript_write",
                target_relative_path="demo/demo-script.txt",
                expected_content=(
                    "step1=open live MiniCode surface first\n"
                    "step2=walk the memory-session-rewind-readiness path\n"
                ),
                seed_content="step1=tbd\nstep2=tbd\n",
                replay_phrases=(
                    "TASK: recover the frontend demo handoff for the live MiniCode surface",
                    "TRACE: wired frontend demo copy to the real MiniCode runtime surfaces",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="paper-abstract",
        title="Paper abstract revision recovery",
        family="transcript",
        task_anchor="TASK: recover the abstract revision that reframes MiniCode around task completion",
        durable_anchor="STATE: abstract must foreground continuity-first task completion over answer-only support",
        transcript_anchor="TRACE: abstract revision now centers task completion and durable operational state",
        goals=(
            TaskGoal(
                id="abstract-angle",
                label="Write the abstract angle note",
                kind="transcript_write",
                target_relative_path="paper/abstract-angle.txt",
                expected_content=(
                    "angle=continuity-first task completion benchmark\n"
                    "contrast=answer support alone is insufficient\n"
                ),
                seed_content="angle=unclear\ncontrast=missing\n",
                replay_phrases=(
                    "TASK: recover the abstract revision that reframes MiniCode around task completion",
                    "STATE: abstract must foreground continuity-first task completion over answer-only support",
                    "TRACE: abstract revision now centers task completion and durable operational state",
                ),
            ),
            TaskGoal(
                id="abstract-claim",
                label="Write the abstract claim note",
                kind="transcript_write",
                target_relative_path="paper/abstract-claim.txt",
                expected_content=(
                    "claim=task completion requires transcript plus durable operational state\n"
                    "scope=matched interrupted coding tasks only\n"
                ),
                seed_content="claim=tbd\nscope=tbd\n",
                replay_phrases=(
                    "TASK: recover the abstract revision that reframes MiniCode around task completion",
                    "TRACE: abstract revision now centers task completion and durable operational state",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="conversion-repair",
        title="Conversion repair continuity recovery",
        family="checkpoint",
        task_anchor="TASK: finish the single-session-preference conversion repair without losing durable state",
        durable_anchor="STATE: durable state and rewind checkpoints must survive the conversion",
        transcript_anchor="TRACE: conversion patch kept the durable-state contract and follow-up audit",
        goals=(
            TaskGoal(
                id="restore-conversion-state",
                label="Restore the conversion continuity file",
                kind="checkpoint_restore",
                target_relative_path="state/conversion-continuity.txt",
                expected_content="mode=before\nanchor_policy=durable\n",
                seed_content="mode=after\nanchor_policy=regressed\n",
            ),
            TaskGoal(
                id="conversion-followup",
                label="Write the conversion follow-up note",
                kind="transcript_write",
                target_relative_path="state/conversion-followup.txt",
                expected_content=(
                    "follow_up=rerun continuity audit after conversion repair\n"
                    "constraint=do not drop durable state\n"
                ),
                seed_content="follow_up=pending\nconstraint=unknown\n",
                replay_phrases=(
                    "STATE: durable state and rewind checkpoints must survive the conversion",
                    "TRACE: conversion patch kept the durable-state contract and follow-up audit",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="benchmark-packaging",
        title="Benchmark packaging recovery",
        family="checkpoint",
        task_anchor="TASK: finish the benchmark packaging repair without losing the evidence manifest",
        durable_anchor="STATE: benchmark manifests and rerun instructions must survive the interruption",
        transcript_anchor="TRACE: repaired the benchmark package and queued the verification rerun",
        goals=(
            TaskGoal(
                id="restore-benchmark-manifest",
                label="Restore the benchmark evidence manifest",
                kind="checkpoint_restore",
                target_relative_path="benchmarks/evidence-manifest.txt",
                expected_content="manifest=matched-evidence\nstatus=checkpoint-restorable\n",
                seed_content="manifest=missing\nstatus=manual-rebuild\n",
            ),
            TaskGoal(
                id="benchmark-rerun-note",
                label="Write the benchmark rerun note",
                kind="transcript_write",
                target_relative_path="benchmarks/evidence-rerun-note.txt",
                expected_content=(
                    "rerun=verify benchmark package after manifest restore\n"
                    "constraint=do not rebuild evidence from memory only\n"
                ),
                seed_content="rerun=pending\nconstraint=unknown\n",
                replay_phrases=(
                    "STATE: benchmark manifests and rerun instructions must survive the interruption",
                    "TRACE: repaired the benchmark package and queued the verification rerun",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="provider-readiness",
        title="Provider readiness recovery",
        family="readiness",
        task_anchor="TASK: keep the provider switch reproducible after interruption",
        durable_anchor="STATE: provider fallback guidance must stay attached to the session",
        transcript_anchor="TRACE: validated provider channel and reproducible switch steps",
        readiness_issue="ISSUE: provider fallback path requires manual audit",
        readiness_guidance="Keep continuity surfaces visible after interruption.",
        goals=(
            TaskGoal(
                id="provider-switch-note",
                label="Write the provider switch note",
                kind="transcript_write",
                target_relative_path="runtime/provider-switch-note.txt",
                expected_content=(
                    "provider_switch=reproducible\n"
                    "constraint=fallback guidance stays with session\n"
                ),
                seed_content="provider_switch=unknown\nconstraint=missing\n",
                replay_phrases=(
                    "TASK: keep the provider switch reproducible after interruption",
                    "TRACE: validated provider channel and reproducible switch steps",
                ),
            ),
            TaskGoal(
                id="provider-readiness-audit",
                label="Write the provider readiness audit",
                kind="readiness_write",
                target_relative_path="runtime/provider-readiness-audit.txt",
                expected_content=(
                    "audit=provider fallback path requires manual audit\n"
                    "guidance=keep continuity surfaces visible after interruption\n"
                ),
                seed_content="audit=pending\nguidance=pending\n",
                inspect_phrases=(
                    "ISSUE: provider fallback path requires manual audit",
                    "Keep continuity surfaces visible after interruption.",
                    "fallback coverage",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="offline-fallback",
        title="Offline fallback readiness recovery",
        family="readiness",
        task_anchor="TASK: keep the offline evaluation fallback package reproducible after interruption",
        durable_anchor="STATE: fallback routing and manual validation guidance must stay attached to the run",
        transcript_anchor="TRACE: validated the offline fallback ladder and manual validation gate",
        readiness_issue="ISSUE: offline evaluation fallback matrix requires validation",
        readiness_guidance="Keep fallback routing visible before resuming the interrupted run.",
        goals=(
            TaskGoal(
                id="offline-fallback-note",
                label="Write the offline fallback note",
                kind="transcript_write",
                target_relative_path="runtime/offline-fallback-note.txt",
                expected_content=(
                    "fallback=offline-eval ladder preserved\n"
                    "constraint=validation guidance stays attached to run\n"
                ),
                seed_content="fallback=unknown\nconstraint=missing\n",
                replay_phrases=(
                    "TASK: keep the offline evaluation fallback package reproducible after interruption",
                    "TRACE: validated the offline fallback ladder and manual validation gate",
                ),
            ),
            TaskGoal(
                id="offline-fallback-audit",
                label="Write the offline fallback audit",
                kind="readiness_write",
                target_relative_path="runtime/offline-fallback-audit.txt",
                expected_content=(
                    "audit=offline evaluation fallback matrix requires validation\n"
                    "guidance=keep fallback routing visible before resuming the interrupted run\n"
                ),
                seed_content="audit=pending\nguidance=pending\n",
                inspect_phrases=(
                    "ISSUE: offline evaluation fallback matrix requires validation",
                    "Keep fallback routing visible before resuming the interrupted run.",
                    "fallback coverage",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="release-bundle",
        title="Release bundle completion recovery",
        family="cross_surface",
        task_anchor="TASK: finish the paper release bundle after the interruption",
        durable_anchor="STATE: matched controls and task-completion evidence must stay in the bundle",
        transcript_anchor="TRACE: prepared the release bundle around continuity, bridge, and task completion",
        readiness_issue="ISSUE: release artifact bundle needs final verification",
        readiness_guidance="Do not claim broader generality than the matched suite supports.",
        goals=(
            TaskGoal(
                id="restore-release-package",
                label="Restore the release package manifest",
                kind="checkpoint_restore",
                target_relative_path="release/release-package.txt",
                expected_content="package=matched\nstatus=ready-for-verification\n",
                seed_content="package=lost\nstatus=needs-rebuild\n",
            ),
            TaskGoal(
                id="release-handback",
                label="Write the release handback note",
                kind="cross_surface_write",
                target_relative_path="release/release-handback.txt",
                expected_content=(
                    "bundle=matched continuity package\n"
                    "next_step=final verification only after checkpoints and readiness are restored\n"
                ),
                seed_content="bundle=pending\nnext_step=pending\n",
                replay_phrases=(
                    "TASK: finish the paper release bundle after the interruption",
                    "TRACE: prepared the release bundle around continuity, bridge, and task completion",
                ),
                inspect_phrases=(
                    "ISSUE: release artifact bundle needs final verification",
                    "Do not claim broader generality than the matched suite supports.",
                ),
                preview_phrases=("release-package.txt",),
                restored_relative_paths=("release/release-package.txt",),
            ),
        ),
    ),
    TaskScenario(
        slug="figure-package",
        title="Figure package completion recovery",
        family="cross_surface",
        task_anchor="TASK: finish the figure package after the benchmark interruption",
        durable_anchor="STATE: figure manifest and verification handback must stay coupled",
        transcript_anchor="TRACE: rebuilt the figure package around matched traces and verification notes",
        readiness_issue="ISSUE: figure artifact package needs final evidence check",
        readiness_guidance="Verify matched trace support before exporting the figure package.",
        goals=(
            TaskGoal(
                id="restore-figure-manifest",
                label="Restore the figure package manifest",
                kind="checkpoint_restore",
                target_relative_path="paper/figure-package-manifest.txt",
                expected_content="figures=matched-traces\nstatus=ready-for-evidence-check\n",
                seed_content="figures=lost\nstatus=needs-regeneration\n",
            ),
            TaskGoal(
                id="figure-handback",
                label="Write the figure package handback",
                kind="cross_surface_write",
                target_relative_path="paper/figure-package-handback.txt",
                expected_content=(
                    "package=matched figure evidence bundle\n"
                    "next_step=final evidence check only after manifest restore and readiness review\n"
                ),
                seed_content="package=pending\nnext_step=pending\n",
                replay_phrases=(
                    "TASK: finish the figure package after the benchmark interruption",
                    "TRACE: rebuilt the figure package around matched traces and verification notes",
                ),
                inspect_phrases=(
                    "ISSUE: figure artifact package needs final evidence check",
                    "Verify matched trace support before exporting the figure package.",
                ),
                preview_phrases=("figure-package-manifest.txt",),
                restored_relative_paths=("paper/figure-package-manifest.txt",),
            ),
        ),
    ),
    TaskScenario(
        slug="failure-boundary",
        title="Failure boundary recovery",
        family="transcript",
        task_anchor="TASK: recover the paper failure boundary note without overstating the evidence",
        durable_anchor="STATE: claim boundaries must stay attached to the matched task-completion evidence",
        transcript_anchor="TRACE: rewrote the failure boundary note around matched evidence and explicit scope control",
        goals=(
            TaskGoal(
                id="failure-boundary-note",
                label="Write the failure boundary note",
                kind="transcript_write",
                target_relative_path="paper/failure-boundary.txt",
                expected_content=(
                    "boundary=matched interrupted coding tasks only\n"
                    "unsupported=broader autonomy claims remain future work\n"
                ),
                seed_content="boundary=unclear\nunsupported=missing\n",
                replay_phrases=(
                    "TASK: recover the paper failure boundary note without overstating the evidence",
                    "STATE: claim boundaries must stay attached to the matched task-completion evidence",
                    "TRACE: rewrote the failure boundary note around matched evidence and explicit scope control",
                ),
            ),
            TaskGoal(
                id="failure-boundary-followup",
                label="Write the failure boundary follow-up",
                kind="transcript_write",
                target_relative_path="paper/failure-boundary-followup.txt",
                expected_content=(
                    "next_step=separate supported claims from future-work conjectures\n"
                    "constraint=do not generalize beyond matched evidence\n"
                ),
                seed_content="next_step=tbd\nconstraint=tbd\n",
                replay_phrases=(
                    "TASK: recover the paper failure boundary note without overstating the evidence",
                    "TRACE: rewrote the failure boundary note around matched evidence and explicit scope control",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="task-completion-table",
        title="Task completion table recovery",
        family="checkpoint",
        task_anchor="TASK: restore the task-completion table package after the interruption",
        durable_anchor="STATE: the exact-completion table source must survive as a checkpoint-restorable artifact",
        transcript_anchor="TRACE: restored the table source and queued a clean recompute of the published summary",
        goals=(
            TaskGoal(
                id="restore-task-table",
                label="Restore the task completion table source",
                kind="checkpoint_restore",
                target_relative_path="paper/task-completion-table.txt",
                expected_content="table=task-completion-summary\nstatus=checkpoint-restorable\n",
                seed_content="table=lost\nstatus=hand-reconstruct\n",
            ),
            TaskGoal(
                id="task-table-followup",
                label="Write the task table follow-up",
                kind="transcript_write",
                target_relative_path="paper/task-completion-table-followup.txt",
                expected_content=(
                    "rerun=recompute task-completion summary after table restore\n"
                    "constraint=do not hand-reconstruct the published table from prose\n"
                ),
                seed_content="rerun=pending\nconstraint=unknown\n",
                replay_phrases=(
                    "STATE: the exact-completion table source must survive as a checkpoint-restorable artifact",
                    "TRACE: restored the table source and queued a clean recompute of the published summary",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="submission-compile",
        title="Submission compile recovery",
        family="checkpoint",
        task_anchor="TASK: finish the AAAI submission compile package without losing the restored source bundle",
        durable_anchor="STATE: compile inputs and rerun instructions must survive the interruption together",
        transcript_anchor="TRACE: restored the compile bundle and queued a deterministic resubmission build",
        goals=(
            TaskGoal(
                id="restore-submission-compile",
                label="Restore the submission compile bundle",
                kind="checkpoint_restore",
                target_relative_path="paper/submission-compile-bundle.txt",
                expected_content="bundle=aaai-compile-inputs\nstatus=checkpoint-restorable\n",
                seed_content="bundle=missing\nstatus=manual-assembly\n",
            ),
            TaskGoal(
                id="submission-compile-followup",
                label="Write the submission compile follow-up",
                kind="transcript_write",
                target_relative_path="paper/submission-compile-followup.txt",
                expected_content=(
                    "rerun=execute deterministic submission compile after bundle restore\n"
                    "constraint=keep restored sources and compile instructions coupled\n"
                ),
                seed_content="rerun=pending\nconstraint=unknown\n",
                replay_phrases=(
                    "STATE: compile inputs and rerun instructions must survive the interruption together",
                    "TRACE: restored the compile bundle and queued a deterministic resubmission build",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="repro-checklist",
        title="Repro checklist readiness recovery",
        family="readiness",
        task_anchor="TASK: keep the reproducibility checklist actionable after the interruption",
        durable_anchor="STATE: reproducibility guidance must stay attached to provider routing and output paths",
        transcript_anchor="TRACE: rebuilt the repro checklist around provider routing and artifact paths",
        readiness_issue="ISSUE: reproducibility checklist requires environment verification",
        readiness_guidance="Verify provider routing and artifact output paths before marking the run reproducible.",
        goals=(
            TaskGoal(
                id="repro-checklist-note",
                label="Write the repro checklist note",
                kind="transcript_write",
                target_relative_path="runtime/repro-checklist-note.txt",
                expected_content=(
                    "repro=checklist preserved across interruption\n"
                    "constraint=provider routing stays visible with artifact paths\n"
                ),
                seed_content="repro=unknown\nconstraint=missing\n",
                replay_phrases=(
                    "TASK: keep the reproducibility checklist actionable after the interruption",
                    "TRACE: rebuilt the repro checklist around provider routing and artifact paths",
                ),
            ),
            TaskGoal(
                id="repro-checklist-audit",
                label="Write the repro checklist audit",
                kind="readiness_write",
                target_relative_path="runtime/repro-checklist-audit.txt",
                expected_content=(
                    "audit=reproducibility checklist requires environment verification\n"
                    "guidance=verify provider routing and artifact output paths before marking the run reproducible\n"
                ),
                seed_content="audit=pending\nguidance=pending\n",
                inspect_phrases=(
                    "ISSUE: reproducibility checklist requires environment verification",
                    "Verify provider routing and artifact output paths before marking the run reproducible.",
                    "fallback coverage",
                ),
            ),
        ),
    ),
    TaskScenario(
        slug="reviewer-response-bundle",
        title="Reviewer response bundle recovery",
        family="cross_surface",
        task_anchor="TASK: finish the reviewer response bundle after the interruption",
        durable_anchor="STATE: reviewer-facing claims and restored evidence manifests must stay coupled",
        transcript_anchor="TRACE: rebuilt the reviewer response bundle around matched claims and restored evidence",
        readiness_issue="ISSUE: reviewer response bundle needs evidence reconciliation",
        readiness_guidance="Keep reviewer-facing claim wording aligned with the matched benchmark scope.",
        goals=(
            TaskGoal(
                id="restore-reviewer-bundle",
                label="Restore the reviewer response manifest",
                kind="checkpoint_restore",
                target_relative_path="paper/reviewer-response-manifest.txt",
                expected_content="bundle=reviewer-response-evidence\nstatus=ready-for-reconciliation\n",
                seed_content="bundle=lost\nstatus=needs-rebuild\n",
            ),
            TaskGoal(
                id="reviewer-response-handback",
                label="Write the reviewer response handback",
                kind="cross_surface_write",
                target_relative_path="paper/reviewer-response-handback.txt",
                expected_content=(
                    "bundle=matched reviewer response package\n"
                    "next_step=reconcile claims only after manifest restore and readiness review\n"
                ),
                seed_content="bundle=pending\nnext_step=pending\n",
                replay_phrases=(
                    "TASK: finish the reviewer response bundle after the interruption",
                    "TRACE: rebuilt the reviewer response bundle around matched claims and restored evidence",
                ),
                inspect_phrases=(
                    "ISSUE: reviewer response bundle needs evidence reconciliation",
                    "Keep reviewer-facing claim wording aligned with the matched benchmark scope.",
                ),
                preview_phrases=("reviewer-response-manifest.txt",),
                restored_relative_paths=("paper/reviewer-response-manifest.txt",),
            ),
        ),
    ),
)


TASK_COMPLETION_CONDITIONS: tuple[TaskCondition, ...] = (
    TaskCondition(
        key="memory_off",
        label="Memory-Off",
        include_history=False,
        include_transcript=False,
        include_checkpoint=False,
        include_readiness=False,
    ),
    TaskCondition(
        key="weak_session",
        label="Weak-Session",
        include_history=True,
        include_transcript=True,
        include_checkpoint=False,
        include_readiness=False,
    ),
    TaskCondition(
        key="memory_backed_continuity",
        label="Memory-Backed Continuity",
        include_history=True,
        include_transcript=True,
        include_checkpoint=True,
        include_readiness=True,
    ),
)

TASK_COMPLETION_ABLATION_CONDITIONS: tuple[TaskCondition, ...] = (
    TaskCondition(
        key="memory_off",
        label="Memory-Off",
        include_history=False,
        include_transcript=False,
        include_checkpoint=False,
        include_readiness=False,
    ),
    TaskCondition(
        key="history_only",
        label="History-Only",
        include_history=True,
        include_transcript=False,
        include_checkpoint=False,
        include_readiness=False,
    ),
    TaskCondition(
        key="weak_session",
        label="Weak-Session",
        include_history=True,
        include_transcript=True,
        include_checkpoint=False,
        include_readiness=False,
    ),
    TaskCondition(
        key="session_plus_checkpoint",
        label="Session+Checkpoint",
        include_history=True,
        include_transcript=True,
        include_checkpoint=True,
        include_readiness=False,
    ),
    TaskCondition(
        key="session_plus_readiness",
        label="Session+Readiness",
        include_history=True,
        include_transcript=True,
        include_checkpoint=False,
        include_readiness=True,
    ),
    TaskCondition(
        key="stale_continuity_package",
        label="Stale-Continuity-Package",
        include_history=True,
        include_transcript=True,
        include_checkpoint=True,
        include_readiness=True,
        stale_checkpoint=True,
        stale_readiness=True,
    ),
    TaskCondition(
        key="memory_backed_continuity",
        label="Memory-Backed Continuity",
        include_history=True,
        include_transcript=True,
        include_checkpoint=True,
        include_readiness=True,
    ),
)


def _run_command(
    label: str,
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 180,
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return {
        "label": label,
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _prepare_workspace(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _checkpoint_seed_for_goal(goal: TaskGoal, condition: TaskCondition) -> str:
    if not condition.stale_checkpoint:
        return goal.expected_content
    if goal.kind == "checkpoint_restore":
        return STALE_CHECKPOINT_CONTENT
    return goal.seed_content


def _seed_session(
    scenario: TaskScenario,
    condition: TaskCondition,
    *,
    workspace: Path,
) -> str:
    _prepare_workspace(workspace)
    session = create_new_session(workspace=str(workspace))

    for goal in scenario.goals:
        target = workspace / goal.target_relative_path
        _write_text(target, goal.seed_content)
        if condition.include_checkpoint and goal.kind == "checkpoint_restore":
            create_file_checkpoint(
                session,
                file_path=str(target),
                existed=True,
                previous_content=_checkpoint_seed_for_goal(goal, condition),
            )

    session.messages = [{"role": "user", "content": scenario.task_anchor}]
    if condition.include_history:
        session.history = [scenario.task_anchor, scenario.durable_anchor]
    if condition.include_transcript:
        session.transcript_entries = [
            {
                "id": 1,
                "kind": "progress",
                "category": "runtime",
                "runtimeKind": "phase",
                "runtimeStep": 2,
                "runtimePhase": "verify",
                "body": "Runtime phase: verify.",
            },
            {
                "id": 2,
                "kind": "tool",
                "toolName": "edit_file",
                "status": "success",
                "body": scenario.transcript_anchor,
            },
        ]
    if condition.include_readiness:
        session.readiness_report = {
            "status": "ready" if not condition.stale_readiness else "stale",
            "provider": "task-completion-benchmark",
            "provider_channel": "deterministic-harness",
            "provider_ready": not condition.stale_readiness,
            "fallback_candidates": ["local-mock", "offline-review"],
            "viable_fallbacks": ["local-mock"] if not condition.stale_readiness else [],
            "fallback_guidance": [
                scenario.readiness_guidance
                if not condition.stale_readiness
                else STALE_READINESS_GUIDANCE
            ],
            "issues": [
                scenario.readiness_issue
                if not condition.stale_readiness
                else STALE_READINESS_ISSUE
            ],
        }
    save_session(session, force_full=True)
    return session.session_id


def _contains_phrases(text: str, phrases: tuple[str, ...]) -> bool:
    if not phrases:
        return True
    lowered = text.lower()
    return all(phrase.lower() in lowered for phrase in phrases)


def _checkpoint_expectations(
    scenario: TaskScenario,
) -> dict[str, str]:
    return {
        goal.target_relative_path: goal.expected_content
        for goal in scenario.goals
        if goal.kind == "checkpoint_restore"
    }


def _goal_target_state(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _evaluate_goal(
    goal: TaskGoal,
    *,
    workspace: Path,
    replay_output: str,
    inspect_output: str,
    preview_output: str,
    checkpoint_expectations: dict[str, str],
) -> dict[str, Any]:
    target = workspace / goal.target_relative_path
    evidence: dict[str, bool] = {}

    if goal.kind == "transcript_write":
        evidence["replay_surface"] = _contains_phrases(replay_output, goal.replay_phrases)
        if evidence["replay_surface"]:
            _write_text(target, goal.expected_content)
    elif goal.kind == "readiness_write":
        evidence["inspect_surface"] = _contains_phrases(inspect_output, goal.inspect_phrases)
        if evidence["inspect_surface"]:
            _write_text(target, goal.expected_content)
    elif goal.kind == "cross_surface_write":
        evidence["replay_surface"] = _contains_phrases(replay_output, goal.replay_phrases)
        evidence["inspect_surface"] = _contains_phrases(inspect_output, goal.inspect_phrases)
        evidence["preview_surface"] = _contains_phrases(preview_output, goal.preview_phrases)
        evidence["restored_state"] = all(
            _goal_target_state(workspace / relative_path) == checkpoint_expectations.get(relative_path, "")
            for relative_path in goal.restored_relative_paths
        )
        if all(evidence.values()):
            _write_text(target, goal.expected_content)
    elif goal.kind == "checkpoint_restore":
        evidence["rewind_surface"] = _goal_target_state(target) == goal.expected_content
    else:
        raise ValueError(f"Unsupported goal kind: {goal.kind}")

    final_content = _goal_target_state(target)
    completed = final_content == goal.expected_content
    return {
        "goal_id": goal.id,
        "label": goal.label,
        "kind": goal.kind,
        "target_relative_path": goal.target_relative_path,
        "completed": completed,
        "evidence": evidence,
        "final_content": final_content,
    }


def _evaluate_condition(
    scenario: TaskScenario,
    condition: TaskCondition,
    *,
    output_root: Path,
) -> dict[str, Any]:
    trace_dir = output_root / scenario.slug / condition.key
    workspace = trace_dir / "workspace"
    session_id = _seed_session(scenario, condition, workspace=workspace)

    inspect = _run_command(
        "inspect-session",
        [sys.executable, "-m", "minicode.main", "--inspect-session", session_id],
        cwd=REPO_ROOT,
    )
    replay = _run_command(
        "replay-session",
        [sys.executable, "-m", "minicode.main", "--replay-session", session_id],
        cwd=REPO_ROOT,
    )
    preview = _run_command(
        "preview-rewind",
        [sys.executable, "-m", "minicode.main", "--preview-rewind", session_id],
        cwd=REPO_ROOT,
    )
    rewind = _run_command(
        "rewind",
        [sys.executable, "-m", "minicode.main", "--rewind", session_id],
        cwd=REPO_ROOT,
    )

    trace_dir.mkdir(parents=True, exist_ok=True)
    _write_text(trace_dir / "inspect.txt", inspect["stdout"] + inspect["stderr"])
    _write_text(trace_dir / "replay.txt", replay["stdout"] + replay["stderr"])
    _write_text(trace_dir / "preview_rewind.txt", preview["stdout"] + preview["stderr"])
    _write_text(trace_dir / "rewind.txt", rewind["stdout"] + rewind["stderr"])

    checkpoint_expectations = _checkpoint_expectations(scenario)
    goal_results = [
        _evaluate_goal(
            goal,
            workspace=workspace,
            replay_output=replay["stdout"],
            inspect_output=inspect["stdout"],
            preview_output=preview["stdout"],
            checkpoint_expectations=checkpoint_expectations,
        )
        for goal in scenario.goals
    ]
    completed_goal_count = sum(1 for result in goal_results if result["completed"])
    total_goal_count = len(goal_results)
    exact_completion = completed_goal_count == total_goal_count
    goal_recall = completed_goal_count / total_goal_count if total_goal_count else 0.0

    manifest = {
        "scenario": scenario.slug,
        "condition": condition.key,
        "goal_results": goal_results,
    }
    _write_text(
        trace_dir / "completion_manifest.json",
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
    )

    return {
        "scenario": scenario.slug,
        "scenario_title": scenario.title,
        "family": scenario.family,
        "condition": condition.key,
        "condition_label": condition.label,
        "session_id": session_id,
        "workspace": str(workspace),
        "trace_dir": str(trace_dir),
        "seed_profile": {
            "include_history": condition.include_history,
            "include_transcript": condition.include_transcript,
            "include_checkpoint": condition.include_checkpoint,
            "include_readiness": condition.include_readiness,
            "stale_checkpoint": condition.stale_checkpoint,
            "stale_readiness": condition.stale_readiness,
        },
        "completed_goal_count": completed_goal_count,
        "total_goal_count": total_goal_count,
        "exact_completion": exact_completion,
        "goal_recall": goal_recall,
        "goal_results": goal_results,
        "commands": {
            "inspect": inspect,
            "replay": replay,
            "preview_rewind": preview,
            "rewind": rewind,
        },
    }


def evaluate_task_completion(
    *,
    output_root: Path | None = None,
    conditions: Sequence[TaskCondition] = TASK_COMPLETION_CONDITIONS,
    scenarios: Sequence[TaskScenario] = TASK_COMPLETION_SCENARIOS,
) -> list[dict[str, Any]]:
    active_output_root = Path(output_root) if output_root is not None else OUTPUT_ROOT
    active_output_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        for condition in conditions:
            results.append(
                _evaluate_condition(
                    scenario,
                    condition,
                    output_root=active_output_root,
                )
            )
    return results


def _family_order(scenarios: Sequence[TaskScenario]) -> tuple[str, ...]:
    families: list[str] = []
    for scenario in scenarios:
        if scenario.family not in families:
            families.append(scenario.family)
    families.append("overall")
    return tuple(families)


def summarize_task_completion(
    results: list[dict[str, Any]],
    *,
    conditions: Sequence[TaskCondition] = TASK_COMPLETION_CONDITIONS,
    scenarios: Sequence[TaskScenario] = TASK_COMPLETION_SCENARIOS,
) -> list[TaskCompletionSummaryRow]:
    summaries: list[TaskCompletionSummaryRow] = []
    families = _family_order(scenarios)
    for condition in conditions:
        condition_rows = [row for row in results if row["condition"] == condition.key]
        for family in families:
            subset = (
                condition_rows
                if family == "overall"
                else [row for row in condition_rows if row["family"] == family]
            )
            if not subset:
                summaries.append(
                    TaskCompletionSummaryRow(
                        condition=condition.key,
                        condition_label=condition.label,
                        family=family,
                        exact_completion_rate=0.0,
                        goal_recall=0.0,
                        scenario_count=0,
                        goal_hits=0,
                        goal_total=0,
                    )
                )
                continue
            exact_hits = sum(1 for row in subset if row["exact_completion"])
            scenario_count = len(subset)
            goal_hits = sum(int(row["completed_goal_count"]) for row in subset)
            goal_total = sum(int(row["total_goal_count"]) for row in subset)
            summaries.append(
                TaskCompletionSummaryRow(
                    condition=condition.key,
                    condition_label=condition.label,
                    family=family,
                    exact_completion_rate=exact_hits / scenario_count,
                    goal_recall=goal_hits / goal_total if goal_total else 0.0,
                    scenario_count=scenario_count,
                    goal_hits=goal_hits,
                    goal_total=goal_total,
                )
            )
    return summaries


def _condition_labels(conditions: Sequence[TaskCondition]) -> str:
    return ", ".join(condition.label for condition in conditions)


def task_completion_eval_as_dict(
    results: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
    output_root: Path | None = None,
    conditions: Sequence[TaskCondition] = TASK_COMPLETION_CONDITIONS,
    scenarios: Sequence[TaskScenario] = TASK_COMPLETION_SCENARIOS,
    title: str = DEFAULT_TASK_COMPLETION_TITLE,
) -> dict[str, Any]:
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    active_output_root = Path(output_root) if output_root is not None else OUTPUT_ROOT
    summaries = summarize_task_completion(results, conditions=conditions, scenarios=scenarios)
    condition_summary: dict[str, dict[str, dict[str, Any]]] = {}
    for summary in summaries:
        family_bucket = condition_summary.setdefault(summary.condition, {})
        family_bucket[summary.family] = {
            "label": summary.condition_label,
            "exact_completion_rate": summary.exact_completion_rate,
            "goal_recall": summary.goal_recall,
            "scenario_count": summary.scenario_count,
            "goal_hits": summary.goal_hits,
            "goal_total": summary.goal_total,
        }

    return {
        "generated_at": timestamp,
        "repo_root": str(REPO_ROOT),
        "output_root": str(active_output_root),
        "title": title,
        "results": results,
        "summary": [asdict(summary) for summary in summaries],
        "condition_summary": condition_summary,
        "scenario_count": len(scenarios),
        "goal_count": sum(len(scenario.goals) for scenario in scenarios),
        "scenarios": [asdict(scenario) for scenario in scenarios],
        "conditions": [asdict(condition) for condition in conditions],
    }


def task_completion_eval_as_markdown(
    results: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
    conditions: Sequence[TaskCondition] = TASK_COMPLETION_CONDITIONS,
    scenarios: Sequence[TaskScenario] = TASK_COMPLETION_SCENARIOS,
    title: str = DEFAULT_TASK_COMPLETION_TITLE,
    metric_line: str = DEFAULT_TASK_COMPLETION_METRIC,
    interpretation_lines: Sequence[str] | None = None,
) -> str:
    summary_index = {
        (summary.condition, summary.family): summary
        for summary in summarize_task_completion(results, conditions=conditions, scenarios=scenarios)
    }
    active_interpretation_lines = (
        tuple(interpretation_lines)
        if interpretation_lines is not None
        else DEFAULT_TASK_COMPLETION_INTERPRETATION
    )
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()

    lines = [
        f"# {title}",
        "",
        f"- Generated at: {timestamp}",
        f"- Scenarios: {len(scenarios)} interrupted long-track coding tasks",
        f"- Conditions: {_condition_labels(conditions)}",
        f"- Metric: {metric_line}",
        "",
        "## Condition Summary",
        "",
        "| condition | transcript_exact | checkpoint_exact | readiness_exact | cross_exact | overall_exact | overall_goal_recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition in conditions:
        transcript = summary_index[(condition.key, "transcript")]
        checkpoint = summary_index[(condition.key, "checkpoint")]
        readiness = summary_index[(condition.key, "readiness")]
        cross_surface = summary_index[(condition.key, "cross_surface")]
        overall = summary_index[(condition.key, "overall")]
        lines.append(
            "| "
            + condition.label
            + " | "
            + f"{transcript.exact_completion_rate:.2f}"
            + " | "
            + f"{checkpoint.exact_completion_rate:.2f}"
            + " | "
            + f"{readiness.exact_completion_rate:.2f}"
            + " | "
            + f"{cross_surface.exact_completion_rate:.2f}"
            + " | "
            + f"{overall.exact_completion_rate:.2f}"
            + " | "
            + f"{overall.goal_recall:.2f} ({overall.goal_hits}/{overall.goal_total})"
            + " |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
        ]
    )
    for line in active_interpretation_lines:
        lines.append(f"- {line}")

    lines.extend(
        [
            "",
            "## Scenario Breakdown",
            "",
            "| scenario | family | condition | completed_goals | exact | trace_dir |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for result in results:
        lines.append(
            "| "
            + result["scenario_title"]
            + " | "
            + result["family"]
            + " | "
            + result["condition_label"]
            + " | "
            + f"{result['completed_goal_count']}/{result['total_goal_count']}"
            + " | "
            + ("1.00" if result["exact_completion"] else "0.00")
            + " | "
            + f"`{result['trace_dir']}`"
            + " |"
        )

    return "\n".join(lines) + "\n"


def write_task_completion_eval_artifacts(
    results: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
    output_root: Path | None = None,
    output_json: Path | None = None,
    output_md: Path | None = None,
    conditions: Sequence[TaskCondition] = TASK_COMPLETION_CONDITIONS,
    scenarios: Sequence[TaskScenario] = TASK_COMPLETION_SCENARIOS,
    title: str = DEFAULT_TASK_COMPLETION_TITLE,
    metric_line: str = DEFAULT_TASK_COMPLETION_METRIC,
    interpretation_lines: Sequence[str] | None = None,
) -> dict[str, Any]:
    payload = task_completion_eval_as_dict(
        results,
        generated_at=generated_at,
        output_root=output_root,
        conditions=conditions,
        scenarios=scenarios,
        title=title,
    )
    markdown = task_completion_eval_as_markdown(
        results,
        generated_at=payload["generated_at"],
        conditions=conditions,
        scenarios=scenarios,
        title=title,
        metric_line=metric_line,
        interpretation_lines=interpretation_lines,
    )
    json_path = output_json or (BENCHMARKS_DIR / "paper_a_task_completion_eval_results.json")
    markdown_path = output_md or (BENCHMARKS_DIR / "paper_a_task_completion_eval_results.md")
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(markdown, encoding="utf-8")
    return payload


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    results = evaluate_task_completion(output_root=OUTPUT_ROOT)
    payload = write_task_completion_eval_artifacts(
        results,
        generated_at=generated_at,
        output_root=OUTPUT_ROOT,
    )
    print(
        json.dumps(
            {
                "generated_at": payload["generated_at"],
                "condition_summary": payload["condition_summary"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
