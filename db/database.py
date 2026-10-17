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
    fresh = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'activities'").fetchone() is None
    schema = config.SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    if fresh:  # a new database already has the latest schema
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
    elif _migrate(conn):
        conn.executescript(schema)  # recreate views dropped by migrations
    return conn


# Changes to existing tables, applied once each, in order (tracked with PRAGMA user_version).
# New tables/views/indexes go straight into schema.sql; also update schema.sql to the end state.
MIGRATIONS: list[str] = [
    # 1: new tags (cycling, hiking_walking). SQLite can't alter a CHECK constraint, so rebuild the table.
    """
    DROP VIEW IF EXISTS v_weekly;
    DROP VIEW IF EXISTS v_activities;
    CREATE TABLE activity_tags_new (
        activity_id  INTEGER PRIMARY KEY REFERENCES activities(activity_id) ON DELETE CASCADE,
        tag          TEXT NOT NULL CHECK (tag IN ('o_race','o_training','interval','long_run','easy_run','strength','cycling','hiking_walking','other')),
        source       TEXT NOT NULL CHECK (source IN ('auto','manual')),
        updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    INSERT INTO activity_tags_new SELECT activity_id, tag, source, updated_at FROM activity_tags;
    DROP TABLE activity_tags;
    ALTER TABLE activity_tags_new RENAME TO activity_tags;
    CREATE INDEX IF NOT EXISTS idx_tags_tag ON activity_tags(tag);
    """,
    # 2: lap bookkeeping
    "ALTER TABLE activities ADD COLUMN laps_fetched INTEGER NOT NULL DEFAULT 0;",
]


def _migrate(conn: sqlite3.Connection) -> bool:
    """Apply pending migrations. Returns True if any ran."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(script)
        conn.execute(f"PRAGMA user_version = {i}")
        conn.commit()
    return version < len(MIGRATIONS)


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
