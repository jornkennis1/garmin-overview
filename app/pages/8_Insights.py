"""Insights: long-term trends (aerobic efficiency, resting HR, VO2 max) and personal records."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c
import insights

c.setup_page("Insights", "💡")
c.sidebar()  # trends and records always use all activities
acts = c.load_activities()
c.require_data(acts)
daily = c.load_daily()
today = pd.Timestamp.today().normalize()
st.caption("Long-term trends and records over all your activities. For how you're doing right now, see **Today**.")

# ---------------------------------------------------------------- trends
st.subheader("Trends")
eff = insights.efficiency(acts)
items = insights.trend_insights(eff, daily, today)
if items:
    insights.render(items)
else:
    st.caption("Not enough history yet to compare with a year ago.")

monthly = pd.DataFrame()
if not daily.empty:
    monthly = (daily.assign(month=daily["date"].dt.to_period("M").dt.to_timestamp())
               .groupby("month").agg(resting_hr=("resting_hr", "median"), vo2max=("vo2max", "mean"),
                                     hrv=("hrv_overnight_avg", "median")))


def trend_chart(x, y, title: str, hover: str, help_text: str) -> None:
    st.markdown(f"**{title}**", help=help_text)
    s = pd.Series(list(y), index=list(x)).dropna() if y is not None else pd.Series(dtype=float)
    if s.empty:
        st.caption("No data yet.")
        return
    x, y = s.index, s.values
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers", connectgaps=True, hovertemplate=hover + "<extra></extra>",
                               line=dict(color=c.SERIES_MAIN, width=2), marker=dict(size=8)))
    c.show(c.style_fig(fig, height=240, legend=False))


t = st.columns(3)
with t[0]:
    trend_chart(eff["month"], eff["m_per_beat"], "Aerobic efficiency (m per heartbeat)", "%{y:.2f} m/beat",
                "Easy and long runs of 20+ minutes: average speed divided by average heart rate, median per month. "
                "Higher = more distance for the same effort. Terrain and heat add noise.")
with t[1]:
    trend_chart(monthly.index if not monthly.empty else [], monthly.get("resting_hr"), "Resting HR (monthly median)",
                "%{y:.0f} bpm", "Lower usually means better aerobic fitness and recovery.")
with t[2]:
    trend_chart(monthly.index if not monthly.empty else [], monthly.get("vo2max"), "VO2 max (monthly average)",
                "%{y:.1f}", "Garmin's estimate from pace and heart rate; only updated on runs and rides with GPS.")

# ---------------------------------------------------------------- records
st.subheader("Personal records")
rec = insights.records(acts, daily)
if rec.empty:
    st.caption("No records yet.")
else:
    st.dataframe(rec, hide_index=True, width="stretch",
                 column_config={"Open": st.column_config.LinkColumn("Details", display_text="open")})
    st.caption("Records use all activities, including FIT imports. Rename an activity on the Activity page to make "
               "this list easier to read.")
