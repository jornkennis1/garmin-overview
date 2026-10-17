"""Incremental sync from Garmin Connect into data/garmin.db.

Usage (from the project folder, with the venv active):
    python -m garmin_sync.sync                    # normal daily use: only fetch what's new
    python -m garmin_sync.sync --since 2026-09-01 # limit history (handy for a first test)
    python -m garmin_sync.sync --no-details       # skip per-activity HR/pace streams (faster)

Safe to interrupt with Ctrl+C: everything fetched so far is saved and the next run resumes.
"""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta

from garminconnect import (
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)
from garminconnect.activity_details import parse_activity_detail_metrics

import config
from db.database import connect, get_state, set_state, upsert
from garmin_sync.auth import LoginError, get_client, save_tokens

PAGE_SIZE = 100
RAW_SAMPLE_DIR = config.DATA_DIR / "raw" / "samples"


class RateLimited(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers

def call(fn, *args, sample: str | None = None, optional: bool = False, **kwargs):
    """Call a Garmin API method politely: pause afterwards, back off on HTTP 429.

    With optional=True, other errors (e.g. an endpoint your watch doesn't support)
    are reported and None is returned instead of stopping the sync.
    """
    for attempt in range(4):
        try:
            result = fn(*args, **kwargs)
            time.sleep(config.API_DELAY_S)
            if sample:
                _save_sample(sample, result)
            return result
        except GarminConnectTooManyRequestsError:
            wait = 60 * 2**attempt
            print(f"  Garmin rate limit hit, waiting {wait}s ...", flush=True)
            time.sleep(wait)
        except GarminConnectConnectionError as e:
            if not optional:
                raise
            time.sleep(config.API_DELAY_S)
            _warn_once(fn.__name__, e)
            return None
    raise RateLimited("Garmin keeps rate-limiting; stopping. Run the sync again later to resume.")


_warned: set[str] = set()


def _warn_once(name: str, err: Exception) -> None:
    if name not in _warned:
        _warned.add(name)
        print(f"  note: {name} failed ({err}); continuing without it.", flush=True)


def _save_sample(name: str, data) -> None:
    """Keep the latest raw response per endpoint (git-ignored) to help debug parsing."""
    if not data:
        return
    RAW_SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_SAMPLE_DIR / f"{name}.json").write_text(json.dumps(data, indent=1)[:500_000], encoding="utf-8")


def first(d: dict | None, *keys):
    """Return the first non-None value among `keys` (dotted paths allowed)."""
    if not isinstance(d, dict):
        return None
    for key in keys:
        cur = d
        for part in key.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is not None:
            return cur
    return None


def non_negative(v):
    """Garmin uses -1/-2 for 'no data' in several fields."""
    return v if isinstance(v, (int, float)) and v >= 0 else None


def compact(row: dict) -> dict:
    return {k: v for k, v in row.items() if v is not None}


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ---------------------------------------------------------------- activities

def parse_activity(a: dict) -> dict:
    return {
        "activity_id": a["activityId"],
        "start_time_local": a.get("startTimeLocal"),
        "start_time_utc": a.get("startTimeGMT"),
        "name": a.get("activityName"),
        "sport_type": first(a, "activityType.typeKey"),
        "event_type": first(a, "eventType.typeKey"),
        "duration_s": a.get("duration"),
        "moving_s": a.get("movingDuration"),
        "distance_m": a.get("distance"),
        "elev_gain_m": a.get("elevationGain"),
        "elev_loss_m": a.get("elevationLoss"),
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "aerobic_te": a.get("aerobicTrainingEffect"),
        "anaerobic_te": a.get("anaerobicTrainingEffect"),
        "training_load": a.get("activityTrainingLoad"),
        "calories": a.get("calories"),
        "avg_speed_mps": a.get("averageSpeed"),
        "source": "api",
        "raw_json": json.dumps(a),
    }


def sync_activities(client, conn, since: str | None) -> int:
    """Fetch activity summaries, newest first, until we reach ones we already have."""
    backfill_done = get_state(conn, "activities_backfill_done") == "1"
    start, new, reached_end, seen_existing = 0, 0, False, False
    print("Activities: fetching summaries ...", flush=True)
    while True:
        page = call(client.get_activities, start, PAGE_SIZE, sample="activities_page") or []
        stop = False
        for a in page:
            if since and (a.get("startTimeLocal") or "")[:10] < since:
                stop = True
                break
            exists = conn.execute(
                "SELECT 1 FROM activities WHERE activity_id = ?", (a["activityId"],)
            ).fetchone()
            if exists and backfill_done:
                seen_existing = True
                if start > 0:  # always refresh the newest page (renames, late load values)
                    stop = True
                    break
            upsert(conn, "activities", parse_activity(a), "activity_id")
            new += not exists
        conn.commit()
        stop = stop or seen_existing
        if len(page) < PAGE_SIZE:
            reached_end = not stop
            break
        if stop:
            break
        start += PAGE_SIZE
        print(f"  ... {start} activities scanned, {new} new", flush=True)
    if reached_end and not since:
        set_state(conn, "activities_backfill_done", "1")
        conn.commit()
    print(f"Activities: {new} new.", flush=True)
    return new


