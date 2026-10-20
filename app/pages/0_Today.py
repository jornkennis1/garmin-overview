"""Today: readiness, fitness, sleep, this week and health metrics. Click any box for a 30-day chart."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c
import insights
import planning
from garmin_sync.metrics import load_curves

c.setup_page("Today", "☀️")
tags = c.sidebar()
daily = c.load_daily()
acts_all = c.load_activities()

today = pd.Timestamp.today().normalize()
this_monday = today - pd.Timedelta(days=today.weekday())
since30 = today - pd.Timedelta(days=29)
_next = planning.load_races().query("end_date >= @today").head(1)
_race = (f"  ·  {'race now' if len(_next) and _next.iloc[0]['date'] <= today else 'next race'}: "
         f"**{_next.iloc[0]['name']}** ({_next.iloc[0]['priority']}) "
         f"{planning.race_when(_next.iloc[0], today)}") if len(_next) else ""
st.caption(f"{today:%A %d %B %Y}{_race}  ·  click a box for a short explanation and the last 30 days")

d = daily.set_index("date").sort_index() if not daily.empty else pd.DataFrame()
if not d.empty:
    d = d[~d.index.duplicated(keep="last")]
    d["sleep_h"] = d["sleep_s"] / 3600
acts = c.filter_tags(acts_all, tags)

# ---------------------------------------------------------------- heads-up (all activities, ignores the tag filter)
with st.expander("Heads-up", expanded=True, icon=":material/notifications:"):
    items = insights.readiness(acts_all, daily, today)
    if items:
        insights.render(items)
    else:
        st.caption("Not enough recent data for a check yet.")

# Every box is a bordered container with an invisible full-size button on top (see CSS below).
st.html(f"""<style>
[class*="st-key-box_"] {{ position: relative; transition: background-color .15s; }}
[class*="st-key-box_"]:hover {{ background-color: {c.BOX_HOVER}; }}
[class*="st-key-box_"] [class*="st-key-open_"] {{ position: absolute; inset: 0; z-index: 5; margin: 0;
    width: 100% !important; max-width: none !important; }}
[class*="st-key-box_"] [class*="st-key-open_"] div,
[class*="st-key-box_"] [class*="st-key-open_"] button {{ width: 100% !important; max-width: none !important;
    height: 100%; opacity: 0; cursor: pointer; }}
