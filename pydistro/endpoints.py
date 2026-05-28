"""DistroKid endpoint constants.

Mirrors endpoints.go. Path templates use ``{id}`` placeholders for ``str.format``.
"""

from __future__ import annotations

BASE_URL = "https://distrokid.com/api/v1"
VIDEO_WATCH_URL = "https://distrokid.com/videos/watch/{id}"

RELEASES = "/releases"
RELEASE = "/releases/{id}"
TRACKS = "/releases/{id}/tracks"
TRACK_STATS = "/stats/track/{id}"
RELEASE_STATS = "/stats/releases/{id}"

# Header used by the Go client to mimic the official iOS app. Not required.
DEFAULT_USER_AGENT = "DistroKid/369 CFNetwork/1492.0.1 Darwin/23.3.0"
