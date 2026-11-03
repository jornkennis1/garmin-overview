"""Smoke test: every dashboard page runs without errors on a small made-up database."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from db.database import connect
from garmin_sync.tagging import apply_auto_tags

from conftest import add_activity

PAGES = sorted((Path(__file__).resolve().parents[1] / "app" / "pages").glob("*.py")) + [
    Path(__file__).resolve().parents[1] / "app" / "Overview.py"]


@pytest.fixture(scope="module")
def sample_data():
    """Fill the default (temporary) database: 10 weeks of training, daily metrics, a race and a note."""
    conn = connect()
    for table in ("activities", "daily_metrics", "races", "day_notes", "week_plans"):
        conn.execute(f"DELETE FROM {table}")
    today = date.today()
    names = ["Forest O training", "6x1000 intervals", "Easy run", "Long run"]
    for i in range(70):
        if i % 7 in (2, 5):
            continue
        d = today - timedelta(days=i)
        add_activity(conn, 1000 + i, f"{d} 18:00:00", name=names[i % 4], duration_s=2400 + 60 * (i % 5),
                     distance_m=8000 + 1500 * (i % 6), avg_hr=140 + i % 20, max_hr=175, training_load=60 + i % 40,
                     elev_gain_m=50 + i)
        conn.executemany("INSERT INTO activity_hr_zones (activity_id, zone, seconds, zone_low_bpm) VALUES (?,?,?,?)",
                         [(1000 + i, z, 600 - 100 * z + 300, 100 + 15 * z) for z in range(1, 6)])
        conn.execute("INSERT INTO daily_metrics (date, resting_hr, hrv_overnight_avg, hrv_baseline_low, sleep_s) "
                     "VALUES (?,?,?,?,?)", (d.isoformat(), 45 + i % 3, 60 + i % 5, 55, 27000))
    conn.execute("INSERT INTO activity_extra_tags (activity_id, tag) VALUES (1000, 'interval')")
    conn.execute("INSERT INTO races (date, name, priority) VALUES (?, 'Club champs', 'A')",
                 ((today + timedelta(days=20)).isoformat(),))
    conn.execute("INSERT INTO day_notes (date, end_date, kind, text) VALUES (?, ?, 'illness', 'cold')",
                 ((today - timedelta(days=12)).isoformat(), (today - timedelta(days=10)).isoformat()))
    conn.commit()
    apply_auto_tags(conn)
    conn.close()


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_runs(sample_data, page):
    at = AppTest.from_file(str(page), default_timeout=30).run()
    assert not at.exception, [e.message for e in at.exception]
