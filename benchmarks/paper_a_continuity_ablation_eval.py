from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minicode.paper_a_continuity_eval import (
    ABLATION_CONTINUITY_INTERPRETATION,
    ABLATION_CONTINUITY_TITLE,
    ABLATION_OUTPUT_ROOT,
    CONTINUITY_ABLATION_CONDITIONS,
    evaluate_continuity,
    write_continuity_eval_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"


def main() -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    results = evaluate_continuity(
        output_root=ABLATION_OUTPUT_ROOT,
        conditions=CONTINUITY_ABLATION_CONDITIONS,
    )
    payload = write_continuity_eval_artifacts(
        results,
        generated_at=generated_at,
        output_root=ABLATION_OUTPUT_ROOT,
        output_json=BENCHMARKS_DIR / "paper_a_continuity_ablation_eval_results.json",
        output_md=BENCHMARKS_DIR / "paper_a_continuity_ablation_eval_results.md",
        conditions=CONTINUITY_ABLATION_CONDITIONS,
        title=ABLATION_CONTINUITY_TITLE,
        interpretation_lines=ABLATION_CONTINUITY_INTERPRETATION,
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
