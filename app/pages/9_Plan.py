"""Plan: race calendar with a form-on-race-day projection, weekly plan vs actual, and season comparison."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c
import config
import insights
import planning as pl

c.setup_page("Plan", "🗓️")
c.sidebar()  # planning always uses all activities
acts = c.load_activities()
c.require_data(acts)
today = pd.Timestamp.today().normalize()
this_monday = pl.monday(today)
races = pl.load_races()
upcoming = races[races["date"] >= today]

tab_races, tab_week, tab_season = st.tabs(["Races", "Weekly plan", "Season"])

# ================================================================= races
with tab_races:
    if not upcoming.empty:
        nxt = upcoming.iloc[0]
        a_races = upcoming[upcoming["priority"] == "A"]
        k = st.columns(3)
        k[0].metric("Next race", nxt["name"], f"{nxt['date']:%a %d %b} · {pl.weeks_to(nxt['date'], today)}",
                    delta_color="off", delta_arrow="off", border=True)
        if not a_races.empty:
            a = a_races.iloc[0]
            k[1].metric("Next main goal (A)", a["name"], f"{a['date']:%a %d %b} · {pl.weeks_to(a['date'], today)}",
                        delta_color="off", delta_arrow="off", border=True)
        k[2].metric("Races planned", len(upcoming), f"{len(a_races)} A · {int((upcoming['priority'] == 'B').sum())} B · "
                    f"{int((upcoming['priority'] == 'C').sum())} C", delta_color="off", delta_arrow="off", border=True)

    st.subheader("Race calendar")
    st.caption("Add a row for each race you plan to run. **A** = main goal (gets a full taper), **B** = important, "
               "**C** = training race. Delete a row with the checkbox on the left and the bin icon.")
    editor = races.assign(date=races["date"].dt.date)
    edited = st.data_editor(
        editor, num_rows="dynamic", hide_index=True, key="race_editor",
        column_order=["date", "name", "discipline", "priority", "goal", "notes"],
        column_config={
            "date": st.column_config.DateColumn("Date", required=True, format="ddd DD MMM YYYY"),
            "name": st.column_config.TextColumn("Race", required=True, max_chars=80),
            "discipline": st.column_config.SelectboxColumn("Discipline", options=pl.DISCIPLINES),
            "priority": st.column_config.SelectboxColumn("Priority", options=list(pl.PRIORITIES), default="B",
                                                         required=True, help="; ".join(pl.PRIORITIES.values())),
            "goal": st.column_config.TextColumn("Goal", max_chars=120, help="e.g. 'top 10', 'clean race', 'qualify'"),
            "notes": st.column_config.TextColumn("Notes", max_chars=300),
        },
    )
    changed = not edited.reset_index(drop=True).equals(editor.reset_index(drop=True))
    if st.button("Save races", type="primary", disabled=not changed, key="save_races"):
        pl.save_races(edited, races)
        st.session_state.pop("race_editor", None)
        st.toast("Races saved")
        st.rerun()

    # ------------------------------------------------------------ projection to race day
    if not upcoming.empty:
        st.subheader("Form on race day")
        choices = upcoming["race_id"].tolist()
        default = a_races.iloc[0]["race_id"] if not a_races.empty else choices[0]
        rid = st.selectbox("Race", choices, index=choices.index(default), key="proj_race",
                           format_func=lambda r: (lambda x: f"{x['date']:%d %b %Y} · {x['name']} ({x['priority']})")(
                               upcoming.set_index("race_id").loc[r]))
        race = upcoming.set_index("race_id").loc[rid]
        race_day = race["date"]
        usual = pl.usual_week_hours(acts, today)
        plans = pl.load_plans()
        planned = plans["hours"].dropna().to_dict()
        taper = pl.taper_plan(race, usual)
        rl = pl.race_load(acts)
        extra = {r["date"]: rl for _, r in upcoming.iterrows() if r["date"] <= race_day}
        mine = pl.project(acts, today, race_day, planned, usual, extra)
        tapered = pl.project(acts, today, race_day, {**planned, **taper}, usual, extra)
        # Form the morning of the race = end of the day before.
        before = race_day - pd.Timedelta(days=1)
        m_row, t_row = mine.loc[before], tapered.loc[before]

        k = st.columns(4)
        k[0].metric("Form on race morning · your plan", pl.fmt_form(m_row['tsb']), border=True,
                    help="Form = fitness − fatigue. Positive = fresh. Weeks without a plan continue at your usual "
                         f"volume ({usual:.1f} h/week, the average of the last 4 weeks).")
        k[1].metric("Form · suggested taper", pl.fmt_form(t_row['tsb']), border=True,
                    help="Same, with the suggested taper for this race's priority.")
        k[2].metric("Fitness on race day · your plan", f"{m_row['ctl']:.0f}", f"{m_row['ctl'] - mine.loc[today, 'ctl']:+.0f} vs today",
                    delta_color="off", delta_arrow="off", border=True)
        k[3].metric("Fitness · suggested taper", f"{t_row['ctl']:.0f}", f"{t_row['ctl'] - tapered.loc[today, 'ctl']:+.0f} vs today",
                    delta_color="off", delta_arrow="off", border=True)
        insights.render([pl.form_verdict(m_row["tsb"], m_row["ctl"])])

        show_from = today - pd.Timedelta(days=42)
        fig = go.Figure()
        hist = mine[(mine.index >= show_from) & ~mine["projected"]]
        fig.add_scatter(x=hist.index, y=hist["tsb"], name="Form so far", mode="lines",
                        line=dict(color=c.SERIES_MAIN, width=2), hovertemplate="%{y:+.0f}")
        for df, name, color, dash in ((mine, "Your plan", c.SERIES_MAIN, "dash"),
                                      (tapered, "Suggested taper", c.SERIES_SECOND, "dot")):
            p = df[(df.index >= today) & (df.index <= before)]  # up to race eve, not the race itself
            fig.add_scatter(x=p.index, y=p["tsb"], name=name, mode="lines", line=dict(color=color, width=2, dash=dash),
                            hovertemplate="%{y:+.0f}")
        fig.add_hline(y=0, line_width=1, line_color=c.AXIS)
        fig.add_vline(x=race_day, line_width=1, line_dash="dot", line_color=c.AVG_LINE)
        fig.add_annotation(x=race_day, y=1, yref="paper", text=race["name"], showarrow=False, xanchor="right",
                           font=dict(size=12, color=c.TEXT_MUTED))
        c.show(c.style_fig(fig, height=320, y_title="form (fitness − fatigue)"))

        if taper:
            weeks = ", ".join(f"week of {w:%d %b}: {h:.1f} h" for w, h in sorted(taper.items()))
            st.markdown(f"**Suggested taper** for an {race['priority']} race, from your usual {usual:.1f} h/week: {weeks}. "
                        "Keep 1–2 short sessions with race-pace bits; drop the long and the extra easy ones.")
            free = [w for w in taper if pd.isna(plans["hours"].get(w)) if w >= this_monday]
            if st.button(f"Put the taper in my weekly plan ({len(free)} empty week{'s' if len(free) != 1 else ''})",
                         disabled=not free, key="apply_taper",
                         help="Fills only weeks that don't have planned hours yet; your own plan is never overwritten."):
                rows = pd.DataFrame([{"hours": taper[w], "sessions": None, "o_sessions": None, "hard_sessions": None,
                                      "notes": f"Taper for {race['name']}"} for w in free],
                                    index=pd.Index(free, name="week_start"))
                pl.save_plans(rows)
                st.toast("Taper added to the weekly plan")
                st.rerun()
        else:
            st.caption("C races get no taper: train through them.")
        st.caption(f"Projection assumes about {pl.load_per_hour(acts, today):.0f} load per hour (your last 8 weeks) and "
                   f"a race load of {rl:.0f}. It's a guide, not a promise: illness, heat and sleep matter too.")

    # ------------------------------------------------------------ results of past races
    past = races[races["date"] < today].sort_values("date", ascending=False)
    if not past.empty:
        st.subheader("Past races")
        day_acts = acts.sort_values("load", ascending=False).drop_duplicates("day").set_index("day")
        rows = []
        for _, r in past.iterrows():
            a = day_acts.loc[r["date"]] if r["date"] in day_acts.index else None
            rows.append({"Date": f"{r['date']:%d %b %Y}", "Race": r["name"], "Priority": r["priority"],
                         "Goal": r["goal"] if isinstance(r["goal"], str) else "", "Time": c.fmt_duration(a["duration_s"]) if a is not None else "–",
                         "Avg HR": "–" if a is None or pd.isna(a["avg_hr"]) else f"{a['avg_hr']:.0f}",
                         "Load": "–" if a is None or pd.isna(a["load"]) else f"{a['load']:.0f}",
                         "Open": f"/Activity?id={int(a['activity_id'])}" if a is not None else None})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Open": st.column_config.LinkColumn("Activity", display_text="open")})
        st.caption("The activity is the one with the highest load on the race date.")

# ================================================================= weekly plan
with tab_week:
    last_race_week = pl.monday(upcoming["date"].max()) if not upcoming.empty else this_monday
    weeks = pd.date_range(this_monday - pd.Timedelta(weeks=4),
                          max(this_monday + pd.Timedelta(weeks=8), last_race_week), freq="7D")
    plans = pl.load_plans().reindex(weeks)
    actual = pl.weekly_actuals(acts).reindex(weeks).fillna(0)  # no sessions = 0 done; future weeks are blanked below
    race_names = races.assign(week=races["date"].map(pl.monday)).groupby("week")["name"].agg(", ".join)
    table = pd.DataFrame({
        "Week": [f"{w:%d %b}" + (" (now)" if w == this_monday else "") for w in weeks],
        "Races": race_names.reindex(weeks).fillna("").values,
        "Plan h": plans["hours"].values,
        "Plan sessions": plans["sessions"].values,
        "Plan O": plans["o_sessions"].values,
        "Plan hard": plans["hard_sessions"].values,
        "Notes": plans["notes"].fillna("").values,
        "Done h": actual["actual_hours"].round(1).where(weeks <= this_monday).values,
        "Done sessions": actual["actual_sessions"].where(weeks <= this_monday).values,
        "Done O": actual["actual_o"].where(weeks <= this_monday).values,
        "Done hard": actual["actual_hard"].where(weeks <= this_monday).values,
    }, index=weeks)
    usual = pl.usual_week_hours(acts, today)
    st.caption(f"Fill in what you plan per week; the *Done* columns fill themselves. Your usual week lately: "
               f"{usual:.1f} h. **Hard** = intervals, races or sessions with 10+ minutes in Z4–5.")
    edited = st.data_editor(
        table, hide_index=True, key="plan_editor", height=38 + 35 * len(table),
        disabled=["Week", "Races", "Done h", "Done sessions", "Done O", "Done hard"],
        column_config={
            "Plan h": st.column_config.NumberColumn("Plan h", min_value=0, max_value=60, step=0.5, format="%.1f"),
            "Plan sessions": st.column_config.NumberColumn("Plan sessions", min_value=0, max_value=30, step=1),
            "Plan O": st.column_config.NumberColumn("Plan O", min_value=0, max_value=20, step=1,
                                                    help="Orienteering sessions (race or training)"),
            "Plan hard": st.column_config.NumberColumn("Plan hard", min_value=0, max_value=20, step=1),
            "Notes": st.column_config.TextColumn("Notes", max_chars=200),
        },
    )
    edit_cols = ["Plan h", "Plan sessions", "Plan O", "Plan hard", "Notes"]
    diff = (edited[edit_cols].fillna("").astype(str) != table[edit_cols].fillna("").astype(str)).any(axis=1)
    if st.button(f"Save plan ({int(diff.sum())} week{'s' if diff.sum() != 1 else ''})", type="primary",
                 disabled=not diff.any(), key="save_plan"):
        rows = edited.loc[diff, edit_cols].set_axis(pl.PLAN_COLS, axis=1)
        rows.index = edited.index[diff]
        pl.save_plans(rows)
        st.session_state.pop("plan_editor", None)
        st.toast("Plan saved")
        st.rerun()

    # planned vs done chart (past and current weeks + the plan ahead)
    fig = go.Figure()
    done = table["Done h"]
    fig.add_bar(x=weeks, y=done, name="Done", marker_color=c.SERIES_MAIN, hovertemplate="%{y:.1f} h")
    fig.add_scatter(x=weeks, y=table["Plan h"], name="Planned", mode="markers",
                    marker=dict(symbol="line-ew-open", size=34, line=dict(width=3, color=c.AVG_LINE)),
                    hovertemplate="%{y:.1f} h planned")
    c.show(c.style_fig(fig, height=300, y_title="hours per week").update_layout(hovermode="x unified"))

    past_weeks = table[(table.index < this_monday) & table["Plan h"].notna()]
    if len(past_weeks) >= 2:
        ratio = past_weeks["Done h"].fillna(0).sum() / past_weeks["Plan h"].sum()
        level = "good" if 0.85 <= ratio <= 1.15 else "info"
        insights.render([insights.Insight(
            level, f"You did {ratio:.0%} of your planned hours",
            f"Over the last {len(past_weeks)} planned weeks: {past_weeks['Done h'].fillna(0).sum():.1f} of "
            f"{past_weeks['Plan h'].sum():.1f} h. " + ("Right on plan." if level == "good" else
            "Way more than planned often means easy days crept in; much less means the plan may be too ambitious."))])

# ================================================================= season
with tab_season:
    a = pl.season_frame(acts)
    label = st.segmented_control("Compare", list(pl.SEASON_METRICS), default="Hours", key="season_metric") or "Hours"
    col, unit = pl.SEASON_METRICS[label]
    cur = pl.season_start(today)
    seasons = sorted(a["season"].unique(), reverse=True)[:5]
    ins = pl.season_insight(a, today, col, label, unit)
    if ins:
        insights.render([ins])

    fig = go.Figure()
    for i, s in enumerate(seasons):
        s = pd.Timestamp(s)
        until = (today - s).days if s == cur else None
        y = pl.cumulative(a, col, s, until)
        color, width = (c.SERIES_MAIN, 3) if i == 0 else (c.SERIES_SECOND, 2) if i == 1 else (c.MUTED, 1.5)
        fig.add_scatter(x=y.index, y=y.values, name=pl.season_label(s), mode="lines",
                        line=dict(color=color, width=width), hovertemplate="%{y:.0f}" + (f" {unit}" if unit else ""))
        if i < 2 and len(y):
            fig.add_annotation(x=y.index[-1], y=y.values[-1], text=pl.season_label(s), showarrow=False,
                               xanchor="left", xshift=4, font=dict(size=12, color=c.TEXT_MUTED))
    month_starts = pd.date_range(cur, cur + pd.DateOffset(months=11), freq="MS")
    fig.update_xaxes(tickvals=[(m - cur).days for m in month_starts], ticktext=[f"{m:%b}" for m in month_starts],
                     title_text=f"season (starts in {cur:%B}; set season_start_month in settings.toml)")
    c.show(c.style_fig(fig, height=380, y_title=f"cumulative {label.lower()}"))
    st.caption("Each line adds up the season day by day, so you can see whether you're ahead of or behind other seasons "
               "at the same point. The current season is the thick line.")

    st.subheader("Seasons")
    st.dataframe(pl.season_table(a, today), hide_index=True, width="stretch")
