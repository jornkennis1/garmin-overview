"""Recovery: resting HR, HRV, sleep, body battery and stress, with 7-day rolling averages."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import common as c

c.setup_page("Recovery", "😴")
c.tag_filter_sidebar()
daily = c.load_daily()
c.require_data(daily, "daily metrics")
acts = c.load_activities()

days = c.period_selector("Period", {"30 days": 30, "90 days": 90, "6 months": 182, "12 months": 365, "All": 100_000},
                         "90 days", "rec_period")
today = pd.Timestamp.today().normalize()

# Rolling averages are computed on the full series, then cut to the period (no warm-up gap).
d = daily.set_index("date").asfreq("D")
d["sleep_h"] = d["sleep_s"] / 3600
for col in ("resting_hr", "hrv_overnight_avg", "sleep_h", "sleep_score", "stress_avg", "bb_high"):
    d[f"{col}_7d"] = d[col].rolling(7, min_periods=3).mean()
d["load"] = acts.groupby("day")["load"].sum().reindex(d.index).fillna(0)
d = d[d.index >= today - pd.Timedelta(days=days - 1)]

# ---------------------------------------------------------------- latest values
latest = d.dropna(subset=["resting_hr"]).iloc[-1] if d["resting_hr"].notna().any() else None
m = st.columns(5)
if latest is not None:
    m[0].metric("Resting HR", f"{latest['resting_hr']:.0f} bpm",
                None if pd.isna(latest["resting_hr_7d"]) else f"{latest['resting_hr'] - latest['resting_hr_7d']:+.1f} vs 7d",
                delta_color="inverse", border=True, help=f"Latest day: {latest.name:%d %b}")
hrv_row = d.dropna(subset=["hrv_overnight_avg"])
if not hrv_row.empty:
    h = hrv_row.iloc[-1]
    m[1].metric("HRV last night", f"{h['hrv_overnight_avg']:.0f} ms",
                None if pd.isna(h["hrv_overnight_avg_7d"]) else f"{h['hrv_overnight_avg'] - h['hrv_overnight_avg_7d']:+.0f} vs 7d",
                border=True, help=f"Garmin status: {h['hrv_status'] or '–'}")
sleep_row = d.dropna(subset=["sleep_h"])
if not sleep_row.empty:
    s = sleep_row.iloc[-1]
    m[2].metric("Sleep last night", c.fmt_duration(s["sleep_s"]),
                None if pd.isna(s["sleep_score"]) else f"score {s['sleep_score']:.0f}", delta_color="off", border=True)
ready = d.dropna(subset=["readiness_score"])
if not ready.empty:
    r = ready.iloc[-1]
    m[3].metric("Training readiness", f"{r['readiness_score']:.0f}", r["readiness_level"] or None,
                delta_color="off", border=True)
status = d.dropna(subset=["status"])
if not status.empty:
    t = status.iloc[-1]
    acwr = f"ACWR {t['acwr']:.1f}" if pd.notna(t["acwr"]) else None
    m[4].metric("Training status", str(t["status"]).replace("_", " ").capitalize(), acwr, delta_color="off", border=True,
                help="Garmin training status; ACWR = acute:chronic workload ratio (0.8–1.5 is Garmin's optimal range).")

# ---------------------------------------------------------------- trend charts (small multiples, shared time axis)
panels = [
    ("Resting HR (bpm)", "resting_hr", c.SERIES_MAIN),
    ("HRV overnight (ms)", "hrv_overnight_avg", c.SERIES_MAIN),
    ("Sleep (hours)", "sleep_h", c.SERIES_MAIN),
    ("Sleep score", "sleep_score", c.SERIES_MAIN),
    ("Body battery max", "bb_high", c.SERIES_MAIN),
    ("Stress (avg)", "stress_avg", c.SERIES_MAIN),
]
panels = [p for p in panels if d[p[1]].notna().any()]
n = len(panels) + 1
fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                    subplot_titles=[p[0] for p in panels] + ["Training load (context)"])
for i, (title, col, color) in enumerate(panels, start=1):
    if col == "hrv_overnight_avg" and d["hrv_baseline_low"].notna().any():
        # Garmin's "balanced" HRV range as a shaded band.
        fig.add_scatter(x=d.index, y=d["hrv_baseline_high"], mode="lines", line=dict(width=0), showlegend=False,
                        hoverinfo="skip", row=i, col=1)
        fig.add_scatter(x=d.index, y=d["hrv_baseline_low"], mode="lines", line=dict(width=0), fill="tonexty",
                        fillcolor=c.BAND_FILL, name="Garmin balanced range", showlegend=False,
                        hovertemplate="baseline low %{y:.0f}", row=i, col=1)
    if col == "sleep_h":
        fig.add_bar(x=d.index, y=d[col], name=title, marker_color=c.SERIES_SOFTER, showlegend=False,
                    hovertemplate="%{y:.1f} h", row=i, col=1)
    else:
        fig.add_scatter(x=d.index, y=d[col], mode="markers", marker=dict(size=6, color=c.SERIES_SOFT),
                        name=f"{title} daily", showlegend=False, hovertemplate="%{y:.0f}", row=i, col=1)
    fig.add_scatter(x=d.index, y=d[f"{col}_7d"], mode="lines", line=dict(color=color, width=2),
                    name=f"{title} 7-day avg", showlegend=False, hovertemplate="7d %{y:.1f}", row=i, col=1)
fig.add_bar(x=d.index, y=d["load"], marker_color=c.SERIES_SECOND, name="Load", showlegend=False,
            hovertemplate="load %{y:.0f}", row=n, col=1)
c.style_fig(fig, height=170 * n + 40, legend=False)
fig.update_layout(hovermode="x unified", margin=dict(t=40))
fig.update_annotations(font_size=13, xanchor="left", x=0)
c.show(fig)
st.caption("Dots/light bars = daily values, dark line = 7-day rolling average. "
           "Shaded band on HRV = Garmin's balanced range. Sleep and HRV belong to the night ending that morning.")
