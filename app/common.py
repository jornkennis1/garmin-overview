"""Shared helpers for the dashboard pages: data loading, the global tag filter, colours, formatting."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from db.database import connect, get_state  # noqa: E402

# ---------------------------------------------------------------- colours (light + dark)
# Categorical slots in fixed order (validated for colour-blind separation in both modes); one per tag.
# HR zones / load are ordered magnitudes, so they use one hue: light->dark on a light surface,
# dim->bright on a dark surface. Each mode has its own validated steps, not an automatic flip.
THEMES = {
    "light": {
        "TAG_COLORS": {"o_race": "#2a78d6", "o_training": "#eb6834", "interval": "#1baf7a", "long_run": "#eda100",
                       "easy_run": "#e87ba4", "strength": "#008300", "cycling": "#6250d6",
                       "hiking_walking": "#e34948", "other": "#8a8984"},
        "ZONE_COLORS": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
        "ZONE3_COLORS": {"easy": "#86b6ef", "moderate": "#2a78d6", "hard": "#104281"},
        "LOAD_RAMP": ["#cde2fb", "#9ec5f4", "#5598e7", "#256abf", "#104281"],
        "SERIES_MAIN": "#2a78d6", "SERIES_SECOND": "#eb6834", "SERIES_SOFT": "#9ec5f4", "SERIES_SOFTER": "#cde2fb",
        "BAND_FILL": "rgba(42,120,214,0.10)", "HR_LINE": "#e34948", "ELEV_LINE": "#6b6a65",
        "ELEV_FILL": "rgba(107,106,101,0.12)", "LAP_LINE": "#b5b4ae", "AVG_LINE": "#3b3a37",
        "MUTED": "#a3a29c", "SURFACE": "#ffffff", "TEXT": "#1f1e1c", "TEXT_MUTED": "#6b6a65",
        "GRID": "#eeede9", "AXIS": "#d6d5d0", "CELL_BG": "#f7f7f5", "CHIP_BG": "#ffffff", "WEEK_BG": "#eef3fb",
        "BOX_HOVER": "#f4f3f0",
    },
    "dark": {
        "TAG_COLORS": {"o_race": "#3987e5", "o_training": "#d95926", "interval": "#199e70", "long_run": "#c98500",
                       "easy_run": "#d55181", "strength": "#008300", "cycling": "#9085e9",
                       "hiking_walking": "#e66767", "other": "#8a8984"},
        "ZONE_COLORS": ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
        "ZONE3_COLORS": {"easy": "#256abf", "moderate": "#5598e7", "hard": "#9ec5f4"},
        "LOAD_RAMP": ["#104281", "#1c5cab", "#3987e5", "#6da7ec", "#b7d3f6"],
        "SERIES_MAIN": "#3987e5", "SERIES_SECOND": "#d95926", "SERIES_SOFT": "#256abf", "SERIES_SOFTER": "#184f95",
        "BAND_FILL": "rgba(57,135,229,0.16)", "HR_LINE": "#e66767", "ELEV_LINE": "#a3a29c",
        "ELEV_FILL": "rgba(163,162,156,0.15)", "LAP_LINE": "#5c5b57", "AVG_LINE": "#d6d5d0",
        "MUTED": "#76756f", "SURFACE": "#1a1a19", "TEXT": "#f0efec", "TEXT_MUTED": "#a8a79f",
        "GRID": "#2e2e2c", "AXIS": "#45443f", "CELL_BG": "#232321", "CHIP_BG": "#2c2c2a", "WEEK_BG": "#1d2a3b",
        "BOX_HOVER": "#262624",
    },
}
ZONE3_LABELS = {"easy": "Easy (Z1–2)", "moderate": "Moderate (Z3)", "hard": "Hard (Z4–5)"}
LOAD_BUCKETS = [0, 50, 100, 175, 275]  # lower bounds per ramp step (activity load)


def is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def apply_theme() -> None:
    """Expose the current theme's colours as module constants (c.TAG_COLORS etc.).

    Single-user local app, so module globals are fine; they are set at the start of every page run.
    """
    globals().update(THEMES["dark" if is_dark() else "light"])


apply_theme()

TAG_LABELS = config.TAGS


# ---------------------------------------------------------------- formatting

def fmt_duration(seconds) -> str:
    if seconds is None or pd.isna(seconds):
        return "–"
    m = int(round(seconds / 60))
    return f"{m // 60}:{m % 60:02d}"


def fmt_hours(h) -> str:
    return "–" if h is None or pd.isna(h) else f"{h:.1f} h"


def fmt_pace(speed_mps) -> str:
    if not speed_mps or pd.isna(speed_mps) or speed_mps <= 0:
        return "–"
    sec = 1000 / speed_mps
    return f"{int(sec // 60)}:{int(sec % 60):02d} /km"


def sport_label(sport_type) -> str:
    return (sport_type or "unknown").replace("_", " ").capitalize()


def load_bucket_color(load) -> str:
    if load is None or pd.isna(load):
        return LOAD_RAMP[0]
    idx = max(i for i, b in enumerate(LOAD_BUCKETS) if load >= b)
    return LOAD_RAMP[idx]


# ---------------------------------------------------------------- data

def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = connect()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


@st.cache_data(ttl=300)
def load_activities() -> pd.DataFrame:
    df = query("SELECT * FROM v_activities ORDER BY start_time_local")
    df["start"] = pd.to_datetime(df["start_time_local"])
    df["day"] = pd.to_datetime(df["day"])
    df["week_start"] = pd.to_datetime(df["week_start"])
    df["hours"] = df["hours"].fillna(0)
    return df


@st.cache_data(ttl=300)
def load_daily() -> pd.DataFrame:
    df = query("SELECT * FROM daily_metrics ORDER BY date")
    ts = query("SELECT * FROM training_status ORDER BY date")
    df["date"] = pd.to_datetime(df["date"])
    ts["date"] = pd.to_datetime(ts["date"])
    return df.merge(ts.drop(columns=["updated_at"]), on="date", how="outer").sort_values("date")


@st.cache_data(ttl=300)
def load_samples(activity_id: int) -> pd.DataFrame:
    return query("SELECT * FROM activity_samples WHERE activity_id = ? ORDER BY t_offset_s", (activity_id,))


@st.cache_data(ttl=300)
def load_zones(activity_id: int) -> pd.DataFrame:
    return query("SELECT zone, seconds, zone_low_bpm FROM activity_hr_zones WHERE activity_id = ? ORDER BY zone",
                 (activity_id,))


@st.cache_data(ttl=300)
def load_laps(activity_id: int) -> pd.DataFrame:
    return query("SELECT * FROM activity_laps WHERE activity_id = ? ORDER BY lap_index", (activity_id,))


def clear_cache() -> None:
    st.cache_data.clear()


# ---------------------------------------------------------------- page scaffolding

def setup_page(title: str, icon: str = "🧭") -> None:
    st.set_page_config(page_title=f"{title} · Training", page_icon=icon, layout="wide")
    apply_theme()
    st.title(title)


def tag_filter_sidebar() -> list[str]:
    """Global tag filter shown in the sidebar on every page; the choice survives page switches."""
    if "tag_filter" not in st.session_state:
        st.session_state["tag_filter"] = list(TAG_LABELS)

    def _store():
        st.session_state["tag_filter"] = st.session_state["_tag_filter_widget"]

    st.sidebar.multiselect(
        "Show tags",
        options=list(TAG_LABELS),
        default=st.session_state["tag_filter"],
        format_func=TAG_LABELS.get,
        key="_tag_filter_widget",
        on_change=_store,
    )
    st.sidebar.caption("Filter applies to all pages. Edit tags on the **Tags** or **Activity** page.")
    _sync_sidebar()
    return st.session_state["tag_filter"]


def _sync_sidebar() -> None:
    """'Sync now' button: runs the same incremental sync as the terminal command."""
    st.sidebar.divider()
    if msg := st.session_state.pop("sync_msg", None):
        st.toast(msg)
    if st.sidebar.button("Sync now", icon=":material/sync:", width="stretch",
                         help="Fetch new data from Garmin, like `python -m garmin_sync.sync`."):
        with st.sidebar.status("Syncing with Garmin ...", expanded=True) as status:
            proc = subprocess.Popen(
                [sys.executable, "-m", "garmin_sync.sync"], cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
            )
            box, lines = st.empty(), []
            for line in proc.stdout:
                lines.append(line.rstrip())
                box.code("\n".join(lines[-10:]), language=None)
            proc.wait()
            if proc.returncode == 0:
                clear_cache()
                st.session_state["sync_msg"] = lines[-1] if lines else "Sync complete."
                st.rerun()
            status.update(label="Sync failed: see the output above", state="error")
    conn = connect()
    try:
        last = get_state(conn, "last_sync")
    finally:
        conn.close()
    st.sidebar.caption(f"Last sync: {last or 'never'}")


def filter_tags(df: pd.DataFrame, tags: list[str]) -> pd.DataFrame:
    return df[df["tag"].isin(tags)]


def require_data(df: pd.DataFrame, what: str = "activities") -> None:
    if df.empty:
        st.info(f"No {what} yet. Run `python -m garmin_sync.sync` first (see README).")
        st.stop()


# ---------------------------------------------------------------- charts

def style_fig(fig: go.Figure, height: int = 340, y_title: str | None = None, legend: bool = True) -> go.Figure:
    """Consistent, quiet chart styling: recessive grid, legend on top, thin marks, unified hover."""
    fig.update_layout(
        template="plotly_dark" if is_dark() else "plotly_white",
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        font=dict(size=13, color=TEXT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title_text=""),
        showlegend=legend,
        hovermode="x unified",
        bargap=0.25,
        barcornerradius=4,
        plot_bgcolor=SURFACE,
        paper_bgcolor=SURFACE,
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, ticks="outside", tickcolor=AXIS)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title_text=y_title)
    # 2px surface gap between stacked/adjacent bar segments.
    fig.update_traces(marker_line_color=SURFACE, marker_line_width=1, selector=dict(type="bar"))
    return fig


def show(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def period_selector(label: str, options: dict[str, int], default: str, key: str) -> int:
    """Horizontal period picker; returns the number of days for the chosen option."""
    choice = st.segmented_control(label, list(options), default=default, key=key) or default
    return options[choice]
