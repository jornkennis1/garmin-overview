"""Weekly / monthly report."""

import pandas as pd

import report

from conftest import add_activity

LABELS = {"o_training": "Orienteering training", "interval": "Interval", "easy_run": "Easy run", "other": "Other"}
COLORS = {"o_training": "#eb6834", "interval": "#1baf7a", "easy_run": "#e87ba4", "other": "#8a8984"}


def activities(conn) -> pd.DataFrame:
    """Like app/common.load_activities, without Streamlit."""
    df = pd.read_sql_query("SELECT * FROM v_activities ORDER BY start_time_local", conn)
    df["start"] = pd.to_datetime(df["start_time_local"])
    df["day"] = pd.to_datetime(df["day"])
    df["week_start"] = pd.to_datetime(df["week_start"])
    df["hours"] = df["hours"].fillna(0)
    df["extras"] = df["extra_tags"].fillna("").map(lambda v: [t for t in v.split(",") if t])
    return df


def test_period_bounds_and_shift():
    assert report.period_bounds("week", "2026-11-05") == (pd.Timestamp("2026-11-02"), pd.Timestamp("2026-11-08"))
    assert report.period_bounds("month", "2026-02-14") == (pd.Timestamp("2026-02-01"), pd.Timestamp("2026-02-28"))
    assert report.shift("month", pd.Timestamp("2026-01-01"), -1)[0] == pd.Timestamp("2025-12-01")
    assert report.shift("week", pd.Timestamp("2026-11-02"), -1)[0] == pd.Timestamp("2026-10-26")


def test_period_starts_newest_first():
    starts = report.period_starts("month", "2026-09-20", pd.Timestamp("2026-11-03"))
    assert starts == [pd.Timestamp("2026-11-01"), pd.Timestamp("2026-10-01"), pd.Timestamp("2026-09-01")]


def test_titles():
    assert report.title("week", pd.Timestamp("2026-10-26"), pd.Timestamp("2026-11-01")) == "Week 44, 26 Oct – 01 Nov 2026"
    assert report.title("month", pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31")) == "October 2026"


def test_build_week_report(db):
    add_activity(db, 1, "2026-10-27 18:00:00", name="Forest <b>night</b> O", duration_s=3600, training_load=90,
                 avg_hr=150)
    add_activity(db, 2, "2026-10-29 07:00:00", name="Morning run", duration_s=1800, training_load=30)
    add_activity(db, 3, "2026-10-20 07:00:00", name="Last week", duration_s=1800, training_load=30)
    db.executemany("INSERT INTO activity_tags (activity_id, tag, source) VALUES (?, ?, 'manual')",
                   [(1, "o_training"), (2, "easy_run"), (3, "easy_run")])
    db.execute("INSERT INTO activity_extra_tags (activity_id, tag) VALUES (1, 'interval')")
    db.commit()
    notes = pd.DataFrame({"note_id": [1], "date": pd.to_datetime(["2026-10-31"]),
                          "end_date": pd.to_datetime(["2026-11-01"]), "kind": ["illness"], "text": ["cold"], "days": [2]})
    races = pd.DataFrame(columns=["race_id", "date", "end_date", "name", "discipline", "priority", "goal", "notes", "days"])
    plans = pd.DataFrame({"hours": [2.0], "sessions": [3], "o_sessions": [1], "hard_sessions": [1], "notes": ["easy week"]},
                         index=pd.to_datetime(["2026-10-26"]))
    daily = pd.DataFrame({"date": pd.to_datetime(["2026-10-27"]), "resting_hr": [44.0], "hrv_overnight_avg": [60.0],
                          "sleep_s": [27000.0]})

    doc = report.build("week", pd.Timestamp("2026-10-28"), activities(db), daily, notes, races, plans, LABELS, COLORS)

    assert doc.startswith("<!doctype html>") and doc.endswith("</html>")
    assert "Week 44" in doc
    assert "1.5 h" in doc  # this week's time; last week's activity isn't counted
    assert "Forest &lt;b&gt;night&lt;/b&gt; O" in doc  # names are escaped
    assert "Orienteering training + Interval" in doc
    assert "Illness: cold" in doc
    assert "Plan vs actual" in doc and "easy week" in doc
    assert "<svg" in doc and "<script" not in doc


def test_build_empty_month(db):
    empty = pd.DataFrame(columns=["note_id", "date", "end_date", "kind", "text", "days"])
    add_activity(db, 1, "2026-01-05 18:00:00")
    db.commit()
    doc = report.build("month", pd.Timestamp("2026-03-01"), activities(db), pd.DataFrame(), empty,
                       empty.rename(columns={"note_id": "race_id"}), pd.DataFrame(), LABELS, COLORS)
    assert "No training recorded this month." in doc
