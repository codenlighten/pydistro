"""pydistro — unofficial Python API wrapper for DistroKid.

Two entry points, mirroring the Go library:

  * ``DistroKid(token)`` — authenticated JSON API (releases, tracks, stats).
  * ``get_video`` / ``get_videos`` — public video metadata (no token needed).

This is an independent, unofficial tool and is not affiliated with DistroKid.
Use responsibly and in accordance with DistroKid's terms of service.
"""

from __future__ import annotations

from .catalog import (
    Catalog,
    CatalogEntry,
    CheckResult,
    MixCheckResult,
    TrackCheck,
    normalize_title,
)
from .client import DistroKid
from .exceptions import (
    APIError,
    AuthError,
    DistroKidError,
    VideoUnavailableError,
)
from .models import (
    Icon,
    Link,
    Release,
    ReleaseArtwork,
    ReleaseLinks,
    ReleaseStats,
    ServiceStats,
    StatsData,
    StatsPoint,
    Track,
    TrackStats,
    Video,
    VideoStore,
    VideoType,
)
from .tracklist import TracklistItem, parse_tracklist
from .videos import get_video, get_videos

__version__ = "0.1.0"

__all__ = [
    "DistroKid",
    "get_video",
    "get_videos",
    # catalog / matching
    "Catalog",
    "CatalogEntry",
    "CheckResult",
    "MixCheckResult",
    "TrackCheck",
    "normalize_title",
    # tracklist parsing
    "parse_tracklist",
    "TracklistItem",
    # models
    "Release",
    "ReleaseStats",
    "Track",
    "TrackStats",
    "Video",
    "VideoType",
    "VideoStore",
    "ServiceStats",
    "StatsData",
    "StatsPoint",
    "Link",
    "Icon",
    "ReleaseArtwork",
    "ReleaseLinks",
    # exceptions
    "DistroKidError",
    "APIError",
    "AuthError",
    "VideoUnavailableError",
    "__version__",
]
