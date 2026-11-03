"""Weekly / monthly training report as one self-contained HTML file (Report page): to keep, or send to a coach.

Time, heart-rate zones and load first, distance last (orienteering). No scripts and no external files, so it
opens anywhere and prints cleanly to PDF from the browser.
"""

import html
from datetime import datetime

import pandas as pd

import notes as nt
import planning as pl
from garmin_sync.tagging import has_tag

KINDS = {"week": "Week", "month": "Month"}


# ---------------------------------------------------------------- periods

def period_bounds(kind: str, anchor) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last day of the week (Monday–Sunday) or calendar month containing `anchor`."""
    d = pd.Timestamp(anchor).normalize()
    if kind == "week":
        start = pl.monday(d)
        return start, start + pd.Timedelta(days=6)
    start = d.replace(day=1)
    return start, start + pd.offsets.MonthEnd(0)


def shift(kind: str, start: pd.Timestamp, n: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The period `n` periods after (negative: before) the one starting at `start`."""
    if kind == "week":
        return period_bounds(kind, start + pd.Timedelta(weeks=n))
    return period_bounds(kind, start + pd.DateOffset(months=n))


def period_starts(kind: str, first_day, today, limit: int = 104) -> list[pd.Timestamp]:
    """Starts of every period from today back to the one with `first_day`, newest first."""
    start, _ = period_bounds(kind, today)
    first, _ = period_bounds(kind, first_day)
    out = []
    while start >= first and len(out) < limit:
        out.append(start)
        start, _ = shift(kind, start, -1)
    return out


def title(kind: str, start: pd.Timestamp, end: pd.Timestamp) -> str:
    if kind == "month":
        return f"{start:%B %Y}"
    when = f"{start:%d} – {end:%d %b %Y}" if start.month == end.month else f"{start:%d %b} – {end:%d %b %Y}"
    return f"Week {start.isocalendar().week}, {when}"


# ---------------------------------------------------------------- numbers

def totals(a: pd.DataFrame) -> dict:
    z = a[["easy_s", "moderate_s", "hard_s"]].sum()
    return {"hours": a["hours"].sum(), "sessions": len(a), "load": a["load"].fillna(0).sum(),
            "km": a["distance_m"].fillna(0).sum() / 1000, "climb": a["elev_gain_m"].fillna(0).sum(),
            "easy": z["easy_s"], "moderate": z["moderate_s"], "hard": z["hard_s"], "zone_total": z.sum(),
            "o": int(has_tag(a, ["o_race", "o_training"]).sum()), "races": int(has_tag(a, ["o_race"]).sum()),
            "hard_sessions": int(pl.is_hard(a).sum()) if len(a) else 0}


def _between(df: pd.DataFrame, col: str, start, end) -> pd.DataFrame:
    return df[(df[col] >= start) & (df[col] <= end)]


def recovery(daily: pd.DataFrame, start, end) -> dict:
    d = _between(daily, "date", start, end) if not daily.empty else daily
    if d.empty:
        return {}
    return {"rhr": d["resting_hr"].mean(), "hrv": d["hrv_overnight_avg"].mean(), "sleep": (d["sleep_s"] / 3600).mean()}


# ---------------------------------------------------------------- html helpers

def _e(v) -> str:
    return html.escape("" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))


def _hm(seconds) -> str:
    if seconds is None or pd.isna(seconds):
        return "–"
    m = int(round(seconds / 60))
    return f"{m // 60}:{m % 60:02d}"


def _delta(now: float, before: float | None, unit: str = "", digits: int = 0) -> str:
    if before is None or pd.isna(before) or pd.isna(now):
        return ""
    diff = now - before
    if round(diff, digits) == 0:
        return '<span class="d">same</span>'
    return f'<span class="d">{diff:+.{digits}f}{unit}</span>'


def _pct(a, b) -> str:
    return f"{100 * a / b:.0f}%" if b else "–"


