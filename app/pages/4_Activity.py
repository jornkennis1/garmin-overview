"""Activity detail: summary (time, HR, load first), HR / pace / elevation over time, zones, tag editor."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import common as c
from db.database import connect
from garmin_sync.tagging import reset_to_auto, set_manual_tag

c.setup_page("Activity", "🏃")
tags = c.sidebar()
acts_all = c.load_activities()
c.require_data(acts_all)
acts = c.filter_tags(acts_all, tags).sort_values("start", ascending=False)

CYCLING = ("cycling", "biking", "ride")

# ---------------------------------------------------------------- choose activity
qp_id = st.query_params.get("id")
selected_id = int(qp_id) if qp_id and qp_id.lstrip("-").isdigit() else None
options = acts["activity_id"].tolist()
if selected_id is not None and selected_id not in options and selected_id in acts_all["activity_id"].values:
    options = [selected_id] + options
if not options:
    st.info("No activities match the tag filter.")
    st.stop()
labels = acts_all.set_index("activity_id")


def label(aid: int) -> str:
    a = labels.loc[aid]
    return (f"{a['start']:%a %d %b %Y %H:%M} · {c.sport_label(a['sport_type'])} · "
            f"{c.fmt_duration(a['duration_s'])} · {c.TAG_LABELS.get(a['tag'], a['tag'])}")


index = options.index(selected_id) if selected_id in options else 0
aid = st.selectbox("Activity", options, index=index, format_func=label)
if str(aid) != qp_id:
    st.query_params["id"] = str(aid)
a = labels.loc[aid]
is_cycling = any(k in (a["sport_type"] or "") for k in CYCLING)

# ---------------------------------------------------------------- summary (time / HR / load first, pace last)
st.subheader(a["name"] or c.sport_label(a["sport_type"]))
m = st.columns(6)
m[0].metric("Time", c.fmt_duration(a["duration_s"]),
            None if pd.isna(a["moving_s"]) else f"moving {c.fmt_duration(a['moving_s'])}", delta_color="off", border=True)
m[1].metric("Avg HR", "–" if pd.isna(a["avg_hr"]) else f"{a['avg_hr']:.0f} bpm",
            None if pd.isna(a["max_hr"]) else f"max {a['max_hr']:.0f}", delta_color="off", border=True)
m[2].metric("Training load", "–" if pd.isna(a["training_load"]) else f"{a['training_load']:.0f}",
            None if pd.isna(a["trimp"]) else f"TRIMP {a['trimp']:.0f}", delta_color="off", border=True,
            help="Garmin training load (EPOC). TRIMP is the heart-rate-based load computed locally.")
m[3].metric("Training effect", "–" if pd.isna(a["aerobic_te"]) else f"{a['aerobic_te']:.1f} aer",
            None if pd.isna(a["anaerobic_te"]) else f"{a['anaerobic_te']:.1f} anaer", delta_color="off", border=True)
m[4].metric("Climb", "–" if pd.isna(a["elev_gain_m"]) else f"{a['elev_gain_m']:.0f} m",
            None if pd.isna(a["distance_m"]) else f"{a['distance_m'] / 1000:.1f} km", delta_color="off", border=True)
avg_speed = a["distance_m"] / a["moving_s"] if a["moving_s"] and a["distance_m"] else None
m[5].metric("Speed" if is_cycling else "Pace",
            ("–" if not avg_speed else f"{avg_speed * 3.6:.1f} km/h") if is_cycling else c.fmt_pace(avg_speed),
            border=True, help="Pace is a weak measure in orienteering terrain; prefer time, HR and load.")

# ---------------------------------------------------------------- tag editor
with st.container(border=True):
    c.name_editor(a.rename(aid), "act")
    tc = st.columns([3, 1, 1, 3], vertical_alignment="bottom")
    tag_keys = list(c.TAG_LABELS)
    new_tag = tc[0].selectbox("Tag", tag_keys, index=tag_keys.index(a["tag"]) if a["tag"] in tag_keys else 0,
                              format_func=c.TAG_LABELS.get, key=f"tag_{aid}")
    if tc[1].button("Save tag", type="primary", disabled=new_tag == a["tag"] and a["tag_source"] == "manual"):
        conn = connect()
        try:
            set_manual_tag(conn, int(aid), new_tag)
        finally:
            conn.close()
        c.clear_cache()
        st.toast(f"Tagged as {c.TAG_LABELS[new_tag]}")
        st.rerun()
    if tc[2].button("Reset to auto", disabled=a["tag_source"] != "manual"):
        conn = connect()
        try:
            reset_to_auto(conn, int(aid))
        finally:
            conn.close()
        c.clear_cache()
        st.rerun()
    tc[3].caption(f"Current: **{c.TAG_LABELS.get(a['tag'], a['tag'])}** "
                  f"({'set by you' if a['tag_source'] == 'manual' else 'automatic suggestion'})")

# ---------------------------------------------------------------- streams
s = c.load_samples(int(aid))
zones = c.load_zones(int(aid))
laps = c.load_laps(int(aid))
zone_lows = zones["zone_low_bpm"].tolist() if len(zones) == 5 and zones["zone_low_bpm"].notna().all() else None


def hr_zone_color(hr) -> str:
    if hr is None or pd.isna(hr) or not zone_lows:
        return c.MUTED
    return c.ZONE_COLORS[max(0, sum(1 for lo in zone_lows if hr >= lo) - 1)]

if s.empty:
    st.info("No HR/pace stream stored for this activity (run the sync without --no-details).")
else:
    s["min"] = s["t_offset_s"] / 60
    ts = s.set_index(pd.to_timedelta(s["t_offset_s"], unit="s"))
    speed = ts["speed_mps"].rolling("30s", min_periods=1).mean().to_numpy()
    if is_cycling:
        s["pace_val"], pace_title, pace_hover = speed * 3.6, "Speed (km/h)", "%{y:.1f} km/h"
    else:
        pace = 1000 / speed / 60  # min/km
        s["pace_val"] = pd.Series(pace).where((speed > 0.5) & (pace < 15))  # hide stops / walking pauses
        pace_title, pace_hover = "Pace (min/km, smoothed 30 s)", "%{y:.2f} min/km"
    rows = [("Heart rate (bpm)", "hr"), (pace_title, "pace_val"), ("Elevation (m)", "altitude_m")]
    rows = [r for r in rows if s[r[1]].notna().any()]
    fig = make_subplots(rows=len(rows), cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=[r[0] for r in rows], row_heights=[0.45] + [0.55 / max(1, len(rows) - 1)] * (len(rows) - 1))
    for i, (title, col) in enumerate(rows, start=1):
        if col == "hr" and len(zones) == 5 and zones["zone_low_bpm"].notna().all():
            lows = zones["zone_low_bpm"].tolist()
            highs = lows[1:] + [max(s["hr"].max(), lows[-1]) + 5]
            for z, (lo, hi) in enumerate(zip(lows, highs)):
                fig.add_hrect(y0=lo, y1=hi, fillcolor=c.ZONE_COLORS[z], opacity=0.12, line_width=0, row=i, col=1)
        hover = {"hr": "%{y:.0f} bpm", "pace_val": pace_hover, "altitude_m": "%{y:.0f} m"}[col]
        color = {"hr": c.HR_LINE, "pace_val": c.SERIES_MAIN, "altitude_m": c.ELEV_LINE}[col]
        fig.add_scatter(x=s["min"], y=s[col], mode="lines", line=dict(width=1.5, color=color), name=title,
                        hovertemplate=hover, showlegend=False, connectgaps=False,
                        fill="tozeroy" if col == "altitude_m" else None,
                        fillcolor=c.ELEV_FILL if col == "altitude_m" else None, row=i, col=1)
        if col == "pace_val" and not is_cycling:
            fig.update_yaxes(autorange="reversed", row=i, col=1)
        if col == "altitude_m":
            lo, hi = s[col].min(), s[col].max()
            fig.update_yaxes(range=[lo - 5, hi + 5], row=i, col=1)
    fig.update_xaxes(title_text="minutes", row=len(rows), col=1)
    if 1 < len(laps) <= 80 and laps["start_offset_s"].notna().all():
        for off in laps["start_offset_s"].iloc[1:]:  # lap boundaries
            fig.add_vline(x=off / 60, line_width=1, line_dash="dot", line_color=c.LAP_LINE)
    c.style_fig(fig, height=260 * len(rows), legend=False)
    fig.update_annotations(font_size=13, xanchor="left", x=0)
    c.show(fig)

# ---------------------------------------------------------------- laps
if len(laps) > 1:
    st.subheader(f"Laps ({len(laps)})")
    lp = laps.copy()
    if lp["start_offset_s"].isna().any():
        lp["start_offset_s"] = lp["duration_s"].fillna(0).cumsum().shift(fill_value=0)
    lp["speed"] = lp["avg_speed_mps"].where(lp["avg_speed_mps"] > 0, lp["distance_m"] / lp["duration_s"])
    lp["pace_txt"] = [f"{v * 3.6:.1f} km/h" if is_cycling else c.fmt_pace(v) for v in lp["speed"]]
    metric = st.segmented_control("Lap bars show", ["Avg HR", "Speed" if is_cycling else "Pace"],
                                  default="Avg HR", key="lap_metric") or "Avg HR"
    if metric == "Avg HR":
        y, y_title, y_hover = lp["avg_hr"], "avg HR (bpm)", "%{y:.0f} bpm"
    elif is_cycling:
        y, y_title, y_hover = lp["speed"] * 3.6, "km/h", "%{y:.1f} km/h"
    else:
        y = (1000 / lp["speed"] / 60).where(lp["speed"] > 0.5)
        y_title, y_hover = "pace (min/km)", "%{y:.2f} min/km"
    custom = list(zip(lp["lap_index"], lp["duration_s"].map(c.fmt_duration), (lp["distance_m"] / 1000).round(2),
                      lp["pace_txt"], lp["avg_hr"].round(0), lp["intensity"].fillna("")))
    fig = go.Figure(go.Bar(
        x=(lp["start_offset_s"] + lp["duration_s"] / 2) / 60, width=lp["duration_s"] / 60 * 0.97, y=y,
        marker_color=[hr_zone_color(h) for h in lp["avg_hr"]], customdata=custom,
        hovertemplate=("Lap %{customdata[0]} %{customdata[5]}<br>%{customdata[1]} · %{customdata[2]} km"
                       "<br>%{customdata[3]} · %{customdata[4]} bpm<extra></extra>"),
    ))
    if metric != "Avg HR" and not is_cycling:
        fig.update_yaxes(autorange="reversed")
    elif metric == "Avg HR" and y.notna().any():
        fig.update_yaxes(range=[max(0, y.min() - 15), y.max() + 5])
    c.style_fig(fig, height=300, y_title=y_title, legend=False).update_layout(hovermode="closest", bargap=0)
    fig.update_xaxes(title_text="minutes")
    c.show(fig)
    st.caption("Bar width = lap duration; colour = HR zone of the lap's average HR.")
    st.dataframe(
        pd.DataFrame({
            "Lap": lp["lap_index"],
            "Type": lp["intensity"].fillna("").str.capitalize(),
            "Time": lp["duration_s"].map(c.fmt_duration),
            "Distance (km)": (lp["distance_m"] / 1000).round(2),
            "Speed" if is_cycling else "Pace": lp["pace_txt"],
            "Avg HR": lp["avg_hr"].round(0),
            "Max HR": lp["max_hr"].round(0),
            "Climb (m)": lp["elev_gain_m"].round(0),
        }),
        hide_index=True,
        height=min(420, 38 + 35 * len(lp)),
    )

# ---------------------------------------------------------------- time in zones
if not zones.empty and zones["seconds"].sum() > 0:
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Time in zones")
        zl = [f"Z{int(z)}" + (f" (≥{int(lo)})" if pd.notna(lo) else "") for z, lo in zip(zones["zone"], zones["zone_low_bpm"])]
        fig = go.Figure(go.Bar(
            y=zl, x=zones["seconds"] / 60, orientation="h", marker_color=c.ZONE_COLORS[: len(zones)],
            text=[c.fmt_duration(v) for v in zones["seconds"]], textposition="outside",
            hovertemplate="%{x:.0f} min<extra></extra>",
        ))
        fig.update_yaxes(autorange="reversed")
        c.style_fig(fig, height=260, y_title=None, legend=False).update_layout(hovermode="closest")
        fig.update_xaxes(title_text="minutes")
        c.show(fig)
    with right:
        tot = zones["seconds"].sum()
        z = dict(zip(zones["zone"], zones["seconds"]))
        st.subheader("3-zone split")
        k = st.columns(3)
        k[0].metric("Easy", f"{100 * (z.get(1, 0) + z.get(2, 0)) / tot:.0f}%", border=True)
        k[1].metric("Moderate", f"{100 * z.get(3, 0) / tot:.0f}%", border=True)
        k[2].metric("Hard", f"{100 * (z.get(4, 0) + z.get(5, 0)) / tot:.0f}%", border=True)

# ---------------------------------------------------------------- optional map
if not s.empty and s["lat"].notna().any():
    if st.toggle("Show route map", help="Loads map tiles from OpenStreetMap (your route stays local, "
                                          "but the tile server sees which area you view)."):
        pts = s.dropna(subset=["lat", "lon"])
        fig = go.Figure(go.Scattermap(lat=pts["lat"], lon=pts["lon"], mode="lines", line=dict(width=3, color=c.HR_LINE)))
        fig.update_layout(map=dict(style="open-street-map", center=dict(lat=pts["lat"].mean(), lon=pts["lon"].mean()),
                                   zoom=13), height=450, margin=dict(l=0, r=0, t=0, b=0))
        c.show(fig)
