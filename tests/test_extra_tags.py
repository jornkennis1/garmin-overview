"""Extra tags on top of the main tag."""

import pandas as pd
import pytest

from garmin_sync.tagging import apply_auto_tags, has_tag, save_custom_tags, set_extra_tags, set_manual_tag

from conftest import add_activity


def view(conn) -> dict:
    return {r["activity_id"]: (r["tag"], r["extra_tags"]) for r in conn.execute("SELECT * FROM v_activities")}


def test_extra_tags_show_in_the_view_sorted_and_without_the_main_tag(db):
    add_activity(db, 1, "2026-10-01 18:00:00", name="Sprint O in town")
    db.commit()
    apply_auto_tags(db)
    set_extra_tags(db, 1, ["long_run", "interval", "o_training", "interval"])
    assert view(db) == {1: ("o_training", "interval,long_run")}
    set_extra_tags(db, 1, [])
    assert view(db) == {1: ("o_training", None)}


def test_unknown_extra_tag_is_refused(db):
    add_activity(db, 1, "2026-10-01 18:00:00")
    db.commit()
    with pytest.raises(ValueError):
        set_extra_tags(db, 1, ["no_such_tag"])


def test_extra_that_becomes_the_main_tag_is_dropped(db):
    add_activity(db, 1, "2026-10-01 18:00:00")
    db.commit()
    apply_auto_tags(db)
    set_extra_tags(db, 1, ["interval", "o_training"])
    set_manual_tag(db, 1, "interval")
    assert view(db) == {1: ("interval", "o_training")}
    # Same when the auto rules move the main tag onto an extra tag (here: a name keyword).
    db.execute("DELETE FROM activity_tags")
    db.execute("UPDATE activities SET name = 'Forest training with map'")
    apply_auto_tags(db)
    assert view(db) == {1: ("o_training", None)}


def test_removing_your_own_tag_removes_it_as_extra_tag(db):
    add_activity(db, 1, "2026-10-01 18:00:00")
    db.commit()
    save_custom_tags(db, [{"key": None, "label": "Club night"}])
    key = db.execute("SELECT key FROM custom_tags").fetchone()[0]
    set_extra_tags(db, 1, [key])
    save_custom_tags(db, [])
    assert view(db)[1][1] is None


def test_has_tag_checks_main_and_extra_tags():
    acts = pd.DataFrame({"tag": ["interval", "easy_run", "o_race"], "extras": [["o_training"], [], []]})
    assert has_tag(acts, ["o_training"]).tolist() == [True, False, False]
    assert has_tag(acts, ["o_race", "o_training"]).tolist() == [True, False, True]
    assert has_tag(acts.drop(columns="extras"), ["o_training"]).tolist() == [False, False, False]
