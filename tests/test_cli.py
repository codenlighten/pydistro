"""Tests for the CLI. Catalog commands run offline against a saved cache,
so no token or network is needed."""

import json

import pytest

from pydistro import Catalog, CatalogEntry, Release, Track
from pydistro.cli import main


@pytest.fixture
def cache_file(tmp_path):
    cat = Catalog([
        CatalogEntry(Track(id=1, title="Midnight Dub Session", isrc="USABC0000001"),
                     Release(id=1, artist="Zion Gates Music", title="Midnight Dub Session")),
        CatalogEntry(Track(id=2, title="Lions Roar", isrc=""),
                     Release(id=2, artist="Zion Gates Music", title="Lions Roar")),
    ])
    path = tmp_path / "catalog.json"
    cat.save(str(path))
    return str(path)


def run(argv):
    return main(argv)


def test_check_mix_human_output(cache_file, capsys):
    desc = "0:00 Midnight Dub Session\n3:42 Lions Roar\n9:50 Unknown Song"
    code = run(["check-mix", "--cache", cache_file, "--offline", "--text", desc])
    out = capsys.readouterr().out
    assert code == 0
    assert "2/3 matched" in out
    assert "MISS" in out and "Unknown Song" in out
    assert "backfill" in out  # Lions Roar has no ISRC


def test_check_mix_json_output(cache_file, capsys):
    desc = "0:00 Midnight Dub Session"
    code = run(["check-mix", "--cache", cache_file, "--offline", "--json", "--text", desc])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert data["total"] == 1
    assert data["tracks"][0]["isrc"] == "USABC0000001"
    assert data["tracks"][0]["status"] == "OK"


def test_check_mix_strict_exit_code(cache_file):
    # An unknown song under --strict should exit nonzero.
    code = run(["check-mix", "--cache", cache_file, "--offline", "--strict",
                "--text", "0:00 Totally Unknown Track"])
    assert code == 1


def test_check_single_title(cache_file, capsys):
    code = run(["check", "Midnight Dub Session", "--cache", cache_file, "--offline"])
    out = capsys.readouterr().out
    assert code == 0
    assert "OK" in out
    assert "USABC0000001" in out


def test_missing_command(cache_file, capsys):
    code = run(["missing", "--cache", cache_file, "--offline",
                "--text", "Midnight Dub Session"])
    out = capsys.readouterr().out
    assert code == 0
    # Only "Lions Roar" should be reported as not yet posted.
    assert "Lions Roar" in out
    assert "Midnight Dub Session" not in out.split(":", 1)[1]


def test_offline_without_cache_errors(tmp_path):
    missing = str(tmp_path / "nope.json")
    with pytest.raises(SystemExit):
        run(["check", "x", "--cache", missing, "--offline"])


def test_check_mix_url_fetches_description(cache_file, capsys, monkeypatch):
    from pydistro.youtube import YouTubeSnippet
    import pydistro.cli as cli

    def fake_fetch(url_or_id, api_key, **kw):
        assert api_key == "test-key"
        return YouTubeSnippet(
            video_id="JgEquXGIRaE",
            title="Reggae Mix #5",
            description="0:00 Midnight Dub Session\n3:42 Lions Roar",
            channel_title="Zion Gates Music",
        )

    monkeypatch.setattr(cli, "fetch_snippet", fake_fetch)
    code = run(["check-mix", "--cache", cache_file, "--offline",
                "--url", "https://youtu.be/JgEquXGIRaE", "--youtube-api-key", "test-key"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Reggae Mix #5" in out          # title header printed
    assert "2/2 matched" in out


def test_check_mix_url_without_key_errors(cache_file, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        run(["check-mix", "--cache", cache_file, "--offline", "--url", "JgEquXGIRaE"])


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        run(["--version"])
    assert e.value.code == 0
    assert "pydistro" in capsys.readouterr().out
