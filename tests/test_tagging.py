"""Auto-tag rules. Thresholds are read from config, so the tests follow the defaults in config.py."""

import config
from garmin_sync.tagging import apply_auto_tags, looks_like_intervals, set_manual_tag, suggest_tag

from conftest import add_activity

KM = 1000


def run(**kw) -> dict:
    return {"sport_type": "running", "name": "", "distance_m": 8 * KM, **kw}


def test_orienteering_race_and_training():
    assert suggest_tag(run(name="Jukola night leg")) == "o_race"
    assert suggest_tag(run(name="Forest middle", event_type="race")) == "o_race"
    assert suggest_tag(run(name="Sprint O in town")) == "o_training"
    assert suggest_tag(run(o_prob=config.O_PROB_THRESHOLD)) == "o_training"
    assert suggest_tag(run(o_prob=config.O_PROB_THRESHOLD - 0.01)) == "easy_run"


def test_interval_needs_enough_distance():
    long_enough = config.INTERVAL_MIN_TOTAL_KM * KM
    assert suggest_tag(run(name="6x1000", distance_m=long_enough)) == "interval"
    assert suggest_tag(run(name="6x1000", distance_m=long_enough - 1)) == "easy_run"
    assert suggest_tag(run(sport_type="track_running", distance_m=long_enough)) == "interval"


def test_keywords_match_whole_words_only():
    assert suggest_tag(run(name="Mapleton loop")) == "easy_run"  # "map" inside a word
    assert suggest_tag(run(name="Training with map")) == "o_training"


def test_long_run_and_other_sports():
    assert suggest_tag(run(distance_m=config.LONG_RUN_MIN_KM * KM)) == "long_run"
    assert suggest_tag({"sport_type": "strength_training"}) == "strength"
    assert suggest_tag({"sport_type": "road_biking"}) == "cycling"
    assert suggest_tag({"sport_type": "hiking"}) == "hiking_walking"
    assert suggest_tag({"sport_type": "swimming"}) == "other"
    assert suggest_tag({}) == "other"


def test_custom_tags_win_over_built_in_rules():
    custom = [{"key": "c_club", "matcher": None, "sport_types": {"running"}}]
    assert suggest_tag(run(name="Jukola"), custom) == "c_club"


def test_lap_pattern_intervals():
    a = {"distance_m": config.INTERVAL_MIN_KM * KM, "n_laps": config.INTERVAL_MIN_LAPS,
         "lap_dist_cv": config.INTERVAL_LAP_DIST_CV, "lap_alternation": config.INTERVAL_ALTERNATION,
         "lap_fast_slow_gap": config.INTERVAL_FAST_SLOW_GAP}
    assert looks_like_intervals(a)
    assert not looks_like_intervals({**a, "lap_dist_cv": 0.0})  # even 1 km auto-laps
    assert looks_like_intervals({"has_interval_laps": 1})


def test_apply_auto_tags_keeps_manual_tags(db):
    add_activity(db, 1, "2026-10-01 18:00:00", name="Jukola")
    add_activity(db, 2, "2026-10-02 18:00:00", name="Jukola")
    db.commit()
    set_manual_tag(db, 2, "easy_run")
    apply_auto_tags(db)
    tags = dict(db.execute("SELECT activity_id, tag FROM activity_tags").fetchall())
    assert tags == {1: "o_race", 2: "easy_run"}
