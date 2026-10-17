"""SQLite access shared by the sync scripts and the dashboard."""

import sqlite3
from pathlib import Path

import config


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    """Open the database, creating it and applying the schema if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def upsert(conn: sqlite3.Connection, table: str, row: dict, key: str | tuple[str, ...]) -> None:
    """Insert a row, or update the given columns if the key already exists.

    Columns not present in `row` are left untouched on update.
    """
    keys = (key,) if isinstance(key, str) else key
    cols = list(row)
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in keys)
    if "updated_at" not in cols and _has_column(conn, table, "updated_at"):
        updates += (", " if updates else "") + "updated_at = datetime('now')"
    conflict = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(keys)}) {conflict}",
        row,
    )


_column_cache: dict[tuple[str, str], bool] = {}


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if (table, column) not in _column_cache:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        _column_cache[(table, column)] = column in cols
    return _column_cache[(table, column)]


def get_state(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    upsert(conn, "sync_state", {"key": key, "value": value}, "key")
