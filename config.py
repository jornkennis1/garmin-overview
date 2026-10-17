"""Central settings. Secrets are NOT stored here; they come from .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "garmin.db"
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
