from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minicode.paper_a_multisession_bridge_eval import (
    evaluate_multisession_bridge,
    multisession_bridge_eval_as_dict,
    multisession_bridge_eval_as_markdown,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"


def main() -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    rows = evaluate_multisession_bridge()
    payload = multisession_bridge_eval_as_dict(rows)
    payload["generated_at"] = generated_at

    json_path = BENCHMARKS_DIR / "paper_a_multisession_bridge_eval_results.json"
    markdown_path = BENCHMARKS_DIR / "paper_a_multisession_bridge_eval_results.md"

    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        multisession_bridge_eval_as_markdown(rows),
        encoding="utf-8",
    )

    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


if __name__ == "__main__":
    main()