.tbox-label {{ color: {c.TEXT_MUTED}; font-size: .85rem; margin-bottom: .1rem; }}
.tbox-value {{ font-size: 2rem; font-weight: 600; line-height: 1.15; color: {c.TEXT}; }}
.tbox-unit {{ font-size: 1rem; font-weight: 400; color: {c.TEXT_MUTED}; margin-left: .2rem; }}
.tbox-sub {{ color: {c.TEXT_MUTED}; font-size: .85rem; margin-top: .15rem; }}
</style>""")


# ---------------------------------------------------------------- helpers

def latest(col: str):
    """(value, date) of the most recent non-empty value, or (None, None)."""
    if d.empty or col not in d or d[col].dropna().empty:
        return None, None
    s = d[col].dropna()
    return s.iloc[-1], s.index[-1]


def avg_before(col: str, day, days: int = 7):
    if day is None:
        return None
    s = d.loc[(d.index < day) & (d.index >= day - pd.Timedelta(days=days)), col].dropna()
    return s.mean() if len(s) else None


def when(day) -> str:
    if day is None:
        return ""
    if day == today:
        return "today"
    if day == today - pd.Timedelta(days=1):
        return "yesterday"
    return f"{day:%d %b}"


def box_html(label: str, value: str, unit: str = "", sub: str = "") -> str:
    return (f'<div class="tbox-label">{label}</div><div class="tbox-value">{value}'
            f'<span class="tbox-unit">{unit}</span></div><div class="tbox-sub">{sub or "&nbsp;"}</div>')


def last30(col: str) -> pd.Series:
    if d.empty or col not in d:
        return pd.Series(dtype=float)
    return d.loc[d.index >= since30, col].reindex(pd.date_range(since30, today, freq="D"))


def mini(fig: go.Figure, height: int = 120, x_labels: bool = True) -> None:
    c.style_fig(fig, height=height, legend=False)
    fig.update_layout(margin=dict(l=0, r=0, t=4, b=0), hovermode=False)
    fig.update_xaxes(visible=x_labels, showticklabels=x_labels, ticks="", tickfont=dict(size=10))
    fig.update_yaxes(showticklabels=False, showgrid=False)
    st.plotly_chart(fig, width="stretch", config={"staticPlot": True})


def box(key: str, content, sparkline: pd.Series | None = None) -> None:
    """A clickable box: `content` is HTML or a callable that renders inside the box."""
    with st.container(border=True, key=f"box_{key}"):
        if callable(content):
            content()
        else:
            st.markdown(content, unsafe_allow_html=True)
        if sparkline is not None and sparkline.notna().sum() >= 2:
            fig = go.Figure(go.Scatter(x=sparkline.index, y=sparkline, mode="lines", connectgaps=True,
                                       line=dict(color=c.SERIES_MAIN, width=2)))
            mini(fig, height=48, x_labels=False)
        if st.button("open", key=f"open_{key}"):
            detail(key)


# ---------------------------------------------------------------- popup with explanation + 30-day chart

INFO = {
    "readiness": ("Training readiness", "Garmin's 0–100 estimate of how ready you are for hard training, based on sleep, recovery time, HRV and recent load."),
    "fitness": ("Fitness & fatigue", "Fitness is your 42-day average daily load and fatigue your 7-day average; form (fitness minus fatigue) far below zero means a lot of accumulated fatigue."),
    "sleep": ("Sleep", "Total sleep per night split into stages; deep and REM sleep matter most for recovery."),
    "week": ("Training per day", "Your training time per day over the last 30 days, coloured by tag."),
    "split": ("Sport split", "How your training time over the last 30 days is divided across tags."),
    "resting_hr": ("Resting heart rate", "Your lowest heart rate at rest during the day; a rise of 5+ bpm above your normal can signal fatigue, illness or stress."),
    "hrv_overnight_avg": ("HRV", "Your average overnight heart rate variability; above your normal usually means good recovery, a clear drop suggests stress or fatigue."),
    "stress_avg": ("Stress", "Garmin's average all-day stress level (0–100) derived from HRV; lower means more relaxed."),
    "bb": ("Body battery", "Garmin's energy estimate (0–100); the daily high shows how well you recharged overnight, the low how much you used."),
    "steps": ("Steps", "Total steps per day, including those during activities."),
    "active_kcal": ("Active calories", "Calories burned through movement and training, on top of your resting metabolism."),
    "vo2max": ("VO2 max", "Garmin's estimate of your maximal aerobic capacity (ml/kg/min), derived from pace and heart rate during runs and rides."),
    "weight_kg": ("Weight", "Your weigh-ins from a Garmin scale or entered manually in Garmin Connect."),
    "respiration_avg": ("Respiration", "Your average breaths per minute while awake; a clear rise above normal can be an early sign of illness or overreaching."),
}
UNITS = {"resting_hr": "bpm", "hrv_overnight_avg": "ms", "stress_avg": "", "steps": "steps", "active_kcal": "kcal",
         "vo2max": "ml/kg/min", "weight_kg": "kg", "respiration_avg": "brpm"}


def line_with_avg(col: str, unit: str) -> go.Figure:
    s = last30(col)
    full = d[col] if col in d else pd.Series(dtype=float)
    avg7 = full.rolling(7, min_periods=3).mean().reindex(s.index)
    fig = go.Figure()
    fig.add_scatter(x=s.index, y=s, mode="markers+lines", name="daily", connectgaps=False,
                    line=dict(color=c.MUTED, width=1), marker=dict(size=8, color=c.MUTED),
                    hovertemplate=f"%{{y:.1f}} {unit}")
    if avg7.notna().sum() > 1:
        fig.add_scatter(x=avg7.index, y=avg7, mode="lines", name="7-day average",
                        line=dict(color=c.SERIES_MAIN, width=2.5), hovertemplate=f"7d %{{y:.1f}} {unit}")
    return fig


def detail(key: str) -> None:
    st.dialog(INFO[key][0], width="large")(_detail_body)(key)


def _detail_body(key: str) -> None:
    st.write(INFO[key][1])
    days = pd.date_range(since30, today, freq="D")
    fig = go.Figure()
    legend = False
    if key == "readiness":
        s = last30("readiness_score")
        fig.add_bar(x=s.index, y=s, marker_color=c.SERIES_MAIN, hovertemplate="%{y:.0f}")
        fig.update_yaxes(range=[0, 100])
    elif key == "fitness":
        curves = load_curves(acts_all.groupby("day")["load"].sum()).reindex(days)
        fig.add_scatter(x=days, y=curves["ctl"], name="Fitness (42 d)", mode="lines", line=dict(color=c.SERIES_MAIN, width=2.5))
        fig.add_scatter(x=days, y=curves["atl"], name="Fatigue (7 d)", mode="lines", line=dict(color=c.SERIES_SECOND, width=2.5))
        legend = True
    elif key == "sleep":
        stages = [("deep_s", "Deep", c.ZONE_COLORS[4]), ("rem_s", "REM", c.ZONE_COLORS[2]),
                  ("light_s", "Light", c.ZONE_COLORS[0]), ("awake_s", "Awake", c.MUTED)]
        for col, name, color in stages:
            s = last30(col) / 3600
            fig.add_bar(x=s.index, y=s, name=name, marker_color=color, hovertemplate="%{y:.1f} h")
        fig.update_layout(barmode="stack")
        legend = True
        score = last30("sleep_score")
        if score.notna().any():
            st.caption(f"Average sleep score over these 30 days: {score.mean():.0f}")
    elif key in ("week", "split"):
        recent = acts[acts["day"] >= since30]
        if key == "week":
            piv = recent.pivot_table(index="day", columns="tag", values="hours", aggfunc="sum").reindex(days).fillna(0)
            for tag, color in c.TAG_COLORS.items():
                if tag in piv and piv[tag].sum() > 0:
                    fig.add_bar(x=piv.index, y=piv[tag], name=c.TAG_LABELS[tag], marker_color=color,
                                marker_pattern=c.bar_pattern(tag), hovertemplate="%{y:.1f} h")
            fig.update_layout(barmode="stack")
        else:
            split = recent.groupby("tag")["hours"].sum()
            order = [t for t in c.TAG_COLORS if split.get(t, 0) > 0]
            fig.add_bar(y=[c.TAG_LABELS[t] for t in order], x=[split[t] for t in order], orientation="h",
                        marker_color=[c.TAG_COLORS[t] for t in order],
                        marker_pattern_shape=[c.TAG_PATTERNS.get(t, "") for t in order],
                        marker_pattern_fgcolor=c.SURFACE, marker_pattern_solidity=0.3, text=[c.fmt_hours(split[t]) for t in order],
                        textposition="outside", hovertemplate="%{x:.1f} h<extra></extra>")
            fig.update_yaxes(autorange="reversed")
        legend = key == "week"
    elif key == "bb":
        lo, hi = last30("bb_low"), last30("bb_high")
        fig.add_bar(x=hi.index, y=hi - lo, base=lo, marker_color=c.SERIES_MAIN, name="low → high",
                    customdata=list(zip(lo, hi)), hovertemplate="%{customdata[0]:.0f} → %{customdata[1]:.0f}<extra></extra>")
        fig.update_yaxes(range=[0, 100])
    elif key in ("steps", "active_kcal"):
        s = last30(key)
        fig.add_bar(x=s.index, y=s, marker_color=c.SERIES_MAIN, hovertemplate=f"%{{y:,.0f}} {UNITS[key]}")
    else:
        fig = line_with_avg(key, UNITS.get(key, ""))
        legend = True
    c.style_fig(fig, height=320, legend=legend)
    if key == "split":
        fig.update_layout(hovermode="closest")
    c.show(fig)


# ---------------------------------------------------------------- row 1: readiness, fitness, sleep
r1 = st.columns(3)
with r1[0]:
    v, day = latest("readiness_score")
    level, _ = latest("readiness_level")
    box("readiness", box_html("Training readiness", "–" if v is None else f"{v:.0f}", "/ 100",
                              f"{str(level).replace('_', ' ').capitalize() if level else ''} · {when(day)}".strip(" ·")),
        sparkline=last30("readiness_score"))
with r1[1]:
    curves = load_curves(acts_all.groupby("day")["load"].sum()) if not acts_all.empty else pd.DataFrame()
    if curves.empty:
        box("fitness", box_html("Fitness", "–"))
    else:
        ctl, atl = curves["ctl"].iloc[-1], curves["atl"].iloc[-1]
        status, _ = latest("status")
        sub = f"Fatigue {atl:.0f} · Form {ctl - atl:+.0f}" + (f" · {str(status).replace('_', ' ').capitalize()}" if status else "")
        box("fitness", box_html("Fitness (42-day load)", f"{ctl:.0f}", "", sub),
            sparkline=curves["ctl"].reindex(pd.date_range(since30, today, freq="D")))
with r1[2]:
    v, day = latest("sleep_s")
    score, _ = latest("sleep_score")
    deep = d.loc[day, "deep_s"] if day is not None else None
    rem = d.loc[day, "rem_s"] if day is not None else None
    sub = " · ".join(x for x in [f"score {score:.0f}" if score is not None else "",
                                 f"deep {c.fmt_duration(deep)}" if deep is not None and pd.notna(deep) else "",
                                 f"REM {c.fmt_duration(rem)}" if rem is not None and pd.notna(rem) else ""] if x)
    box("sleep", box_html(f"Sleep{' · ' + when(day) if day is not None and day != today else ''}",
                          c.fmt_duration(v) if v is not None else "–", "h", sub),
        sparkline=last30("sleep_h"))

# ---------------------------------------------------------------- row 2: this week + sport split
week = acts[acts["day"] >= this_monday]
prev4 = acts[(acts["day"] >= this_monday - pd.Timedelta(days=28)) & (acts["day"] < this_monday)]
r2 = st.columns([3, 2])
with r2[0]:
    def week_content():
        avg_h = prev4["hours"].sum() / 4
        st.markdown(box_html(f"This week · {this_monday:%d %b} – {today:%d %b}",
                             c.fmt_hours(week["hours"].sum()).replace(" h", ""), "h",
                             f"{len(week)} sessions · load {week['load'].sum():.0f} · 4-week avg {avg_h:.1f} h"),
                    unsafe_allow_html=True)
        days = pd.date_range(this_monday, this_monday + pd.Timedelta(days=6), freq="D")
        piv = week.pivot_table(index="day", columns="tag", values="hours", aggfunc="sum").reindex(days).fillna(0)
        fig = go.Figure()
        for tag, color in c.TAG_COLORS.items():
            if tag in piv and piv[tag].sum() > 0:
                fig.add_bar(x=[f"{x:%a}" for x in piv.index], y=piv[tag], marker_color=color,
                            marker_pattern=c.bar_pattern(tag))
        if not fig.data:
            fig.add_bar(x=[f"{x:%a}" for x in days], y=[0] * 7)
        fig.update_layout(barmode="stack", bargap=0.35)
        mini(fig, height=110)
    box("week", week_content)
with r2[1]:
    def split_content():
        st.markdown('<div class="tbox-label">Sport split this week</div>', unsafe_allow_html=True)
        split = week.groupby("tag")["hours"].sum()
        order = [t for t in c.TAG_COLORS if split.get(t, 0) > 0]
        if not order:
            st.markdown('<div class="tbox-sub">No training yet this week.</div>', unsafe_allow_html=True)
            return
        total = split.sum()
        rows = "".join(
            f'<div style="display:flex;align-items:center;gap:8px;margin:5px 0;font-size:.9rem">'
            f'<span style="width:110px;color:{c.TEXT}">{c.TAG_LABELS[t]}</span>'
            f'<span style="flex:1;background:{c.CELL_BG};border-radius:4px;height:10px">'
            f'<span style="display:block;width:{100 * split[t] / total:.0f}%;height:10px;border-radius:4px;'
            f'background:{c.swatch_css(t)}"></span></span>'
            f'<span style="width:52px;text-align:right;color:{c.TEXT_MUTED}">{c.fmt_hours(split[t])}</span></div>'
            for t in order)
        st.markdown(rows, unsafe_allow_html=True)
    box("split", split_content)

# ---------------------------------------------------------------- health grid
st.subheader("Health")


def health_box(key: str, label: str, col: str, fmt: str, unit: str, better: str | None, compare_days: int = 7,
               sub_extra: str = ""):
    v, day = latest(col)
    if v is None:
        box(key, box_html(label, "–", "", "no data yet"))
        return
    ref = avg_before(col, day, compare_days)
    sub = when(day)
    if ref is not None and better is not None:
        diff = v - ref
        arrow = "▲" if diff > 0 else "▼" if diff < 0 else "="
        sub += f" · {arrow} {abs(diff):{fmt}} vs {compare_days}-day avg"
    if sub_extra:
        sub += f" · {sub_extra}"
    box(key, box_html(label, f"{v:{fmt}}", unit, sub), sparkline=last30(col))


grid = st.columns(3)
with grid[0]:
    health_box("resting_hr", "Resting HR", "resting_hr", ".0f", "bpm", "lower")
    hb_v, _ = latest("bb_high")
    lo_v, lo_day = latest("bb_low")
    box("bb", box_html("Body battery", "–" if hb_v is None else f"{hb_v:.0f}", "max",
                       "" if lo_v is None else f"low {lo_v:.0f} · {when(lo_day)}"), sparkline=last30("bb_high"))
    health_box("vo2max", "VO2 max", "vo2max", ".1f", "ml/kg/min", "higher", compare_days=30)
with grid[1]:
    status, _ = latest("hrv_status")
    health_box("hrv_overnight_avg", "HRV (overnight)", "hrv_overnight_avg", ".0f", "ms", "higher",
               sub_extra=str(status).capitalize() if status else "")
    health_box("steps", "Steps", "steps", ",.0f", "", "none")
    health_box("weight_kg", "Weight", "weight_kg", ".1f", "kg", "none", compare_days=30)
with grid[2]:
    health_box("stress_avg", "Stress (avg)", "stress_avg", ".0f", "/ 100", "lower")
    health_box("active_kcal", "Active calories", "active_kcal", ",.0f", "kcal", "none")
    health_box("respiration_avg", "Respiration (awake)", "respiration_avg", ".1f", "brpm", "none")

if d.empty or d[["active_kcal", "respiration_avg"]].dropna(how="all").empty:
    st.caption("Active calories, respiration and weight appear after your next sync.")