def parse_zones(activity_id: int, zones) -> list[dict]:
    rows = []
    for z in zones or []:
        zone, secs = first(z, "zoneNumber"), first(z, "secsInZone")
        if zone is None or secs is None:
            continue
        rows.append({
            "activity_id": activity_id,
            "zone": int(zone),
            "seconds": float(secs),
            "zone_low_bpm": first(z, "zoneLowBoundary"),
        })
    return rows


def parse_samples(activity_id: int, details: dict) -> list[dict]:
    rows, t0 = [], None
    for s in parse_activity_detail_metrics(details or {}):
        offset = first(s, "sumElapsedDuration", "sumDuration")
        ts = s.get("directTimestamp")
        if offset is None and ts is not None:
            t0 = ts if t0 is None else t0
            offset = (ts - t0) / 1000
        if offset is None:
            continue
        rows.append({
            "activity_id": activity_id,
            "t_offset_s": float(offset),
            "hr": s.get("directHeartRate"),
            "speed_mps": first(s, "directSpeed", "directEnhancedSpeed"),
            "altitude_m": first(s, "directElevation", "directEnhancedElevation"),
            "distance_m": s.get("sumDistance"),
            "cadence": first(s, "directRunCadence", "directDoubleCadence", "directBikeCadence"),
            "lat": s.get("directLatitude"),
            "lon": s.get("directLongitude"),
        })
    return rows


def sync_activity_details(client, conn, since: str | None) -> int:
    """Fetch HR time-in-zone and the HR/pace stream for activities that lack them."""
    sql = "SELECT activity_id, start_time_local, name FROM activities WHERE details_fetched = 0 AND source = 'api'"
    params: list = []
    if since:
        sql += " AND start_time_local >= ?"
        params.append(since)
    todo = conn.execute(sql + " ORDER BY start_time_local DESC", params).fetchall()
    if not todo:
        return 0
    print(f"Activity details: {len(todo)} activities to fetch (HR zones + HR/pace stream) ...", flush=True)
    done = 0
    for row in todo:
        aid = row["activity_id"]
        try:
            zones = call(client.get_activity_hr_in_timezones, aid, sample="activity_hr_zones")
            details = call(client.get_activity_details, aid, maxchart=config.ACTIVITY_SAMPLE_POINTS,
                           sample="activity_details")
        except GarminConnectNotFoundError:
            zones, details = [], {}
        except GarminConnectConnectionError as e:
            print(f"  skipping {aid} ({row['start_time_local']}): {e}", flush=True)
            continue
        conn.execute("DELETE FROM activity_hr_zones WHERE activity_id = ?", (aid,))
        conn.execute("DELETE FROM activity_samples WHERE activity_id = ?", (aid,))
        for z in parse_zones(aid, zones):
            upsert(conn, "activity_hr_zones", z, ("activity_id", "zone"))
        samples = parse_samples(aid, details)
        if samples:
            conn.executemany(
                "INSERT OR REPLACE INTO activity_samples VALUES "
                "(:activity_id, :t_offset_s, :hr, :speed_mps, :altitude_m, :distance_m, :cadence, :lat, :lon)",
                samples,
            )
        conn.execute("UPDATE activities SET details_fetched = 1 WHERE activity_id = ?", (aid,))
        conn.commit()
        done += 1
        if done % 25 == 0 or done == len(todo):
            print(f"  ... {done}/{len(todo)} (now at {row['start_time_local'][:10]})", flush=True)
    return done


# ---------------------------------------------------------------- daily metrics (per day)

def parse_user_summary(s: dict) -> dict:
    return {
        "resting_hr": first(s, "restingHeartRate"),
        "stress_avg": non_negative(first(s, "averageStressLevel")),
        "steps": first(s, "totalSteps"),
        "bb_high": first(s, "bodyBatteryHighestValue"),
        "bb_low": first(s, "bodyBatteryLowestValue"),
        "bb_charged": first(s, "bodyBatteryChargedValue"),
        "bb_drained": first(s, "bodyBatteryDrainedValue"),
    }


def parse_sleep(s: dict) -> dict:
    dto = first(s, "dailySleepDTO") or {}
    return {
        "sleep_s": first(dto, "sleepTimeSeconds"),
        "deep_s": first(dto, "deepSleepSeconds"),
        "light_s": first(dto, "lightSleepSeconds"),
        "rem_s": first(dto, "remSleepSeconds"),
        "awake_s": first(dto, "awakeSleepSeconds"),
        "sleep_score": first(dto, "sleepScores.overall.value"),
    }


