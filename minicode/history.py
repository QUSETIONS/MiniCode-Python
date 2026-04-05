from __future__ import annotations

import json

from minicode.config import MINI_CODE_DIR, MINI_CODE_HISTORY_PATH


def load_history_entries() -> list[str]:
    if not MINI_CODE_HISTORY_PATH.exists():
        return []
    try:
        parsed = json.loads(MINI_CODE_HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    entries = parsed.get("entries", [])
    return [str(entry) for entry in entries] if isinstance(entries, list) else []


def save_history_entries(entries: list[str]) -> None:
    MINI_CODE_DIR.mkdir(parents=True, exist_ok=True)
    MINI_CODE_HISTORY_PATH.write_text(
        json.dumps({"entries": entries[-200:]}, indent=2) + "\n",
        encoding="utf-8",
    )

