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


# ---------------------------------------------------------------- your own tags
# Extra tags you add on the Settings page (table custom_tags). Each can have auto rules: words in the
# activity name and/or Garmin sport types. Their rules are checked before the built-in ones.

def load_custom_tags(conn: sqlite3.Connection) -> list[dict]:
    try:
        rows = conn.execute("SELECT key, label, color_slot, keywords, sport_types FROM custom_tags "
                            "ORDER BY created_at, key").fetchall()
    except sqlite3.OperationalError:  # database from before custom tags (read-only connections can't migrate)
        return []
    out = []
    for r in rows:
        words = [w.strip() for w in (r[3] or "").split(",") if w.strip()]
        sports = {s.strip().lower() for s in (r[4] or "").split(",") if s.strip()}
        out.append({"key": r[0], "label": r[1], "color_slot": r[2] or 0, "keywords": words,
                    "sport_types": sports, "matcher": _matcher(words) if words else None})
    return out


def all_tags(conn: sqlite3.Connection) -> dict[str, str]:
    """Every tag key -> label: built-in tags, your own tags, and "other" last."""
    tags = {k: v for k, v in config.TAGS.items() if k != "other"}
    tags.update({t["key"]: t["label"] for t in load_custom_tags(conn)})
    tags["other"] = config.TAGS["other"]
    return tags


def custom_tag_key(label: str, existing: set[str]) -> str:
    base = "my_" + (re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "tag")
    key, n = base, 2
    while key in existing or key in config.TAGS:
        key, n = f"{base}_{n}", n + 1
    return key


def save_custom_tags(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """Replace your own tags with `rows` (dicts with key (None = new), label, color_slot, keywords, sport_types).

    Activities with a removed tag fall back to the auto rules (also manually tagged ones, since their
    tag no longer exists). Auto tags are re-applied afterwards.
    """
    old = {t["key"] for t in load_custom_tags(conn)}
    keep = set()
    for r in rows:
        label = (r.get("label") or "").strip()
        if not label:
            continue
        key = r.get("key") or custom_tag_key(label, old | keep)
        keep.add(key)
        conn.execute(
            """INSERT INTO custom_tags (key, label, color_slot, keywords, sport_types) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (key) DO UPDATE SET label = excluded.label, color_slot = excluded.color_slot,
               keywords = excluded.keywords, sport_types = excluded.sport_types""",
            (key, label, int(r.get("color_slot") or 0), (r.get("keywords") or "").strip() or None,
             (r.get("sport_types") or "").strip() or None),
        )
    for key in old - keep:
        conn.execute("DELETE FROM activity_tags WHERE tag = ?", (key,))
        conn.execute("DELETE FROM activity_extra_tags WHERE tag = ?", (key,))
        conn.execute("DELETE FROM custom_tags WHERE key = ?", (key,))
    conn.commit()
    apply_auto_tags(conn)


def has_tag(acts, tags):
    """For a DataFrame of v_activities rows: True where the main tag or an extra tag is in `tags`.

    Uses the `extras` list column (see app/common.load_activities) when it's there.
    """
    tags = set(tags)
    hit = acts["tag"].isin(tags)
    if "extras" in acts:
        hit |= acts["extras"].map(lambda xs: bool(tags & set(xs)))
    return hit


# ---------------------------------------------------------------- rules

def suggest_tag(a: dict, custom: list[dict] | None = None) -> str:
    """`a` holds activity columns plus activity_features columns (missing ones may be None).
    `custom`: your own tags (load_custom_tags), whose rules win over the built-in ones."""
    name = a.get("name") or ""
    sport = a.get("sport_type") or ""
    for t in custom or []:
        if (t["matcher"] and t["matcher"].search(name)) or sport.lower() in t["sport_types"]:
            return t["key"]
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
        long_enough = _num(a.get("distance_m")) >= config.INTERVAL_MIN_TOTAL_KM * 1000
        if long_enough and (sport == "track_running" or _INTERVAL.search(name) or looks_like_intervals(a)):
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
        """SELECT a.activity_id, a.sport_type, a.event_type, COALESCE(NULLIF(a.custom_name, ''), a.name) AS name,
                  a.duration_s, a.distance_m,
                  f.n_laps, f.lap_dist_cv, f.lap_alternation, f.lap_fast_slow_gap, f.has_interval_laps, f.o_prob,
                  t.tag
           FROM activities a
           LEFT JOIN activity_features f USING (activity_id)
           LEFT JOIN activity_tags t USING (activity_id)
           WHERE t.source IS NULL OR t.source = 'auto'"""
    ).fetchall()
    custom = load_custom_tags(conn)
    changed = 0
    for r in rows:
        tag = suggest_tag(dict(r), custom)
        if tag != r["tag"]:
            conn.execute(
                """INSERT INTO activity_tags (activity_id, tag, source) VALUES (?, ?, 'auto')
                   ON CONFLICT (activity_id) DO UPDATE SET tag = excluded.tag, updated_at = datetime('now')""",
                (r["activity_id"], tag),
            )
            changed += 1
    # An extra tag that became the main tag is redundant.
    conn.execute("DELETE FROM activity_extra_tags WHERE (activity_id, tag) IN (SELECT activity_id, tag FROM activity_tags)")
    conn.commit()
    return changed


