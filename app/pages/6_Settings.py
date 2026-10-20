"""Settings: which tags the pages show, your own tags, appearance (light/dark) and the state of the data."""

import json

import pandas as pd
import streamlit as st

import common as c
import config
from db.database import connect, get_state
from garmin_sync.tagging import load_custom_tags, save_custom_tags

c.setup_page("Settings", "⚙️")
c.sidebar()

# ---------------------------------------------------------------- tags shown on the pages
st.subheader("Tags shown on the pages")
hidden = c.hidden_tags()
shown = st.multiselect("Show tags", list(c.TAG_LABELS), default=[t for t in c.TAG_LABELS if t not in hidden],
                       format_func=c.TAG_LABELS.get, key="shown_tags",
                       help="Applies to Today, Overview, Calendar, Intensity and Activity. Insights, Plan and O-analysis "
                            "always use all activities.")
if set(shown) != set(t for t in c.TAG_LABELS if t not in hidden):
    c.set_hidden_tags([t for t in c.TAG_LABELS if t not in shown])
    st.rerun()
st.caption("Remembered between sessions. Tags you add later are shown automatically.")

# ---------------------------------------------------------------- your own tags
st.subheader("Your own tags")
st.markdown(
    "Add tags for anything the built-in ones don't cover, e.g. *Crosstrainer*, *Swimming* or *Sprint training*. "
    "Give a tag **words** (found in the activity name, comma-separated) and/or **Garmin sport types** to tag "
    "activities automatically; these rules win over the built-in auto rules. Without rules you set the tag by "
    "hand on the **Tags** or **Activity** page. A tag you set by hand is never changed."
)
conn = connect()
try:
    custom = load_custom_tags(conn)
    sports = [r[0] for r in conn.execute(
        "SELECT sport_type FROM activities WHERE sport_type IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC")]
    counts = dict(conn.execute("SELECT tag, count(*) FROM activity_tags GROUP BY tag").fetchall())
finally:
    conn.close()
table = pd.DataFrame([{"key": t["key"], "Tag": t["label"], "Colour": c.HUE_NAMES[t["color_slot"] % 8],
                       "Words in name": ", ".join(t["keywords"]), "Sport types": ", ".join(sorted(t["sport_types"])),
                       "Activities": counts.get(t["key"], 0)} for t in custom],
                     columns=["key", "Tag", "Colour", "Words in name", "Sport types", "Activities"])
edited = st.data_editor(
    table, num_rows="dynamic", hide_index=True, key="custom_tag_editor",
    column_order=["Tag", "Colour", "Words in name", "Sport types", "Activities"], disabled=["Activities"],
    column_config={
        "Tag": st.column_config.TextColumn("Tag", required=True, max_chars=40),
        "Colour": st.column_config.SelectboxColumn(
            "Colour", options=c.HUE_NAMES, required=True, default=c.HUE_NAMES[len(custom) % 8],
            help="One of the dashboard's 8 colours; your own tags are drawn hatched so they don't look like a built-in tag."),
        "Words in name": st.column_config.TextColumn("Words in name", help="e.g. cardio, crosstrainer"),
        "Sport types": st.column_config.TextColumn("Sport types", help="Garmin types, e.g. indoor_cardio, lap_swimming"),
    },
)
st.caption("Garmin sport types in your data: " + ", ".join(f"`{s}`" for s in sports[:25]))
changed = not edited.fillna("").astype(str).reset_index(drop=True).equals(table.fillna("").astype(str).reset_index(drop=True))
removed = set(table["key"]) - set(edited["key"].dropna())
if removed:
    names = ", ".join(table.set_index("key").loc[sorted(removed), "Tag"])
    st.warning(f"Saving removes **{names}**. Activities with that tag get an automatic tag again.")
