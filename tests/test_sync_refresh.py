"""Re-checking recent activities: renames are picked up, activities deleted in Garmin are removed."""

from datetime import date, timedelta

import pytest

import config
from garmin_sync import sync

from conftest import add_activity


class FakeGarmin:
    def __init__(self, activities):
        self.activities = activities
        self.calls = []

    def get_activities_by_date(self, start, end):
        self.calls.append((start, end))
        return [a for a in self.activities if start <= a["startTimeLocal"][:10] <= end]


def garmin_activity(activity_id: int, day: date, name: str) -> dict:
    return {"activityId": activity_id, "startTimeLocal": f"{day} 18:00:00", "activityName": name,
            "activityType": {"typeKey": "running"}}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "API_DELAY_S", 0)
    monkeypatch.setattr(sync, "RAW_SAMPLE_DIR", tmp_path / "samples")


def ids(conn) -> set[int]:
    return {r[0] for r in conn.execute("SELECT activity_id FROM activities")}


def test_rename_and_delete_within_the_window(db):
    today = date.today()
    recent, old = today - timedelta(days=2), today - timedelta(days=100)
    add_activity(db, 1, f"{recent} 18:00:00", name="Morning Run", custom_name="My own name")
    add_activity(db, 2, f"{recent} 19:00:00")  # deleted in Garmin
    add_activity(db, 3, f"{old} 18:00:00")  # deleted too, but outside the window: kept
    add_activity(db, 4, f"{today} 07:00:00")  # today must count as inside the window
    add_activity(db, 5, f"{recent} 20:00:00", source="fit")  # FIT imports are never removed
    db.execute("INSERT INTO activity_tags (activity_id, tag, source) VALUES (2, 'o_race', 'manual')")
    db.execute("INSERT INTO o_maps (activity_id, image_file, map_points, track_points) VALUES (2, 'm2.png', '[]', '[]')")
    db.commit()
    (config.DATA_DIR / "maps").mkdir()
    (config.DATA_DIR / "maps" / "m2.png").write_bytes(b"png")

    client = FakeGarmin([garmin_activity(1, recent, "Forest middle"), garmin_activity(4, today, "Run")])
    removed = sync.refresh_recent_activities(client, db, days=30, since=None)

    assert removed == 1
    assert ids(db) == {1, 3, 4, 5}
    name, custom = db.execute("SELECT name, custom_name FROM activities WHERE activity_id = 1").fetchone()
    assert (name, custom) == ("Forest middle", "My own name")  # Garmin's name updated, yours kept
    assert db.execute("SELECT count(*) FROM activity_tags WHERE activity_id = 2").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM o_maps").fetchone()[0] == 0
    assert not (config.DATA_DIR / "maps" / "m2.png").exists()
    assert client.calls == [((today - timedelta(days=29)).isoformat(), (today + timedelta(days=1)).isoformat())]


def test_empty_answer_from_garmin_removes_nothing(db):
    add_activity(db, 1, f"{date.today()} 07:00:00")
    db.commit()
    assert sync.refresh_recent_activities(FakeGarmin([]), db, days=30, since=None) == 0
    assert ids(db) == {1}


def test_refresh_respects_since_and_can_be_turned_off(db):
    today = date.today()
    client = FakeGarmin([])
    assert sync.refresh_recent_activities(client, db, days=0, since=None) == 0
    assert sync.refresh_recent_activities(client, db, days=30, since=(today + timedelta(days=1)).isoformat()) == 0
    assert client.calls == []
    sync.refresh_recent_activities(client, db, days=30, since=(today - timedelta(days=3)).isoformat())
    assert client.calls[0][0] == (today - timedelta(days=3)).isoformat()
