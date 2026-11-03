"""A database created with the very first schema must migrate to the same tables as a fresh one."""

import sqlite3
from pathlib import Path

from db.database import MIGRATIONS, connect

V0_SCHEMA = Path(__file__).parent / "fixtures" / "schema_v0.sql"  # db/schema.sql of the initial commit


def shape(conn: sqlite3.Connection) -> dict:
    """Columns (name, type, not null, default, pk) per table, plus index and view names."""
    out = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
        out[name] = sorted(tuple(r)[1:] for r in conn.execute(f"PRAGMA table_info({name})"))
    for kind in ("index", "view"):
        out[kind] = sorted(r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'", (kind,)))
    return out


def test_old_database_migrates_to_current_schema(tmp_path):
    old = tmp_path / "old.db"
    raw = sqlite3.connect(old)
    raw.executescript(V0_SCHEMA.read_text(encoding="utf-8"))
    raw.execute("INSERT INTO activities (activity_id, start_time_local, name, sport_type) "
                "VALUES (1, '2026-01-01 10:00:00', 'Old run', 'running')")
    raw.execute("INSERT INTO activity_tags (activity_id, tag, source) VALUES (1, 'o_race', 'manual')")
    raw.commit()
    raw.close()

    migrated = connect(old)
    fresh = connect(tmp_path / "fresh.db")
    try:
        assert shape(migrated) == shape(fresh)
        for conn in (migrated, fresh):
            assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        # Data survives the table rebuilds, and the views work on the migrated database.
        row = migrated.execute("SELECT name, tag FROM v_activities WHERE activity_id = 1").fetchone()
        assert tuple(row) == ("Old run", "o_race")
    finally:
        migrated.close()
        fresh.close()


def test_connect_twice_is_a_no_op(tmp_path):
    path = tmp_path / "garmin.db"
    connect(path).close()
    conn = connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    finally:
        conn.close()


def test_schema_runs_once_per_process_and_again_for_a_new_file(tmp_path, monkeypatch):
    from db import database

    runs = []
    real = database.init_db
    monkeypatch.setattr(database, "init_db", lambda conn: (runs.append(1), real(conn)))
    path = tmp_path / "garmin.db"
    for _ in range(3):
        database.connect(path).close()
    assert len(runs) == 1
    path.unlink()  # e.g. "start over": a new database file gets the schema again
    database.connect(path).close()
    assert len(runs) == 2
