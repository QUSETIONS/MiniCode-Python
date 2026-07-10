from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minicode.paper_a_task_completion_eval import main


if __name__ == "__main__":
    main()
