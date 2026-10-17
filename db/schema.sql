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
    laps_fetched       INTEGER NOT NULL DEFAULT 0,   -- 1 once laps are stored (or not applicable)
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
    tag          TEXT NOT NULL CHECK (tag IN ('o_race','o_training','interval','long_run','easy_run','strength','cycling','hiking_walking','other')),
    source       TEXT NOT NULL CHECK (source IN ('auto','manual')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_laps (
    activity_id     INTEGER NOT NULL REFERENCES activities(activity_id) ON DELETE CASCADE,
    lap_index       INTEGER NOT NULL,         -- 1-based
    start_offset_s  REAL,                     -- seconds since activity start
    duration_s      REAL,                     -- elapsed
    moving_s        REAL,
    distance_m      REAL,
    avg_hr          REAL,
    max_hr          REAL,
    avg_speed_mps   REAL,
    elev_gain_m     REAL,
    elev_loss_m     REAL,
    intensity       TEXT,                     -- Garmin lap intensity: ACTIVE, REST, WARMUP, COOLDOWN, INTERVAL, RECOVERY (if set)
    PRIMARY KEY (activity_id, lap_index)
);

-- Derived per-activity features used for automatic tagging (garmin_sync/features.py).
CREATE TABLE IF NOT EXISTS activity_features (
    activity_id         INTEGER PRIMARY KEY REFERENCES activities(activity_id) ON DELETE CASCADE,
    n_laps              INTEGER,
    lap_dist_cv         REAL,     -- coefficient of variation of lap distances (auto-lap ~0)
    lap_alternation     REAL,     -- share of lap-to-lap changes that flip fast<->slow
    lap_fast_slow_gap   REAL,     -- relative speed gap between faster and slower half of laps
    has_interval_laps   INTEGER,  -- 1 if Garmin marked laps as INTERVAL/RECOVERY
    turns_per_km        REAL,     -- GPS direction changes > 60 degrees per km (orienteering signature)
    stop_frac           REAL,     -- share of time slower than 1 m/s
    speed_cv            REAL,     -- variability of (smoothed) speed while moving
    o_prob              REAL,     -- orienteering probability from the model trained on manual tags (NULL = no model yet)
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_state (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

CREATE INDEX IF NOT EXISTS idx_activities_utc ON activities(start_time_utc);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON activity_tags(tag);

-- ---------------------------------------------------------------- views
-- Views are recreated on every connect so changes here always take effect.

-- One row per activity with its tag, a single "load" number and the 3-zone split.
DROP VIEW IF EXISTS v_activities;
CREATE VIEW v_activities AS
SELECT
    a.activity_id,
    a.start_time_local,
    date(a.start_time_local)                         AS day,
    date(a.start_time_local, 'weekday 0', '-6 days') AS week_start,   -- Monday
    a.name,
    a.sport_type,
    a.event_type,
    COALESCE(t.tag, 'other')                         AS tag,
    t.source                                         AS tag_source,
    a.duration_s,
    a.moving_s,
    a.duration_s / 3600.0                            AS hours,
    a.distance_m,
    a.elev_gain_m,
    a.avg_hr,
    a.max_hr,
    a.aerobic_te,
    a.anaerobic_te,
    a.training_load,
    a.trimp,
    COALESCE(a.training_load, a.trimp)               AS load,
    z.z1_s, z.z2_s, z.z3_s, z.z4_s, z.z5_s,
    COALESCE(z.z1_s, 0) + COALESCE(z.z2_s, 0)        AS easy_s,       -- Z1-2
    COALESCE(z.z3_s, 0)                              AS moderate_s,   -- Z3
    COALESCE(z.z4_s, 0) + COALESCE(z.z5_s, 0)        AS hard_s,       -- Z4-5
    a.source,
    f.n_laps,
    f.turns_per_km,
    f.stop_frac,
    f.o_prob
FROM activities a
LEFT JOIN activity_tags t USING (activity_id)
LEFT JOIN activity_features f USING (activity_id)
LEFT JOIN (
    SELECT activity_id,
           SUM(CASE WHEN zone = 1 THEN seconds END) AS z1_s,
           SUM(CASE WHEN zone = 2 THEN seconds END) AS z2_s,
           SUM(CASE WHEN zone = 3 THEN seconds END) AS z3_s,
           SUM(CASE WHEN zone = 4 THEN seconds END) AS z4_s,
           SUM(CASE WHEN zone = 5 THEN seconds END) AS z5_s
    FROM activity_hr_zones GROUP BY activity_id
) z USING (activity_id);

-- Weekly totals (Monday-based weeks).
DROP VIEW IF EXISTS v_weekly;
CREATE VIEW v_weekly AS
SELECT
    week_start,
    COUNT(*)                        AS sessions,
    SUM(hours)                      AS hours,
    SUM(load)                       AS load,
    SUM(distance_m) / 1000.0        AS distance_km,
    SUM(elev_gain_m)                AS elev_gain_m,
    SUM(COALESCE(z1_s, 0)) / 3600.0 AS z1_h,
    SUM(COALESCE(z2_s, 0)) / 3600.0 AS z2_h,
    SUM(COALESCE(z3_s, 0)) / 3600.0 AS z3_h,
    SUM(COALESCE(z4_s, 0)) / 3600.0 AS z4_h,
    SUM(COALESCE(z5_s, 0)) / 3600.0 AS z5_h,
    SUM(easy_s) / 3600.0            AS easy_h,
    SUM(moderate_s) / 3600.0        AS moderate_h,
    SUM(hard_s) / 3600.0            AS hard_h
FROM v_activities
GROUP BY week_start;
