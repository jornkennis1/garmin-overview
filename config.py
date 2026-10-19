"""Central settings with sensible defaults.

Personal overrides go in `settings.toml` (git-ignored; copy `settings.example.toml`).
Secrets are NOT stored here or there; they come from .env.
"""

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("GARMIN_DB_PATH") or DATA_DIR / "garmin.db")  # override only for testing
SCHEMA_PATH = ROOT / "db" / "schema.sql"

# Login tokens live outside the repo so they can never be committed.
TOKEN_DIR = os.path.expanduser(os.getenv("GARMIN_TOKEN_DIR", "~/.garminconnect"))

# Be polite to Garmin: pause between API calls (seconds).
API_DELAY_S = 0.6

# Daily-metric backfill stops after this many consecutive days without any data.
DAILY_BACKFILL_EMPTY_STOP = 60

# Sleep and HRV are sometimes finalised a day or two late, so re-fetch this many recent days.
DAILY_REFRESH_DAYS = 3

# On the very first sync, fetch this many recent days with the detailed per-day endpoints.
# Older history is fetched with faster 28-day range endpoints.
DAILY_INITIAL_RECENT_DAYS = 28

# Training status/readiness only exist per day, so their history is limited to this many days.
TRAINING_STATUS_BACKFILL_DAYS = 365

# Number of HR/pace samples requested per activity (Garmin downsamples to this many points).
ACTIVITY_SAMPLE_POINTS = 2000

# ---------------------------------------------------------------- tags
# The tag set used everywhere (key -> label shown in the dashboard).
TAGS = {
    "o_race": "Orienteering race",
    "o_training": "Orienteering training",
    "interval": "Interval",
    "long_run": "Long run",
    "easy_run": "Easy run",
    "strength": "Strength",
    "cycling": "Cycling",
    "hiking_walking": "Hiking / walking",
    "other": "Other",
}

# Auto-tag keywords, matched case-insensitively as whole words in the activity name.
# Edit freely; manual tags are never overwritten. Re-run `python -m garmin_sync.tagging` to re-apply.
O_RACE_KEYWORDS = [
    "woc", "jwoc", "eoc", "ejoc", "world cup", "wre", "o-ringen", "jukola", "venla", "tiomila",
    "10mila", "race", "championship", "championships", "competition",
]
O_KEYWORDS = [
    "orienteering", "o-training", "o training", "sprint o", "middle", "long distance", "relay",
    "forest", "map", "control", "controls", "o-run", "o run",
]
INTERVAL_KEYWORDS = [
    "interval", "intervals", "tempo", "threshold", "track", "fartlek", "hill reps", "repeats",
    r"\d+\s?x\s?\d+",  # e.g. 6x1000, 4 x 5
]

RUN_TYPES = {
    "running", "trail_running", "street_running", "treadmill_running", "indoor_running",
    "track_running", "ultra_run", "obstacle_run", "virtual_run",
}
STRENGTH_TYPES = {"strength_training"}
# Sport types containing these words get the cycling / hiking-walking tag.
CYCLING_WORDS = ("cycling", "biking", "ride", "bmx")
HIKE_WALK_WORDS = ("hiking", "walking", "mountaineering")

LONG_RUN_MIN_KM = 15

# Month your training season starts (1 = January). Used by the season comparison on the Plan page.
SEASON_START_MONTH = 1

# Interval detection from laps (besides keywords and laps Garmin marks as interval/recovery):
# a run of at least INTERVAL_MIN_KM with at least INTERVAL_MIN_LAPS laps of uneven length
# whose pace alternates between fast and slow.
INTERVAL_MIN_KM = 12
INTERVAL_MIN_LAPS = 6
INTERVAL_LAP_DIST_CV = 0.25    # coefficient of variation of lap distances (auto-lap 1 km ~ 0)
INTERVAL_ALTERNATION = 0.6     # share of lap-to-lap changes that flip between fast and slow
INTERVAL_FAST_SLOW_GAP = 0.12  # fast laps at least 12% faster than slow laps

# Orienteering detection: trained on your manual tags once you have at least this many
# manually tagged orienteering runs AND this many manually tagged other runs.
O_MODEL_MIN_EXAMPLES = 8
O_PROB_THRESHOLD = 0.6

# Garmin lap data is not fetched for these activity types (sets/reps, no meaningful laps).
NO_LAP_TYPES = {"strength_training", "indoor_cardio", "mobility", "yoga", "pilates", "hiit", "breathwork"}

# ---------------------------------------------------------------- heart rate / load
# Leave as None to estimate from your data (HRmax = highest activity max HR seen,
# resting HR = median of the last 60 days). Set a number to override.
HR_MAX = None
HR_REST = None
# Banister TRIMP weighting factor: 1.92 (standard "male" curve) or 1.67 ("female" curve).
TRIMP_K = 1.92
# Fallback zone lower bounds (bpm, Z1..Z5) for FIT imports when Garmin's zones are unknown.
# None = derive from HRmax at 50/60/70/80/90 %.
HR_ZONE_LOWER_BOUNDS = None


# ---------------------------------------------------------------- personal overrides
# Every top-level key in settings.toml overrides the constant of the same name above
# (case-insensitive, e.g. `hr_max = 195` sets HR_MAX). Unknown keys are an error, so typos don't
# go unnoticed. TOML has no "None": leave a key out to keep the default.
SETTINGS_PATH = ROOT / "settings.toml"
_OVERRIDABLE = {
    "HR_MAX", "HR_REST", "TRIMP_K", "HR_ZONE_LOWER_BOUNDS", "TAGS",
    "O_RACE_KEYWORDS", "O_KEYWORDS", "INTERVAL_KEYWORDS", "LONG_RUN_MIN_KM",
    "INTERVAL_MIN_KM", "INTERVAL_MIN_LAPS", "INTERVAL_LAP_DIST_CV", "INTERVAL_ALTERNATION",
    "INTERVAL_FAST_SLOW_GAP", "O_MODEL_MIN_EXAMPLES", "O_PROB_THRESHOLD", "API_DELAY_S",
    "TRAINING_STATUS_BACKFILL_DAYS", "SEASON_START_MONTH",
}


def _apply_settings(path: Path) -> None:
    if not path.exists():
        return
    try:
        user = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"{path.name} is not valid TOML: {e}") from None
    for key, value in user.items():
        name = key.upper()
        if name not in _OVERRIDABLE:
            raise SystemExit(f"Unknown setting '{key}' in {path.name}. "
                             f"Allowed: {', '.join(sorted(k.lower() for k in _OVERRIDABLE))}")
        if name == "TAGS":
            unknown = set(value) - set(TAGS)
            if unknown:
                raise SystemExit(f"[tags] in {path.name} can only rename existing tags, not add "
                                 f"{', '.join(sorted(unknown))}")
            value = {**TAGS, **value}  # relabel only; the tag keys are fixed
        globals()[name] = value


_apply_settings(SETTINGS_PATH)
