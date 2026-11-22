"""Atomic source/outbox writes and a persistent conservative spend ledger."""
import json
import sqlite3
from pathlib import Path

# Owner approved $31 total on 9 November 2026 for the bounded memory check.
APPROVED_BUDGET_MICRO_USD = 31_000_000

class Store:
    def __init__(self, path: str | Path = ":memory:", *, must_exist: bool = False):
        # Desktop startup must never turn a missing budget ledger into a reset.
        self.db = (sqlite3.connect(Path(path).absolute().as_uri()+'?mode=rw', uri=True)
                   if must_exist else sqlite3.connect(str(path)))
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if must_exist and version != 1:
            self.db.close()
            raise ValueError('Existing spending ledger is unavailable; do not recreate it')
        if version not in (0, 1):
            raise ValueError(f"Unsupported database schema {version}")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY REFERENCES sources(id), attempts INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS spending (
                id TEXT PRIMARY KEY, reserved INTEGER NOT NULL, actual INTEGER);
            PRAGMA user_version=1;
        """)

    def record(self, source_id: str, body: dict, *, memory: bool = False) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sources VALUES (?,?)", (source_id, json.dumps(body)))
            if memory:
                self.db.execute("INSERT OR IGNORE INTO outbox(id) VALUES (?)", (source_id,))

    def pending(self) -> list[dict]:
        return [dict(id=row[0], body=json.loads(row[1]), attempts=row[2]) for row in
                self.db.execute("SELECT s.id,s.body,o.attempts FROM sources s JOIN outbox o ON s.id=o.id WHERE o.completed=0 ORDER BY s.rowid")]

    def attempt(self, source_id: str, *, succeeded: bool) -> None:
        with self.db:
            self.db.execute("UPDATE outbox SET attempts=attempts+1, completed=? WHERE id=?", (int(succeeded), source_id))

    def sources(self) -> list[dict]:
        return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM sources ORDER BY rowid")]

    def reserve(self, request_id: str, maximum_micro_usd: int, cap_micro_usd: int) -> None:
        """Reserve a worst-case charge BEFORE sending a future paid request.

        Unsettled reservations survive restart. Duplicate IDs fail closed.
        The database transaction also serializes independent connections.
        """
        if type(maximum_micro_usd) is not int or type(cap_micro_usd) is not int or maximum_micro_usd <= 0 or not 0 <= cap_micro_usd <= APPROVED_BUDGET_MICRO_USD:
            raise ValueError("Invalid spend reservation")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT 1 FROM spending WHERE actual>reserved LIMIT 1").fetchone():
                raise ValueError("Overage requires reconciliation before further spending")
            used = self.db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spending").fetchone()[0]
            if used + maximum_micro_usd > cap_micro_usd:
                raise ValueError("Experiment budget exhausted")
            self.db.execute("INSERT INTO spending(id,reserved) VALUES (?,?)", (request_id, maximum_micro_usd))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def settle(self, request_id: str, actual_micro_usd: int) -> None:
        if type(actual_micro_usd) is not int or actual_micro_usd < 0:
            raise ValueError("Negative charge")
        row = self.db.execute("SELECT reserved,actual FROM spending WHERE id=?", (request_id,)).fetchone()
        if row is None or row[1] is not None:
            raise ValueError("Missing or already settled reservation")
        with self.db:
            self.db.execute("UPDATE spending SET actual=? WHERE id=?", (actual_micro_usd, request_id))
        if actual_micro_usd > row[0]:
            raise ValueError("Actual charge exceeded reservation; recorded for reconciliation")

    def used_micro_usd(self) -> int:
        return self.db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spending").fetchone()[0]

    def close(self) -> None:
        self.db.close()