def set_manual_tag(conn: sqlite3.Connection, activity_id: int, tag: str) -> None:
    if tag not in all_tags(conn):
        raise ValueError(f"unknown tag {tag!r}")
    conn.execute(
        """INSERT INTO activity_tags (activity_id, tag, source) VALUES (?, ?, 'manual')
           ON CONFLICT (activity_id) DO UPDATE SET tag = excluded.tag, source = 'manual',
           updated_at = datetime('now')""",
        (activity_id, tag),
    )
    conn.execute("DELETE FROM activity_extra_tags WHERE activity_id = ? AND tag = ?", (activity_id, tag))
    conn.commit()


def set_extra_tags(conn: sqlite3.Connection, activity_id: int, tags: list[str]) -> None:
    """Replace an activity's extra tags (on top of its main tag; set by hand only, never automatic)."""
    known = all_tags(conn)
    unknown = [t for t in tags if t not in known]
    if unknown:
        raise ValueError(f"unknown tag(s) {', '.join(map(repr, unknown))}")
    main = conn.execute("SELECT tag FROM activity_tags WHERE activity_id = ?", (activity_id,)).fetchone()
    conn.execute("DELETE FROM activity_extra_tags WHERE activity_id = ?", (activity_id,))
    conn.executemany("INSERT INTO activity_extra_tags (activity_id, tag) VALUES (?, ?)",
                     [(activity_id, t) for t in dict.fromkeys(tags) if not main or t != main[0]])
    conn.commit()


def set_custom_name(conn: sqlite3.Connection, activity_id: int, name: str | None) -> None:
    """Give an activity your own name (None or empty = back to Garmin's name).

    Names feed the keyword rules, so auto tags are re-applied (manual tags are never touched).
    """
    name = (name or "").strip() or None
    conn.execute("UPDATE activities SET custom_name = ? WHERE activity_id = ?", (name, activity_id))
    apply_auto_tags(conn)


def reset_to_auto(conn: sqlite3.Connection, activity_id: int) -> None:
    """Drop a manual tag so the auto rules apply again."""
    conn.execute("DELETE FROM activity_tags WHERE activity_id = ? AND source = 'manual'", (activity_id,))
    apply_auto_tags(conn)


if __name__ == "__main__":
    from db.database import connect

    c = connect()
    print(f"{apply_auto_tags(c)} auto tags updated.")
    labels = all_tags(c)
    for row in c.execute("SELECT tag, source, count(*) n FROM activity_tags GROUP BY 1, 2 ORDER BY 3 DESC"):
        print(f"  {labels.get(row['tag'], row['tag']):<24} {row['source']:<7} {row['n']}")
