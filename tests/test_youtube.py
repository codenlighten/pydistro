"""Tests for YouTube id extraction and Data API fetching (mocked transport)."""

import httpx
import pytest

from pydistro import YouTubeError, extract_video_id, fetch_snippet


@pytest.mark.parametrize("url,expected", [
    ("JgEquXGIRaE", "JgEquXGIRaE"),
    ("https://www.youtube.com/watch?v=JgEquXGIRaE", "JgEquXGIRaE"),
    ("https://www.youtube.com/watch?v=JgEquXGIRaE&list=PL123&t=10", "JgEquXGIRaE"),
    ("https://youtu.be/JgEquXGIRaE", "JgEquXGIRaE"),
    ("https://youtu.be/JgEquXGIRaE?t=42", "JgEquXGIRaE"),
    ("https://www.youtube.com/shorts/JgEquXGIRaE", "JgEquXGIRaE"),
    ("https://www.youtube.com/embed/JgEquXGIRaE", "JgEquXGIRaE"),
    ("https://www.youtube.com/live/JgEquXGIRaE", "JgEquXGIRaE"),
])
def test_extract_video_id(url, expected):
    assert extract_video_id(url) == expected


def test_extract_video_id_invalid():
    with pytest.raises(YouTubeError):
        extract_video_id("https://example.com/not-a-video")


def test_fetch_snippet_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id"] == "JgEquXGIRaE"
        assert request.url.params["part"] == "snippet"
        return httpx.Response(200, json={
            "items": [{"snippet": {
                "title": "Neon Kingston Street Reggae Mix | Zion Gates Music",
                "description": "0:00 Midnight Dub Session\n3:42 Lions Roar",
                "channelTitle": "Zion Gates Music",
            }}]
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    snip = fetch_snippet("https://youtu.be/JgEquXGIRaE", "fake-key", client=client)
    assert snip.video_id == "JgEquXGIRaE"
    assert snip.channel_title == "Zion Gates Music"
    assert "Midnight Dub Session" in snip.description


def test_fetch_snippet_no_key():
    with pytest.raises(YouTubeError):
        fetch_snippet("JgEquXGIRaE", "")


def test_fetch_snippet_not_found():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []})))
    with pytest.raises(YouTubeError, match="no video found"):
        fetch_snippet("JgEquXGIRaE", "k", client=client)


def test_fetch_snippet_api_error_hides_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "API key not valid"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(YouTubeError, match="API key not valid"):
        fetch_snippet("JgEquXGIRaE", "bad", client=client)
