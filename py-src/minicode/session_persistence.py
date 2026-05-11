"""Session persistence for automatic save and resume.

Saves session state (messages, model, context) to disk periodically
and on shutdown, allowing recovery after crashes.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minicode.config import MINI_CODE_DIR
from minicode.logging_config import get_logger

logger = get_logger("session_persistence")


@dataclass
class SessionState:
    """Serializable session state."""
    session_id: str
    model: str
    messages: list[dict[str, Any]]
    timestamp: float
    compaction_level: int = 0
    total_turns: int = 0
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "model": self.model,
            "messages": self.messages,
            "timestamp": self.timestamp,
            "compaction_level": self.compaction_level,
            "total_turns": self.total_turns,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        return cls(
            session_id=data["session_id"],
            model=data["model"],
            messages=data.get("messages", []),
            timestamp=data.get("timestamp", time.time()),
            compaction_level=data.get("compaction_level", 0),
            total_turns=data.get("total_turns", 0),
            version=data.get("version", 1),
        )


class SessionPersistence:
    """Manages automatic session save and resume."""

    def __init__(
        self,
        session_id: str,
        workspace: str,
        *,
        auto_save_interval: float = 30.0,
        max_sessions: int = 10,
    ):
        self.session_id = session_id
        self.workspace = workspace
        self._auto_save_interval = auto_save_interval
        self._max_sessions = max_sessions
        self._last_save: float = 0.0
        self._sessions_dir = MINI_CODE_DIR / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self) -> Path:
        safe_id = self.session_id.replace("/", "_").replace("\\", "_")
        return self._sessions_dir / f"{safe_id}.json"

    def save(
        self,
        model: str,
        messages: list[dict[str, Any]],
        compaction_level: int = 0,
        total_turns: int = 0,
        force: bool = False,
    ) -> bool:
        """Save session state to disk."""
        now = time.time()
        if not force and now - self._last_save < self._auto_save_interval:
            return False

        state = SessionState(
            session_id=self.session_id,
            model=model,
            messages=messages,
            timestamp=now,
            compaction_level=compaction_level,
            total_turns=total_turns,
        )

        path = self._session_path()
        try:
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(str(tmp_path), str(path))
            self._last_save = now
            logger.debug("Session saved: %s (%d messages)", self.session_id, len(messages))
            self._cleanup_old_sessions()
            return True
        except Exception as e:
            logger.warning("Failed to save session: %s", e)
            return False

    def load(self) -> SessionState | None:
        """Load session state from disk."""
        path = self._session_path()
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = SessionState.from_dict(data)
            age_hours = (time.time() - state.timestamp) / 3600
            if age_hours > 24:
                logger.info("Session %s expired (%.1f hours old)", self.session_id, age_hours)
                path.unlink(missing_ok=True)
                return None
            logger.info("Session loaded: %s (%d messages, %.1f hours old)",
                       self.session_id, len(state.messages), age_hours)
            return state
        except Exception as e:
            logger.warning("Failed to load session: %s", e)
            return None

    def delete(self) -> bool:
        """Delete saved session."""
        path = self._session_path()
        if path.exists():
            path.unlink()
            logger.info("Session deleted: %s", self.session_id)
            return True
        return False

    def _cleanup_old_sessions(self) -> None:
        """Remove oldest sessions if exceeding max_sessions."""
        sessions = sorted(
            self._sessions_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in sessions[self._max_sessions:]:
            old.unlink()
            logger.debug("Cleaned up old session: %s", old.name)

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all available sessions."""
        sessions = []
        for path in sorted(self._sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                age_hours = (time.time() - data.get("timestamp", 0)) / 3600
                sessions.append({
                    "session_id": data.get("session_id", path.stem),
                    "model": data.get("model", "unknown"),
                    "messages": len(data.get("messages", [])),
                    "age_hours": round(age_hours, 1),
                    "compaction_level": data.get("compaction_level", 0),
                    "total_turns": data.get("total_turns", 0),
                })
            except Exception:
                continue
        return sessions
