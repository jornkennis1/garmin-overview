"""Read-only MCP server so the Claude Desktop app can analyse the training database.

Claude Desktop starts this script itself (see README, "Use with Claude Desktop"). It speaks the
Model Context Protocol (JSON-RPC 2.0, one message per line) over stdin/stdout, with no extra
dependencies. The database is opened read-only and every SQL statement is checked by SQLite's
authorizer, so nothing can be changed. No tool reads credentials or tokens; Claude only sees the
query results it asks for.

Manual test:  .venv\\Scripts\\python mcp_server.py --selftest
"""

import json
import re
import sqlite3
import sys
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import config  # noqa: E402
from garmin_sync.metrics import load_curves  # noqa: E402
from garmin_sync.tagging import all_tags  # noqa: E402

SERVER_INFO = {"name": "garmin-training", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"
MAX_ROWS = 500
QUERY_TIMEOUT_S = 10


def tag_labels() -> dict[str, str]:
    """Built-in tags plus the user's own (custom_tags), key -> label."""
    try:
        conn = connect()
    except RuntimeError:
        return dict(config.TAGS)
    try:
        return all_tags(conn)
    finally:
        conn.close()


def log(msg: str) -> None:
    """stdout is the protocol channel; diagnostics go to stderr (Claude Desktop's MCP log)."""
    print(f"[garmin-training] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- database (read-only)

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                    getattr(sqlite3, "SQLITE_RECURSIVE", 33)}


def _authorizer(action, arg1, arg2, dbname, source):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def connect() -> sqlite3.Connection:
    if not config.DB_PATH.exists():
        raise RuntimeError("No database yet: run `python -m garmin_sync.sync` in the project folder first.")
    conn = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = 1")
    conn.set_authorizer(_authorizer)
    started = time.monotonic()
    conn.set_progress_handler(lambda: int(time.monotonic() - started > QUERY_TIMEOUT_S), 10_000)
    return conn


def df(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = connect()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


# ---------------------------------------------------------------- formatting helpers

def table(frame: pd.DataFrame, max_rows: int = MAX_ROWS, max_cell: int = 200) -> str:
    """Compact pipe table (cheap in tokens, easy for Claude to read)."""
    if frame.empty:
        return "(no rows)"
    frame = frame.head(max_rows)
    cols = [str(c) for c in frame.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in frame.itertuples(index=False):
        cells = []
        for v in row:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                cells.append("")
            elif isinstance(v, float):
                cells.append(f"{v:.1f}" if abs(v) < 1000 else f"{v:,.0f}")
            else:
                cells.append(str(v).replace("|", "/").replace("\n", " ")[:max_cell])
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def hm(seconds) -> str:
    if seconds is None or pd.isna(seconds):
        return ""
    m = int(round(seconds / 60))
    return f"{m // 60}:{m % 60:02d}"


def period(args: dict, default_days: int = 30) -> tuple[date, date]:
    end = date.fromisoformat(args["end_date"]) if args.get("end_date") else date.today()
    if args.get("start_date"):
        start = date.fromisoformat(args["start_date"])
    else:
        start = end - timedelta(days=int(args.get("days") or default_days) - 1)
    if start > end:
        raise ValueError("start_date is after end_date")
    return start, end


def day_notes(start: date, end: date) -> list[str]:
    """Calendar notes overlapping the period, as bullet lines (none on a database from before notes)."""
    try:
        n = df("SELECT date, end_date, kind, text FROM day_notes WHERE date <= ? AND COALESCE(end_date, date) >= ? "
               "ORDER BY date", (end.isoformat(), start.isoformat()))
    except (sqlite3.Error, pd.errors.DatabaseError):
        return []
    return [f"- {r.kind}: {r.text or ''} ({r.date}{' – ' + r.end_date if r.end_date else ''})" for r in n.itertuples()]


def pct(a, b) -> str:
    return f"{100 * a / b:.0f}%" if b else "–"


# ---------------------------------------------------------------- tools

def tool_training_summary(args: dict) -> str:
    start, end = period(args)
    n_days = (end - start).days + 1
    prev_start, prev_end = start - timedelta(days=n_days), start - timedelta(days=1)
    acts = df("SELECT * FROM v_activities WHERE day BETWEEN ? AND ? ORDER BY start_time_local",
              (prev_start.isoformat(), end.isoformat()))
    cur = acts[acts["day"] >= start.isoformat()]
    prev = acts[acts["day"] < start.isoformat()]

    def totals(a: pd.DataFrame) -> dict:
        z = a[["easy_s", "moderate_s", "hard_s"]].sum()
        return {"hours": a["hours"].sum(), "sessions": len(a), "load": a["load"].sum(),
                "easy": z["easy_s"], "moderate": z["moderate_s"], "hard": z["hard_s"], "zone_total": z.sum()}

    t, p = totals(cur), totals(prev)
    out = [f"# Training summary {start} – {end} ({n_days} days)",
           "Orienteering athlete: prioritise time, HR zones and load over pace/distance.", "",
           "## Totals (vs previous period of equal length)",
           f"- Training time: {t['hours']:.1f} h (previous {p['hours']:.1f} h)",
           f"- Sessions: {t['sessions']} (previous {p['sessions']})",
           f"- Load: {t['load']:.0f} (previous {p['load']:.0f})",
           f"- Intensity (share of HR-zone time): easy Z1–2 {pct(t['easy'], t['zone_total'])}, "
           f"moderate Z3 {pct(t['moderate'], t['zone_total'])}, hard Z4–5 {pct(t['hard'], t['zone_total'])} "
           f"(previous: easy {pct(p['easy'], p['zone_total'])}, hard {pct(p['hard'], p['zone_total'])})"]
    notes = day_notes(start, end)
    if notes:
        out += ["", "## Notes (injury / illness / holiday)", *notes]
    if cur.empty:
        return "\n".join(out + ["", "No activities in this period."])

    by_tag = (cur.groupby("tag")
              .agg(hours=("hours", "sum"), sessions=("activity_id", "count"), load=("load", "sum"),
                   auto_tagged=("tag_source", lambda s: int((s != "manual").sum())))
              .sort_values("hours", ascending=False).reset_index())
    labels = tag_labels()
    by_tag["tag"] = by_tag["tag"].map(lambda k: labels.get(k, k))
    by_tag["share"] = (100 * by_tag["hours"] / by_tag["hours"].sum()).round(0).astype(int).astype(str) + "%"
    out += ["", "## Per tag", table(by_tag),
            "_auto_tagged = rule/model suggestions (manual tags are ground truth)._"]

    weekly = (cur.groupby("week_start")
              .agg(hours=("hours", "sum"), sessions=("activity_id", "count"), load=("load", "sum"),
                   easy_h=("easy_s", lambda s: s.sum() / 3600), hard_h=("hard_s", lambda s: s.sum() / 3600))
              .reset_index())
    out += ["", "## Per week (Monday-based)", table(weekly)]

    top = cur.sort_values("load", ascending=False).head(5)
    out += ["", "## Hardest sessions (by load)", table(pd.DataFrame({
        "activity_id": top["activity_id"], "date": top["start_time_local"].str[:16], "tag": top["tag"].map(lambda k: labels.get(k, k)),
        "sport": top["sport_type"], "time": top["duration_s"].map(hm), "avg_hr": top["avg_hr"],
        "load": top["load"], "hard_min": (top["hard_s"] / 60).round(0)}))]
    races = cur[cur["tag"] == "o_race"]
    if not races.empty:
        out += ["", "## Orienteering races", table(pd.DataFrame({
            "activity_id": races["activity_id"], "date": races["day"], "name": races["name"],
            "time": races["duration_s"].map(hm), "avg_hr": races["avg_hr"], "max_hr": races["max_hr"],
            "load": races["load"]}))]

    all_load = df("SELECT day, SUM(load) AS load FROM v_activities GROUP BY day")
    curves = load_curves(all_load.set_index(pd.to_datetime(all_load["day"]))["load"])
    if not curves.empty:
        e = curves.loc[:pd.Timestamp(end)].iloc[-1]
        s = curves.loc[:pd.Timestamp(start)].iloc[-1] if (curves.index <= pd.Timestamp(start)).any() else e
        out += ["", "## Fitness / fatigue (all activities)",
                f"- Fitness (CTL, 42-day load): {s['ctl']:.0f} → {e['ctl']:.0f}",
                f"- Fatigue (ATL, 7-day load): {s['atl']:.0f} → {e['atl']:.0f}",
                f"- Form (TSB = CTL − ATL): {e['tsb']:+.0f} at end of period"]
    return "\n".join(out)


def tool_recovery_summary(args: dict) -> str:
    start, end = period(args)
    d = df("""SELECT d.*, t.status, t.acute_load, t.chronic_load, t.acwr, t.vo2max, t.readiness_score
              FROM daily_metrics d LEFT JOIN training_status t USING (date)
              WHERE d.date BETWEEN ? AND ? ORDER BY d.date""",
           (start.isoformat(), end.isoformat()))
    out = [f"# Recovery & health {start} – {end}"]
    if d.empty:
        return "\n".join(out + ["No daily metrics in this period."])
    d["sleep_h"] = d["sleep_s"] / 3600
    metrics = [("Resting HR (bpm)", "resting_hr"), ("HRV overnight (ms)", "hrv_overnight_avg"),
               ("Sleep (h)", "sleep_h"), ("Sleep score", "sleep_score"), ("Body battery max", "bb_high"),
               ("Stress avg", "stress_avg"), ("Training readiness", "readiness_score"), ("Steps", "steps"),
               ("Active kcal", "active_kcal"), ("Respiration (brpm)", "respiration_avg"),
               ("VO2 max", "vo2max"), ("Weight (kg)", "weight_kg")]
    rows = []
    for label, col in metrics:
        s = d[col].dropna()
        if s.empty:
            continue
        first7, last7 = s.head(7).mean(), s.tail(7).mean()
        rows.append({"metric": label, "latest": s.iloc[-1], "avg": s.mean(), "min": s.min(), "max": s.max(),
                     "first_7d_avg": first7, "last_7d_avg": last7, "days": len(s)})
    out += ["", table(pd.DataFrame(rows))]
    if d["hrv_status"].notna().any():
        counts = d["hrv_status"].value_counts().to_dict()
        out += ["", "HRV status days: " + ", ".join(f"{k} {v}" for k, v in counts.items())]
    if d["status"].notna().any():
        last = d.dropna(subset=["status"]).iloc[-1]
        out += [f"Latest Garmin training status: {last['status']} (ACWR {last['acwr']}, "
                f"acute {last['acute_load']}, chronic {last['chronic_load']}) on {last['date']}"]
    flags = []
    if d["resting_hr"].notna().sum() >= 7:
        base = d["resting_hr"].median()
        for _, r in d[d["resting_hr"] >= base + 5].iterrows():
            flags.append(f"{r['date']}: resting HR {r['resting_hr']:.0f} (median {base:.0f})")
    if d["hrv_baseline_low"].notna().any():
        for _, r in d[d["hrv_overnight_avg"] < d["hrv_baseline_low"]].iterrows():
            flags.append(f"{r['date']}: HRV {r['hrv_overnight_avg']:.0f} below Garmin baseline {r['hrv_baseline_low']:.0f}")
    if flags:
        out += ["", "## Notable days", *[f"- {f}" for f in flags[:30]]]
    return "\n".join(out)


def tool_list_activities(args: dict) -> str:
    start, end = period(args, default_days=30)
    sql = "SELECT * FROM v_activities WHERE day BETWEEN ? AND ?"
    params: list = [start.isoformat(), end.isoformat()]
    if args.get("tag"):
        sql += " AND tag = ?"
        params.append(args["tag"])
    if args.get("sport"):
        sql += " AND sport_type LIKE ?"
        params.append(f"%{args['sport']}%")
    a = df(sql + " ORDER BY start_time_local DESC LIMIT ?", (*params, int(args.get("limit") or 100)))
    return f"Activities {start} – {end}:\n" + table(pd.DataFrame({
        "activity_id": a["activity_id"], "start": a["start_time_local"].str[:16], "tag": a["tag"],
        "extra_tags": a.get("extra_tags"), "tag_source": a["tag_source"], "sport": a["sport_type"], "name": a["name"], "time": a["duration_s"].map(hm),
        "km": (a["distance_m"] / 1000).round(1), "climb_m": a["elev_gain_m"], "avg_hr": a["avg_hr"],
        "load": a["load"], "easy_min": (a["easy_s"] / 60).round(0), "hard_min": (a["hard_s"] / 60).round(0),
        "laps": a["n_laps"]}))


def tool_get_activity(args: dict) -> str:
    aid = int(args["activity_id"])
    a = df("SELECT * FROM v_activities WHERE activity_id = ?", (aid,))
    if a.empty:
        return f"No activity with id {aid}."
    r = a.iloc[0]
    out = [f"# {r['name']} ({r['start_time_local']})",
           f"- Sport {r['sport_type']}, tag {tag_labels().get(r['tag'], r['tag'])} ({r['tag_source'] or 'none'})"
           + (f", extra tags {r['extra_tags']}" if isinstance(r.get("extra_tags"), str) else "") + f", event {r['event_type']}",
           f"- Time {hm(r['duration_s'])} (moving {hm(r['moving_s'])}), distance {(r['distance_m'] or 0) / 1000:.2f} km, "
           f"climb {r['elev_gain_m']} m",
           f"- HR avg {r['avg_hr']} / max {r['max_hr']}, Garmin load {r['training_load']}, TRIMP {r['trimp']}, "
           f"TE aerobic {r['aerobic_te']} / anaerobic {r['anaerobic_te']}",
           f"- Orienteering signals: turns/km {r['turns_per_km']}, stopped {r['stop_frac']}, O probability {r['o_prob']}"]
    zones = df("SELECT zone, seconds, zone_low_bpm FROM activity_hr_zones WHERE activity_id = ? ORDER BY zone", (aid,))
    if not zones.empty:
        zones["time"] = zones["seconds"].map(hm)
        out += ["", "## HR zones", table(zones[["zone", "zone_low_bpm", "time"]])]
    laps = df("SELECT * FROM activity_laps WHERE activity_id = ? ORDER BY lap_index", (aid,))
    if not laps.empty:
        laps["pace_min_km"] = (1000 / laps["avg_speed_mps"] / 60).where(laps["avg_speed_mps"] > 0.5).round(2)
        out += ["", f"## Laps ({len(laps)})", table(pd.DataFrame({
            "lap": laps["lap_index"], "type": laps["intensity"], "time": laps["duration_s"].map(hm),
            "m": laps["distance_m"].round(0), "pace_min_km": laps["pace_min_km"], "avg_hr": laps["avg_hr"],
            "max_hr": laps["max_hr"], "climb_m": laps["elev_gain_m"]}), max_rows=80)]
    s = df("SELECT t_offset_s, hr, speed_mps FROM activity_samples WHERE activity_id = ? AND hr IS NOT NULL "
           "ORDER BY t_offset_s", (aid,))
    if len(s) > 20:
        half = len(s) // 2
        out += ["", "## HR stream", f"- First half avg HR {s['hr'][:half].mean():.0f}, second half {s['hr'][half:].mean():.0f} "
                f"(cardiac drift {s['hr'][half:].mean() - s['hr'][:half].mean():+.0f} bpm)"]
    return "\n".join(out)


def tool_daily_metrics(args: dict) -> str:
    start, end = period(args, default_days=30)
    if (end - start).days > 180:
        start = end - timedelta(days=180)
    d = df("""SELECT d.date, d.resting_hr, d.hrv_overnight_avg AS hrv, d.hrv_status, d.sleep_s, d.sleep_score,
                     d.bb_high, d.bb_low, d.stress_avg, d.steps, d.active_kcal, d.respiration_avg, d.weight_kg,
                     t.readiness_score, t.status, t.vo2max
              FROM daily_metrics d LEFT JOIN training_status t USING (date)
              WHERE d.date BETWEEN ? AND ? ORDER BY d.date""", (start.isoformat(), end.isoformat()))
    d["sleep"] = d.pop("sleep_s").map(hm)
    return f"Daily metrics {start} – {end}:\n" + table(d)


_SQL_START = re.compile(r"^\s*(with|select)\b", re.IGNORECASE)


def tool_query_database(args: dict) -> str:
    sql = (args.get("sql") or "").strip().rstrip(";")
    if not _SQL_START.match(sql) or ";" in sql:
        return "Only a single SELECT (or WITH … SELECT) statement is allowed."
    conn = connect()
    try:
        cur = conn.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.DatabaseError as e:
        return f"SQL error: {e}"
    finally:
        conn.close()
    more = len(rows) > MAX_ROWS
    result = table(pd.DataFrame([tuple(r) for r in rows[:MAX_ROWS]], columns=cols))
    return result + (f"\n(first {MAX_ROWS} rows shown; add LIMIT or aggregate)" if more else "")


def tool_data_reference(args: dict) -> str:
    return (ROOT / "DATA.md").read_text(encoding="utf-8")


DATE_PROPS = {
    "days": {"type": "integer", "description": "Number of days ending at end_date (default 30)."},
    "start_date": {"type": "string", "description": "YYYY-MM-DD (overrides days)."},
    "end_date": {"type": "string", "description": "YYYY-MM-DD (default today)."},
}

TOOLS = {
    "training_summary": (tool_training_summary, {
        "description": "Training overview for a period: totals vs the previous period, hours/sessions/load per tag, "
                       "easy/moderate/hard HR-zone split, weekly breakdown, hardest sessions, races, and fitness/"
                       "fatigue (CTL/ATL/TSB). Start here for any 'how is my training going' question.",
        "inputSchema": {"type": "object", "properties": DATE_PROPS}}),
    "recovery_summary": (tool_recovery_summary, {
        "description": "Recovery and health for a period: resting HR, HRV (+status), sleep, body battery, stress, "
                       "readiness, steps, active calories, respiration, VO2 max and weight (latest, average, trend "
                       "first vs last week) plus notable days (high resting HR, HRV below baseline).",
        "inputSchema": {"type": "object", "properties": DATE_PROPS}}),
    "list_activities": (tool_list_activities, {
        "description": "List activities in a period with tag, time, HR, load and zone minutes. Optional filters: "
                       "tag (o_race, o_training, interval, long_run, easy_run, strength, cycling, hiking_walking, "
                       "other) and sport (substring of the Garmin sport type, e.g. 'running').",
        "inputSchema": {"type": "object", "properties": {
            **DATE_PROPS, "tag": {"type": "string"}, "sport": {"type": "string"},
            "limit": {"type": "integer", "description": "Max rows (default 100)."}}}}),
    "get_activity": (tool_get_activity, {
        "description": "Full detail of one activity: summary, HR zones, laps (split analysis) and HR drift.",
        "inputSchema": {"type": "object", "properties": {"activity_id": {"type": "integer"}},
                        "required": ["activity_id"]}}),
    "daily_metrics": (tool_daily_metrics, {
        "description": "Day-by-day health metrics (max 180 days) for detailed trend questions.",
        "inputSchema": {"type": "object", "properties": DATE_PROPS}}),
    "query_database": (tool_query_database, {
        "description": "Run one read-only SQL SELECT on the SQLite training database (max 500 rows). Call "
                       "data_reference first to see tables, columns and units. Prefer views v_activities and v_weekly.",
        "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}),
    "data_reference": (tool_data_reference, {
        "description": "Database documentation: tables, columns, units, tag meanings, example queries and "
                       "guidance for answering training questions.",
        "inputSchema": {"type": "object", "properties": {}}}),
}

PROMPTS = {
    "training_review": {
        "description": "Coach-style review of the last N days with concrete advice.",
        "arguments": [{"name": "days", "description": "Number of days (default 30)", "required": False}],
        "text": ("Act as my orienteering coach. Use the garmin-training tools (training_summary and recovery_summary "
                 "for the last {days} days, plus details where useful) to review my training: volume and consistency, "
                 "intensity distribution, orienteering-specific work, load vs recovery signals (resting HR, HRV, "
                 "sleep). Then give 3–5 concrete, prioritised suggestions for the coming 2 weeks. Prioritise time, "
                 "HR and load over pace, and say when conclusions rest on auto-tagged sessions."),
    },
    "weekly_checkin": {
        "description": "Short check-in on this week and how recovered I am today.",
        "arguments": [],
        "text": ("Give me a short weekly check-in: use training_summary for the last 7 days and recovery_summary for "
                 "the last 14 days. How does this week compare, how recovered am I today, and what should I do in the "
                 "next 2–3 days?"),
    },
}


# ---------------------------------------------------------------- JSON-RPC / MCP plumbing

def handle(msg: dict) -> dict | None:
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:  # notification (e.g. notifications/initialized): no response
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
                   "capabilities": {"tools": {}, "prompts": {}},
                   "serverInfo": SERVER_INFO,
                   "instructions": "Read-only access to an orienteer's Garmin training database. Summaries first "
                                   "(training_summary, recovery_summary), details on request."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, **spec} for n, (_, spec) in TOOLS.items()]})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool {name}"}}
        try:
            text = TOOLS[name][0](args)
            return ok({"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:  # report to Claude instead of crashing the server
            log(traceback.format_exc())
            return ok({"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
    if method == "prompts/list":
        return ok({"prompts": [{"name": n, "description": p["description"], "arguments": p["arguments"]}
                               for n, p in PROMPTS.items()]})
    if method == "prompts/get":
        p = PROMPTS.get(params.get("name"))
        if not p:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown prompt"}}
        days = (params.get("arguments") or {}).get("days") or 30
        return ok({"description": p["description"],
                   "messages": [{"role": "user", "content": {"type": "text", "text": p["text"].format(days=days)}}]})
    if method in ("resources/list", "resources/templates/list"):
        return ok({"resources": [], "resourceTemplates": []})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve() -> None:
    log(f"started, database {config.DB_PATH}")
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    for raw in stdin:
        line = raw.decode("utf-8").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            resp = handle(msg) if isinstance(msg, dict) else None
        if resp is not None:
            stdout.write((json.dumps(resp, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
            stdout.flush()


def selftest() -> None:
    for name in ("training_summary", "recovery_summary", "list_activities", "daily_metrics"):
        text = TOOLS[name][0]({"days": 14})
        print(f"===== {name} =====\n{text[:1500]}\n")
    print(tool_query_database({"sql": "SELECT tag, count(*) n FROM v_activities GROUP BY tag"}))
    print(tool_query_database({"sql": "DELETE FROM activities"}))
    print(tool_query_database({"sql": "SELECT 1; DROP TABLE activities"}))


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else serve()
