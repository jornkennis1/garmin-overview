"""Taper, projection and race-date helpers on the Plan page."""

import pandas as pd
import pytest

import planning


def acts_frame(days: list[str], hours: float = 1.0, load: float = 60.0) -> pd.DataFrame:
    d = pd.to_datetime(days)
    return pd.DataFrame({"day": d, "week_start": [planning.monday(x) for x in d], "hours": hours,
                         "load": load, "activity_id": range(len(d)), "tag": "easy_run", "hard_s": 0})


def test_monday():
    assert planning.monday("2026-11-05") == pd.Timestamp("2026-11-02")  # Thursday -> Monday
    assert planning.monday("2026-11-02") == pd.Timestamp("2026-11-02")


def test_taper_plan_for_an_a_race():
    race = pd.Series({"date": pd.Timestamp("2026-11-21"), "priority": "A"})  # Saturday
    plan = planning.taper_plan(race, usual_hours=10)
    race_week = pd.Timestamp("2026-11-16")
    assert plan == {race_week - pd.Timedelta(weeks=2): 9.0, race_week - pd.Timedelta(weeks=1): 7.5, race_week: 5.5}
    assert planning.taper_plan(pd.Series({"date": race_week, "priority": "C"}), 10) == {}


def test_usual_week_hours_uses_the_last_four_full_weeks():
    today = pd.Timestamp("2026-11-04")
    days = pd.date_range("2026-10-05", "2026-11-03").strftime("%Y-%m-%d").tolist()  # 4 full weeks + this week
    assert planning.usual_week_hours(acts_frame(days), today) == 7.0


def test_projection_spreads_planned_load_over_the_remaining_days():
    today = pd.Timestamp("2026-11-04")  # Wednesday
    acts = acts_frame(["2026-11-02", "2026-11-03"], hours=1.0, load=60.0)  # 2 h done this week, 60 load/h
    p = planning.project(acts, today, until=pd.Timestamp("2026-11-15"), week_hours={}, default_hours=5)
    this_week = p.loc["2026-11-05":"2026-11-08", "load"]
    assert this_week.sum() == pytest.approx(3 * 60)  # 5 planned - 2 done = 3 h, spread over Thu..Sun
    assert p.loc["2026-11-09":"2026-11-15", "load"].sum() == pytest.approx(5 * 60)
    assert not p.loc[:today, "projected"].any() and p.loc["2026-11-05":, "projected"].all()


def test_fmt_dates_and_race_when():
    one = {"date": pd.Timestamp("2026-11-14"), "end_date": pd.Timestamp("2026-11-14"), "days": 1}
    two = {"date": pd.Timestamp("2026-10-31"), "end_date": pd.Timestamp("2026-11-01"), "days": 2}
    assert planning.fmt_dates(one) == "Sat 14 Nov"
    assert planning.fmt_dates(two) == "Sat 31 Oct – Sun 01 Nov"
    assert planning.race_when(two, pd.Timestamp("2026-11-01")) == "ongoing · day 2 of 2"
    assert planning.race_when(one, pd.Timestamp("2026-11-14")) == "today"
