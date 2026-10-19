"""Rule-based insights: short sentences that say what the charts mean, with the reason behind them.

Every rule compares you with your own recent normal (not population norms) and stays quiet when the
data is missing or too old. Thresholds are deliberately conservative: a warning should be rare.
"""

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from garmin_sync.metrics import load_curves

ICONS = {"warning": ":material/warning:", "info": ":material/lightbulb:", "good": ":material/check_circle:"}


@dataclass
class Insight:
    level: str  # "warning" | "info" | "good"
    title: str
    text: str


def render(items: list[Insight]) -> None:
    for i in items:
        body = f"**{i.title}.** {i.text}"
        {"warning": st.warning, "info": st.info, "good": st.success}[i.level](body, icon=ICONS[i.level])


def _daily(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.set_index("date").sort_index()
    d = d[~d.index.duplicated(keep="last")]
    d["sleep_h"] = d["sleep_s"] / 3600
    return d


def _recent(s: pd.Series, today: pd.Timestamp, n: int, within_days: int) -> pd.Series:
    """The last n values, but only if the newest is at most within_days old."""
    s = s.dropna()
    if s.empty or (today - s.index[-1]).days > within_days:
        return pd.Series(dtype=float)
    return s.iloc[-n:]


def _baseline(s: pd.Series, today: pd.Timestamp, start_days: int = 33, end_days: int = 4):
    window = s[(s.index >= today - pd.Timedelta(days=start_days)) & (s.index < today - pd.Timedelta(days=end_days))]
    window = window.dropna()
    return window.median() if len(window) >= 10 else None


# ---------------------------------------------------------------- Today: how am I doing right now?

def readiness(acts: pd.DataFrame, daily: pd.DataFrame, today: pd.Timestamp) -> list[Insight]:
    out: list[Insight] = []
    checked = []

    # Load ramp: 7-day (fatigue) vs 42-day (fitness) average daily load.
    curves = load_curves(acts.groupby("day")["load"].sum()) if not acts.empty else pd.DataFrame()
    if not curves.empty and curves["ctl"].iloc[-1] >= 10:
        atl, ctl = curves["atl"].iloc[-1], curves["ctl"].iloc[-1]
        ratio = atl / ctl
        checked.append("load")
        if ratio > 1.5:
            out.append(Insight("warning", "Load is ramping up fast",
                               f"Your last-7-days load is {ratio:.1f}× your 6-week average. Jumps this big are when "
                               "fatigue and niggles build up; plan easy days or a rest day soon."))
        elif ratio > 1.3:
            out.append(Insight("info", "Load is building",
                               f"Your last-7-days load is {ratio:.1f}× your 6-week average. Fine for a block of "
                               "harder training, as long as you recover well."))
        elif ratio < 0.7 and ctl >= 20:
            out.append(Insight("info", "Light period",
                               f"Your last-7-days load is only {ratio:.0%} of your 6-week average. Good for recovery "
                               "or a taper; if it lasts more than about two weeks, fitness starts to drop."))

    if daily.empty:
        return out
    d = _daily(daily)

    # HRV against Garmin's personal balanced range.
    hrv = _recent(d["hrv_overnight_avg"], today, 3, 2)
    low = d["hrv_baseline_low"].dropna()
    if len(hrv) and not low.empty:
        checked.append("HRV")
        below = hrv < low.iloc[-1]
        if len(hrv) == 3 and below.all():
            out.append(Insight("warning", "HRV below your normal range 3 nights in a row",
                               f"Last night {hrv.iloc[-1]:.0f} ms, your range starts at {low.iloc[-1]:.0f} ms. "
                               "Your body is under stress (training, illness, poor sleep or life). Keep it easy until "
                               "it's back in range."))
        elif below.iloc[-1]:
            out.append(Insight("info", "HRV dipped last night",
                               f"{hrv.iloc[-1]:.0f} ms, just under your normal range (from {low.iloc[-1]:.0f} ms). "
                               "One low night is common after a hard day; watch whether it recovers."))

    # Resting HR against your own last month.
    rhr = _recent(d["resting_hr"], today, 3, 2)
    base = _baseline(d["resting_hr"], today)
    rhr_up = 0.0
    if len(rhr) and base is not None:
        checked.append("resting HR")
        diff = rhr_up = rhr.mean() - base
        if diff >= 5:
            out.append(Insight("warning", "Resting HR is up",
                               f"{rhr.mean():.0f} bpm over the last days vs your normal {base:.0f} bpm (+{diff:.0f}). "
                               "A rise of 5+ bpm often means fatigue, a coming cold, heat or stress."))
        elif diff >= 3:
            out.append(Insight("info", "Resting HR slightly up",
                               f"{rhr.mean():.0f} bpm vs your normal {base:.0f} bpm (+{diff:.0f})."))

    # Sleep.
    sleep3 = _recent(d["sleep_h"], today, 3, 2)
    sleep7 = _recent(d["sleep_h"], today, 7, 2)
    if len(sleep3):
        checked.append("sleep")
        if len(sleep3) == 3 and sleep3.mean() < 6.5:
            out.append(Insight("warning", "Short on sleep",
                               f"{sleep3.mean():.1f} h per night over the last 3 nights. Sleep is when you adapt to "
                               "training; consider moving a hard session."))
        elif len(sleep7) >= 5 and sleep7.mean() < 7:
            out.append(Insight("info", "Sleep a bit short this week",
                               f"{sleep7.mean():.1f} h per night on average over the last week."))

    # Respiration: an early illness signal.
    resp = _recent(d["respiration_avg"], today, 2, 2)
    rbase = _baseline(d["respiration_avg"], today)
    if len(resp) == 2 and rbase is not None and (resp.mean() - rbase >= 1.5 or
                                                  (resp.mean() - rbase >= 1.0 and rhr_up >= 3)):
        out.append(Insight("info", "Breathing rate is up",
                           f"{resp.mean():.1f} vs your normal {rbase:.1f} breaths/min. Together with a higher "
                           "resting HR this can be an early sign of illness."))

    # Rest days / long gaps (only meaningful if you train regularly).
    if not acts.empty and not curves.empty and curves["ctl"].iloc[-1] >= 15:
        days_with = set(acts.loc[acts["day"] >= today - pd.Timedelta(days=9), "day"])
        if len(days_with) >= 10:
            out.append(Insight("info", "No rest day in 10 days",
                               "Easy sessions help, but a full day off now and then lets body and mind recover."))
        gap = (today - acts["day"].max()).days
        if gap >= 4:
            out.append(Insight("info", f"{gap} days without training",
                               "Fine if planned (taper, illness, holiday). Fitness only starts to drop noticeably "
                               "after about two weeks."))

    if checked and not any(i.level == "warning" for i in out):
        out.insert(0, Insight("good", "No warning signs",
                              f"Checked {', '.join(checked)}: nothing unusual compared with your own normal."))
    return out


# ---------------------------------------------------------------- Overview: what happened this week?

def week_summary(acts: pd.DataFrame, today: pd.Timestamp) -> str:
    """A few sentences about this week so far and last week, compared with the 4 weeks before."""
    monday = today - pd.Timedelta(days=today.weekday())
    week = acts[acts["day"] >= monday]
    lines = []
    if week.empty:
        lines.append(f"**This week** (since {monday:%a %d %b}): no sessions yet.")
    else:
        zones = week[["easy_s", "moderate_s", "hard_s"]].sum()
        easy = f" {100 * zones['easy_s'] / zones.sum():.0f}% of heart-rate time was easy." if zones.sum() else ""
        top = week.sort_values("load", ascending=False, na_position="last").iloc[0]
        days = "today" if today == monday else f"Mon–{today:%a}"
        o_n = int(week["tag"].isin(["o_race", "o_training"]).sum())
        o_txt = f" {o_n} orienteering session{'s' if o_n != 1 else ''}." if o_n else ""
        lines.append(
            f"**This week so far** ({days}): {week['hours'].sum():.1f} h in {len(week)} session"
            f"{'s' if len(week) != 1 else ''}, load {week['load'].sum():.0f}.{easy}{o_txt} "
            f"Biggest session: *{top['name'] or 'unnamed'}* on {top['start']:%a} "
            f"({_dur(top['duration_s'])}, load {0 if pd.isna(top['load']) else top['load']:.0f})."
        )

    last_mon = monday - pd.Timedelta(days=7)
    weeks = (acts[(acts["day"] >= monday - pd.Timedelta(days=35)) & (acts["day"] < monday)]
             .groupby("week_start")["hours"].sum()
             .reindex(pd.date_range(monday - pd.Timedelta(days=35), last_mon, freq="7D"), fill_value=0))
    last_h, avg4 = weeks.iloc[-1], weeks.iloc[:-1].mean()
    lw = acts[(acts["day"] >= last_mon) & (acts["day"] < monday)]
    if avg4 > 0 or last_h > 0:
        change = f" ({(last_h / avg4 - 1):+.0%} vs the 4 weeks before, {avg4:.1f} h on average)" if avg4 > 0 else ""
        zones = lw[["easy_s", "moderate_s", "hard_s"]].sum()
        easy = f" Easy share {100 * zones['easy_s'] / zones.sum():.0f}%." if zones.sum() else ""
        lines.append(f"**Last week**: {last_h:.1f} h in {len(lw)} sessions{change}.{easy}")
        if avg4 > 0 and last_h > 1.4 * avg4:
            lines.append("That was a big step up in volume; the week after a jump like that is a good moment "
                         "for some extra recovery.")
    return "  \n".join(lines)


def _dur(s) -> str:
    if s is None or pd.isna(s):
        return "–"
    m = int(round(s / 60))
    return f"{m // 60}:{m % 60:02d}"


# ---------------------------------------------------------------- Intensity

def intensity(period: pd.DataFrame, previous: pd.DataFrame) -> list[Insight]:
    out = []
    tot = period[["easy_s", "moderate_s", "hard_s"]].sum()
    if tot.sum() < 3600:
        return out
    pct = 100 * tot / tot.sum()
    if pct["moderate_s"] >= 25:
        out.append(Insight("info", "Lots of grey-zone time",
                           f"{pct['moderate_s']:.0f}% of your heart-rate time is in Z3. That zone is tiring but gives "
                           "less specific benefit than truly easy or truly hard work. Try making easy sessions "
                           "easier and hard sessions harder."))
    elif pct["easy_s"] < 70:
        out.append(Insight("info", "High intensity share",
                           f"Only {pct['easy_s']:.0f}% of your heart-rate time is easy. Most endurance athletes do "
                           "about 75–80% easy; orienteering races push this up, so check it over a longer period."))
    if pct["hard_s"] < 3 and tot.sum() > 10 * 3600:
        out.append(Insight("info", "Very little hard work",
                           f"Only {pct['hard_s']:.0f}% in Z4–5. If races are coming up, one quality session a week "
                           "(intervals or a race-pace O training) keeps your top end sharp."))
    ptot = previous[["easy_s", "moderate_s", "hard_s"]].sum()
    if ptot.sum() >= 3600:
        pprev = 100 * ptot / ptot.sum()
        delta = pct["easy_s"] - pprev["easy_s"]
        if abs(delta) >= 8:
            out.append(Insight("info", f"Easy share {'up' if delta > 0 else 'down'} {abs(delta):.0f} points",
                               f"{pct['easy_s']:.0f}% easy now vs {pprev['easy_s']:.0f}% in the period before."))
    return out


# ---------------------------------------------------------------- Recovery: month-on-month trends

def recovery_trends(daily: pd.DataFrame, today: pd.Timestamp) -> list[Insight]:
    if daily.empty:
        return []
    d = _daily(daily)
    now = d[d.index > today - pd.Timedelta(days=28)]
    before = d[(d.index <= today - pd.Timedelta(days=28)) & (d.index > today - pd.Timedelta(days=56))]
    out = []

    def pair(col):
        a, b = now[col].dropna(), before[col].dropna()
        return (a.median(), b.median()) if len(a) >= 10 and len(b) >= 10 else (None, None)

    a, b = pair("resting_hr")
    if a is not None and abs(a - b) >= 2:
        out.append(Insight("good" if a < b else "info", f"Resting HR {'down' if a < b else 'up'} {abs(a - b):.0f} bpm",
                           f"{a:.0f} bpm over the last 4 weeks vs {b:.0f} the 4 weeks before. "
                           + ("Usually a sign of better aerobic fitness or recovery." if a < b else
                              "Can come from accumulated fatigue, heat, stress or a cold.")))
    a, b = pair("hrv_overnight_avg")
    if a is not None and b and abs(a / b - 1) >= 0.07:
        out.append(Insight("good" if a > b else "info", f"HRV {'up' if a > b else 'down'} {abs(a / b - 1):.0%}",
                           f"{a:.0f} ms over the last 4 weeks vs {b:.0f} ms before. "
                           + ("Your body is coping well with the training." if a > b else
                              "A lasting drop points to more stress than you recover from.")))
    a, b = pair("sleep_h")
    if a is not None and abs(a - b) >= 1 / 3:
        out.append(Insight("good" if a > b else "info", f"Sleeping {abs(a - b) * 60:.0f} min {'more' if a > b else 'less'}",
                           f"{a:.1f} h per night over the last 4 weeks vs {b:.1f} h before."))
    if not out and len(now) >= 10:
        out.append(Insight("good", "Stable", "Resting HR, HRV and sleep are about the same as the month before."))
    return out


# ---------------------------------------------------------------- O-analysis

def orienteering(o: pd.DataFrame, acts: pd.DataFrame, today: pd.Timestamp) -> list[Insight]:
    out = []
    if o.empty:
        return out
    o = o.sort_values("start")
    last = o.iloc[-1]
    gap = (today - last["day"]).days
    if gap >= 14:
        out.append(Insight("info", f"{gap} days since your last orienteering session",
                           "Navigation is a skill that fades without practice; even a short map walk or "
                           "map-memory exercise keeps it sharp."))
    since8 = today - pd.Timedelta(days=56)
    recent_all = acts[acts["day"] >= since8]["hours"].sum()
    recent_o = o[o["day"] >= since8]["hours"].sum()
    if recent_all > 0 and recent_o > 0:
        out.append(Insight("info", f"Orienteering is {recent_o / recent_all:.0%} of your training",
                           f"{recent_o:.1f} of {recent_all:.1f} h over the last 8 weeks."))
    stops = o.dropna(subset=["stop_frac"])
    if len(stops) >= 16:
        a, b = stops["stop_frac"].iloc[-8:].median(), stops["stop_frac"].iloc[-16:-8].median()
        if b and abs(a - b) >= 0.02:
            out.append(Insight("good" if a < b else "info",
                               f"{'Less' if a < b else 'More'} time stopped",
                               f"Your last 8 O sessions: {a:.0%} of the time below 1 m/s, vs {b:.0%} in the 8 before. "
                               + ("Fewer stops usually means smoother navigation (terrain and course type matter too)."
                                  if a < b else "More map reading or hesitation, or simply harder terrain or courses.")))
    races = o[(o["tag"] == "o_race") & (o["start"].dt.year == today.year)]
    if len(races):
        nxt = "" if len(races) == 1 else f", last one on {races['start'].iloc[-1]:%d %b}"
        hr = races["avg_hr"].dropna()
        hr_txt = f" Average race HR {hr.mean():.0f} bpm." if len(hr) else ""
        out.append(Insight("info", f"{len(races)} race{'s' if len(races) != 1 else ''} this season",
                           f"First on {races['start'].iloc[0]:%d %b}{nxt}.{hr_txt}"))
    return out


# ---------------------------------------------------------------- records & long-term trends

RUN_TAGS = ["easy_run", "long_run"]


def records(acts: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    rows = []

    def best(df, col, what, fmt, largest=True):
        df = df.dropna(subset=[col])
        if df.empty:
            return
        r = df.loc[df[col].idxmax() if largest else df[col].idxmin()]
        rows.append({"Record": what, "Value": fmt(r[col]), "Date": r["start"].strftime("%d %b %Y"),
                     "Activity": r["name"] or "", "Open": f"/Activity?id={int(r['activity_id'])}"})

    best(acts, "duration_s", "Longest session", _dur)
    best(acts[acts["sport_type"].str.contains("run", na=False)], "distance_m", "Longest run",
         lambda v: f"{v / 1000:.1f} km")
    best(acts, "elev_gain_m", "Most climb in one session", lambda v: f"{v:.0f} m")
    best(acts, "load", "Highest training load", lambda v: f"{v:.0f}")
    best(acts[acts["tag"].isin(["o_race", "o_training"])], "duration_s", "Longest orienteering session", _dur)

    weeks = acts.groupby("week_start")["hours"].sum()
    if len(weeks):
        rows.append({"Record": "Biggest week", "Value": f"{weeks.max():.1f} h",
                     "Date": f"week of {weeks.idxmax():%d %b %Y}", "Activity": "", "Open": None})
    if not daily.empty:
        d = daily.dropna(subset=["vo2max"]) if "vo2max" in daily else pd.DataFrame()
        if not d.empty:
            r = d.loc[d["vo2max"].idxmax()]
            rows.append({"Record": "Highest VO2 max", "Value": f"{r['vo2max']:.0f}", "Date": f"{r['date']:%d %b %Y}",
                         "Activity": "", "Open": None})
        d = daily.dropna(subset=["resting_hr"])
        if not d.empty:
            r = d.loc[d["resting_hr"].idxmin()]
            rows.append({"Record": "Lowest resting HR", "Value": f"{r['resting_hr']:.0f} bpm",
                         "Date": f"{r['date']:%d %b %Y}", "Activity": "", "Open": None})
    return pd.DataFrame(rows)


def efficiency(acts: pd.DataFrame) -> pd.DataFrame:
    """Monthly 'metres per heartbeat' on easy and long runs: speed (m/min) / average HR (beats/min).

    Higher = more distance for the same effort, i.e. better aerobic fitness. Terrain and heat add noise,
    so only months with at least 3 runs of 20+ minutes count.
    """
    runs = acts[acts["tag"].isin(RUN_TAGS) & (acts["moving_s"] >= 1200) & (acts["avg_hr"] > 80)
                & (acts["distance_m"] > 0)].copy()
    if runs.empty:
        return pd.DataFrame(columns=["month", "m_per_beat", "runs"])
    runs["m_per_beat"] = (runs["distance_m"] / (runs["moving_s"] / 60)) / runs["avg_hr"]
    runs["month"] = runs["start"].dt.to_period("M").dt.to_timestamp()
    m = runs.groupby("month").agg(m_per_beat=("m_per_beat", "median"), runs=("activity_id", "count")).reset_index()
    return m[m["runs"] >= 3]


def trend_insights(eff: pd.DataFrame, daily: pd.DataFrame, today: pd.Timestamp) -> list[Insight]:
    """Last 3 months vs the same 3 months a year earlier (removes the seasonal effect)."""
    out = []
    lo, hi = today - pd.DateOffset(months=3), today
    ylo, yhi = lo - pd.DateOffset(years=1), hi - pd.DateOffset(years=1)

    def window(df, col, date_col):
        a = df[(df[date_col] > lo) & (df[date_col] <= hi)][col].dropna()
        b = df[(df[date_col] > ylo) & (df[date_col] <= yhi)][col].dropna()
        return (a, b) if len(a) and len(b) else (None, None)

    a, b = window(eff, "m_per_beat", "month")
    if a is not None:
        ch = a.mean() / b.mean() - 1
        if abs(ch) >= 0.02:
            out.append(Insight("good" if ch > 0 else "info", f"Aerobic efficiency {ch:+.0%} vs a year ago",
                               f"On easy and long runs you now cover {a.mean():.2f} m per heartbeat, vs "
                               f"{b.mean():.2f} m in the same months last year."))
        else:
            out.append(Insight("info", "Aerobic efficiency stable",
                               f"About {a.mean():.2f} m per heartbeat on easy runs, the same as a year ago."))
    if not daily.empty and "vo2max" in daily:
        a, b = window(daily, "vo2max", "date")
        if a is not None and abs(a.mean() - b.mean()) >= 1:
            up = a.mean() > b.mean()
            out.append(Insight("good" if up else "info", f"VO2 max {'up' if up else 'down'} vs a year ago",
                               f"{a.mean():.0f} now vs {b.mean():.0f} in the same months last year."))
    return out