def parse_hrv_summary(h: dict) -> dict:
    return {
        "hrv_overnight_avg": first(h, "lastNightAvg"),
        "hrv_weekly_avg": first(h, "weeklyAvg"),
        "hrv_baseline_low": first(h, "baseline.balancedLow"),
        "hrv_baseline_high": first(h, "baseline.balancedUpper"),
        "hrv_status": first(h, "status"),
    }


def parse_training_status(ts: dict, readiness: dict | None) -> dict:
    latest = first(ts, "mostRecentTrainingStatus.latestTrainingStatusData") or {}
    # One entry per device; prefer the primary training device.
    devices = [v for v in latest.values() if isinstance(v, dict)]
    dev = next((d for d in devices if d.get("primaryTrainingDevice")), devices[0] if devices else {})
    phrase = first(dev, "trainingStatusFeedbackPhrase")
    return {
        "status": re.sub(r"_\d+$", "", phrase) if isinstance(phrase, str) else None,
        "acute_load": first(dev, "acuteTrainingLoadDTO.dailyTrainingLoadAcute"),
        "chronic_load": first(dev, "acuteTrainingLoadDTO.dailyTrainingLoadChronic"),
        "acwr": first(dev, "acuteTrainingLoadDTO.dailyAcuteChronicWorkloadRatio"),
        "vo2max": first(ts, "mostRecentVO2Max.generic.vo2MaxPreciseValue", "mostRecentVO2Max.generic.vo2MaxValue"),
        "readiness_score": first(readiness, "score"),
        "readiness_level": first(readiness, "level"),
    }


def fetch_day(client, conn, d: date, with_status: bool = True) -> bool:
    """Fetch all daily endpoints for one day. Returns True if any data was found."""
    ds = d.isoformat()
    row = {}
    row.update(parse_user_summary(call(client.get_user_summary, ds, sample="user_summary", optional=True) or {}))
    row.update(parse_sleep(call(client.get_sleep_data, ds, sample="sleep_day", optional=True) or {}))
    row.update(parse_hrv_summary(first(call(client.get_hrv_data, ds, sample="hrv_day", optional=True), "hrvSummary") or {}))
    row = compact(row)
    if row.get("steps") == 0 and len(row) == 1:
        row = {}
    if row:
        upsert(conn, "daily_metrics", {"date": ds, **row}, "date")
    found = bool(row)
    if with_status:
        found = fetch_training_status(client, conn, d) or found
    conn.commit()
    return found


def fetch_training_status(client, conn, d: date) -> bool:
    ds = d.isoformat()
    ts = call(client.get_training_status, ds, sample="training_status", optional=True) or {}
    readiness = call(client.get_morning_training_readiness, ds, sample="training_readiness", optional=True)
    status = compact(parse_training_status(ts, readiness))
    if status:
        upsert(conn, "training_status", {"date": ds, **status}, "date")
    return bool(status)


# ---------------------------------------------------------------- daily metrics (history, 28-day chunks)

def _rows(data, *list_keys) -> list[dict]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    for k in list_keys:
        v = first(data, k)
        if isinstance(v, list):
            return [r for r in v if isinstance(r, dict)]
    return []


def fetch_range(client, conn, start: date, end: date) -> int:
    """Fetch summaries, sleep and HRV for a date range in a few calls. Returns days with data."""
    s, e = start.isoformat(), end.isoformat()
    by_day: dict[str, dict] = {}

    for r in _rows(call(client.get_daily_summaries, s, e, sample="daily_summaries_range", optional=True), "data"):
        if day := first(r, "calendarDate"):
            by_day.setdefault(day, {}).update(parse_user_summary(r))

    for r in call(client.get_sleep_daily, s, e, sample="sleep_range", optional=True) or []:
        day, v = first(r, "calendarDate"), first(r, "values") or r
        if day:
            by_day.setdefault(day, {}).update({
                "sleep_s": first(v, "totalSleepTimeInSeconds", "totalSleepSeconds", "sleepTimeSeconds"),
                "deep_s": first(v, "deepTime", "deepSleepSeconds", "deepSleepTimeInSeconds"),
                "light_s": first(v, "lightTime", "lightSleepSeconds", "lightSleepTimeInSeconds"),
                "rem_s": first(v, "remTime", "remSleepSeconds", "remSleepTimeInSeconds"),
                "awake_s": first(v, "awakeTime", "awakeSleepSeconds", "awakeTimeInSeconds"),
                "sleep_score": first(v, "sleepScore", "overallScore", "sleepScores.overall.value"),
            })

    hrv = call(client.get_hrv_data_range, s, e, sample="hrv_range", optional=True)
    for r in _rows(hrv, "hrvSummaries"):
        if day := first(r, "calendarDate"):
            by_day.setdefault(day, {}).update(parse_hrv_summary(r))

    found = 0
    for day, row in by_day.items():
        row = compact(row)
        if not row or (row.get("steps") in (0, None) and len(row) <= 1):
            continue
        upsert(conn, "daily_metrics", {"date": day, **row}, "date")
        found += 1
    conn.commit()
    return found