if st.button("Save tags", type="primary", disabled=not changed, key="save_custom_tags"):
    rows = [{"key": r["key"] if isinstance(r["key"], str) else None, "label": r["Tag"],
             "color_slot": c.HUE_NAMES.index(r["Colour"]) if r["Colour"] in c.HUE_NAMES else 0,
             "keywords": r["Words in name"] if isinstance(r["Words in name"], str) else "",
             "sport_types": r["Sport types"] if isinstance(r["Sport types"], str) else ""}
            for _, r in edited.iterrows() if isinstance(r["Tag"], str) and r["Tag"].strip()]
    conn = connect()
    try:
        save_custom_tags(conn, rows)
    finally:
        conn.close()
    c.clear_cache()
    st.session_state.pop("custom_tag_editor", None)
    st.toast("Tags saved and auto tags updated")
    st.rerun()

# ---------------------------------------------------------------- appearance
st.subheader("Appearance")
mode = "dark" if c.is_dark() else "light"
st.markdown(
    f"The dashboard is currently in **{mode} mode**. By default it follows your Windows setting "
    "(Settings → Personalisation → Colours → *Choose your mode*)."
)
st.markdown(
    "To switch manually: open the **⋮ menu** at the top right and pick **System**, **Light** or **Dark**. "
    "Your browser remembers the choice. All charts, the calendar and the Today boxes switch along."
)
st.caption("Streamlit doesn't let an app change the theme from code, which is why this lives in the ⋮ menu.")

# ---------------------------------------------------------------- data status
st.subheader("Data")
conn = connect()
try:
    stats = {
        "Activities": conn.execute("SELECT count(*), min(date(start_time_local)), max(date(start_time_local)) FROM activities").fetchone(),
        "Days of health metrics": conn.execute("SELECT count(*), min(date), max(date) FROM daily_metrics").fetchone(),
        "Days of training status": conn.execute("SELECT count(*), min(date), max(date) FROM training_status").fetchone(),
        "Activities with laps": conn.execute("SELECT count(DISTINCT activity_id), NULL, NULL FROM activity_laps").fetchone(),
        "Manually tagged activities": conn.execute("SELECT count(*), NULL, NULL FROM activity_tags WHERE source = 'manual'").fetchone(),
    }
    last_sync = get_state(conn, "last_sync")
    model = json.loads(get_state(conn, "o_model") or "null")
finally:
    conn.close()

rows = [{"What": k, "Count": f"{v[0]:,}", "From": v[1] or "", "Until": v[2] or ""} for k, v in stats.items()]
st.dataframe(rows, hide_index=True, width="content")
st.markdown(f"Last sync: **{last_sync or 'never'}**. Use **Sync now** in the sidebar or run "
            "`python -m garmin_sync.sync` in a terminal.")
if model:
    st.markdown(f"Orienteering model: trained on {model['n_pos']} orienteering and {model['n_neg']} other runs "
                f"(cross-validated accuracy {model['cv_accuracy']:.0%}). Retrain on the **Tags** page.")

# ---------------------------------------------------------------- where settings live
st.subheader("Other settings")
st.markdown(
    "Tagging thresholds, keywords, HRmax / resting HR overrides and the orienteering threshold are in "
    "`settings.toml` in the project folder (copy `settings.example.toml`; defaults are in `config.py`). "
    "After changing them, run `python -m garmin_sync.tagging` "
    "(tags) or `python -m garmin_sync.metrics` (TRIMP)."
)
st.caption(f"Current rules: long run ≥ {config.LONG_RUN_MIN_KM} km · interval only from {config.INTERVAL_MIN_TOTAL_KM} km · "
           f"lap-based intervals from {config.INTERVAL_MIN_KM} km "
           f"and ≥ {config.INTERVAL_MIN_LAPS} laps · orienteering when the O score ≥ {config.O_PROB_THRESHOLD:.0%}.")
st.caption("Privacy: everything stays on this computer. The dashboard only listens on localhost, login tokens live in "
           "`~/.garminconnect`, the data in `data/` and your settings in `settings.toml`; none of it is committed.")
