"""Offline tests for the video scraper, using saved HTML fixtures."""

from datetime import datetime

import pytest

from pydistro import Video, VideoStore, VideoType, VideoUnavailableError
from pydistro.videos import _parse_dk_date, _parse_video, _video_type


def parse(fixture, name: str, video_id: str) -> Video:
    video = Video(id=video_id, type=_video_type(video_id))
    return _parse_video(fixture(name), video)


def test_video_type_detection():
    assert _video_type("Rc92Mqy6SWr") == VideoType.VIZY
    assert _video_type("mv-abc") == VideoType.MINIVIDEO
    assert _video_type("dv-xyz") == VideoType.DISTROVID


def test_parse_vizy(fixture):
    v = parse(fixture, "video_vizy.html", "Rc92Mqy6SWr")
    assert v.type == VideoType.VIZY
    assert v.artist == "Cool Artist"
    assert v.title == "Great Song"
    assert v.uploader == "cooluser"
    assert v.distrokid_views == 12345
    assert v.upload_date == datetime(2024, 1, 2)
    assert v.description == "This is the description."
    assert v.thumbnail.endswith("/thumb.jpg")
    assert v.animated_thumbnail.endswith("/animated.gif")
    assert v.source_url.endswith("/stream.m3u8")
    assert v.recommended == ["abc123", "def456"]


def test_parse_vizy_stores(fixture):
    v = parse(fixture, "video_vizy.html", "Rc92Mqy6SWr")
    # dsp-41 (Apple Music) and dsp-42 (Tidal) visible; dsp-40 (Vevo) hidden.
    assert v.stores[VideoStore.APPLEMUSIC] is True
    assert v.stores[VideoStore.TIDAL] is True
    assert v.stores[VideoStore.VEVO] is False
    assert set(v.available_stores()) == {VideoStore.APPLEMUSIC, VideoStore.TIDAL}


def test_parse_minivideo(fixture):
    v = parse(fixture, "video_minivideo.html", "mv-K0ye9T6Xv")
    assert v.type == VideoType.MINIVIDEO
    # " Mini Video" suffix trimmed from the title.
    assert v.title == "My Song"
    # Artist pulled from the first recommended video.
    assert v.artist == "MV Artist"
    assert v.recommended == ["mv-rel1"]


def test_parse_distrovid(fixture):
    v = parse(fixture, "video_distrovid.html", "dv-5yW2dTd8N")
    assert v.type == VideoType.DISTROVID
    assert v.title == "DistroVid Title"
    assert v.artist == "DV Artist Name"
    assert v.release_date == datetime(2023, 3, 15)
    assert v.release_date_string == "Mar 15, 2023"


def test_parse_unavailable_raises(fixture):
    video = Video(id="bad", type=VideoType.VIZY)
    with pytest.raises(VideoUnavailableError):
        _parse_video(fixture("video_unavailable.html"), video)


def test_artist_falls_back_to_uploader(fixture):
    # A vizy page whose title has no "Artist - " split still gets an artist.
    html = (
        "<html><head><title>x - y</title></head><body>"
        '<div class="videoMetadataContainer">'
        '<div style="line-height: 1.5;">SingleWordTitle</div>'
        '<div class="vUsername">fallbackuser</div>'
        "</div></body></html>"
    )
    video = Video(id="z", type=VideoType.VIZY)
    v = _parse_video(html, video)
    assert v.artist == "fallbackuser"


def test_parse_dk_date_handles_padding_and_garbage():
    assert _parse_dk_date("Jan  2, 2024") == datetime(2024, 1, 2)
    assert _parse_dk_date("Mar 15, 2023") == datetime(2023, 3, 15)
    assert _parse_dk_date("not a date") is None
    assert _parse_dk_date("") is None