def _day_chart(a: pd.DataFrame, start, end, kind: str, labels: dict, colors: dict) -> str:
    """Inline SVG: hours per day, stacked by main tag."""
    days = pd.date_range(start, end, freq="D")
    piv = (a.pivot_table(index="day", columns="tag", values="hours", aggfunc="sum")
           .reindex(days).fillna(0) if not a.empty else pd.DataFrame(index=days))
    top = max(1.0, float(piv.sum(axis=1).max()) if len(piv.columns) else 1.0)
    top = float(int(top) + 1) if top > int(top) else top  # whole hours on the axis
    w, h, left, bottom = 680, 150, 34, 20
    slot = (w - left) / len(days)
    bw = max(4.0, slot * 0.7)
    scale = (h - bottom - 6) / top
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Hours per day">']
    for frac in (0.5, 1.0):
        y = h - bottom - top * frac * scale
        parts.append(f'<line x1="{left}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{left - 6}" y="{y + 4:.1f}" class="ax" text-anchor="end">{top * frac:g} h</text>')
    parts.append(f'<line x1="{left}" x2="{w}" y1="{h - bottom}" y2="{h - bottom}" class="base"/>')
    for i, d in enumerate(days):
        x = left + i * slot + (slot - bw) / 2
        y = h - bottom
        for tag in labels:
            v = piv.at[d, tag] if tag in piv.columns else 0
            if v > 0:
                bh = v * scale
                y -= bh
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2" '
                             f'fill="{colors.get(tag, "#8a8984")}"><title>{d:%a %d %b}: {labels[tag]} {v:.1f} h</title></rect>')
        if kind == "week" or d.day == 1 or d.day % 5 == 0:
            text = f"{d:%a}" if kind == "week" else f"{d.day}"
            parts.append(f'<text x="{x + bw / 2:.1f}" y="{h - 5}" class="ax" text-anchor="middle">{text}</text>')
    parts.append("</svg>")
    return "".join(parts)


CSS = """
:root{--text:#1f1e1c;--muted:#6b6a65;--line:#e4e3de;--cell:#f7f7f5;--accent:#2a78d6;
  --easy:#86b6ef;--moderate:#2a78d6;--hard:#104281}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 16px 40px}
h1{font-size:24px;margin:0 0 2px}
h2{font-size:16px;margin:28px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.sub{color:var(--muted);margin:0 0 18px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}
.kpi{background:var(--cell);border-radius:8px;padding:10px 12px}
.kpi b{display:block;font-size:20px}
.kpi small,.d{color:var(--muted);font-size:12px}
.kpi .d{display:block}
ul{margin:6px 0;padding-left:20px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line);padding:4px 6px}
td{border-bottom:1px solid var(--line);padding:4px 6px;vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:baseline}
.zones{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:6px 0}
.zones div{color:#fff;font-size:12px;line-height:22px;padding-left:6px;white-space:nowrap;overflow:hidden}
.legend{color:var(--muted);font-size:12px}
svg .grid{stroke:var(--line)} svg .base{stroke:#c9c8c2} svg .ax{fill:var(--muted);font-size:11px}
footer{margin-top:32px;color:var(--muted);font-size:12px}
@media print{main{padding:0}h2{break-after:avoid}tr{break-inside:avoid}@page{margin:14mm}}
"""


# ---------------------------------------------------------------- the report

