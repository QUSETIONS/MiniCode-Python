from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minicode.paper_a_retrieval_probe_eval import (
    OUTPUT_ROOT,
    evaluate_retrieval_probe,
    retrieval_probe_eval_as_dict,
    retrieval_probe_eval_as_markdown,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"


def main() -> None:
    BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    rows = evaluate_retrieval_probe()
    payload = retrieval_probe_eval_as_dict(rows)
    payload["generated_at"] = generated_at
    payload["repo_root"] = str(REPO_ROOT)
    payload["output_root"] = str(OUTPUT_ROOT)

    json_path = BENCHMARKS_DIR / "paper_a_retrieval_probe_eval_results.json"
    markdown_path = BENCHMARKS_DIR / "paper_a_retrieval_probe_eval_results.md"
    detailed_rows_path = OUTPUT_ROOT / "query_rows.json"

    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        retrieval_probe_eval_as_markdown(rows),
        encoding="utf-8",
    )
    detailed_rows_path.write_text(
        json.dumps(payload["rows"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    print(f"Wrote {detailed_rows_path}")


if __name__ == "__main__":
    main()
