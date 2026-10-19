"""Overview: this week vs recent weeks, weekly volume and load (part of `streamlit run app/Dashboard.py`)."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c
import insights
import planning
from garmin_sync.metrics import load_curves

c.setup_page("Overview")
tags = c.tag_filter_sidebar()
acts_all = c.load_activities()
c.require_data(acts_all)
acts = c.filter_tags(acts_all, tags)

today = pd.Timestamp.today().normalize()
this_monday = today - pd.Timedelta(days=today.weekday())

# ---------------------------------------------------------------- weekly table (tag-filtered)
first_week = acts_all["week_start"].min()
week_index = pd.date_range(first_week, this_monday, freq="7D")
weekly = (
    acts.groupby("week_start")
    .agg(hours=("hours", "sum"), sessions=("activity_id", "count"), load=("load", "sum"),
         easy_s=("easy_s", "sum"), moderate_s=("moderate_s", "sum"), hard_s=("hard_s", "sum"))
    .reindex(week_index, fill_value=0)
)
zone_total = weekly[["easy_s", "moderate_s", "hard_s"]].sum(axis=1)
weekly["pct_easy"] = (100 * weekly["easy_s"] / zone_total).where(zone_total > 0)

cur = weekly.loc[this_monday]
prev4 = weekly.loc[this_monday - pd.Timedelta(days=28): this_monday - pd.Timedelta(days=7)]
last = weekly.loc[this_monday - pd.Timedelta(days=7)] if len(prev4) else None


def delta(value, ref, fmt="{:+.1f}"):
    return None if ref is None or pd.isna(ref) or pd.isna(value) else fmt.format(value - ref)


st.subheader(f"This week  ·  {this_monday:%d %b} – {today:%d %b}")
cols = st.columns(4)
cols[0].metric("Training time", c.fmt_hours(cur["hours"]), delta(cur["hours"], prev4["hours"].mean(), "{:+.1f} h"),
               help="Compared with the average of the previous 4 full weeks.", border=True)
cols[1].metric("Sessions", int(cur["sessions"]), delta(cur["sessions"], prev4["sessions"].mean()), border=True,
               help="Compared with the average of the previous 4 full weeks.")
cols[2].metric("Training load", f"{cur['load']:.0f}", delta(cur["load"], prev4["load"].mean(), "{:+.0f}"), border=True,
               help="Garmin training load per activity (TRIMP where Garmin load is missing), summed.")
cols[3].metric("Easy share (Z1–2)", "–" if pd.isna(cur["pct_easy"]) else f"{cur['pct_easy']:.0f}%",
               delta(cur["pct_easy"], prev4["pct_easy"].mean(), "{:+.0f} pp"), delta_color="off", border=True,
               help="Share of heart-rate zone time spent in Z1–Z2.")
if last is not None:
    st.caption(
        f"Last week: {c.fmt_hours(last['hours'])}, {int(last['sessions'])} sessions, load {last['load']:.0f}.  "
        f"4-week average: {c.fmt_hours(prev4['hours'].mean())}, {prev4['sessions'].mean():.1f} sessions, "
        f"load {prev4['load'].mean():.0f}."
    )

with st.container(border=True):
    st.markdown(insights.week_summary(acts, today))
    _plan = planning.load_plans()
    if this_monday in _plan.index and pd.notna(_plan.loc[this_monday, "hours"]):
        _p = _plan.loc[this_monday]
        _done = acts_all[acts_all["week_start"] == this_monday]["hours"].sum()
        st.markdown(f"**Plan this week**: {_p['hours']:.1f} h, {_done:.1f} h done so far"
                    + (f" · *{_p['notes']}*" if _p["notes"] else "") + ". Edit it on the **Plan** page.")

# ---------------------------------------------------------------- weekly volume by tag
st.subheader("Weekly volume")
days = c.period_selector("Period", {"6 months": 182, "9 months": 273, "12 months": 365, "All": 100_000},
                         "12 months", "ov_period")
since = this_monday - pd.Timedelta(days=days)
period_acts = acts[acts["week_start"] >= since]
vol = period_acts.pivot_table(index="week_start", columns="tag", values="hours", aggfunc="sum", fill_value=0)
vol = vol.reindex(week_index[week_index >= since], fill_value=0)

fig = go.Figure()
for tag, color in c.TAG_COLORS.items():
    if tag in vol.columns and vol[tag].sum() > 0:
        fig.add_bar(x=vol.index, y=vol[tag], name=c.TAG_LABELS[tag], marker_color=color,
                    hovertemplate="%{y:.1f} h")
total = vol.sum(axis=1)
fig.add_scatter(x=total.index, y=total.rolling(4, min_periods=1).mean(), name="4-week average",
                mode="lines", line=dict(color=c.AVG_LINE, width=2, dash="dot"), hovertemplate="%{y:.1f} h")
fig.update_layout(barmode="stack")
c.show(c.style_fig(fig, height=380, y_title="hours per week"))

# ---------------------------------------------------------------- load
left, right = st.columns(2)
with left:
    st.subheader("Weekly training load")
    wl = weekly.loc[weekly.index >= since, "load"]
    fig = go.Figure(go.Bar(x=wl.index, y=wl, name="Load", marker_color=c.SERIES_MAIN, hovertemplate="%{y:.0f}"))
    c.show(c.style_fig(fig, height=300, y_title="load per week", legend=False))
with right:
    st.subheader("Fitness & fatigue")
    daily_load = acts_all.groupby("day")["load"].sum()
    curves = load_curves(daily_load)
    curves = curves[curves.index >= since]
    fig = go.Figure()
    fig.add_scatter(x=curves.index, y=curves["ctl"], name="Fitness (42-day load)", mode="lines",
                    line=dict(color=c.SERIES_MAIN, width=2), hovertemplate="%{y:.0f}")
    fig.add_scatter(x=curves.index, y=curves["atl"], name="Fatigue (7-day load)", mode="lines",
                    line=dict(color=c.SERIES_SECOND, width=2), hovertemplate="%{y:.0f}")
    c.show(c.style_fig(fig, height=300, y_title="average daily load"))
    st.caption("Uses all activities regardless of the tag filter. Fatigue well above fitness = a hard block.")

# ---------------------------------------------------------------- recent sessions
st.subheader("Recent sessions")
recent = acts.sort_values("start", ascending=False).head(12)
st.dataframe(
    pd.DataFrame({
        "Date": recent["start"].dt.strftime("%a %d %b %H:%M"),
        "Sport": recent["sport_type"].map(c.sport_label),
        "Tag": recent["tag"].map(c.TAG_LABELS),
        "Time": recent["duration_s"].map(c.fmt_duration),
        "Avg HR": recent["avg_hr"].round(0),
        "Load": recent["load"].round(0),
        "Climb (m)": recent["elev_gain_m"].round(0),
        "Open": "/Activity?id=" + recent["activity_id"].astype(str),
    }),
    hide_index=True,
    column_config={"Open": st.column_config.LinkColumn("Details", display_text="open")},
)
