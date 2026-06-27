# Paper A Continuity Evaluation

- Generated at: `2026-06-21T18:53:39.968520+00:00`
- Scenario count: `4`
- Conditions: `Memory-Off`, `Weak-Session`, `Memory-Backed Continuity`
- Metric policy: black-box CLI inspection of saved sessions, replay surfaces, readiness visibility, and durable rewind behavior.

## Aggregate Results

| Condition | Anchor retention | Interruption recovery | Rewind success | Readiness visibility | Context loss |
| --- | ---: | ---: | ---: | ---: | ---: |
| Memory-Off | 0.00 (0/20) | 0.00 (0/16) | 0.00 (0/4) | 0.00 (0/4) | 1.00 |
| Weak-Session | 0.60 (12/20) | 0.50 (8/16) | 0.00 (0/4) | 0.00 (0/4) | 0.40 |
| Memory-Backed Continuity | 1.00 (20/20) | 1.00 (16/16) | 1.00 (4/4) | 1.00 (4/4) | 0.00 |

## Interpretation

- `Weak-Session` preserves the prompt and transcript layer, but it still drops checkpointed file state and readiness state.
- `Memory-Backed Continuity` is the only condition that restores the full continuity package after interruption.
- The gap is not produced by a stronger model path; it is produced by whether durable state is explicitly packaged and recoverable.

## Scenario Traces

| Scenario | Condition | Session | Trace directory |
| --- | --- | --- | --- |
| Conversion repair continuity | Memory-Off | `21a7e9a48890` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\conversion-repair\memory_off` |
| Conversion repair continuity | Weak-Session | `926d584bb34c` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\conversion-repair\weak_session` |
| Conversion repair continuity | Memory-Backed Continuity | `8f057a5ae463` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\conversion-repair\memory_backed_continuity` |
| Demo and README recovery | Memory-Off | `ed0cbe64e77c` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\demo-readme\memory_off` |
| Demo and README recovery | Weak-Session | `db9ab34a7c28` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\demo-readme\weak_session` |
| Demo and README recovery | Memory-Backed Continuity | `65ea425b8dcb` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\demo-readme\memory_backed_continuity` |
| Provider readiness recovery | Memory-Off | `ebbc7c91542f` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\provider-readiness\memory_off` |
| Provider readiness recovery | Weak-Session | `6de5a854ffb5` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\provider-readiness\weak_session` |
| Provider readiness recovery | Memory-Backed Continuity | `c3bad94b4673` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\provider-readiness\memory_backed_continuity` |
| Paper result package recovery | Memory-Off | `0a6a95ca12a9` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\paper-results\memory_off` |
| Paper result package recovery | Weak-Session | `079f8c0ca0db` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\paper-results\weak_session` |
| Paper result package recovery | Memory-Backed Continuity | `06d0dddc17b6` | `D:\Desktop\minicode\outputs\paper_a_continuity_eval\paper-results\memory_backed_continuity` |
