# Paper A Task Completion Causal Ladder

- Generated at: 2026-06-23T01:42:02.029303+00:00
- Scenarios: 14 interrupted long-track coding tasks
- Conditions: Memory-Off, History-Only, Weak-Session, Session+Checkpoint, Session+Readiness, Stale-Continuity-Package, Memory-Backed Continuity
- Metric: exact task completion plus goal recall after black-box CLI continuity recovery

## Condition Summary

| condition | transcript_exact | checkpoint_exact | readiness_exact | cross_exact | overall_exact | overall_goal_recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Memory-Off | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 (0/28) |
| History-Only | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 (0/28) |
| Weak-Session | 1.00 | 0.00 | 0.00 | 0.00 | 0.29 | 0.54 (15/28) |
| Session+Checkpoint | 1.00 | 1.00 | 0.00 | 0.00 | 0.57 | 0.79 (22/28) |
| Session+Readiness | 1.00 | 0.00 | 1.00 | 0.00 | 0.50 | 0.64 (18/28) |
| Stale-Continuity-Package | 1.00 | 0.00 | 0.00 | 0.00 | 0.29 | 0.54 (15/28) |
| Memory-Backed Continuity | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 (28/28) |

## Interpretation

- `Session+Checkpoint` selectively rescues checkpoint-dependent work, but it still fails on readiness-dependent recovery.
- `Session+Readiness` selectively rescues readiness-dependent work, but it still fails when the resumed task requires file restoration.
- `Stale-Continuity-Package` underperforms the fresh package, showing that packaging continuity state is not enough if the packaged state is outdated.
- `Memory-Backed Continuity` is the only condition that completes transcript, checkpoint, readiness, and cross-surface tasks together.

## Scenario Breakdown