def sync_daily(client, conn, since: str | None) -> None:
    today = date.today()
    floor = date.fromisoformat(since) if since else None

    # 1. Recent days: detailed per-day endpoints (incl. training status/readiness).
    last = conn.execute("SELECT max(date) AS d FROM daily_metrics").fetchone()["d"]
    if last:
        start = date.fromisoformat(last) - timedelta(days=config.DAILY_REFRESH_DAYS)
    else:
        start = today - timedelta(days=config.DAILY_INITIAL_RECENT_DAYS - 1)
    if floor:
        start = max(start, floor)
    days = list(daterange(start, today))
    print(f"Daily metrics: {len(days)} recent days ({start} .. {today}) ...", flush=True)
    for d in days:
        fetch_day(client, conn, d)
    if get_state(conn, "daily_backfill_cursor") is None:
        set_state(conn, "daily_backfill_cursor", (start - timedelta(days=1)).isoformat())
        set_state(conn, "status_backfill_cursor", (start - timedelta(days=1)).isoformat())
        conn.commit()

    # 2. History: 28-day chunks going back until Garmin has nothing more.
    if get_state(conn, "daily_backfill_done") != "1":
        cursor = date.fromisoformat(get_state(conn, "daily_backfill_cursor"))
        empty_days = 0
        print("Daily metrics history: fetching in 28-day chunks (newest first) ...", flush=True)
        while empty_days < config.DAILY_BACKFILL_EMPTY_STOP:
            if floor and cursor < floor:
                break
            chunk_start = cursor - timedelta(days=27)
            if floor:
                chunk_start = max(chunk_start, floor)
            found = fetch_range(client, conn, chunk_start, cursor)
            empty_days = empty_days + (cursor - chunk_start).days + 1 if found == 0 else 0
            print(f"  {chunk_start} .. {cursor}: {found} days with data", flush=True)
            cursor = chunk_start - timedelta(days=1)
            set_state(conn, "daily_backfill_cursor", cursor.isoformat())
            conn.commit()
        else:
            set_state(conn, "daily_backfill_done", "1")
            conn.commit()

    # 3. Training status/readiness history (per day only, so limited to recent year).
    if get_state(conn, "status_backfill_done") != "1":
        cursor = date.fromisoformat(get_state(conn, "status_backfill_cursor"))
        limit = today - timedelta(days=config.TRAINING_STATUS_BACKFILL_DAYS)
        if floor:
            limit = max(limit, floor)
        if cursor >= limit:
            print(f"Training status history: {(cursor - limit).days + 1} days ...", flush=True)
        empty_days = 0
        while cursor >= limit and empty_days < 30:
            empty_days = 0 if fetch_training_status(client, conn, cursor) else empty_days + 1
            cursor -= timedelta(days=1)
            set_state(conn, "status_backfill_cursor", cursor.isoformat())
            conn.commit()
        if not floor and (cursor < limit or empty_days >= 30):
            set_state(conn, "status_backfill_done", "1")
            conn.commit()


# ---------------------------------------------------------------- main

def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Sync Garmin Connect data into data/garmin.db")
    p.add_argument("--since", help="only fetch data on or after this date (YYYY-MM-DD)")
    p.add_argument("--no-details", action="store_true", help="skip per-activity HR zones and HR/pace streams")
    p.add_argument("--activities-only", action="store_true")
    p.add_argument("--daily-only", action="store_true")
    args = p.parse_args(argv)
    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            sys.exit("--since must look like 2026-09-01")

    conn = connect()
    try:
        client = get_client()
    except LoginError as e:
        sys.exit(str(e))

    started = time.time()
    try:
        if not args.daily_only:
            sync_activities(client, conn, args.since)
        if not args.activities_only:
            sync_daily(client, conn, args.since)
        if not args.daily_only and not args.no_details:
            sync_activity_details(client, conn, args.since)
    except KeyboardInterrupt:
        print("\nStopped. Everything fetched so far is saved; run the sync again to resume.")
    except RateLimited as e:
        print(f"\n{e}")
    finally:
        conn.commit()
        save_tokens(client)
        n_act = conn.execute("SELECT count(*) FROM activities").fetchone()[0]
        n_day = conn.execute("SELECT count(*) FROM daily_metrics").fetchone()[0]
        conn.close()
    print(f"Done in {time.time() - started:.0f}s. Database now has {n_act} activities and {n_day} days of metrics.")


if __name__ == "__main__":
    main()
