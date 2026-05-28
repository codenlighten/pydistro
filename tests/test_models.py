"""Tests for pydantic model parsing and aliases."""

from datetime import datetime

from pydistro import Release, Track, Video, VideoStore
from pydistro.models import ReleaseArtwork


def test_release_aliases_and_defaults():
    r = Release.model_validate(
        {
            "id": 1,
            "title": "Hello",
            "isdeleted": True,
            "trackcount": 4,
            "recordlabel": "MyLabel",
            "releasedate": "2024-01-15T00:00:00Z",
            "unknown_future_field": "ignored",
        }
    )
    assert r.is_deleted is True
    assert r.track_count == 4
    assert r.record_label == "MyLabel"
    assert r.release_date == datetime.fromisoformat("2024-01-15T00:00:00+00:00")
    # Missing optional fields fall back to sane defaults, not errors.
    assert r.stores == []
    assert r.uuid == ""


def test_artwork_numeric_aliases():
    art = ReleaseArtwork.model_validate({"300": "a.jpg", "100": "b.jpg", "full": "c.jpg"})
    assert art.size_300 == "a.jpg"
    assert art.size_100 == "b.jpg"
    assert art.full == "c.jpg"


def test_track_alias_iscoversong():
    t = Track.model_validate({"id": 9, "iscoversong": True, "hasisrc": True, "tracknum": 2})
    assert t.is_cover_song is True
    assert t.has_isrc is True
    assert t.track_num == 2


def test_video_store_array_defaults_false():
    v = Video(id="x")
    assert v.stores == [False] * len(VideoStore)
    assert v.available_stores() == []
    v.stores[VideoStore.TIDAL] = True
    assert v.available_stores() == [VideoStore.TIDAL]
