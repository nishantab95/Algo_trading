from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from app.core.paths import DATABASE_PATH, ensure_runtime_paths
from app.db.migrations import MIGRATIONS


class Database:
    def __init__(self, path: str | Path = DATABASE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as connection:
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def initialize(self) -> None:
        with self.transaction() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_version")}
            for version, sql in MIGRATIONS:
                if version not in applied:
                    connection.executescript(sql)
                    connection.execute("INSERT INTO schema_version(version, applied_at) VALUES (?, datetime('now'))", (version,))

    def query(self, sql: str, params: Sequence[object] = ()) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]


_DATABASE: Database | None = None


def get_database(path: str | Path | None = None) -> Database:
    global _DATABASE
    if path is not None:
        database = Database(path)
        database.initialize()
        return database
    if _DATABASE is None:
        ensure_runtime_paths()
        _DATABASE = Database()
        _DATABASE.initialize()
    return _DATABASE
