"""Tests for the authenticated client, using an injected httpx MockTransport
so no real network calls are made."""

import httpx
import pytest

from pydistro import APIError, AuthError, DistroKid, RateLimitError


def make_client(handler) -> DistroKid:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://distrokid.com/api/v1")
    return DistroKid("test-token", client=http)


def test_get_releases_parses_items():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/releases"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {"id": 1, "title": "Album One", "trackcount": 3, "artist": "Me"},
                        {"id": 2, "title": "Album Two", "numtracks": "5"},
                    ]
                }
            },
        )

    dk = make_client(handler)
    releases = dk.get_releases()
    assert len(releases) == 2
    assert releases[0].id == 1
    assert releases[0].title == "Album One"
    assert releases[0].track_count == 3
    assert releases[1].num_tracks == "5"


def test_get_release_and_tracks():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/releases/42":
            return httpx.Response(200, json={"data": {"id": 42, "title": "X"}})
        if request.url.path == "/api/v1/releases/42/tracks":
            return httpx.Response(
                200,
                json={"data": {"tracks": [{"id": 7, "title": "T", "duration_seconds": 180, "isrc": "ABC"}]}},
            )
        return httpx.Response(404)

    dk = make_client(handler)
    rel = dk.get_release(42)
    assert rel.id == 42 and rel.title == "X"

    tracks = dk.get_tracks(42)
    assert tracks[0].id == 7
    assert tracks[0].duration_seconds == 180
    assert tracks[0].isrc == "ABC"


def test_track_stats_keyed_by_service():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": 7,
                    "title": "T",
                    "stats": {"spotify": {"data": {"total": 1000, "period": "all", "points": []}}},
                }
            },
        )

    dk = make_client(handler)
    stats = dk.get_track_stats(7)
    assert stats.stats["spotify"].data.total == 1000
    assert stats.stats["spotify"].data.period == "all"


def test_auth_error_on_401():
    dk = make_client(lambda req: httpx.Response(401))
    with pytest.raises(AuthError) as exc:
        dk.get_releases()
    assert exc.value.status_code == 401


def test_api_error_on_404():
    dk = make_client(lambda req: httpx.Response(404))
    with pytest.raises(APIError) as exc:
        dk.get_release(999)
    assert exc.value.status_code == 404


def test_retries_then_succeeds(monkeypatch):
    # Avoid real sleeping during the backoff.
    monkeypatch.setattr("pydistro.client.time.sleep", lambda *_: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": {"items": []}})

    dk = make_client(handler)
    assert dk.get_releases() == []
    assert calls["n"] == 2  # one failure + one success


def test_rate_limit_raises_distinct_type(monkeypatch):
    monkeypatch.setattr("pydistro.client.time.sleep", lambda *_: None)
    dk = make_client(lambda req: httpx.Response(429))
    with pytest.raises(RateLimitError) as exc:
        dk.get_releases()
    assert exc.value.status_code == 429
    # Still an APIError for callers that catch broadly.
    assert isinstance(exc.value, APIError)


def test_context_manager_closes():
    closed = {"v": False}

    class FakeClient:
        def request(self, *a, **k):
            return httpx.Response(200, json={"data": {"items": []}}, request=httpx.Request("GET", "http://x"))

        def close(self):
            closed["v"] = True

    # owns_client stays False when we pass one in, so it won't auto-close...
    dk = DistroKid("t", client=FakeClient())
    with dk:
        pass
    # passed-in client is not owned, so we must NOT close it.
    assert closed["v"] is False
