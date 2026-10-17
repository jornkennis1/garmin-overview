"""Settings: appearance (light/dark) and the state of the local data."""

import json

import streamlit as st

import common as c
import config
from db.database import connect, get_state

c.setup_page("Settings", "⚙️")
c.tag_filter_sidebar()

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
    "`config.py` in the project folder. After changing them, run `python -m garmin_sync.tagging` "
    "(tags) or `python -m garmin_sync.metrics` (TRIMP)."
)
st.caption(f"Current rules: long run ≥ {config.LONG_RUN_MIN_KM} km · lap-based intervals from {config.INTERVAL_MIN_KM} km "
           f"and ≥ {config.INTERVAL_MIN_LAPS} laps · orienteering when the O score ≥ {config.O_PROB_THRESHOLD:.0%}.")
st.caption("Privacy: everything stays on this laptop. The dashboard only listens on localhost, credentials live in "
           "`.env` and the data in `data/`; both are git-ignored.")
