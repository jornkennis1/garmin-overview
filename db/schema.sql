-- Schema for data/garmin.db. Applied idempotently on every connect (CREATE ... IF NOT EXISTS).
-- Units: durations in seconds, distances/elevation in metres, speed in m/s, HR in bpm.
-- Dates/times are ISO-8601 text. Local time is the athlete's wall-clock time.

CREATE TABLE IF NOT EXISTS activities (
    activity_id        INTEGER PRIMARY KEY,   -- Garmin activity id (FIT imports: Garmin id if known, else negative synthetic id)
    start_time_local   TEXT NOT NULL,         -- 'YYYY-MM-DD HH:MM:SS' local time
    start_time_utc     TEXT,                  -- 'YYYY-MM-DD HH:MM:SS' UTC
    name               TEXT,
    sport_type         TEXT,                  -- Garmin typeKey, e.g. running, trail_running, strength_training
    event_type         TEXT,                  -- Garmin event type: race, training, uncategorized, ...
    duration_s         REAL,                  -- elapsed time incl. pauses as recorded by the watch
    moving_s           REAL,
    distance_m         REAL,
    elev_gain_m        REAL,
    elev_loss_m        REAL,
    avg_hr             REAL,
    max_hr             REAL,
    aerobic_te         REAL,                  -- Garmin aerobic training effect 0-5
    anaerobic_te       REAL,                  -- Garmin anaerobic training effect 0-5
    training_load      REAL,                  -- Garmin activity training load (EPOC based)
    trimp              REAL,                  -- Banister TRIMP, computed locally (fallback load)
    calories           REAL,
    avg_speed_mps      REAL,
    source             TEXT NOT NULL DEFAULT 'api',  -- 'api' or 'fit'
    details_fetched    INTEGER NOT NULL DEFAULT 0,   -- 1 once HR zones + samples are stored
    raw_json           TEXT,                  -- full Garmin summary, for re-parsing later
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(start_time_local);

CREATE TABLE IF NOT EXISTS activity_hr_zones (
    activity_id   INTEGER NOT NULL REFERENCES activities(activity_id) ON DELETE CASCADE,
    zone          INTEGER NOT NULL,           -- 1..5 (Garmin HR zones)
    seconds       REAL NOT NULL,
    zone_low_bpm  INTEGER,                    -- lower boundary of the zone at the time of the activity
    PRIMARY KEY (activity_id, zone)
);

CREATE TABLE IF NOT EXISTS activity_samples (
    activity_id   INTEGER NOT NULL REFERENCES activities(activity_id) ON DELETE CASCADE,
    t_offset_s    REAL NOT NULL,              -- seconds since activity start (elapsed)
    hr            REAL,
    speed_mps     REAL,
    altitude_m    REAL,
    distance_m    REAL,                       -- cumulative
    cadence       REAL,
    lat           REAL,
    lon           REAL,
    PRIMARY KEY (activity_id, t_offset_s)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS daily_metrics (
    date               TEXT PRIMARY KEY,      -- 'YYYY-MM-DD' (sleep/HRV belong to the night ending this morning)
    resting_hr         REAL,
    hrv_overnight_avg  REAL,                  -- ms, last-night average
    hrv_weekly_avg     REAL,                  -- ms, Garmin 7-day average
    hrv_baseline_low   REAL,                  -- ms, Garmin balanced range low
    hrv_baseline_high  REAL,                  -- ms, Garmin balanced range high
    hrv_status         TEXT,                  -- BALANCED / UNBALANCED / LOW / POOR
    sleep_s            REAL,
    deep_s             REAL,
    light_s            REAL,
    rem_s              REAL,
    awake_s            REAL,
    sleep_score        REAL,                  -- 0-100
    bb_high            REAL,                  -- body battery 0-100
    bb_low             REAL,
    bb_charged         REAL,
    bb_drained         REAL,
    stress_avg         REAL,                  -- 0-100
    steps              INTEGER,
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS training_status (
    date             TEXT PRIMARY KEY,
    status           TEXT,                    -- e.g. PRODUCTIVE, MAINTAINING, RECOVERY, UNPRODUCTIVE, DETRAINING, PEAKING, OVERREACHING
    acute_load       REAL,                    -- Garmin 7-day acute load
    chronic_load     REAL,                    -- Garmin chronic load
    acwr             REAL,                    -- acute:chronic workload ratio
    vo2max           REAL,
    readiness_score  REAL,                    -- training readiness 0-100
    readiness_level  TEXT,
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_tags (
    activity_id  INTEGER PRIMARY KEY REFERENCES activities(activity_id) ON DELETE CASCADE,
    tag          TEXT NOT NULL CHECK (tag IN ('o_race','o_training','interval','long_run','easy_run','strength','other')),
    source       TEXT NOT NULL CHECK (source IN ('auto','manual')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_state (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
