"""Tags: review and bulk-edit activity tags. Edited tags are saved as manual and never auto-overwritten."""

import json

import pandas as pd
import streamlit as st

import common as c
import config
from db.database import connect, get_state
from garmin_sync.features import update_features
from garmin_sync.tagging import apply_auto_tags, set_manual_tag

c.setup_page("Tags", "🏷️")
c.tag_filter_sidebar()
acts = c.load_activities().sort_values("start", ascending=False)
c.require_data(acts)

# O score: model probability once trained, else how unusual the GPS track's direction changes are (percentile).
has_track = acts["turns_per_km"].notna()
acts["o_score"] = acts["o_prob"] * 100
turn_pct = acts.loc[has_track, "turns_per_km"].rank(pct=True) * 100
no_model = has_track & acts["o_prob"].isna()
acts.loc[no_model, "o_score"] = turn_pct[no_model[no_model].index]

conn = connect()
try:
    model = json.loads(get_state(conn, "o_model") or "null")
finally:
    conn.close()
with st.expander("Orienteering detection", expanded=False):
    n_pos = int(((acts["tag_source"] == "manual") & acts["tag"].isin(["o_training", "o_race"]) & has_track).sum())
    n_neg = int(((acts["tag_source"] == "manual") & acts["tag"].isin(["interval", "long_run", "easy_run"]) & has_track).sum())
    need = config.O_MODEL_MIN_EXAMPLES
    if acts["o_prob"].notna().any() and model:
        st.markdown(f"Model trained on **{model['n_pos']}** orienteering runs and **{model['n_neg']}** other runs "
                    f"you tagged (cross-validated accuracy **{model['cv_accuracy']:.0%}**). Runs with an O score "
                    f"of {config.O_PROB_THRESHOLD:.0%} or more are auto-tagged as orienteering.")
    else:
        st.markdown(f"Not trained yet: you have manually tagged **{n_pos}** orienteering runs and **{n_neg}** other "
                    f"runs; **{need}** of each are needed. Until then the O score is the percentile of GPS direction "
                    f"changes per km. Sort by it below to find candidates quickly.")
    st.caption("Signals: sharp direction changes per km, share of time stopped (map reading), speed variability, "
               "climb per km. Tag more sessions, then retrain.")
    if st.button("Retrain & re-apply auto tags"):
        conn = connect()
        try:
            res = update_features(conn)
            changed = apply_auto_tags(conn)
        finally:
            conn.close()
        c.clear_cache()
        st.toast(f"{changed} auto tags updated." if res["model"] else "Not enough examples yet.")
        st.rerun()

# ---------------------------------------------------------------- filters (local to this page)
f = st.columns([2, 2, 2, 1])
min_day, max_day = acts["day"].min().date(), acts["day"].max().date()
default_from = max(min_day, (pd.Timestamp(max_day) - pd.Timedelta(days=90)).date())
date_range = f[0].date_input("Dates", (default_from, max_day), min_value=min_day, max_value=max_day)
sports = sorted(acts["sport_type"].dropna().unique())
run_sports = [s for s in sports if "run" in s]
sport_sel = f[1].multiselect("Sport", sports, default=run_sports or None, format_func=c.sport_label,
                             placeholder="All sports")
tag_sel = f[2].multiselect("Current tag", list(c.TAG_LABELS), format_func=c.TAG_LABELS.get, placeholder="All tags")
only_auto = f[3].checkbox("Only auto", value=False, help="Hide activities you already tagged yourself.")
sort = st.segmented_control("Sort", ["Newest first", "Most orienteering-like first"], default="Newest first",
                            key="tag_sort") or "Newest first"

view = acts
if isinstance(date_range, tuple) and len(date_range) == 2:
    view = view[(view["day"].dt.date >= date_range[0]) & (view["day"].dt.date <= date_range[1])]
if sport_sel:
    view = view[view["sport_type"].isin(sport_sel)]
if tag_sel:
    view = view[view["tag"].isin(tag_sel)]
if only_auto:
    view = view[view["tag_source"] != "manual"]
if sort != "Newest first":
    view = view.sort_values("o_score", ascending=False, na_position="last")

label_to_key = {v: k for k, v in c.TAG_LABELS.items()}
table = pd.DataFrame({
    "activity_id": view["activity_id"],
    "Date": view["start"].dt.strftime("%Y-%m-%d %H:%M"),
    "Name": view["name"],
    "Sport": view["sport_type"].map(c.sport_label),
    "Time": view["duration_s"].map(c.fmt_duration),
    "Avg HR": view["avg_hr"].round(0),
    "Km": (view["distance_m"] / 1000).round(1),
    "Climb (m)": view["elev_gain_m"].round(0),
    "Laps": view["n_laps"],
    "O score": view["o_score"].round(0),
    "Turns/km": view["turns_per_km"].round(1),
    "Stopped %": (view["stop_frac"] * 100).round(0),
    "Tag": view["tag"].map(c.TAG_LABELS),
    "Set by": view["tag_source"].map({"manual": "you", "auto": "auto"}),
}).reset_index(drop=True)

# The editor tracks edits by row position, so give each filter/sort combination its own editor state.
editor_key = f"tag_editor_{hash(tuple(table['activity_id']))}"
st.caption(f"{len(table)} activities. Change the **Tag** column, then press **Save changes**.")
edited = st.data_editor(
    table,
    hide_index=True,
    disabled=[col for col in table.columns if col != "Tag"],
    column_order=[col for col in table.columns if col != "activity_id"],
    column_config={
        "Tag": st.column_config.SelectboxColumn("Tag", options=list(c.TAG_LABELS.values()), required=True),
        "O score": st.column_config.ProgressColumn("O score", min_value=0, max_value=100, format="%.0f",
                                                   help="How orienteering-like the GPS track is (0–100)."),
    },
    key=editor_key,
    height=min(700, 38 + 35 * max(1, len(table))),
)

changed = edited[edited["Tag"] != table["Tag"]]
cols = st.columns([1, 4])
if cols[0].button(f"Save changes ({len(changed)})", type="primary", disabled=changed.empty):
    conn = connect()
    try:
        for _, row in changed.iterrows():
            set_manual_tag(conn, int(row["activity_id"]), label_to_key[row["Tag"]])
    finally:
        conn.close()
    c.clear_cache()
    st.session_state.pop(editor_key, None)
    st.toast(f"Saved {len(changed)} tag(s).")
    st.rerun()

# ---------------------------------------------------------------- summary
st.subheader("Tag counts")
summary = (acts.groupby(["tag", "tag_source"]).size().unstack(fill_value=0)
           .reindex(list(c.TAG_LABELS), fill_value=0).rename(index=c.TAG_LABELS))
summary.columns = [{"manual": "set by you", "auto": "automatic"}.get(col, col) for col in summary.columns]
st.dataframe(summary, width="content")
