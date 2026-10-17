"""Fallback importer: load activities (and some wellness data) from FIT files / a Garmin export.

Use this if the Garmin API library stops working. Request your data at
https://www.garmin.com/account/datamanagement/exportdata (you get an email with a zip), then:

    python -m garmin_sync.fit_import path\\to\\export.zip      # full Garmin export
    python -m garmin_sync.fit_import path\\to\\folder          # folder with .fit / .zip files
    python -m garmin_sync.fit_import path\\to\\activity.fit    # single file

Activities that already exist (same start time within 60 s) are skipped, so it is safe to
run repeatedly and to mix with the API sync. Existing activities without HR stream get it filled in.
"""

import argparse
import io
import json
import math
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitdecode

import config
from db.database import connect, upsert
from garmin_sync.features import update_features
from garmin_sync.metrics import hr_reference, update_trimp, zone_lower_bounds
from garmin_sync.sync import store_laps
from garmin_sync.tagging import apply_auto_tags

SEMICIRCLE_TO_DEG = 180 / 2**31
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)

# (FIT sport, FIT sub_sport) -> Garmin Connect typeKey, so FIT and API activities look alike.
SPORT_MAP = {
    ("running", "trail"): "trail_running",
    ("running", "treadmill"): "treadmill_running",
    ("running", "track"): "track_running",
    ("running", "street"): "street_running",
    ("running", "indoor_running"): "indoor_running",
    ("running", "virtual_activity"): "virtual_run",
    ("cycling", "road"): "road_biking",
    ("cycling", "mountain"): "mountain_biking",
    ("cycling", "gravel_cycling"): "gravel_cycling",
    ("cycling", "indoor_cycling"): "indoor_cycling",
    ("cycling", "virtual_activity"): "virtual_ride",
    ("training", "strength_training"): "strength_training",
    ("training", "cardio_training"): "indoor_cardio",
    ("training", "yoga"): "yoga",
    ("training", "pilates"): "pilates",
    ("swimming", "lap_swimming"): "lap_swimming",
    ("swimming", "open_water"): "open_water_swimming",
    ("cross_country_skiing", None): "cross_country_skiing_ws",
}


# ---------------------------------------------------------------- finding files