def build(kind: str, start: pd.Timestamp, acts: pd.DataFrame, daily: pd.DataFrame, notes: pd.DataFrame,
          races: pd.DataFrame, plans: pd.DataFrame, labels: dict, colors: dict) -> str:
    """The whole report as an HTML document. `acts` = all activities (load_activities), `labels`/`colors` per tag."""
    start, end = period_bounds(kind, start)
    unit = "week" if kind == "week" else "month"
    a = _between(acts, "day", start, end).sort_values("start")
    t = totals(a)
    p_start, p_end = shift(kind, start, -1)
    p = totals(_between(acts, "day", p_start, p_end))
    four = [totals(_between(acts, "day", *shift(kind, start, -k))) for k in range(1, 5)]
    avg4 = {k: sum(x[k] for x in four) / 4 for k in ("hours", "sessions", "load")}

    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Training report · {_e(title(kind, start, end))}</title><style>{CSS}</style></head><body><main>",
           f"<h1>Training report · {_e(title(kind, start, end))}</h1>",
           f"<p class='sub'>{start:%a %d %b} – {end:%a %d %b %Y}. Compared with the previous {unit} "
           f"and with the average of the 4 {unit}s before.</p>"]

    def kpi(label, value, now, key, unit_txt="", digits=0):
        avg = f"<small>4-{unit} avg {avg4[key]:.{digits}f}{unit_txt}</small>" if key in avg4 else ""
        return (f"<div class='kpi'><small>{label}</small><b>{value}</b>"
                f"{_delta(now, p[key], unit_txt, digits)}{avg}</div>")

    out.append("<div class='kpis'>"
               + kpi("Training time", f"{t['hours']:.1f} h", t["hours"], "hours", " h", 1)
               + kpi("Sessions", t["sessions"], t["sessions"], "sessions")
               + kpi("Load", f"{t['load']:.0f}", t["load"], "load")
               + kpi("Orienteering", t["o"], t["o"], "o")
               + kpi("Hard sessions", t["hard_sessions"], t["hard_sessions"], "hard_sessions")
               + kpi("Climb", f"{t['climb']:.0f} m", t["climb"], "climb", " m")
               + "</div>")

    # Highlights in words.
    hl = []
    if a.empty:
        hl.append(f"No training recorded this {unit}.")
    else:
        top = a.sort_values("load", ascending=False, na_position="last").iloc[0]
        hl.append(f"Biggest session: <b>{_e(top['name'] or top['sport_type'])}</b> on {top['start']:%a %d %b} "
                  f"({_hm(top['duration_s'])}, load {0 if pd.isna(top['load']) else top['load']:.0f}).")
        longest = a.sort_values("duration_s", ascending=False).iloc[0]
        if longest["activity_id"] != top["activity_id"]:
            hl.append(f"Longest: <b>{_e(longest['name'] or longest['sport_type'])}</b> ({_hm(longest['duration_s'])}).")
        if t["o"]:
            hl.append(f"{t['o']} orienteering session{'s' if t['o'] != 1 else ''}"
                      + (f", of which {t['races']} race{'s' if t['races'] != 1 else ''}." if t["races"] else "."))
        rest = len(pd.date_range(start, min(end, pd.Timestamp.today().normalize()))) - a["day"].nunique()
        if rest > 0:
            hl.append(f"{rest} day{'s' if rest != 1 else ''} without training.")
    for _, n in nt.in_range(notes, start, end).iterrows():
        hl.append(f"Note: {_e(nt.describe(n))}.")
    out.append("<h2>Highlights</h2><ul>" + "".join(f"<li>{x}</li>" for x in hl) + "</ul>")

    if not a.empty:
        out.append("<h2>Training per day</h2>" + _day_chart(a, start, end, kind, labels, colors))

    # Intensity.
    if t["zone_total"] > 0:
        z = [("Easy Z1–2", t["easy"], "var(--easy)"), ("Moderate Z3", t["moderate"], "var(--moderate)"),
             ("Hard Z4–5", t["hard"], "var(--hard)")]
        bar = "".join(f"<div style='width:{100 * v / t['zone_total']:.1f}%;background:{col}'>"
                      f"{_pct(v, t['zone_total']) if v / t['zone_total'] > 0.08 else ''}</div>" for _, v, col in z)
        prev = (f" Previous {unit}: easy {_pct(p['easy'], p['zone_total'])}, hard {_pct(p['hard'], p['zone_total'])}."
                if p["zone_total"] else "")
        out.append("<h2>Intensity</h2><div class='zones'>" + bar + "</div><p class='legend'>"
                   + " · ".join(f"{name} {_hm(v)} ({_pct(v, t['zone_total'])})" for name, v, _ in z) + "." + prev + "</p>")

    # Per tag (main tag; extra tags counted separately so no time is counted twice).
    if not a.empty:
        by = a.groupby("tag").agg(n=("activity_id", "count"), hours=("hours", "sum"), load=("load", "sum"))
        extra = pd.Series([x for xs in a["extras"] for x in xs], dtype=object).value_counts() if "extras" in a else pd.Series(dtype=int)
        rows = []
        for tag in [k for k in labels if k in by.index or k in extra.index]:
            r = by.loc[tag] if tag in by.index else {"n": 0, "hours": 0.0, "load": 0.0}
            rows.append(f"<tr><td><span class='sw' style='background:{colors.get(tag, '#8a8984')}'></span>{_e(labels[tag])}</td>"
                        f"<td class='n'>{int(r['n'])}</td><td class='n'>{r['hours']:.1f} h</td>"
                        f"<td class='n'>{_pct(r['hours'], t['hours'])}</td><td class='n'>{r['load']:.0f}</td>"
                        f"<td class='n'>{int(extra.get(tag, 0)) or ''}</td></tr>")
        out.append("<h2>Per tag</h2><table><tr><th>Tag</th><th class='n'>Sessions</th><th class='n'>Time</th>"
                   "<th class='n'>Share</th><th class='n'>Load</th><th class='n'>Also as extra tag</th></tr>"
                   + "".join(rows) + "</table>")

    # Plan vs actual (weekly plans).
    if kind == "week" and start in plans.index:
        plan = plans.loc[start]
        actual = {"hours": f"{t['hours']:.1f} h", "sessions": t["sessions"], "o_sessions": t["o"],
                  "hard_sessions": t["hard_sessions"]}
        names = {"hours": "Time", "sessions": "Sessions", "o_sessions": "Orienteering", "hard_sessions": "Hard sessions"}
        rows = "".join(f"<tr><td>{names[k]}</td><td class='n'>{plan[k]:g}{' h' if k == 'hours' else ''}</td>"
                       f"<td class='n'>{actual[k]}</td></tr>" for k in names if pd.notna(plan[k]))
        if rows:
            note = f"<p class='legend'>Plan note: {_e(plan['notes'])}</p>" if isinstance(plan["notes"], str) and plan["notes"] else ""
            out.append("<h2>Plan vs actual</h2><table><tr><th></th><th class='n'>Planned</th><th class='n'>Done</th></tr>"
                       + rows + "</table>" + note)

    # Races in the period.
    rr = races[(races["date"] <= end) & (races["end_date"] >= start)] if not races.empty else races
    if len(rr):
        out.append("<h2>Races</h2><ul>" + "".join(
            f"<li><b>{_e(r['name'])}</b> ({_e(pl.fmt_dates(r))}, {_e(pl.PRIORITIES.get(r['priority'], r['priority']))})"
            + (f": goal {_e(r['goal'])}" if isinstance(r["goal"], str) and r["goal"] else "") + "</li>"
            for _, r in rr.iterrows()) + "</ul>")

    # Recovery.
    rc, rp = recovery(daily, start, end), recovery(daily, p_start, p_end)
    if rc:
        items = [("Resting HR", "rhr", " bpm", 0), ("HRV (night)", "hrv", " ms", 0), ("Sleep", "sleep", " h", 1)]
        cells = "".join(f"<div class='kpi'><small>{name}</small><b>{rc[k]:.{dg}f}{u}</b>{_delta(rc[k], rp.get(k), u, dg)}</div>"
                        for name, k, u, dg in items if pd.notna(rc.get(k)))
        if cells:
            out.append(f"<h2>Recovery (average per day)</h2><div class='kpis'>{cells}</div>")

    # Sessions.
    if not a.empty:
        rows = "".join(
            f"<tr><td>{r['start']:%a %d %b}</td><td>{_e(r['name'] or r['sport_type'])}</td>"
            f"<td>{_e(' + '.join(labels.get(x, x) for x in [r['tag'], *r.get('extras', [])]))}</td>"
            f"<td class='n'>{_hm(r['duration_s'])}</td><td class='n'>{'' if pd.isna(r['avg_hr']) else f'{r.avg_hr:.0f}'}</td>"
            f"<td class='n'>{_hm(r['hard_s']) if r['hard_s'] else ''}</td>"
            f"<td class='n'>{'' if pd.isna(r['load']) else f'{r.load:.0f}'}</td>"
            f"<td class='n'>{'' if pd.isna(r['distance_m']) or not r['distance_m'] else f'{r.distance_m / 1000:.1f}'}</td></tr>"
            for _, r in a.iterrows())
        out.append("<h2>Sessions</h2><table><tr><th>Day</th><th>Session</th><th>Tag</th><th class='n'>Time</th>"
                   "<th class='n'>Avg HR</th><th class='n'>Z4–5</th><th class='n'>Load</th><th class='n'>km</th></tr>"
                   + rows + "</table>")

    out.append(f"<footer>Made {datetime.now():%d %b %Y %H:%M} from Garmin data. Load = Garmin training load "
               "(heart-rate TRIMP when Garmin has none). Hard session = interval, race or 10+ min in Z4–5.</footer>"
               "</main></body></html>")
    return "".join(out)
