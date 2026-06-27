# Paper A Continuity Causal Ladder

- Generated at: `2026-06-21T18:51:15.876848+00:00`
- Scenario count: `4`
- Conditions: `Memory-Off`, `History-Only`, `Weak-Session`, `Session+Checkpoint`, `Session+Readiness`, `Stale-Continuity-Package`, `Memory-Backed Continuity`
- Metric policy: black-box CLI inspection of saved sessions, replay surfaces, readiness visibility, and durable rewind behavior.

## Aggregate Results

| Condition | Anchor retention | Interruption recovery | Rewind success | Readiness visibility | Context loss |
| --- | ---: | ---: | ---: | ---: | ---: |
| Memory-Off | 0.00 (0/20) | 0.00 (0/16) | 0.00 (0/4) | 0.00 (0/4) | 1.00 |
| History-Only | 0.40 (8/20) | 0.25 (4/16) | 0.00 (0/4) | 0.00 (0/4) | 0.60 |
| Weak-Session | 0.60 (12/20) | 0.50 (8/16) | 0.00 (0/4) | 0.00 (0/4) | 0.40 |
| Session+Checkpoint | 0.80 (16/20) | 0.75 (12/16) | 1.00 (4/4) | 0.00 (0/4) | 0.20 |
| Session+Readiness | 0.80 (16/20) | 0.75 (12/16) | 0.00 (0/4) | 1.00 (4/4) | 0.20 |
| Stale-Continuity-Package | 0.80 (16/20) | 0.75 (12/16) | 0.00 (0/4) | 0.00 (0/4) | 0.20 |
| Memory-Backed Continuity | 1.00 (20/20) | 1.00 (16/16) | 1.00 (4/4) | 1.00 (4/4) | 0.00 |

## Interpretation

- `History-Only` recovers the task frame, but it cannot recover transcript evidence, checkpoints, or readiness state.
- `Session+Checkpoint` rescues rewind behavior without rescuing readiness, while `Session+Readiness` does the opposite.
- `Stale-Continuity-Package` still exposes some continuity surfaces, but it fails exact recovery because the saved state is outdated.
- `Memory-Backed Continuity` is the only condition that restores the complete, fresh continuity package end to end.

## Scenario Traces

| Scenario | Condition | Session | Trace directory |
| --- | --- | --- | --- |
| Conversion repair continuity | Memory-Off | `9d9803b90410` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\conversion-repair\memory_off` |
| Conversion repair continuity | History-Only | `8b7209ae0342` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\conversion-repair\history_only` |
| Conversion repair continuity | Weak-Session | `eb04a457c74a` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\conversion-repair\weak_session` |
| Conversion repair continuity | Session+Checkpoint | `0568d6de7093` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\conversion-repair\session_plus_checkpoint` |
| Conversion repair continuity | Session+Readiness | `f76c50cef73c` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\conversion-repair\session_plus_readiness` |
| Conversion repair continuity | Stale-Continuity-Package | `d628c240b611` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\conversion-repair\stale_continuity_package` |
| Conversion repair continuity | Memory-Backed Continuity | `985f6f1edf50` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\conversion-repair\memory_backed_continuity` |
| Demo and README recovery | Memory-Off | `0ec19ad75bf1` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\demo-readme\memory_off` |
| Demo and README recovery | History-Only | `64eb62969681` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\demo-readme\history_only` |
| Demo and README recovery | Weak-Session | `4fa128f51795` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\demo-readme\weak_session` |
| Demo and README recovery | Session+Checkpoint | `f0db98fcfc75` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\demo-readme\session_plus_checkpoint` |
| Demo and README recovery | Session+Readiness | `3232b34cc4d8` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\demo-readme\session_plus_readiness` |
| Demo and README recovery | Stale-Continuity-Package | `325e737e4926` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\demo-readme\stale_continuity_package` |
| Demo and README recovery | Memory-Backed Continuity | `837a79974907` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\demo-readme\memory_backed_continuity` |
| Provider readiness recovery | Memory-Off | `bf6ddf6afb51` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\provider-readiness\memory_off` |
| Provider readiness recovery | History-Only | `f1222bb3db6a` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\provider-readiness\history_only` |
| Provider readiness recovery | Weak-Session | `8d768f3e08c4` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\provider-readiness\weak_session` |
| Provider readiness recovery | Session+Checkpoint | `53086d89fc91` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\provider-readiness\session_plus_checkpoint` |
| Provider readiness recovery | Session+Readiness | `f5b78f5fea9a` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\provider-readiness\session_plus_readiness` |
| Provider readiness recovery | Stale-Continuity-Package | `c5d18d2599fe` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\provider-readiness\stale_continuity_package` |
| Provider readiness recovery | Memory-Backed Continuity | `1b23486ff051` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\provider-readiness\memory_backed_continuity` |
| Paper result package recovery | Memory-Off | `5dbb969b06b3` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\paper-results\memory_off` |
| Paper result package recovery | History-Only | `ec8911675f12` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\paper-results\history_only` |
| Paper result package recovery | Weak-Session | `460997051530` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\paper-results\weak_session` |
| Paper result package recovery | Session+Checkpoint | `e5f86181d5f4` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\paper-results\session_plus_checkpoint` |
| Paper result package recovery | Session+Readiness | `8a92b54d5df9` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\paper-results\session_plus_readiness` |
| Paper result package recovery | Stale-Continuity-Package | `68ddc691459e` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\paper-results\stale_continuity_package` |
| Paper result package recovery | Memory-Backed Continuity | `b45a3778a3a0` | `D:\Desktop\minicode\outputs\paper_a_continuity_ablation_eval\paper-results\memory_backed_continuity` |
