from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minicode.paper_a_task_completion_eval import (
    ABLATION_OUTPUT_ROOT,
    ABLATION_TASK_COMPLETION_INTERPRETATION,
    ABLATION_TASK_COMPLETION_TITLE,
    TASK_COMPLETION_ABLATION_CONDITIONS,
    evaluate_task_completion,
    write_task_completion_eval_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"


def main() -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    results = evaluate_task_completion(
        output_root=ABLATION_OUTPUT_ROOT,
        conditions=TASK_COMPLETION_ABLATION_CONDITIONS,
    )
    payload = write_task_completion_eval_artifacts(
        results,
        generated_at=generated_at,
        output_root=ABLATION_OUTPUT_ROOT,
        output_json=BENCHMARKS_DIR / "paper_a_task_completion_ablation_eval_results.json",
        output_md=BENCHMARKS_DIR / "paper_a_task_completion_ablation_eval_results.md",
        conditions=TASK_COMPLETION_ABLATION_CONDITIONS,
        title=ABLATION_TASK_COMPLETION_TITLE,
        interpretation_lines=ABLATION_TASK_COMPLETION_INTERPRETATION,
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
