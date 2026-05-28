"""Fetch a YouTube video's title/description via the YouTube Data API v3.

The public watch page is JavaScript-rendered, so scraping the description from
HTML is unreliable. The Data API returns it cleanly. This needs an API key
(free, from the Google Cloud console) supplied via ``--youtube-api-key`` or the
``YOUTUBE_API_KEY`` environment variable.

Only the read-only ``videos.list`` endpoint with ``part=snippet`` is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

from .exceptions import YouTubeError

API_URL = "https://www.googleapis.com/youtube/v3/videos"
DEFAULT_TIMEOUT = 10.0

# A YouTube video id is 11 chars of [A-Za-z0-9_-].
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PATH_PREFIXES = ("/shorts/", "/embed/", "/v/", "/live/")


def extract_video_id(url_or_id: str) -> str:
    """Pull the 11-char video id out of a URL or accept a bare id.

    Handles ``youtube.com/watch?v=``, ``youtu.be/``, ``/shorts/``, ``/embed/``,
    ``/v/`` and ``/live/`` forms.
    """
    s = (url_or_id or "").strip()
    if _ID_RE.match(s):
        return s

    u = urlparse(s)
    host = u.netloc.lower()
    vid = ""
    if "youtu.be" in host:
        vid = u.path.lstrip("/").split("/", 1)[0]
    elif "youtube.com" in host or "youtube-nocookie.com" in host:
        if u.path == "/watch":
            vid = parse_qs(u.query).get("v", [""])[0]
        elif any(u.path.startswith(p) for p in _PATH_PREFIXES):
            parts = u.path.split("/")
            vid = parts[2] if len(parts) > 2 else ""

    if not _ID_RE.match(vid):
        raise YouTubeError(f"could not extract a YouTube video id from {url_or_id!r}")
    return vid


@dataclass
class YouTubeSnippet:
    """The bits of a video's snippet we care about."""

    video_id: str
    title: str
    description: str
    channel_title: str


def fetch_snippet(
    url_or_id: str,
    api_key: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    client: Optional[httpx.Client] = None,
) -> YouTubeSnippet:
    """Fetch title/description/channel for a YouTube video.

    Raises:
        YouTubeError: bad URL/id, missing or rejected key, or video not found.
    """
    if not api_key:
        raise YouTubeError("a YouTube Data API key is required")
    video_id = extract_video_id(url_or_id)
    params = {"part": "snippet", "id": video_id, "key": api_key}

    owns = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        resp = client.get(API_URL, params=params)
    finally:
        if owns:
            client.close()

    if resp.status_code != 200:
        # Surface the API's reason (e.g. bad key, quota) without the key itself.
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            pass
        raise YouTubeError(f"YouTube API error {resp.status_code}: {detail or resp.reason_phrase}")

    items = resp.json().get("items", [])
    if not items:
        raise YouTubeError(f"no video found for id {video_id!r} (private/removed?)")

    snip = items[0].get("snippet", {})
    return YouTubeSnippet(
        video_id=video_id,
        title=snip.get("title", ""),
        description=snip.get("description", ""),
        channel_title=snip.get("channelTitle", ""),
    )
