"""Races, weekly plans, fitness projection to race day, taper suggestion and season comparison."""

import math

import pandas as pd

import config
from db.database import connect
from insights import Insight

DISCIPLINES = ["sprint", "middle", "long", "relay", "night", "ultralong", "other"]
PRIORITIES = {"A": "A · main goal", "B": "B · important", "C": "C · training race"}
# Share of normal weekly volume in the weeks before a race (keys: weeks before the race week; 0 = race week).
# Volume goes down, intensity stays: that keeps fitness while fatigue clears.
TAPER = {"A": {2: 0.9, 1: 0.75, 0: 0.55}, "B": {0: 0.8}, "C": {}}


def monday(d) -> pd.Timestamp:
    d = pd.Timestamp(d).normalize()
    return d - pd.Timedelta(days=d.weekday())


# ---------------------------------------------------------------- storage

def load_races() -> pd.DataFrame:
    """All races; `end_date` is the last day (= `date` for one-day races), `days` the number of race days."""
    conn = connect()
    try:
        df = pd.read_sql_query("SELECT race_id, date, end_date, name, discipline, priority, goal, notes "
                               "FROM races ORDER BY date", conn)
    finally:
        conn.close()
    df["date"] = pd.to_datetime(df["date"])
    df["end_date"] = pd.to_datetime(df["end_date"]).where(lambda s: s > df["date"], df["date"])
    df["days"] = (df["end_date"] - df["date"]).dt.days + 1
    return df


def race_days(races: pd.DataFrame) -> pd.DataFrame:
    """One row per race day: race columns plus `day` and `day_no` (1-based)."""
    rows = []
    for _, r in races.iterrows():
        for n, d in enumerate(pd.date_range(r["date"], r["end_date"], freq="D"), start=1):
            rows.append({**r.to_dict(), "day": d, "day_no": n})
    return pd.DataFrame(rows, columns=[*races.columns, "day", "day_no"])


def fmt_dates(r) -> str:
    """'Sat 14 Nov' or 'Sat 14 – Sun 15 Nov' (with the month on both sides when it changes)."""
    a, b = r["date"], r["end_date"]
    if b <= a:
        return f"{a:%a %d %b}"
    return f"{a:%a %d} – {b:%a %d %b}" if a.month == b.month else f"{a:%a %d %b} – {b:%a %d %b}"


def race_when(r, today: pd.Timestamp) -> str:
    if r["date"] > today:
        return weeks_to(r["date"], today)
    if r["end_date"] >= today:
        return f"ongoing · day {(today - r['date']).days + 1} of {r['days']}" if r["days"] > 1 else "today"
    return "done"


def save_races(edited: pd.DataFrame, original: pd.DataFrame) -> int:
    """Write the race editor back: insert new rows, update changed ones, delete removed ones."""
    conn = connect()
    n = 0
    try:
        keep = set(edited["race_id"].dropna().astype(int))
        for rid in set(original["race_id"].astype(int)) - keep:
            conn.execute("DELETE FROM races WHERE race_id = ?", (rid,))
            n += 1
        for _, r in edited.iterrows():
            if pd.isna(r["date"]) or not str(r["name"] or "").strip():
                continue
            start = pd.Timestamp(r["date"])
            end = pd.Timestamp(r["end_date"]) if pd.notna(r.get("end_date")) else None
            end = end.strftime("%Y-%m-%d") if end is not None and end > start else None  # one day: no end date
            text = lambda v: v if isinstance(v, str) and v.strip() else None  # noqa: E731
            row = (start.strftime("%Y-%m-%d"), end, str(r["name"]).strip(), text(r["discipline"]),
                   r["priority"] if r["priority"] in PRIORITIES else "B", text(r["goal"]), text(r["notes"]))
            if pd.isna(r["race_id"]):
                conn.execute("INSERT INTO races (date, end_date, name, discipline, priority, goal, notes) "
                             "VALUES (?,?,?,?,?,?,?)", row)
            else:
                conn.execute("""UPDATE races SET date=?, end_date=?, name=?, discipline=?, priority=?, goal=?, notes=?,
                                updated_at=datetime('now') WHERE race_id=?""", (*row, int(r["race_id"])))
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def load_plans() -> pd.DataFrame:
    conn = connect()
    try:
        df = pd.read_sql_query("SELECT * FROM week_plans", conn)
    finally:
        conn.close()
    df["week_start"] = pd.to_datetime(df["week_start"])
    return df.set_index("week_start")


PLAN_COLS = ["hours", "sessions", "o_sessions", "hard_sessions", "notes"]


