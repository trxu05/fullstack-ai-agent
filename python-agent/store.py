"""SQLite persistence for StudyBoard sessions."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

_LOCK = threading.Lock()
_DB_PATH = os.getenv("STUDYBOARD_DB", os.path.join(os.path.dirname(__file__), "studyboard.db"))


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS boards (
            session_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return c


def load_board(session_id: str) -> dict[str, Any] | None:
    with _LOCK:
        c = _conn()
        try:
            row = c.execute("SELECT payload FROM boards WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None
            return json.loads(row[0])
        finally:
            c.close()


def save_board(session_id: str, board: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    payload = json.dumps(board)
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                """
                INSERT INTO boards(session_id, payload, updated_at) VALUES(?,?,?)
                ON CONFLICT(session_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (session_id, payload, now),
            )
            c.commit()
        finally:
            c.close()