def iter_inputs(path: Path, tmp: Path):
    """Yield ('fit', name, bytes) and ('json', name, bytes) items from a file, folder or (nested) zip."""
    if path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".fit", ".zip", ".json"):
                yield from iter_inputs(p, tmp)
        return
    suffix = path.suffix.lower()
    if suffix == ".fit":
        yield "fit", path.name, path.read_bytes()
    elif suffix == ".json" and _is_wellness_json(path.name):
        yield "json", path.name, path.read_bytes()
    elif suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                name = info.filename
                low = name.lower()
                if info.is_dir():
                    continue
                if low.endswith(".fit"):
                    yield "fit", Path(name).name, z.read(info)
                elif low.endswith(".json") and _is_wellness_json(name):
                    yield "json", Path(name).name, z.read(info)
                elif low.endswith(".zip"):
                    # Nested zip (Garmin exports put FIT files in UploadedFiles_*.zip): copy to temp, recurse.
                    nested = tmp / f"nested_{abs(hash(name))}.zip"
                    with z.open(info) as src, open(nested, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    try:
                        yield from iter_inputs(nested, tmp)
                    finally:
                        nested.unlink(missing_ok=True)


def _is_wellness_json(name: str) -> bool:
    n = Path(name).name.lower()
    return n.startswith("udsfile") or "sleepdata" in n


# ---------------------------------------------------------------- parsing FIT

def _val(frame, *names):
    for n in names:
        if frame.has_field(n):
            v = frame.get_value(n, fallback=None)
            if v is not None:
                return v
    return None


def _to_utc(v) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        return FIT_EPOCH + timedelta(seconds=v)
    return None


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def parse_fit(data: bytes) -> dict | None:
    """Parse one FIT file. Returns None if it is not an activity (e.g. monitoring/settings files)."""
    file_type, sessions, records, lap_frames, local_offset = None, [], [], [], None
    with fitdecode.FitReader(io.BytesIO(data), check_crc=fitdecode.CrcCheck.DISABLED) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "file_id":
                file_type = _val(frame, "type")
            elif frame.name == "session":
                sessions.append(frame)
            elif frame.name == "lap":
                lap_frames.append(frame)
            elif frame.name == "record":
                ts = _to_utc(_val(frame, "timestamp"))
                if ts is None:
                    continue
                lat, lon = _val(frame, "position_lat"), _val(frame, "position_long")
                records.append({
                    "ts": ts,
                    "hr": _num(_val(frame, "heart_rate")),
                    "speed_mps": _num(_val(frame, "enhanced_speed", "speed")),
                    "altitude_m": _num(_val(frame, "enhanced_altitude", "altitude")),
                    "distance_m": _num(_val(frame, "distance")),
                    "cadence": _num(_val(frame, "cadence")),
                    "lat": lat * SEMICIRCLE_TO_DEG if isinstance(lat, int) else None,
                    "lon": lon * SEMICIRCLE_TO_DEG if isinstance(lon, int) else None,
                })
            elif frame.name == "activity":
                ts, local = _to_utc(_val(frame, "timestamp")), _val(frame, "local_timestamp")
                if isinstance(local, datetime):
                    local = local.replace(tzinfo=timezone.utc)
                elif isinstance(local, (int, float)):
                    local = FIT_EPOCH + timedelta(seconds=local)
                if ts and isinstance(local, datetime):
                    local_offset = local - ts

    if file_type not in ("activity", 4) or not sessions:
        return None

    s0 = sessions[0]
    start_utc = _to_utc(_val(s0, "start_time")) or (records[0]["ts"] if records else None)
    if start_utc is None:
        return None
    if local_offset is None:  # fall back to this laptop's timezone
        local_offset = start_utc.astimezone().utcoffset() or timedelta(0)
    start_local = (start_utc + local_offset).replace(tzinfo=None)

    def total(field):
        vals = [_num(_val(s, field)) for s in sessions]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    sport = str(_val(s0, "sport") or "generic")
    sub = _val(s0, "sub_sport")
    sub = str(sub) if sub is not None and str(sub) != "generic" else None
    sport_type = SPORT_MAP.get((sport, sub)) or SPORT_MAP.get((sport, None)) or sport

    hrs = [_num(_val(s, "avg_heart_rate")) for s in sessions]
    durations = [_num(_val(s, "total_elapsed_time")) or 0 for s in sessions]
    avg_hr = (sum(h * d for h, d in zip(hrs, durations) if h) / sum(d for h, d in zip(hrs, durations) if h)
              if any(hrs) and sum(durations) else None)

    activity = {
        "start_time_local": start_local.strftime("%Y-%m-%d %H:%M:%S"),
        "start_time_utc": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "name": f"{sport_type.replace('_', ' ').title()} (FIT import)",
        "sport_type": sport_type,
        "duration_s": total("total_elapsed_time"),
        "moving_s": total("total_timer_time"),
        "distance_m": total("total_distance"),
        "elev_gain_m": total("total_ascent"),
        "elev_loss_m": total("total_descent"),
        "avg_hr": round(avg_hr, 1) if avg_hr else None,
        "max_hr": max((_num(_val(s, "max_heart_rate")) or 0 for s in sessions), default=None) or None,
        "aerobic_te": _num(_val(s0, "total_training_effect")),
        "anaerobic_te": _num(_val(s0, "total_anaerobic_training_effect")),
        "calories": total("total_calories"),
        "avg_speed_mps": _num(_val(s0, "enhanced_avg_speed", "avg_speed")),
        "source": "fit",
    }
    laps = []
    for i, lap in enumerate(lap_frames, start=1):
        lap_start = _to_utc(_val(lap, "start_time"))
        intensity = _val(lap, "intensity")
        laps.append({
            "lap_index": i,
            "start_offset_s": (lap_start - start_utc).total_seconds() if lap_start else None,
            "duration_s": _num(_val(lap, "total_elapsed_time")),
            "moving_s": _num(_val(lap, "total_timer_time")),
            "distance_m": _num(_val(lap, "total_distance")),
            "avg_hr": _num(_val(lap, "avg_heart_rate")),
            "max_hr": _num(_val(lap, "max_heart_rate")),
            "avg_speed_mps": _num(_val(lap, "enhanced_avg_speed", "avg_speed")),
            "elev_gain_m": _num(_val(lap, "total_ascent")),
            "elev_loss_m": _num(_val(lap, "total_descent")),
            # FIT uses lowercase names (active, rest, warmup, cooldown, recovery, interval); Garmin API uses upper.
            "intensity": str(intensity).upper() if intensity is not None else None,
        })
    return {"activity": activity, "records": records, "laps": laps, "start_utc": start_utc}


def samples_from_records(activity_id: int, records: list[dict], start_utc: datetime) -> list[dict]:
    step = max(1, math.ceil(len(records) / config.ACTIVITY_SAMPLE_POINTS))
    out = []
    for r in records[::step]:
        out.append({
            "activity_id": activity_id,
            "t_offset_s": (r["ts"] - start_utc).total_seconds(),
            **{k: r[k] for k in ("hr", "speed_mps", "altitude_m", "distance_m", "cadence", "lat", "lon")},
        })
    return out


def zones_from_records(activity_id: int, records: list[dict], bounds: list[float] | None) -> list[dict]:
    """Time in Z1..Z5 from the full-resolution HR stream (time below Z1 is not counted, like Garmin)."""
    if not bounds:
        return []
    secs = [0.0] * 5
    for prev, cur in zip(records, records[1:]):
        dt = (cur["ts"] - prev["ts"]).total_seconds()
        hr = cur["hr"]
        if hr is None or dt <= 0 or dt > 30:
            continue
        zone = sum(1 for b in bounds if hr >= b)
        if zone >= 1:
            secs[zone - 1] += dt
    return [
        {"activity_id": activity_id, "zone": i + 1, "seconds": round(s, 1), "zone_low_bpm": bounds[i]}
        for i, s in enumerate(secs)
    ]


# ---------------------------------------------------------------- storing

def _garmin_id_from_name(name: str) -> int | None:
    """Garmin export files are usually named like '<email>_<activityId>.fit'."""
    m = re.findall(r"(\d{8,})", Path(name).stem)
    return int(m[-1]) if m else None


def store_fit(conn, name: str, parsed: dict, bounds) -> str:
    act, records, start_utc = parsed["activity"], parsed["records"], parsed["start_utc"]
    existing = conn.execute(
        """SELECT activity_id, details_fetched FROM activities
           WHERE abs(strftime('%s', start_time_utc) - strftime('%s', ?)) <= 60""",
        (act["start_time_utc"],),
    ).fetchone()
    if existing:
        if existing["details_fetched"] or not records:
            return "duplicate"
        aid = existing["activity_id"]  # API activity without stream: fill it in from the FIT file
        result = "filled"
    else:
        aid = _garmin_id_from_name(name) or -int(start_utc.timestamp())
        if conn.execute("SELECT 1 FROM activities WHERE activity_id = ?", (aid,)).fetchone():
            return "duplicate"
        upsert(conn, "activities", {"activity_id": aid, **act}, "activity_id")
        result = "new"

    conn.execute("DELETE FROM activity_samples WHERE activity_id = ?", (aid,))
    conn.executemany(
        "INSERT OR REPLACE INTO activity_samples VALUES "
        "(:activity_id, :t_offset_s, :hr, :speed_mps, :altitude_m, :distance_m, :cadence, :lat, :lon)",
        samples_from_records(aid, records, start_utc),
    )
    zones = zones_from_records(aid, records, bounds)
    if zones and not conn.execute("SELECT 1 FROM activity_hr_zones WHERE activity_id = ?", (aid,)).fetchone():
        for z in zones:
            upsert(conn, "activity_hr_zones", z, ("activity_id", "zone"))
    conn.execute("UPDATE activities SET details_fetched = 1 WHERE activity_id = ?", (aid,))
    if parsed["laps"] and not conn.execute("SELECT 1 FROM activity_laps WHERE activity_id = ?", (aid,)).fetchone():
        store_laps(conn, aid, [{"activity_id": aid, **lap} for lap in parsed["laps"]])
    conn.execute("DELETE FROM activity_features WHERE activity_id = ?", (aid,))
    return result


def fill_daily(conn, day: str, row: dict) -> bool:
    """Insert a day, or fill only the columns that are still empty (API data wins)."""
    row = {k: v for k, v in row.items() if v is not None}
    if not row:
        return False
    existing = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", (day,)).fetchone()
    if existing:
        row = {k: v for k, v in row.items() if existing[k] is None}
        if not row:
            return False
    upsert(conn, "daily_metrics", {"date": day, **row}, "date")
    return True


def store_wellness_json(conn, name: str, data: bytes) -> int:
    """Best-effort import of daily summaries (UDSFile_*.json) and sleep (*sleepData.json)."""
    from garmin_sync.sync import first, parse_user_summary

    try:
        items = json.loads(data)
    except json.JSONDecodeError:
        return 0
    if isinstance(items, dict):
        items = next((v for v in items.values() if isinstance(v, list)), [])
    n = 0
    is_sleep = "sleepdata" in name.lower()
    for it in items:
        if not isinstance(it, dict):
            continue
        day = first(it, "calendarDate", "calendarDate.date")
        if not isinstance(day, str):
            continue
        if is_sleep:
            parts = [first(it, k) for k in ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds")]
            row = {
                "deep_s": parts[0], "light_s": parts[1], "rem_s": parts[2],
                "awake_s": first(it, "awakeSleepSeconds"),
                "sleep_s": sum(p for p in parts if p) or None,
                "sleep_score": first(it, "sleepScores.overallScore", "sleepScores.overall.value"),
            }
        else:
            row = parse_user_summary(it)
            if row.get("stress_avg") is not None and row["stress_avg"] < 0:
                row["stress_avg"] = None
        n += fill_daily(conn, day[:10], row)
    return n


# ---------------------------------------------------------------- main

def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Import FIT files / a Garmin data export into data/garmin.db")
    p.add_argument("path", help="export .zip, a folder, or a single .fit file")
    args = p.parse_args(argv)
    src = Path(args.path).expanduser()
    if not src.exists():
        sys.exit(f"Not found: {src}")

    conn = connect()
    hr_max, _ = hr_reference(conn)
    bounds = zone_lower_bounds(conn, hr_max)
    counts = {"new": 0, "filled": 0, "duplicate": 0, "not_activity": 0, "error": 0, "days": 0}
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as tmp:
        for i, (kind, name, data) in enumerate(iter_inputs(src, Path(tmp)), start=1):
            try:
                if kind == "json":
                    counts["days"] += store_wellness_json(conn, name, data)
                    continue
                parsed = parse_fit(data)
                if parsed is None:
                    counts["not_activity"] += 1
                    continue
                counts[store_fit(conn, name, parsed, bounds)] += 1
            except Exception as e:  # one broken file should not stop the import
                counts["error"] += 1
                print(f"  could not read {name}: {e}")
            if i % 100 == 0:
                conn.commit()
                print(f"  ... {i} files processed: {counts}", flush=True)
    conn.commit()
    update_trimp(conn)
    update_features(conn)
    apply_auto_tags(conn)
    conn.close()
    print(
        f"Done. Activities: {counts['new']} new, {counts['filled']} existing ones got HR/pace data, "
        f"{counts['duplicate']} already present. Skipped {counts['not_activity']} non-activity FIT files, "
        f"{counts['error']} unreadable. Daily metric days added/filled: {counts['days']}."
    )


if __name__ == "__main__":
    main()