def save_plans(rows: pd.DataFrame) -> None:
    """rows: index week_start, PLAN_COLS. Weeks with nothing filled in are removed."""
    conn = connect()
    try:
        for week, r in rows.iterrows():
            vals = [None if pd.isna(r[c]) or r[c] == "" else r[c] for c in PLAN_COLS]
            key = pd.Timestamp(week).strftime("%Y-%m-%d")
            if all(v is None for v in vals):
                conn.execute("DELETE FROM week_plans WHERE week_start = ?", (key,))
                continue
            vals = [float(vals[0]) if vals[0] is not None else None,
                    *[int(v) if v is not None else None for v in vals[1:4]], vals[4]]
            conn.execute(
                """INSERT INTO week_plans (week_start, hours, sessions, o_sessions, hard_sessions, notes)
                   VALUES (?,?,?,?,?,?) ON CONFLICT (week_start) DO UPDATE SET hours=excluded.hours,
                   sessions=excluded.sessions, o_sessions=excluded.o_sessions, hard_sessions=excluded.hard_sessions,
                   notes=excluded.notes, updated_at=datetime('now')""", (key, *vals))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- actuals

def is_hard(acts: pd.DataFrame) -> pd.Series:
    return acts["tag"].isin(["interval", "o_race"]) | (acts["hard_s"].fillna(0) >= 600)


def weekly_actuals(acts: pd.DataFrame) -> pd.DataFrame:
    a = acts.assign(o=acts["tag"].isin(["o_race", "o_training"]), hard=is_hard(acts))
    return a.groupby("week_start").agg(actual_hours=("hours", "sum"), actual_sessions=("activity_id", "count"),
                                       actual_o=("o", "sum"), actual_hard=("hard", "sum"))


def usual_week_hours(acts: pd.DataFrame, today: pd.Timestamp) -> float:
    """Average hours of the last 4 full weeks: 'keep training like now'."""
    this = monday(today)
    w = acts[(acts["week_start"] >= this - pd.Timedelta(weeks=4)) & (acts["week_start"] < this)]
    return float(w["hours"].sum() / 4)


def taper_plan(race: pd.Series, usual_hours: float) -> dict[pd.Timestamp, float]:
    """Suggested hours per week before a race, as a share of your usual week."""
    rw = monday(race["date"])
    return {rw - pd.Timedelta(weeks=k): round(usual_hours * f, 1) for k, f in TAPER.get(race["priority"], {}).items()}


# ---------------------------------------------------------------- projection

def load_per_hour(acts: pd.DataFrame, today: pd.Timestamp) -> float:
    recent = acts[acts["day"] >= today - pd.Timedelta(days=56)]
    for df in (recent, acts):
        h = df["hours"].sum()
        if h > 2:
            return float(df["load"].fillna(0).sum() / h)
    return 60.0


def project(acts: pd.DataFrame, today: pd.Timestamp, until: pd.Timestamp, week_hours: dict, default_hours: float,
            race_days: dict | None = None) -> pd.DataFrame:
    """Fitness (CTL), fatigue (ATL) and form (TSB) up to `until`, continuing with planned weekly hours.

    week_hours: {monday: hours} for weeks with a plan; other weeks use default_hours. Planned load is spread
    evenly over the days left in each week (the current week counts what's already done). race_days adds an
    expected race load on those days.
    """
    lph = load_per_hour(acts, today)
    hist = acts.groupby("day")["load"].sum()
    start = hist.index.min() if len(hist) else today
    days = pd.date_range(start, until, freq="D")
    load = hist.reindex(days, fill_value=0.0).astype(float)
    future = days[days > today]
    for wk in sorted({monday(d) for d in future}):
        planned = week_hours.get(wk, default_hours) * lph
        done = hist[(hist.index >= wk) & (hist.index <= today)].sum() if wk <= today else 0.0
        left = [d for d in future if monday(d) == wk]
        if left:
            load[left] = max(0.0, planned - done) / len(left)
    for d, extra in (race_days or {}).items():
        if d in load.index and d > today:
            load[d] += extra
    atl = load.ewm(alpha=1 / 7, adjust=False).mean()
    ctl = load.ewm(alpha=1 / 42, adjust=False).mean()
    return pd.DataFrame({"load": load, "atl": atl, "ctl": ctl, "tsb": ctl - atl, "projected": days > today})


def race_load(acts: pd.DataFrame) -> float:
    races = acts.loc[acts["tag"] == "o_race", "load"].dropna()
    return float(races.median()) if len(races) >= 2 else 1.2 * load_per_hour(acts, acts["day"].max())


def fmt_form(tsb: float) -> str:
    return f"{int(round(tsb)) or 0:+d}"  # no "-0"