| scenario | family | condition | completed_goals | exact | trace_dir |
| --- | --- | --- | ---: | ---: | --- |
| README hero surface recovery | transcript | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\readme-hero\memory_off` |
| README hero surface recovery | transcript | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\readme-hero\history_only` |
| README hero surface recovery | transcript | Weak-Session | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\readme-hero\weak_session` |
| README hero surface recovery | transcript | Session+Checkpoint | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\readme-hero\session_plus_checkpoint` |
| README hero surface recovery | transcript | Session+Readiness | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\readme-hero\session_plus_readiness` |
| README hero surface recovery | transcript | Stale-Continuity-Package | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\readme-hero\stale_continuity_package` |
| README hero surface recovery | transcript | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\readme-hero\memory_backed_continuity` |
| Frontend demo handoff recovery | transcript | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\frontend-demo\memory_off` |
| Frontend demo handoff recovery | transcript | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\frontend-demo\history_only` |
| Frontend demo handoff recovery | transcript | Weak-Session | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\frontend-demo\weak_session` |
| Frontend demo handoff recovery | transcript | Session+Checkpoint | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\frontend-demo\session_plus_checkpoint` |
| Frontend demo handoff recovery | transcript | Session+Readiness | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\frontend-demo\session_plus_readiness` |
| Frontend demo handoff recovery | transcript | Stale-Continuity-Package | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\frontend-demo\stale_continuity_package` |
| Frontend demo handoff recovery | transcript | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\frontend-demo\memory_backed_continuity` |
| Paper abstract revision recovery | transcript | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\paper-abstract\memory_off` |
| Paper abstract revision recovery | transcript | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\paper-abstract\history_only` |
| Paper abstract revision recovery | transcript | Weak-Session | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\paper-abstract\weak_session` |
| Paper abstract revision recovery | transcript | Session+Checkpoint | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\paper-abstract\session_plus_checkpoint` |
| Paper abstract revision recovery | transcript | Session+Readiness | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\paper-abstract\session_plus_readiness` |
| Paper abstract revision recovery | transcript | Stale-Continuity-Package | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\paper-abstract\stale_continuity_package` |
| Paper abstract revision recovery | transcript | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\paper-abstract\memory_backed_continuity` |
| Conversion repair continuity recovery | checkpoint | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\conversion-repair\memory_off` |
| Conversion repair continuity recovery | checkpoint | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\conversion-repair\history_only` |
| Conversion repair continuity recovery | checkpoint | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\conversion-repair\weak_session` |
| Conversion repair continuity recovery | checkpoint | Session+Checkpoint | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\conversion-repair\session_plus_checkpoint` |
| Conversion repair continuity recovery | checkpoint | Session+Readiness | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\conversion-repair\session_plus_readiness` |
| Conversion repair continuity recovery | checkpoint | Stale-Continuity-Package | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\conversion-repair\stale_continuity_package` |
| Conversion repair continuity recovery | checkpoint | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\conversion-repair\memory_backed_continuity` |
| Benchmark packaging recovery | checkpoint | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\benchmark-packaging\memory_off` |
| Benchmark packaging recovery | checkpoint | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\benchmark-packaging\history_only` |
| Benchmark packaging recovery | checkpoint | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\benchmark-packaging\weak_session` |
| Benchmark packaging recovery | checkpoint | Session+Checkpoint | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\benchmark-packaging\session_plus_checkpoint` |
| Benchmark packaging recovery | checkpoint | Session+Readiness | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\benchmark-packaging\session_plus_readiness` |
| Benchmark packaging recovery | checkpoint | Stale-Continuity-Package | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\benchmark-packaging\stale_continuity_package` |
| Benchmark packaging recovery | checkpoint | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\benchmark-packaging\memory_backed_continuity` |
| Provider readiness recovery | readiness | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\provider-readiness\memory_off` |
| Provider readiness recovery | readiness | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\provider-readiness\history_only` |
| Provider readiness recovery | readiness | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\provider-readiness\weak_session` |
| Provider readiness recovery | readiness | Session+Checkpoint | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\provider-readiness\session_plus_checkpoint` |
| Provider readiness recovery | readiness | Session+Readiness | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\provider-readiness\session_plus_readiness` |
| Provider readiness recovery | readiness | Stale-Continuity-Package | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\provider-readiness\stale_continuity_package` |
| Provider readiness recovery | readiness | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\provider-readiness\memory_backed_continuity` |
| Offline fallback readiness recovery | readiness | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\offline-fallback\memory_off` |
| Offline fallback readiness recovery | readiness | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\offline-fallback\history_only` |
| Offline fallback readiness recovery | readiness | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\offline-fallback\weak_session` |
| Offline fallback readiness recovery | readiness | Session+Checkpoint | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\offline-fallback\session_plus_checkpoint` |
| Offline fallback readiness recovery | readiness | Session+Readiness | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\offline-fallback\session_plus_readiness` |
| Offline fallback readiness recovery | readiness | Stale-Continuity-Package | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\offline-fallback\stale_continuity_package` |
| Offline fallback readiness recovery | readiness | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\offline-fallback\memory_backed_continuity` |
| Release bundle completion recovery | cross_surface | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\release-bundle\memory_off` |
| Release bundle completion recovery | cross_surface | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\release-bundle\history_only` |
| Release bundle completion recovery | cross_surface | Weak-Session | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\release-bundle\weak_session` |
| Release bundle completion recovery | cross_surface | Session+Checkpoint | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\release-bundle\session_plus_checkpoint` |
| Release bundle completion recovery | cross_surface | Session+Readiness | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\release-bundle\session_plus_readiness` |
| Release bundle completion recovery | cross_surface | Stale-Continuity-Package | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\release-bundle\stale_continuity_package` |
| Release bundle completion recovery | cross_surface | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\release-bundle\memory_backed_continuity` |
| Figure package completion recovery | cross_surface | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\figure-package\memory_off` |
| Figure package completion recovery | cross_surface | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\figure-package\history_only` |
| Figure package completion recovery | cross_surface | Weak-Session | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\figure-package\weak_session` |
| Figure package completion recovery | cross_surface | Session+Checkpoint | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\figure-package\session_plus_checkpoint` |
| Figure package completion recovery | cross_surface | Session+Readiness | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\figure-package\session_plus_readiness` |
| Figure package completion recovery | cross_surface | Stale-Continuity-Package | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\figure-package\stale_continuity_package` |
| Figure package completion recovery | cross_surface | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\figure-package\memory_backed_continuity` |
| Failure boundary recovery | transcript | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\failure-boundary\memory_off` |
| Failure boundary recovery | transcript | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\failure-boundary\history_only` |
| Failure boundary recovery | transcript | Weak-Session | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\failure-boundary\weak_session` |
| Failure boundary recovery | transcript | Session+Checkpoint | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\failure-boundary\session_plus_checkpoint` |
| Failure boundary recovery | transcript | Session+Readiness | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\failure-boundary\session_plus_readiness` |
| Failure boundary recovery | transcript | Stale-Continuity-Package | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\failure-boundary\stale_continuity_package` |
| Failure boundary recovery | transcript | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\failure-boundary\memory_backed_continuity` |
| Task completion table recovery | checkpoint | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\task-completion-table\memory_off` |
| Task completion table recovery | checkpoint | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\task-completion-table\history_only` |
| Task completion table recovery | checkpoint | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\task-completion-table\weak_session` |
| Task completion table recovery | checkpoint | Session+Checkpoint | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\task-completion-table\session_plus_checkpoint` |
| Task completion table recovery | checkpoint | Session+Readiness | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\task-completion-table\session_plus_readiness` |
| Task completion table recovery | checkpoint | Stale-Continuity-Package | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\task-completion-table\stale_continuity_package` |
| Task completion table recovery | checkpoint | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\task-completion-table\memory_backed_continuity` |
| Submission compile recovery | checkpoint | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\submission-compile\memory_off` |
| Submission compile recovery | checkpoint | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\submission-compile\history_only` |
| Submission compile recovery | checkpoint | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\submission-compile\weak_session` |
| Submission compile recovery | checkpoint | Session+Checkpoint | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\submission-compile\session_plus_checkpoint` |
| Submission compile recovery | checkpoint | Session+Readiness | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\submission-compile\session_plus_readiness` |
| Submission compile recovery | checkpoint | Stale-Continuity-Package | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\submission-compile\stale_continuity_package` |
| Submission compile recovery | checkpoint | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\submission-compile\memory_backed_continuity` |
| Repro checklist readiness recovery | readiness | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\repro-checklist\memory_off` |
| Repro checklist readiness recovery | readiness | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\repro-checklist\history_only` |
| Repro checklist readiness recovery | readiness | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\repro-checklist\weak_session` |
| Repro checklist readiness recovery | readiness | Session+Checkpoint | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\repro-checklist\session_plus_checkpoint` |
| Repro checklist readiness recovery | readiness | Session+Readiness | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\repro-checklist\session_plus_readiness` |
| Repro checklist readiness recovery | readiness | Stale-Continuity-Package | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\repro-checklist\stale_continuity_package` |
| Repro checklist readiness recovery | readiness | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\repro-checklist\memory_backed_continuity` |
| Reviewer response bundle recovery | cross_surface | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\reviewer-response-bundle\memory_off` |
| Reviewer response bundle recovery | cross_surface | History-Only | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\reviewer-response-bundle\history_only` |
| Reviewer response bundle recovery | cross_surface | Weak-Session | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\reviewer-response-bundle\weak_session` |
| Reviewer response bundle recovery | cross_surface | Session+Checkpoint | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\reviewer-response-bundle\session_plus_checkpoint` |
| Reviewer response bundle recovery | cross_surface | Session+Readiness | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\reviewer-response-bundle\session_plus_readiness` |
| Reviewer response bundle recovery | cross_surface | Stale-Continuity-Package | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\reviewer-response-bundle\stale_continuity_package` |
| Reviewer response bundle recovery | cross_surface | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_ablation_eval\reviewer-response-bundle\memory_backed_continuity` |
