"""Intensity distribution: time in HR zones per week, easy/hard balance."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c

c.setup_page("Intensity", "❤️")
tags = c.tag_filter_sidebar()
acts = c.filter_tags(c.load_activities(), tags)
c.require_data(acts)

ctrl = st.columns([3, 2])
with ctrl[0]:
    days = c.period_selector("Period", {"3 months": 91, "6 months": 182, "12 months": 365, "All": 100_000},
                             "6 months", "int_period")
with ctrl[1]:
    model = st.segmented_control("Zones", ["3 zones", "5 zones"], default="3 zones", key="int_model") or "3 zones"

today = pd.Timestamp.today().normalize()
this_monday = today - pd.Timedelta(days=today.weekday())
since = this_monday - pd.Timedelta(days=days)
period = acts[acts["week_start"] >= since]
week_index = pd.date_range(max(since, acts["week_start"].min()), this_monday, freq="7D")

if model == "5 zones":
    cols = {f"z{i}_s": (f"Zone {i}", c.ZONE_COLORS[i - 1]) for i in range(1, 6)}
else:
    cols = {f"{k}_s": (c.ZONE3_LABELS[k], c.ZONE3_COLORS[k]) for k in ("easy", "moderate", "hard")}

weekly = period.groupby("week_start")[list(cols)].sum().reindex(week_index, fill_value=0).fillna(0) / 3600

# ---------------------------------------------------------------- time in zones per week
st.subheader("Time in heart-rate zones per week")
fig = go.Figure()
for col, (label, color) in cols.items():
    fig.add_bar(x=weekly.index, y=weekly[col], name=label, marker_color=color, hovertemplate="%{y:.1f} h")
fig.update_layout(barmode="stack")
c.show(c.style_fig(fig, height=380, y_title="hours per week"))

# ---------------------------------------------------------------- easy share trend
z = period.groupby("week_start")[["easy_s", "moderate_s", "hard_s"]].sum().reindex(week_index, fill_value=0)
z_total = z.sum(axis=1)
share = pd.DataFrame({k: 100 * z[f"{k}_s"] / z_total for k in ("easy", "moderate", "hard")}).where(z_total > 0)

left, right = st.columns([3, 2])
with left:
    st.subheader("Easy vs hard share")
    fig = go.Figure()
    fig.add_scatter(x=share.index, y=share["easy"], name=c.ZONE3_LABELS["easy"], mode="lines+markers",
                    line=dict(color=c.ZONE3_COLORS["easy"], width=2), marker=dict(size=8), hovertemplate="%{y:.0f}%")
    fig.add_scatter(x=share.index, y=share["hard"], name=c.ZONE3_LABELS["hard"], mode="lines+markers",
                    line=dict(color=c.ZONE3_COLORS["hard"], width=2), marker=dict(size=8), hovertemplate="%{y:.0f}%")
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    c.show(c.style_fig(fig, height=320, y_title="share of zone time"))

with right:
    st.subheader("Selected period")
    tot = period[["easy_s", "moderate_s", "hard_s"]].sum()
    total = tot.sum()
    if total == 0:
        st.info("No heart-rate zone data in this period.")
    else:
        pct = 100 * tot / total
        m = st.columns(3)
        m[0].metric("Easy (Z1–2)", f"{pct['easy_s']:.0f}%", border=True)
        m[1].metric("Moderate (Z3)", f"{pct['moderate_s']:.0f}%", border=True)
        m[2].metric("Hard (Z4–5)", f"{pct['hard_s']:.0f}%", border=True)
        if pct["easy_s"] >= 75 and pct["hard_s"] > pct["moderate_s"]:
            verdict = "**Polarised**: mostly easy, and more hard than moderate work."
        elif pct["easy_s"] >= 75:
            verdict = "**Pyramidal**: mostly easy, with more moderate than hard work."
        elif pct["moderate_s"] >= pct["hard_s"] and pct["moderate_s"] >= 20:
            verdict = "**Threshold-heavy**: a large share of moderate (Z3) time."
        else:
            verdict = "**High intensity share**: less than 75% easy."
        st.markdown(verdict)
        st.caption(f"Based on {total / 3600:.1f} h of heart-rate zone time in {len(period)} sessions. "
                   "Time below Zone 1 is not counted.")

# ---------------------------------------------------------------- by tag
st.subheader("Zone split per tag")
by_tag = period.groupby("tag")[["easy_s", "moderate_s", "hard_s"]].sum()
by_tag = by_tag[by_tag.sum(axis=1) > 0]
if not by_tag.empty:
    pct = by_tag.div(by_tag.sum(axis=1), axis=0) * 100
    order = [t for t in c.TAG_COLORS if t in pct.index]
    fig = go.Figure()
    for k in ("easy", "moderate", "hard"):
        fig.add_bar(y=[c.TAG_LABELS[t] for t in order], x=pct.loc[order, f"{k}_s"], orientation="h",
                    name=c.ZONE3_LABELS[k], marker_color=c.ZONE3_COLORS[k], hovertemplate="%{x:.0f}%")
    fig.update_layout(barmode="stack", hovermode="y unified")
    fig.update_xaxes(range=[0, 100], ticksuffix="%")
    c.show(c.style_fig(fig, height=80 + 45 * len(order)).update_layout(hovermode="y unified"))
