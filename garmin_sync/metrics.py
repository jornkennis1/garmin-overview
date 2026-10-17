"""Derived metrics: HR reference values, Banister TRIMP and acute/chronic load (ATL/CTL/TSB)."""

import math
import sqlite3

import pandas as pd

import config


def hr_reference(conn: sqlite3.Connection) -> tuple[float | None, float | None]:
    """(HRmax, resting HR) from config overrides, else estimated from the data."""
    # Gym/indoor sessions are excluded: optical HR spikes there are common.
    hr_max = config.HR_MAX or conn.execute(
        """SELECT max(max_hr) FROM activities WHERE max_hr BETWEEN 120 AND 225
           AND sport_type NOT IN ('strength_training', 'indoor_cardio', 'mobility', 'yoga', 'pilates', 'hiit')"""
    ).fetchone()[0]
    hr_rest = config.HR_REST
    if not hr_rest:
        vals = [r[0] for r in conn.execute(
            "SELECT resting_hr FROM daily_metrics WHERE resting_hr > 25 ORDER BY date DESC LIMIT 60")]
        hr_rest = float(pd.Series(vals).median()) if vals else None
    return hr_max, hr_rest


def zone_lower_bounds(conn: sqlite3.Connection, hr_max: float | None) -> list[float] | None:
    """Z1..Z5 lower bounds: config override, else Garmin's most recent zones, else % of HRmax."""
    if config.HR_ZONE_LOWER_BOUNDS:
        return list(config.HR_ZONE_LOWER_BOUNDS)
    row = conn.execute(
        """SELECT z.activity_id FROM activity_hr_zones z JOIN activities a USING (activity_id)
           WHERE z.zone_low_bpm IS NOT NULL GROUP BY z.activity_id HAVING count(*) = 5
           ORDER BY a.start_time_local DESC LIMIT 1"""
    ).fetchone()
    if row:
        return [r[0] for r in conn.execute(
            "SELECT zone_low_bpm FROM activity_hr_zones WHERE activity_id = ? ORDER BY zone", (row[0],))]
    if hr_max:
        return [round(hr_max * p) for p in (0.5, 0.6, 0.7, 0.8, 0.9)]
    return None


def trimp_from_samples(t_s: list[float], hr: list[float], hr_max: float, hr_rest: float) -> float:
    """Banister TRIMP integrated over the HR stream (minutes x HRr x 0.64 e^(k HRr))."""
    total = 0.0
    for i in range(1, len(t_s)):
        dt = t_s[i] - t_s[i - 1]
        h = hr[i]
        if h is None or dt <= 0 or dt > 60:  # skip gaps (pauses) longer than a minute
            continue
        total += (dt / 60) * _trimp_weight(h, hr_max, hr_rest)
    return total


def trimp_from_average(duration_s: float, avg_hr: float, hr_max: float, hr_rest: float) -> float:
    return (duration_s / 60) * _trimp_weight(avg_hr, hr_max, hr_rest)


def _trimp_weight(h: float, hr_max: float, hr_rest: float) -> float:
    hrr = min(max((h - hr_rest) / (hr_max - hr_rest), 0.0), 1.0)
    return hrr * 0.64 * math.exp(config.TRIMP_K * hrr)


def update_trimp(conn: sqlite3.Connection, only_missing: bool = True) -> int:
    """Compute TRIMP for activities (from samples when available)."""
    hr_max, hr_rest = hr_reference(conn)
    if not hr_max or not hr_rest:
        return 0
    sql = "SELECT activity_id, duration_s, moving_s, avg_hr FROM activities"
    if only_missing:
        sql += " WHERE trimp IS NULL"
    n = 0
    for a in conn.execute(sql).fetchall():
        samples = conn.execute(
            "SELECT t_offset_s, hr FROM activity_samples WHERE activity_id = ? AND hr IS NOT NULL ORDER BY t_offset_s",
            (a["activity_id"],),
        ).fetchall()
        if len(samples) > 10:
            value = trimp_from_samples([s[0] for s in samples], [s[1] for s in samples], hr_max, hr_rest)
        elif a["avg_hr"] and (a["moving_s"] or a["duration_s"]):
            value = trimp_from_average(a["moving_s"] or a["duration_s"], a["avg_hr"], hr_max, hr_rest)
        else:
            continue
        conn.execute("UPDATE activities SET trimp = ? WHERE activity_id = ?", (round(value, 1), a["activity_id"]))
        n += 1
    conn.commit()
    return n


def load_curves(daily_load: pd.Series) -> pd.DataFrame:
    """ATL (7-day), CTL (42-day) exponentially weighted load and TSB = CTL - ATL.

    `daily_load` is indexed by date; missing days are treated as rest (0).
    """
    if daily_load.empty:
        return pd.DataFrame(columns=["load", "atl", "ctl", "tsb"])
    idx = pd.date_range(daily_load.index.min(), pd.Timestamp.today().normalize(), freq="D")
    s = daily_load.reindex(idx, fill_value=0.0).astype(float)
    atl = s.ewm(alpha=1 / 7, adjust=False).mean()
    ctl = s.ewm(alpha=1 / 42, adjust=False).mean()
    return pd.DataFrame({"load": s, "atl": atl, "ctl": ctl, "tsb": ctl - atl})


if __name__ == "__main__":
    # Recompute TRIMP for every activity, e.g. after changing HR_MAX / HR_REST in config.py.
    from db.database import connect

    c = connect()
    hr_max, hr_rest = hr_reference(c)
    print(f"HRmax {hr_max}, resting HR {hr_rest}, zones {zone_lower_bounds(c, hr_max)}")
    print(f"TRIMP recomputed for {update_trimp(c, only_missing=False)} activities.")