def form_verdict(tsb: float, ctl: float) -> Insight:
    """Form the morning of the race, relative to fitness (so it works for any training volume)."""
    r = tsb / ctl if ctl else 0
    if r < -0.10:
        return Insight("warning", f"Form {fmt_form(tsb)}: you'd start tired",
                       "Fatigue is still well above fitness on race day. Cut volume in the last 10 days "
                       "(keep a few short, fast sessions) to arrive fresh.")
    if r < 0.05:
        return Insight("info", f"Form {fmt_form(tsb)}: fairly fresh",
                       "Fine for a B or C race. For an A race a little more taper usually helps.")
    if r <= 0.30:
        return Insight("good", f"Form {fmt_form(tsb)}: fresh",
                       "Fatigue has cleared while fitness is kept: a good place to be on race day.")
    return Insight("info", f"Form {fmt_form(tsb)}: very fresh",
                   "You'd be well rested, but a long taper also costs some fitness. Shorten it a bit if this "
                   "is your main race.")


# ---------------------------------------------------------------- seasons

def season_start(d: pd.Timestamp) -> pd.Timestamp:
    m = config.SEASON_START_MONTH
    year = d.year if d.month >= m else d.year - 1
    return pd.Timestamp(year=year, month=m, day=1)


def season_label(start: pd.Timestamp) -> str:
    return str(start.year) if start.month == 1 else f"{start.year}/{str(start.year + 1)[2:]}"


SEASON_METRICS = {
    "Hours": ("hours", "h"),
    "Orienteering hours": ("o_hours", "h"),
    "Training load": ("load", ""),
    "Sessions": ("sessions", ""),
}


def season_frame(acts: pd.DataFrame) -> pd.DataFrame:
    a = acts.copy()
    a["season"] = a["day"].map(season_start)
    a["day_of_season"] = (a["day"] - a["season"]).dt.days
    a["o_hours"] = a["hours"].where(a["tag"].isin(["o_race", "o_training"]), 0.0)
    a["sessions"] = 1
    a["load"] = a["load"].fillna(0)
    return a


def cumulative(a: pd.DataFrame, col: str, season: pd.Timestamp, until_day: int | None = None) -> pd.Series:
    s = a[a["season"] == season].groupby("day_of_season")[col].sum()
    end = until_day if until_day is not None else (season + pd.DateOffset(years=1) - season).days - 1
    return s.reindex(range(end + 1), fill_value=0).cumsum()


def season_table(a: pd.DataFrame, today: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for season, g in a.groupby("season"):
        end = min(today, season + pd.DateOffset(years=1) - pd.Timedelta(days=1))
        weeks = max(1, ((end - season).days + 1) / 7)
        z = g[["easy_s", "moderate_s", "hard_s"]].sum()
        rows.append({
            "Season": season_label(season),
            "Hours": round(g["hours"].sum(), 1),
            "Sessions": len(g),
            "Orienteering h": round(g["o_hours"].sum(), 1),
            "Races": int((g["tag"] == "o_race").sum()),
            "Avg h/week": round(g["hours"].sum() / weeks, 1),
            "Easy %": round(100 * z["easy_s"] / z.sum()) if z.sum() else None,
            "Climb (m)": int(g["elev_gain_m"].fillna(0).sum()),
        })
    return pd.DataFrame(rows).iloc[::-1]


def season_insight(a: pd.DataFrame, today: pd.Timestamp, col: str, label: str, unit: str) -> Insight | None:
    cur = season_start(today)
    prev = cur - pd.DateOffset(years=1)
    day = (today - cur).days
    if day < 14 or a[a["season"] == prev].empty:
        return None
    now = cumulative(a, col, cur, day).iloc[-1]
    then = cumulative(a, col, prev, day).iloc[-1]
    if then <= 0:
        return None
    ch = now / then - 1
    fmt = (lambda v: f"{v:.0f} {unit}".strip()) if unit else (lambda v: f"{v:.0f}")
    if abs(ch) < 0.05:
        return Insight("info", f"Same {label.lower()} as last season",
                       f"{fmt(now)} so far, vs {fmt(then)} at this point last season.")
    return Insight("info", f"{abs(ch):.0%} {'ahead of' if ch > 0 else 'behind'} last season",
                   f"{label}: {fmt(now)} so far this season, vs {fmt(then)} at the same point last season.")


def weeks_to(d: pd.Timestamp, today: pd.Timestamp) -> str:
    n = (pd.Timestamp(d) - today).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    return f"in {n} days" if n < 21 else f"in {math.floor(n / 7)} weeks"
