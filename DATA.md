# Data reference: `data/garmin.db`

SQLite database filled by `garmin_sync/sync.py` (Garmin API) and `garmin_sync/fit_import.py` (FIT/export fallback).
The schema's source of truth is `db/schema.sql`. This file explains it so that questions about training can be answered by querying the database directly.

**Athlete context:** a high-level orienteer. For orienteering, **pace is misleading** (terrain and navigation), so analyse **time, HR, zones and load** first; distance and pace come second.

## Conventions

| Thing | Unit / format |
|---|---|
| Durations | seconds (`*_s`), except `*_h` columns in views (hours) |
| Distance, elevation | metres |
| Speed | m/s (pace min/km = `1000 / speed / 60`) |
| Heart rate | bpm |
| Dates | `'YYYY-MM-DD'` text; activity times `'YYYY-MM-DD HH:MM:SS'` |
| Local vs UTC | `start_time_local` = wall-clock time where the activity happened. **Use it for days/weeks.** |
| Weeks | Monday-based; `week_start` = the Monday |

Query from the project folder:
```powershell
.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect('data/garmin.db'); print(c.execute('SELECT count(*) FROM activities').fetchall())"
```

---

## Tables

### `activities`: one row per recorded activity
| Column | Meaning |
|---|---|
| `activity_id` | Garmin activity id (PK). FIT imports without a known id use a negative synthetic id. |
| `start_time_local`, `start_time_utc` | Start time |
| `name` | Activity name from Garmin, overwritten by every sync. Often Garmin's default, e.g. `"<City> Running"` (in the watch's language); not reliable for classifying. |
| `custom_name` | The user's own name, set in the dashboard (NULL = none). Sync never touches it. |
| `sport_type` | Garmin typeKey: `running`, `trail_running`, `road_biking`, `hiking`, `walking`, `strength_training`, `indoor_cardio`, `mobility`, ... |
| `event_type` | Garmin event type: `race`, `training`, `uncategorized`, ... |
| `duration_s` | Elapsed time incl. pauses |
| `moving_s` | Moving / timer time |
| `distance_m`, `elev_gain_m`, `elev_loss_m` | Distance and climbing |
| `avg_hr`, `max_hr` | Heart rate |
| `aerobic_te`, `anaerobic_te` | Garmin training effect (0–5) |
| `training_load` | Garmin activity training load (EPOC-based). NULL for FIT imports. |
| `trimp` | Banister TRIMP, computed locally from the HR stream (or avg HR). Available for all activities with HR. |
| `calories`, `avg_speed_mps` | |
| `source` | `api` or `fit` |
| `details_fetched` | 1 when HR zones and samples have been stored |
| `laps_fetched` | 1 when laps have been stored (or laps don't apply, e.g. strength) |
| `raw_json` | Full Garmin summary JSON (API only). Use `json_extract(raw_json, '$.field')` for extra fields. |

### `activity_hr_zones`: time in Garmin HR zones per activity
`activity_id`, `zone` (1–5), `seconds`, `zone_low_bpm` (lower bound of that zone when the activity was recorded).
The athlete's Garmin zones are custom: Z1 ≥105, Z2 ≥123, Z3 ≥145, Z4 ≥162, Z5 ≥184 bpm. Check the table for the current values.
3-zone model used in the dashboard: **easy = Z1+Z2, moderate = Z3, hard = Z4+Z5**.

### `activity_samples`: HR/pace stream per activity (~2000 points per activity)
`activity_id`, `t_offset_s` (elapsed seconds since start), `hr`, `speed_mps`, `altitude_m`, `distance_m` (cumulative), `cadence`, `lat`, `lon`.

### `activity_laps`: laps per activity
`activity_id`, `lap_index` (1-based), `start_offset_s` (seconds since start), `duration_s`, `moving_s`, `distance_m`, `avg_hr`, `max_hr`, `avg_speed_mps`, `elev_gain_m`, `elev_loss_m`, `intensity`.
`intensity` is Garmin's lap type: `ACTIVE`, `REST`, `WARMUP`, `COOLDOWN`, `INTERVAL`, `RECOVERY`. Structured workouts use INTERVAL/RECOVERY; manual laps are usually ACTIVE.
Many runs use 1 km auto-laps (laps of equal distance), which say nothing about the session structure.

### `activity_features`: derived per-run features used for auto-tagging (runs only)
| Column | Meaning |
|---|---|
| `n_laps` | Number of laps |
| `lap_dist_cv` | Coefficient of variation of lap distances (≈0 for auto-laps; high for intervals or control splits) |
| `lap_alternation` | Share of lap-to-lap changes that flip between faster and slower than the median lap |
| `lap_fast_slow_gap` | Speed of the faster half of laps relative to the slower half, minus 1 |
| `has_interval_laps` | 1 if Garmin marked laps as INTERVAL/RECOVERY |
| `turns_per_km` | GPS direction changes sharper than 60° per km (path resampled every 15 m). Typical runs ≈ 1–3; orienteering is much higher. |
| `stop_frac` | Share of time slower than 1 m/s (map reading, controls, traffic lights) |
| `speed_cv` | Variability of smoothed speed while moving |
| `o_prob` | Orienteering probability (0–1) from a logistic regression trained on the athlete's **manual** tags. NULL until enough examples exist. Model details are in `sync_state` key `o_model`. |

### `daily_metrics`: one row per day
| Column | Meaning |
|---|---|
| `date` | Calendar day. Sleep/HRV belong to the night **ending** on this morning. |
| `resting_hr` | Resting HR (bpm) |
| `hrv_overnight_avg` | Last-night average HRV (ms) |
| `hrv_weekly_avg` | Garmin 7-day HRV average (ms) |
| `hrv_baseline_low`, `hrv_baseline_high` | Garmin "balanced" HRV range (ms) |
| `hrv_status` | `BALANCED`, `UNBALANCED`, `LOW`, `POOR` |
| `sleep_s`, `deep_s`, `light_s`, `rem_s`, `awake_s` | Sleep duration and stages (s) |
| `sleep_score` | 0–100 |
| `bb_high`, `bb_low`, `bb_charged`, `bb_drained` | Body battery |
| `stress_avg` | Average stress 0–100 |
| `steps` | |
| `active_kcal` | Active calories (movement + training, excluding resting/BMR) |
| `respiration_avg` | Average waking respiration (breaths/min) |
| `weight_kg` | Latest weigh-in that day; NULL on days without a weigh-in |

### `training_status`: Garmin training status per day (last ~365 days)
`date`, `status` (`PRODUCTIVE`, `MAINTAINING`, `RECOVERY`, `UNPRODUCTIVE`, `DETRAINING`, `PEAKING`, `OVERREACHING`, `STRAINED`, ...), `acute_load`, `chronic_load`, `acwr` (acute:chronic ratio), `vo2max`, `readiness_score` (0–100), `readiness_level`.

### `activity_tags`: training category per activity
`activity_id`, `tag`, `source` (`auto` = rule-based suggestion, `manual` = set by the athlete; manual is never overwritten). Besides the built-in tags below, `tag` can be one of the athlete's own tags (`custom_tags.key`, starting with `my_`).

| tag | meaning |
|---|---|
| `o_race` | Orienteering race |
| `o_training` | Orienteering training |
| `interval` | Interval / tempo session |
| `long_run` | Long run (auto: run ≥ 15 km) |
| `easy_run` | Easy run (auto: any other run) |
| `strength` | Strength / gym |
| `cycling` | Any cycling (road, MTB, gravel, indoor) |
| `hiking_walking` | Hiking and walking |
| `other` | Everything else (indoor cardio, mobility, swimming, ...) |

Auto rules live in `garmin_sync/tagging.py`, thresholds and keywords in `config.py` (overridable per user in `settings.toml`):
- interval = runs ≥10 km only; then laps marked INTERVAL/RECOVERY, interval words, track, or ≥12 km with ≥6 uneven, alternating laps
- long run = ≥15 km
- orienteering = keyword, or `o_prob` ≥ 0.6

**Manual tags are ground truth; treat `auto` tags on runs as a best guess.** This matters most for orienteering, since activity names are Garmin defaults.

### `custom_tags`
The athlete's own tags (Settings page), e.g. `my_crosstrainer` = "Crosstrainer".

| Column | Meaning |
|---|---|
| `key`, `label` | Stored in `activity_tags.tag` / shown name |
| `color_slot` | 0-7, palette hue (drawn hatched) |
| `keywords`, `sport_types` | Auto rules: comma-separated words in the activity name / Garmin sport types |

### `o_maps`
Course map per orienteering activity, added on the O-analysis page. The image is `data/maps/<image_file>`.

| Column | Meaning |
|---|---|
| `activity_id` | The activity (one map per activity) |
| `image_file`, `source_name` | Stored PNG in `data/maps/`, original upload name |
| `dpi` | Resolution of the stored image if known (PDF render), for the map-scale estimate |
| `map_points`, `track_points` | JSON: 3 matching points, `[[px, py], ...]` on the image and `[[lat, lon], ...]` on the track. The dashboard fits rotation + scale + offset to them. |

### `races`
Races the user plans to run (Plan page); one row per race, not linked to activities. Find the race activity by date (`v_activities.day = races.date`).

| Column | Meaning |
|---|---|
| `date`, `name` | Race date ('YYYY-MM-DD') and name |
| `discipline` | sprint, middle, long, relay, night, ultralong, other |
| `priority` | A = main goal, B = important, C = training race |
| `goal`, `notes` | Free text |

### `week_plans`
The user's weekly training plan (Plan page). Compare with actuals from `v_activities` grouped by `week_start`.

| Column | Meaning |
|---|---|
| `week_start` | Monday ('YYYY-MM-DD') |
| `hours`, `sessions` | Planned training time and number of sessions |
| `o_sessions`, `hard_sessions` | Planned orienteering sessions; planned hard sessions (intervals, races, or 10+ min in Z4-5) |
| `notes` | Free text, e.g. "Taper for BK Middle" |

### `sync_state`
Key/value bookkeeping for resumable syncs (backfill cursors and done flags).

---

## Views (use these first)

### `v_activities`
`activities` + tag + zones flattened: `activity_id, start_time_local, day, week_start, name, garmin_name, sport_type, event_type, tag, tag_source, duration_s, moving_s, hours, distance_m, elev_gain_m, avg_hr, max_hr, aerobic_te, anaerobic_te, training_load, trimp, load, z1_s..z5_s, easy_s, moderate_s, hard_s, source`.
`name` = the user's own name if set, else Garmin's (`garmin_name` is always Garmin's). `load` = Garmin `training_load` if present, else `trimp`. Also includes `n_laps, turns_per_km, stop_frac, o_prob` from `activity_features`.

### `v_weekly`
Per `week_start`: `sessions, hours, load, distance_km, elev_gain_m, z1_h..z5_h, easy_h, moderate_h, hard_h`.

---

## Example queries

```sql
-- Weekly hours, sessions and load for the last 12 weeks
SELECT week_start, sessions, round(hours, 1) AS hours, round(load) AS load
FROM v_weekly WHERE week_start >= date('now', '-84 days') ORDER BY week_start;

-- Hours per tag per month
SELECT strftime('%Y-%m', day) AS month, tag, round(sum(hours), 1) AS hours
FROM v_activities GROUP BY 1, 2 ORDER BY 1, 3 DESC;

-- Easy/hard balance (share of zone time) per month
SELECT strftime('%Y-%m', day) AS month,
       round(100.0 * sum(easy_s) / nullif(sum(easy_s + moderate_s + hard_s), 0)) AS pct_easy,
       round(100.0 * sum(hard_s) / nullif(sum(easy_s + moderate_s + hard_s), 0)) AS pct_hard
FROM v_activities GROUP BY 1 ORDER BY 1;

-- HRV and resting HR the morning after hard days (load > 150)
SELECT a.day, round(sum(a.load)) AS load, d.hrv_overnight_avg AS hrv_next, d.resting_hr AS rhr_next
FROM v_activities a JOIN daily_metrics d ON d.date = date(a.day, '+1 day')
GROUP BY a.day HAVING sum(a.load) > 150 ORDER BY a.day DESC;

-- 7-day rolling resting HR and HRV
SELECT date, resting_hr,
       round(avg(resting_hr) OVER (ORDER BY date ROWS 6 PRECEDING), 1) AS rhr_7d,
       round(avg(hrv_overnight_avg) OVER (ORDER BY date ROWS 6 PRECEDING), 1) AS hrv_7d
FROM daily_metrics ORDER BY date DESC LIMIT 30;

-- Interval sessions: laps with the fast/slow pattern
SELECT a.day, l.lap_index, l.intensity, round(l.distance_m) AS m, round(l.duration_s) AS s,
       round(1000 / l.avg_speed_mps / 60, 2) AS pace_min_km, l.avg_hr
FROM v_activities a JOIN activity_laps l USING (activity_id)
WHERE a.tag = 'interval' AND a.day >= date('now', '-60 days') ORDER BY a.day, l.lap_index;

-- Orienteering volume per month: manual vs auto-suggested
SELECT strftime('%Y-%m', day) AS month, tag_source, round(sum(hours), 1) AS hours, count(*) AS sessions
FROM v_activities WHERE tag IN ('o_training', 'o_race') GROUP BY 1, 2 ORDER BY 1;

-- All orienteering races with HR and load
SELECT day, name, round(hours, 2) AS hours, avg_hr, max_hr, round(load) AS load
FROM v_activities WHERE tag = 'o_race' ORDER BY day DESC;
```

Acute/chronic load curves (ATL 7 d / CTL 42 d / TSB) are computed in Python by `garmin_sync.metrics.load_curves()` from daily `load` sums. Garmin's own values are in `training_status.acute_load` / `chronic_load`.

---

## Answering training questions (notes for Claude)

- Always state the period and the tag filter used. Weeks are Monday-based.
- For orienteering, summarise in **hours, sessions, HR/zones and load**. Mention pace or distance only when asked.
- Separate manual from auto tags when the answer depends on tags (`tag_source`). Say how many sessions are auto-tagged.
- Load: `load` mixes Garmin load (API) and TRIMP (FIT imports). Within one source they are comparable; across sources, be careful.
- Recovery questions: join `daily_metrics.date` to the day **after** the session for overnight HRV/RHR/sleep.
- Be careful with empty data: `daily_metrics` and `training_status` coverage starts later than the activities, and not every metric exists every day.
- Never read `.env`, `~/.garminconnect/` or anything outside the database for these questions.
