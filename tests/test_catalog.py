"""Tests for the catalog / title-matching check layer."""

import pytest

from pydistro import Catalog, CatalogEntry, Release, Track, normalize_title


def entry(title: str, artist: str = "Zion Gates Music", isrc: "str | None" = None,
          release_id: int = 1, track_id: int = 1) -> CatalogEntry:
    # Unique per-track ISRC by default (real ISRCs are unique); pass "" for none.
    if isrc is None:
        isrc = f"USABC000{track_id:04d}"
    return CatalogEntry(
        track=Track(id=track_id, title=title, isrc=isrc),
        release=Release(id=release_id, artist=artist, title=title),
    )


@pytest.fixture
def catalog() -> Catalog:
    return Catalog([
        entry("Neon Kingston Street Reggae Mix", track_id=1, release_id=1),
        entry("Midnight Dub Session", track_id=2, release_id=2),
        entry("Lions Roar", track_id=3, release_id=3, isrc=""),  # no ISRC
    ])


# --- normalization --------------------------------------------------------- #
def test_normalize_strips_promo_brackets():
    assert normalize_title("Great Song (Official Video)") == "great song"
    assert normalize_title("Great Song [Official Audio]") == "great song"
    assert normalize_title("Great Song (HD)") == "great song"


def test_normalize_keeps_version_markers():
    # Version info must survive so versions stay distinct.
    assert "live" in normalize_title("Great Song (Live)")
    assert "acoustic" in normalize_title("Great Song (Acoustic)")


def test_normalize_strips_feat_and_amp():
    assert normalize_title("Great Song feat. Somebody") == "great song"
    assert normalize_title("Rock & Roll") == "rock and roll"


# --- matching the real channel convention ---------------------------------- #
def test_check_pipe_delimited_real_title(catalog):
    raw = ("Neon Kingston Street Reggae Mix | Zion Gates Music "
           "| Roots & Modern Reggae Revival | Mix #5")
    r = catalog.check(raw)
    assert r.matched is True
    assert r.confidence == 1.0
    assert r.official_title == "Neon Kingston Street Reggae Mix"
    assert r.official_artist == "Zion Gates Music"
    assert r.isrc == "USABC0000001"  # track_id=1
    assert r.issues == []


def test_check_exact_simple(catalog):
    r = catalog.check("Midnight Dub Session")
    assert r.matched and r.confidence == 1.0
    assert r.official_title == "Midnight Dub Session"


def test_check_fuzzy_typo(catalog):
    r = catalog.check("Midnite Dub Session | Zion Gates Music")
    assert r.matched is True
    assert 0.85 <= r.confidence < 1.0
    assert any("fuzzy" in i for i in r.issues)


def test_check_no_match_offers_suggestions(catalog):
    r = catalog.check("Totally Unrelated Pop Banger | Some Other Channel")
    assert r.matched is False
    assert "no catalog match found" in r.issues


def test_check_flags_missing_isrc(catalog):
    r = catalog.check("Lions Roar")
    assert r.matched is True
    assert r.isrc == ""
    assert any("ISRC" in i for i in r.issues)


def test_check_ambiguous_titles_need_artist():
    cat = Catalog([
        entry("Sunrise", artist="Artist A", release_id=1, track_id=1),
        entry("Sunrise", artist="Artist B", release_id=2, track_id=2),
    ])
    r = cat.check("Sunrise")
    assert r.matched is False
    assert any("ambiguous" in i for i in r.issues)
    # Disambiguate by artist.
    r2 = cat.check("Sunrise", artist="Artist B")
    assert r2.matched is True
    assert r2.official_artist == "Artist B"


def test_missing_posts_reports_coverage_gaps(catalog):
    posted = ["Neon Kingston Street Reggae Mix | Zion Gates Music | Mix #5"]
    missing = catalog.missing_posts(posted)
    missing_titles = {e.track.title for e in missing}
    assert "Neon Kingston Street Reggae Mix" not in missing_titles
    assert "Midnight Dub Session" in missing_titles
    assert "Lions Roar" in missing_titles


# --- cache round-trip ------------------------------------------------------ #
def test_find_by_isrc(catalog):
    # track_id=1 -> USABC0000001 (case-insensitive lookup).
    e = catalog.find_by_isrc("usabc0000001")
    assert e is not None and e.track.title == "Neon Kingston Street Reggae Mix"
    assert catalog.find_by_isrc("NOPE") is None
    assert catalog.find_by_isrc("") is None


def test_find_by_title_slug_input(catalog):
    # Filename-slug input (as the DJ Metaverse pipeline passes).
    hits = catalog.find_by_title("midnight_dub_session")
    assert hits and hits[0].track.title == "Midnight Dub Session"


def test_find_by_title_exact_only(catalog):
    hits = catalog.find_by_title("Midnight Dub Session", fuzzy=False)
    assert len(hits) == 1
    assert catalog.find_by_title("midnite dub sesion", fuzzy=False) == []


def test_find_by_title_fuzzy_ranks_best_first(catalog):
    hits = catalog.find_by_title("midnite dub session")  # typo
    assert hits[0].track.title == "Midnight Dub Session"


def test_hyperfollow_link():
    from pydistro.models import Link, ReleaseLinks
    e = CatalogEntry(
        track=Track(id=1, title="X", isrc="A"),
        release=Release(id=1, artist="Zion Gates Music", title="X",
                        links=ReleaseLinks(hyperfollow=Link(href="https://distrokid.com/hyperfollow/x"))),
    )
    assert e.hyperfollow == "https://distrokid.com/hyperfollow/x"
    # No links -> empty string, not an error.
    assert CatalogEntry(Track(id=2, title="Y"), Release(id=2, artist="a", title="Y")).hyperfollow == ""


def test_cache_save_and_load(catalog, tmp_path):
    path = tmp_path / "catalog.json"
    catalog.save(str(path))
    reloaded = Catalog.from_cache(str(path))
    assert len(reloaded.entries) == len(catalog.entries)
    r = reloaded.check("Neon Kingston Street Reggae Mix")
    assert r.matched and r.official_artist == "Zion Gates Music"
