"""Injury / illness / holiday notes and how they quiet the Today insights."""

import pandas as pd
import pytest

import insights
import notes as nt
from db.database import connect


@pytest.fixture
def no_notes():
    """The app modules use the default (temporary) database: start each test without notes."""
    conn = connect()
    conn.execute("DELETE FROM day_notes")
    conn.commit()
    conn.close()


def editor_rows(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["note_id", "date", "end_date", "kind", "text"])


def test_save_and_load_notes(no_notes):
    nt.save_notes(editor_rows([
        {"note_id": None, "date": "2026-10-05", "end_date": "2026-10-08", "kind": "illness", "text": " flu "},
        {"note_id": None, "date": "2026-10-20", "end_date": "2026-10-20", "kind": "nonsense", "text": ""},
        {"note_id": None, "date": None, "kind": "injury"},  # empty row from the editor: skipped
    ]), nt.load_notes())
    n = nt.load_notes()
    assert n["kind"].tolist() == ["illness", "other"]  # unknown kind -> other
    assert n["text"].iloc[0] == "flu" and pd.isna(n["text"].iloc[1])
    assert n["days"].tolist() == [4, 1]
    # Deleting a row in the editor deletes the note.
    nt.save_notes(n.iloc[:1].drop(columns="days"), n)
    assert len(nt.load_notes()) == 1


def test_note_days_and_ranges(no_notes):
    nt.save_notes(editor_rows([{"note_id": None, "date": "2026-10-30", "end_date": "2026-11-02",
                                "kind": "holiday", "text": "ski trip"}]), nt.load_notes())
    n = nt.load_notes()
    assert nt.note_days(n)["day"].dt.strftime("%d").tolist() == ["30", "31", "01", "02"]
    assert len(nt.in_range(n, pd.Timestamp("2026-11-01"), pd.Timestamp("2026-11-30"))) == 1
    assert nt.in_range(n, pd.Timestamp("2026-11-03"), pd.Timestamp("2026-11-30")).empty
    assert nt.describe(n.iloc[0]) == "Holiday: ski trip (Fri 30 Oct – Mon 02 Nov)"


def test_current_break_has_a_grace_period(no_notes):
    nt.save_notes(editor_rows([
        {"note_id": None, "date": "2026-10-01", "end_date": "2026-10-05", "kind": "illness", "text": "cold"},
        {"note_id": None, "date": "2026-10-04", "end_date": None, "kind": "other", "text": "new shoes"},
    ]), nt.load_notes())
    n = nt.load_notes()
    assert nt.current_break(n, pd.Timestamp("2026-10-03"))["text"] == "cold"
    assert nt.current_break(n, pd.Timestamp("2026-10-08"))["text"] == "cold"  # ended 3 days ago
    assert nt.current_break(n, pd.Timestamp("2026-10-09")) is None
    assert nt.current_break(n, pd.Timestamp("2026-09-30")) is None


def test_break_pauses_the_no_training_hint():
    today = pd.Timestamp.today().normalize()
    days = pd.date_range(today - pd.Timedelta(days=90), today - pd.Timedelta(days=6), freq="D")
    acts = pd.DataFrame({"day": days, "load": 80.0})
    cols = ["sleep_s", "hrv_overnight_avg", "hrv_baseline_low", "resting_hr", "respiration_avg"]
    daily = pd.DataFrame({"date": days, **{col: float("nan") for col in cols}})
    titles = [i.title for i in insights.readiness(acts, daily, today)]
    assert {"6 days without training", "Light period"} <= set(titles)
    on_break = insights.readiness(acts, daily, today, on_break="Illness: flu")
    assert not {"6 days without training", "Light period"} & {i.title for i in on_break}
    assert on_break[0].title == "Break noted" and "flu" in on_break[0].text
