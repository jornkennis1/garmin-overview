"""Suggest a tag for each activity. Manual tags (set in the dashboard) are never touched.

Run `python -m garmin_sync.tagging` to re-apply the rules after editing the settings in settings.toml / config.py.
"""

import re
import sqlite3

import config


def _matcher(words: list[str]) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(w if "\\" in w else re.escape(w) for w in words) + r")\b", re.IGNORECASE)


_RACE = _matcher(config.O_RACE_KEYWORDS)
_O = _matcher(config.O_KEYWORDS)
_INTERVAL = _matcher(config.INTERVAL_KEYWORDS)


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def looks_like_intervals(a: dict) -> bool:
    """Lap pattern of an interval session: many uneven laps alternating fast/slow (not 1 km auto-laps)."""
    if a.get("has_interval_laps"):
        return True
    return (
        _num(a.get("distance_m")) >= config.INTERVAL_MIN_KM * 1000
        and _num(a.get("n_laps")) >= config.INTERVAL_MIN_LAPS
        and _num(a.get("lap_dist_cv")) >= config.INTERVAL_LAP_DIST_CV
        and _num(a.get("lap_alternation")) >= config.INTERVAL_ALTERNATION
        and _num(a.get("lap_fast_slow_gap")) >= config.INTERVAL_FAST_SLOW_GAP
    )


def suggest_tag(a: dict) -> str:
    """`a` holds activity columns plus activity_features columns (missing ones may be None)."""
    name = a.get("name") or ""
    sport = a.get("sport_type") or ""
    is_run = sport in config.RUN_TYPES
    is_race = a.get("event_type") == "race" or bool(_RACE.search(name))
    o_prob = a.get("o_prob")
    is_o = bool(_O.search(name)) or (o_prob is not None and o_prob >= config.O_PROB_THRESHOLD)

    if is_run or _O.search(name):
        if is_race:
            return "o_race"
        if is_o:
            return "o_training"
    if is_run:
        if sport == "track_running" or _INTERVAL.search(name) or looks_like_intervals(a):
            return "interval"
        if _num(a.get("distance_m")) >= config.LONG_RUN_MIN_KM * 1000:
            return "long_run"
        return "easy_run"
    if sport in config.STRENGTH_TYPES:
        return "strength"
    if any(w in sport for w in config.CYCLING_WORDS):
        return "cycling"
    if any(w in sport for w in config.HIKE_WALK_WORDS):
        return "hiking_walking"
    return "other"


def apply_auto_tags(conn: sqlite3.Connection) -> int:
    """(Re)compute auto tags for all activities without a manual tag. Returns rows changed."""
    rows = conn.execute(
        """SELECT a.activity_id, a.sport_type, a.event_type, a.name, a.duration_s, a.distance_m,
                  f.n_laps, f.lap_dist_cv, f.lap_alternation, f.lap_fast_slow_gap, f.has_interval_laps, f.o_prob,
                  t.tag
           FROM activities a
           LEFT JOIN activity_features f USING (activity_id)
           LEFT JOIN activity_tags t USING (activity_id)
           WHERE t.source IS NULL OR t.source = 'auto'"""
    ).fetchall()
    changed = 0
    for r in rows:
        tag = suggest_tag(dict(r))
        if tag != r["tag"]:
            conn.execute(
                """INSERT INTO activity_tags (activity_id, tag, source) VALUES (?, ?, 'auto')
                   ON CONFLICT (activity_id) DO UPDATE SET tag = excluded.tag, updated_at = datetime('now')""",
                (r["activity_id"], tag),
            )
            changed += 1
    conn.commit()
    return changed


def set_manual_tag(conn: sqlite3.Connection, activity_id: int, tag: str) -> None:
    if tag not in config.TAGS:
        raise ValueError(f"unknown tag {tag!r}")
    conn.execute(
        """INSERT INTO activity_tags (activity_id, tag, source) VALUES (?, ?, 'manual')
           ON CONFLICT (activity_id) DO UPDATE SET tag = excluded.tag, source = 'manual',
           updated_at = datetime('now')""",
        (activity_id, tag),
    )
    conn.commit()


def reset_to_auto(conn: sqlite3.Connection, activity_id: int) -> None:
    """Drop a manual tag so the auto rules apply again."""
    conn.execute("DELETE FROM activity_tags WHERE activity_id = ? AND source = 'manual'", (activity_id,))
    apply_auto_tags(conn)


if __name__ == "__main__":
    from db.database import connect

    c = connect()
    print(f"{apply_auto_tags(c)} auto tags updated.")
    for row in c.execute("SELECT tag, source, count(*) n FROM activity_tags GROUP BY 1, 2 ORDER BY 3 DESC"):
        print(f"  {config.TAGS[row['tag']]:<24} {row['source']:<7} {row['n']}")
