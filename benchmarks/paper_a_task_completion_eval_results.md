# Paper A Task Completion Eval

- Generated at: 2026-06-22T15:48:49.252996+00:00
- Scenarios: 14 interrupted long-track coding tasks
- Conditions: Memory-Off, Weak-Session, Memory-Backed Continuity
- Metric: exact task completion plus goal recall after black-box CLI continuity recovery

## Condition Summary

| condition | transcript_exact | checkpoint_exact | readiness_exact | cross_exact | overall_exact | overall_goal_recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Memory-Off | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 (0/28) |
| Weak-Session | 1.00 | 0.00 | 0.00 | 0.00 | 0.29 | 0.54 (15/28) |
| Memory-Backed Continuity | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 (28/28) |

## Interpretation

- Weak session access completes transcript-only tasks, but it still fails when the resumed task depends on checkpoint restoration or readiness state.
- Memory-backed continuity is the only condition that completes every matched long-track task in the suite end to end.
- The completion gap appears after answer support, not before it: answer-facing summaries are not enough when the resumed task also depends on durable operational state.

## Scenario Breakdown

| scenario | family | condition | completed_goals | exact | trace_dir |
| --- | --- | --- | ---: | ---: | --- |
| README hero surface recovery | transcript | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\readme-hero\memory_off` |
| README hero surface recovery | transcript | Weak-Session | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\readme-hero\weak_session` |
| README hero surface recovery | transcript | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\readme-hero\memory_backed_continuity` |
| Frontend demo handoff recovery | transcript | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\frontend-demo\memory_off` |
| Frontend demo handoff recovery | transcript | Weak-Session | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\frontend-demo\weak_session` |
| Frontend demo handoff recovery | transcript | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\frontend-demo\memory_backed_continuity` |
| Paper abstract revision recovery | transcript | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\paper-abstract\memory_off` |
| Paper abstract revision recovery | transcript | Weak-Session | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\paper-abstract\weak_session` |
| Paper abstract revision recovery | transcript | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\paper-abstract\memory_backed_continuity` |
| Conversion repair continuity recovery | checkpoint | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\conversion-repair\memory_off` |
| Conversion repair continuity recovery | checkpoint | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\conversion-repair\weak_session` |
| Conversion repair continuity recovery | checkpoint | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\conversion-repair\memory_backed_continuity` |
| Benchmark packaging recovery | checkpoint | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\benchmark-packaging\memory_off` |
| Benchmark packaging recovery | checkpoint | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\benchmark-packaging\weak_session` |
| Benchmark packaging recovery | checkpoint | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\benchmark-packaging\memory_backed_continuity` |
| Provider readiness recovery | readiness | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\provider-readiness\memory_off` |
| Provider readiness recovery | readiness | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\provider-readiness\weak_session` |
| Provider readiness recovery | readiness | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\provider-readiness\memory_backed_continuity` |
| Offline fallback readiness recovery | readiness | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\offline-fallback\memory_off` |
| Offline fallback readiness recovery | readiness | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\offline-fallback\weak_session` |
| Offline fallback readiness recovery | readiness | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\offline-fallback\memory_backed_continuity` |
| Release bundle completion recovery | cross_surface | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\release-bundle\memory_off` |
| Release bundle completion recovery | cross_surface | Weak-Session | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\release-bundle\weak_session` |
| Release bundle completion recovery | cross_surface | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\release-bundle\memory_backed_continuity` |
| Figure package completion recovery | cross_surface | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\figure-package\memory_off` |
| Figure package completion recovery | cross_surface | Weak-Session | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\figure-package\weak_session` |
| Figure package completion recovery | cross_surface | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\figure-package\memory_backed_continuity` |
| Failure boundary recovery | transcript | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\failure-boundary\memory_off` |
| Failure boundary recovery | transcript | Weak-Session | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\failure-boundary\weak_session` |
| Failure boundary recovery | transcript | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\failure-boundary\memory_backed_continuity` |
| Task completion table recovery | checkpoint | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\task-completion-table\memory_off` |
| Task completion table recovery | checkpoint | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\task-completion-table\weak_session` |
| Task completion table recovery | checkpoint | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\task-completion-table\memory_backed_continuity` |
| Submission compile recovery | checkpoint | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\submission-compile\memory_off` |
| Submission compile recovery | checkpoint | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\submission-compile\weak_session` |
| Submission compile recovery | checkpoint | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\submission-compile\memory_backed_continuity` |
| Repro checklist readiness recovery | readiness | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\repro-checklist\memory_off` |
| Repro checklist readiness recovery | readiness | Weak-Session | 1/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\repro-checklist\weak_session` |
| Repro checklist readiness recovery | readiness | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\repro-checklist\memory_backed_continuity` |
| Reviewer response bundle recovery | cross_surface | Memory-Off | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\reviewer-response-bundle\memory_off` |
| Reviewer response bundle recovery | cross_surface | Weak-Session | 0/2 | 0.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\reviewer-response-bundle\weak_session` |
| Reviewer response bundle recovery | cross_surface | Memory-Backed Continuity | 2/2 | 1.00 | `D:\Desktop\minicode\outputs\paper_a_task_completion_eval\reviewer-response-bundle\memory_backed_continuity` |
