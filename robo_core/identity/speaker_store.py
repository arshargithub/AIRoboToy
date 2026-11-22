"""
SQLite-backed storage for enrolled speaker voiceprints.
Each speaker has a name and a 192-dim embedding stored as a BLOB.
"""
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from robo_core.identity.speaker_encoder import EMBEDDING_DIM

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(Path.home(), ".johnny", "voiceprints.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS speakers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    UNIQUE NOT NULL,
    embedding   BLOB   NOT NULL,
    enrolled_at TEXT   NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 1
);
"""


class SpeakerStore:
    """CRUD layer over the local voiceprint database."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        logger.info("Speaker store opened at %s", self.db_path)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def enroll(self, name: str, embedding: np.ndarray, sample_count: int = 1) -> None:
        """Insert or replace a speaker voiceprint."""
        if embedding.shape != (EMBEDDING_DIM,):
            raise ValueError(f"Expected ({EMBEDDING_DIM},) embedding, got {embedding.shape}")
        blob = embedding.astype(np.float32).tobytes()
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO speakers (name, embedding, enrolled_at, sample_count) "
            "VALUES (?, ?, ?, ?)",
            (name.strip().lower(), blob, now, sample_count),
        )
        self._conn.commit()
        logger.info("Enrolled speaker '%s' (%d samples)", name, sample_count)

    def remove(self, name: str) -> bool:
        """Remove a speaker. Returns True if a row was deleted."""
        cur = self._conn.execute(
            "DELETE FROM speakers WHERE name = ?", (name.strip().lower(),)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_all(self) -> Dict[str, np.ndarray]:
        """Return {name: embedding} for every enrolled speaker."""
        rows = self._conn.execute(
            "SELECT name, embedding FROM speakers"
        ).fetchall()
        return {
            name: np.frombuffer(blob, dtype=np.float32).copy()
            for name, blob in rows
        }

    def list_speakers(self) -> List[Tuple[str, str, int]]:
        """Return [(name, enrolled_at, sample_count), ...] for display."""
        return self._conn.execute(
            "SELECT name, enrolled_at, sample_count FROM speakers ORDER BY name"
        ).fetchall()

    def get(self, name: str) -> Optional[np.ndarray]:
        """Return a single speaker's embedding or None."""
        row = self._conn.execute(
            "SELECT embedding FROM speakers WHERE name = ?",
            (name.strip().lower(),),
        ).fetchone()
        if row is None:
            return None
        return np.frombuffer(row[0], dtype=np.float32).copy()

    @property
    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM speakers").fetchone()[0]

    def close(self):
        self._conn.close()
