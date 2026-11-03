"""Calendar: month grid of activities, coloured by tag or by load, with weekly totals, races and notes."""

import calendar
import html

import pandas as pd
import streamlit as st

import common as c
import notes as nt
import planning as pl

c.setup_page("Calendar", "📅")
tags = c.sidebar()
acts = c.filter_tags(c.load_activities(), tags)

today = pd.Timestamp.today().normalize()
if "cal_month" not in st.session_state:
    # The month is kept in the URL so "back" from an activity returns to the same month.
    try:
        st.session_state["cal_month"] = pd.Timestamp(st.query_params.get("month", "") + "-01")
    except ValueError:
        st.session_state["cal_month"] = today.replace(day=1)


def shift(months: int):
    st.session_state["cal_month"] = (st.session_state["cal_month"] + pd.DateOffset(months=months)).replace(day=1)


nav = st.columns([1, 1, 1, 3, 3], vertical_alignment="center")
nav[0].button("◀ Prev", on_click=shift, args=(-1,), width="stretch")
nav[1].button("Today", on_click=lambda: st.session_state.update(cal_month=today.replace(day=1)), width="stretch")
nav[2].button("Next ▶", on_click=shift, args=(1,), width="stretch")
month = st.session_state["cal_month"]
st.query_params["month"] = f"{month:%Y-%m}"
nav[3].markdown(f"### {month:%B %Y}")
color_by = nav[4].segmented_control("Colour by", ["Tag", "Load"], default="Tag", key="cal_color") or "Tag"

# ---------------------------------------------------------------- build grid
grid_start = month - pd.Timedelta(days=month.weekday())
month_end = month + pd.offsets.MonthEnd(0)
grid_end = month_end + pd.Timedelta(days=6 - month_end.weekday())
in_grid = acts[(acts["day"] >= grid_start) & (acts["day"] <= grid_end)].sort_values("start")
by_day = {d: g for d, g in in_grid.groupby("day")}
# Planned races (Plan page), on every day of a multi-day race; shown regardless of the tag filter.
rd = pl.race_days(pl.load_races())
races_by_day = {d: g for d, g in rd[(rd["day"] >= grid_start) & (rd["day"] <= grid_end)].groupby("day")}
# Injury / illness / holiday notes, edited below the calendar.
all_notes = nt.load_notes()
nd = nt.note_days(all_notes)
notes_by_day = {d: g for d, g in nd[(nd["day"] >= grid_start) & (nd["day"] <= grid_end)].groupby("day")}
NOTE_COLORS = {"injury": c.HR_LINE, "illness": c.SERIES_SECOND, "holiday": c.TEXT_MUTED, "other": c.TEXT_MUTED}

CSS = f"""
<style>
.cal{{width:100%;border-collapse:separate;border-spacing:4px;table-layout:fixed;font-size:13px;color:{c.TEXT}}}
.cal th{{color:{c.TEXT_MUTED};font-weight:600;text-align:left;padding:2px 6px}}
.cal td{{vertical-align:top;background:{c.CELL_BG};border-radius:8px;padding:6px;height:110px}}
.cal td.out{{opacity:.45}}
.cal td.today{{outline:2px solid {c.SERIES_MAIN}}}
.cal td.week{{background:{c.WEEK_BG};width:11%}}
.cal .dn{{color:{c.TEXT_MUTED};font-weight:600;margin-bottom:4px}}
.cal a.act{{display:block;text-decoration:none;color:{c.TEXT};border-radius:6px;
  background:var(--c) left top / 6px 100% no-repeat, {c.CHIP_BG};padding:3px 6px 3px 12px;margin-bottom:4px;line-height:1.25}}
.cal a.act:hover{{box-shadow:0 1px 4px rgba(0,0,0,.25)}}
.cal a.act small{{color:{c.TEXT_MUTED}}}
.cal a.race{{display:block;text-decoration:none;color:{c.TEXT};border:1.5px dashed {c.TAG_COLORS["o_race"]};
  border-radius:6px;padding:2px 6px;margin-bottom:4px;font-weight:600;line-height:1.25;overflow-wrap:anywhere}}
.cal a.race small{{color:{c.TEXT_MUTED};font-weight:400}}
.legend .flag{{color:{c.TAG_COLORS["o_race"]};font-weight:700}}
.cal div.note{{color:{c.TEXT};border-left:3px solid var(--c);background:{c.CHIP_BG};border-radius:4px;
  padding:2px 6px;margin-bottom:4px;line-height:1.25;overflow-wrap:anywhere}}
.cal div.note small{{color:{c.TEXT_MUTED}}}
.legend .ni{{color:var(--c);font-weight:700}}
.cal .wk b{{font-size:15px}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;margin:6px 0 2px;font-size:13px;color:{c.TEXT}}}
.legend span{{display:inline-flex;align-items:center;gap:6px}}
.legend i{{width:12px;height:12px;border-radius:3px;display:inline-block;background:var(--c)}}
</style>
"""


def chip(a) -> str:
    color = c.swatch_css(a["tag"]) if color_by == "Tag" else f"linear-gradient({(lc := c.load_bucket_color(a['load']))}, {lc})"
    hr = f" · {a['avg_hr']:.0f} bpm" if pd.notna(a["avg_hr"]) else ""
    load = f" · load {a['load']:.0f}" if pd.notna(a["load"]) else ""
    title = html.escape(f"{a['name'] or ''} — {c.tag_text(a)}")
    return (
        f'<a class="act" style="--c:{color}" href="/Activity?id={a["activity_id"]}" target="_self" title="{title}">'
        f"<b>{c.fmt_duration(a['duration_s'])}</b> {html.escape(c.sport_label(a['sport_type']))}"
        f"<br><small>{a['start']:%H:%M}{hr}{load}</small></a>"
    )


