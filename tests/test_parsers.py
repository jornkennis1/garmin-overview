"""Parsing of Garmin API responses (made-up, trimmed-down examples of the real shapes)."""

from garmin_sync.sync import (
    first, non_negative, parse_activity, parse_hrv_summary, parse_laps, parse_samples, parse_sleep,
    parse_training_status, parse_user_summary, parse_zones,
)


def test_first_follows_dotted_paths_and_skips_none():
    d = {"a": None, "b": {"c": 3}, "x": 0}
    assert first(d, "a", "b.c") == 3
    assert first(d, "x", "b.c") == 0  # 0 is a value, not "missing"
    assert first(d, "missing.deep") is None
    assert first(None, "a") is None


def test_non_negative_drops_garmin_no_data_markers():
    assert non_negative(-1) is None
    assert non_negative(-2) is None
    assert non_negative(0) == 0
    assert non_negative("12") is None


def test_parse_activity():
    a = {
        "activityId": 101, "activityName": "Forest run", "startTimeLocal": "2026-10-01 18:00:00",
        "startTimeGMT": "2026-10-01 16:00:00", "activityType": {"typeKey": "trail_running"},
        "eventType": {"typeKey": "race"}, "duration": 3600.0, "distance": 10000.0, "averageHR": 150,
        "activityTrainingLoad": 120.5,
    }
    row = parse_activity(a)
    assert row["activity_id"] == 101
    assert row["sport_type"] == "trail_running"
    assert row["event_type"] == "race"
    assert row["training_load"] == 120.5
    assert row["max_hr"] is None
    assert row["source"] == "api"


def test_parse_zones_skips_incomplete_entries():
    zones = [{"zoneNumber": 1, "secsInZone": 60, "zoneLowBoundary": 100},
             {"zoneNumber": 2, "secsInZone": None}, {"secsInZone": 5}]
    assert parse_zones(1, zones) == [{"activity_id": 1, "zone": 1, "seconds": 60.0, "zone_low_bpm": 100}]
    assert parse_zones(1, None) == []


def test_parse_samples_maps_positional_metrics():
    details = {
        "metricDescriptors": [{"key": "sumElapsedDuration", "metricsIndex": 0},
                              {"key": "directHeartRate", "metricsIndex": 1},
                              {"key": "directSpeed", "metricsIndex": 2}],
        "activityDetailMetrics": [{"metrics": [0.0, 120, 3.0]}, {"metrics": [5.0, 125, 3.2]}],
    }
    rows = parse_samples(7, details)
    assert [(r["t_offset_s"], r["hr"], r["speed_mps"]) for r in rows] == [(0.0, 120, 3.0), (5.0, 125, 3.2)]


def test_parse_samples_falls_back_to_timestamps():
    details = {
        "metricDescriptors": [{"key": "directTimestamp", "metricsIndex": 0},
                              {"key": "directHeartRate", "metricsIndex": 1}],
        "activityDetailMetrics": [{"metrics": [1_000_000, 110]}, {"metrics": [1_004_000, 112]}],
    }
    assert [r["t_offset_s"] for r in parse_samples(7, details)] == [0.0, 4.0]
    assert parse_samples(7, {}) == []


def test_parse_laps_uses_lap_start_times():
    splits = {"lapDTOs": [
        {"lapIndex": 1, "startTimeGMT": "2026-10-01T16:00:00.0", "duration": 300, "distance": 1000},
        {"lapIndex": 2, "startTimeGMT": "2026-10-01T16:06:00.0", "duration": 240, "distance": 1000,
         "intensityType": "INTERVAL"},
    ]}
    laps = parse_laps(1, splits, "2026-10-01 16:00:00")
    assert [lap["start_offset_s"] for lap in laps] == [0.0, 360.0]  # 60 s pause between the laps
    assert laps[1]["intensity"] == "INTERVAL"


def test_parse_laps_without_start_times_adds_up_durations():
    splits = {"lapDTOs": [{"duration": 300}, {"duration": 240}, {"duration": 200}]}
    laps = parse_laps(1, splits, None)
    assert [lap["start_offset_s"] for lap in laps] == [0.0, 300.0, 540.0]
    assert [lap["lap_index"] for lap in laps] == [1, 2, 3]


def test_parse_user_summary_flat_and_nested_agree():
    flat = {"restingHeartRate": 45, "averageStressLevel": -1, "totalSteps": 9000}
    nested = {"heartRate": {"restingValue": 45}, "stress": {"avgLevel": -1}, "movement": {"steps": {"value": 9000}}}
    assert parse_user_summary(flat) == parse_user_summary(nested)
    assert parse_user_summary(flat)["stress_avg"] is None


def test_parse_sleep_and_hrv():
    sleep = parse_sleep({"dailySleepDTO": {"sleepTimeSeconds": 28000, "sleepScores": {"overall": {"value": 81}}}})
    assert sleep["sleep_s"] == 28000 and sleep["sleep_score"] == 81
    hrv = parse_hrv_summary({"lastNightAvg": 62, "baseline": {"balancedLow": 55, "balancedUpper": 70}, "status": "BALANCED"})
    assert (hrv["hrv_overnight_avg"], hrv["hrv_baseline_low"], hrv["hrv_status"]) == (62, 55, "BALANCED")


def test_parse_training_status_prefers_primary_device():
    ts = {
        "mostRecentTrainingStatus": {"latestTrainingStatusData": {
            "111": {"trainingStatusFeedbackPhrase": "DETRAINING_1"},
            "222": {"primaryTrainingDevice": True, "trainingStatusFeedbackPhrase": "PRODUCTIVE_3",
                    "acuteTrainingLoadDTO": {"dailyTrainingLoadAcute": 500, "dailyAcuteChronicWorkloadRatio": 1.1}},
        }},
        "mostRecentVO2Max": {"generic": {"vo2MaxValue": 58}},
    }
    row = parse_training_status(ts, {"score": 70, "level": "HIGH"})
    assert row["status"] == "PRODUCTIVE"  # the "_3" suffix is stripped
    assert row["acute_load"] == 500
    assert row["vo2max"] == 58
    assert row["readiness_score"] == 70
    assert parse_training_status({}, None)["status"] is None
