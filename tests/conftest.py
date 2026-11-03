"""Test setup: never touch your real database or settings.toml.

The environment variables must be set before `config` is imported, so this runs first. All test data
is made up; never copy real responses from data/raw/samples into tests/ (the repo is shared).
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="garmin_tests_"))
os.environ["GARMIN_DB_PATH"] = str(_TMP / "unused.db")
os.environ["GARMIN_SETTINGS_PATH"] = str(_TMP / "no-settings.toml")  # defaults from config.py only

for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import config  # noqa: E402
from db.database import connect  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh database with the current schema; DATA_DIR points to a temp folder too."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = connect(tmp_path / "garmin.db")
    yield conn
    conn.close()


def add_activity(conn, activity_id: int, start: str, **cols) -> None:
    row = {"activity_id": activity_id, "start_time_local": start, "name": f"Run {activity_id}",
           "sport_type": "running", "source": "api", **cols}
    conn.execute(f"INSERT INTO activities ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                 tuple(row.values()))