def race_banner(r) -> str:
    multi = f" · day {r['day_no']}/{r['days']}" if r["days"] > 1 else ""
    title = html.escape(f"{r['name']} ({pl.PRIORITIES.get(r['priority'], r['priority'])}){multi}"
                        + (f" · goal: {r['goal']}" if isinstance(r["goal"], str) and r["goal"] else ""))
    return (f'<a class="race" href="/Plan" target="_self" title="{title}">⚑ {html.escape(r["name"])} '
            f'<small>({r["priority"]}){multi}</small></a>')


def note_banner(n, day) -> str:
    multi = f" · day {(day - n['date']).days + 1}/{n['days']}" if n["days"] > 1 else ""
    text = n["text"] if isinstance(n["text"], str) and n["text"] else nt.KINDS[n["kind"]]
    return (f'<div class="note" style="--c:{NOTE_COLORS.get(n["kind"], c.TEXT_MUTED)}" title="{html.escape(nt.describe(n))}">'
            f'{nt.ICONS.get(n["kind"], "")} {html.escape(text)}<small>{multi}</small></div>')


rows = ['<table class="cal"><tr>' + "".join(f"<th>{d}</th>" for d in calendar.day_abbr) + "<th>Week</th></tr>"]
day = grid_start
while day <= grid_end:
    cells = []
    week_acts = in_grid[(in_grid["day"] >= day) & (in_grid["day"] < day + pd.Timedelta(days=7))]
    for _ in range(7):
        cls = []
        if day.month != month.month:
            cls.append("out")
        if day == today:
            cls.append("today")
        content = "".join(note_banner(n, day) for _, n in notes_by_day[day].iterrows()) if day in notes_by_day else ""
        content += "".join(race_banner(r) for _, r in races_by_day[day].iterrows()) if day in races_by_day else ""
        content += "".join(chip(a) for _, a in by_day[day].iterrows()) if day in by_day else ""
        cells.append(f'<td class="{" ".join(cls)}"><div class="dn">{day.day}</div>{content}</td>')
        day += pd.Timedelta(days=1)
    wk = (
        f'<td class="week"><div class="wk"><b>{c.fmt_hours(week_acts["hours"].sum())}</b><br>'
        f'{len(week_acts)} sessions<br>load {week_acts["load"].sum():.0f}</div></td>'
    )
    rows.append("<tr>" + "".join(cells) + wk + "</tr>")
rows.append("</table>")

if color_by == "Tag":
    items = [(c.TAG_LABELS[t], c.swatch_css(t)) for t in c.TAG_COLORS]
else:
    bounds = c.LOAD_BUCKETS + [None]
    items = [(f"load {lo}–{hi}" if hi else f"load {lo}+", col)
             for lo, hi, col in zip(bounds, bounds[1:], [f"linear-gradient({x}, {x})" for x in c.LOAD_RAMP])]
legend = ('<div class="legend">' + "".join(f'<span style="--c:{col}"><i></i>{lbl}</span>' for lbl, col in items)
          + '<span><b class="flag">⚑</b> Planned race (add on the Plan page)</span>'
          + "".join(f'<span style="--c:{NOTE_COLORS[k]}"><b class="ni">{nt.ICONS[k]}</b>{lbl}</span>'
                    for k, lbl in nt.KINDS.items() if k != "other")
          + "</div>")

st.html(CSS + legend + "".join(rows))

month_acts = acts[(acts["day"] >= month) & (acts["day"] <= month_end)]
st.caption(
    f"{month:%B}: {c.fmt_hours(month_acts['hours'].sum())} in {len(month_acts)} sessions, "
    f"load {month_acts['load'].sum():.0f}. Click an activity for details."
)

# ---------------------------------------------------------------- notes editor
with st.expander("Injury, illness and holiday notes", icon=":material/healing:"):
    st.caption("Note when you were injured, ill or away, so the breaks make sense later. During an injury, illness "
               "or holiday the **Today** page doesn't warn about missing or light training. For more than one day, "
               "fill in **Until**. Delete a row with the checkbox on the left and the bin icon.")
    editor = all_notes.drop(columns=["days"]).assign(
        date=all_notes["date"].dt.date, end_date=all_notes["end_date"].where(all_notes["days"] > 1).dt.date)
    edited = st.data_editor(
        editor, num_rows="dynamic", hide_index=True, key="note_editor",
        column_order=["date", "end_date", "kind", "text"],
        column_config={
            "date": st.column_config.DateColumn("From", required=True, format="ddd DD MMM YYYY"),
            "end_date": st.column_config.DateColumn("Until", format="ddd DD MMM YYYY",
                                                    help="Last day; leave empty for one day"),
            "kind": st.column_config.SelectboxColumn("Kind", options=list(nt.KINDS), default="illness",
                                                     required=True, format_func=nt.KINDS.get),
            "text": st.column_config.TextColumn("Note", max_chars=200, help="e.g. 'flu', 'sprained ankle', 'ski trip'"),
        },
    )
    if st.button("Save notes", type="primary", key="save_notes",
                 disabled=edited.reset_index(drop=True).equals(editor.reset_index(drop=True))):
        nt.save_notes(edited, all_notes)
        st.session_state.pop("note_editor", None)
        st.toast("Notes saved")
        st.rerun()
