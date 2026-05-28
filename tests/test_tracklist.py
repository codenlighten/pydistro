"""Tests for tracklist parsing and whole-mix checking."""

import pytest

from pydistro import (
    Catalog,
    CatalogEntry,
    Release,
    Track,
    parse_tracklist,
)


def entry(title: str, isrc: str = "USABC0000001", rid: int = 0) -> CatalogEntry:
    return CatalogEntry(
        track=Track(id=rid, title=title, isrc=isrc),
        release=Release(id=rid, artist="Zion Gates Music", title=title),
    )


# --- parsing --------------------------------------------------------------- #
def test_parse_basic_timestamps():
    desc = """
    Tracklist:
    0:00 Midnight Dub Session
    3:42 Lions Roar
    7:15 Neon Kingston Street
    """
    items = parse_tracklist(desc)
    assert [i.raw_title for i in items] == [
        "Midnight Dub Session",
        "Lions Roar",
        "Neon Kingston Street",
    ]
    assert items[0].seconds == 0
    assert items[1].seconds == 3 * 60 + 42
    assert items[1].timestamp == "3:42"


def test_parse_various_formats():
    desc = """
    1. Song One 0:00
    00:00 - Song Two
    [1:02:33] Song Three
    0:00 | Song Four
    #5 Song Five 2:00
    """
    titles = [i.raw_title for i in parse_tracklist(desc)]
    assert titles == ["Song One", "Song Two", "Song Three", "Song Four", "Song Five"]


def test_parse_hours_to_seconds():
    items = parse_tracklist("1:02:33 Long One")
    assert items[0].seconds == 3600 + 2 * 60 + 33


def test_parse_ignores_lines_without_timestamps():
    desc = "Follow me!\nhttps://example.com\nSubscribe\n0:00 Real Song"
    items = parse_tracklist(desc)
    assert len(items) == 1
    assert items[0].raw_title == "Real Song"


def test_parse_preserves_title_brackets_strips_timestamp_brackets():
    # A bracketed timestamp is consumed; a bracketed title suffix survives.
    items = parse_tracklist("[0:00] Babylon Falls (Official Audio)\n3:00 Roots (Live)")
    assert items[0].raw_title == "Babylon Falls (Official Audio)"
    assert items[1].raw_title == "Roots (Live)"


def test_parse_artist_dash_title_kept_whole():
    # The "Artist - Title" split is handled later by check(); parser keeps it.
    items = parse_tracklist("0:00 Zion Gates Music - Lions Roar")
    assert items[0].raw_title == "Zion Gates Music - Lions Roar"


# --- whole-mix check ------------------------------------------------------- #
@pytest.fixture
def catalog():
    return Catalog([
        entry("Midnight Dub Session", rid=1),
        entry("Lions Roar", isrc="", rid=2),       # no ISRC
        entry("Neon Kingston Street", rid=3),
    ])


def test_check_tracklist_aggregates(catalog):
    desc = """
    0:00 Midnight Dub Session
    3:42 Lions Roar
    7:15 Neon Kingston Street
    9:50 Some Song Not In Catalog
    """
    mix = catalog.check_tracklist(desc)
    assert mix.total == 4
    assert len(mix.matched) == 3
    assert len(mix.unmatched) == 1
    assert mix.unmatched[0].item.raw_title == "Some Song Not In Catalog"
    assert len(mix.missing_isrc) == 1
    assert mix.missing_isrc[0].result.official_title == "Lions Roar"
    assert "3/4 matched" in mix.summary()


def test_check_tracklist_preserves_timestamps(catalog):
    mix = catalog.check_tracklist("3:42 Lions Roar")
    assert mix.checks[0].item.timestamp == "3:42"
    assert mix.checks[0].result.isrc == ""  # surfaced for backfill
