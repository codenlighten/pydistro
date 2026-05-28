"""Pydantic models mirroring the DistroKid API and video pages.

These port the Go structs (releases.go, track.go, videos.go) to pydantic v2.
Using pydantic gets us validation, JSON aliases, and lenient parsing of the
sometimes-messy upstream payloads for free. Every model ignores unknown fields
so DistroKid adding keys won't break deserialization.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    # populate_by_name lets callers build models with the Python field names
    # while we still parse the upstream JSON aliases.
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# --------------------------------------------------------------------------- #
# Shared / nested
# --------------------------------------------------------------------------- #
class Link(_Base):
    href: str = ""
    type: str = ""
    rel: str = ""


class Icon(_Base):
    icon: str = ""
    alt: str = ""


class ReleaseArtwork(_Base):
    size_300: str = Field(default="", alias="300")
    full: str = ""
    size_100: str = Field(default="", alias="100")


class ReleaseLinks(_Base):
    release_edit: Optional[Link] = Field(default=None, alias="Releaseedit")
    detail: Optional[Link] = None
    tracks: Optional[Link] = None
    hyperfollow: Optional[Link] = None


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
class StatsPoint(_Base):
    date: Optional[datetime] = None
    count: int = 0


class StatsData(_Base):
    points: List[StatsPoint] = Field(default_factory=list)
    total: int = 0
    period: str = ""


class ServiceStats(_Base):
    data: StatsData = Field(default_factory=StatsData)


# --------------------------------------------------------------------------- #
# Tracks
# --------------------------------------------------------------------------- #
class TrackLinks(_Base):
    stats: Optional[Link] = None
    track_credits: Optional[Link] = Field(default=None, alias="trackcredits")
    track_lyrics: Optional[Link] = Field(default=None, alias="tracklyrics")


class TrackStatsLinks(_Base):
    release: Optional[Link] = None


class Track(_Base):
    duration_seconds: int = 0
    isrc: str = ""
    is_cover_song: bool = Field(default=False, alias="iscoversong")
    links: Optional[TrackLinks] = None
    has_isrc: bool = Field(default=False, alias="hasisrc")
    id: int = 0
    track_num: int = Field(default=0, alias="tracknum")
    title: str = ""


class TrackStats(_Base):
    artist: str = ""
    duration_seconds: int = 0
    isrc: str = ""
    stats: Dict[str, ServiceStats] = Field(default_factory=dict)
    links: Optional[TrackStatsLinks] = None
    id: int = 0
    artwork: Optional[ReleaseArtwork] = None
    track_num: int = Field(default=0, alias="tracknum")
    title: str = ""


# --------------------------------------------------------------------------- #
# Releases
# --------------------------------------------------------------------------- #
class Release(_Base):
    stores: List[str] = Field(default_factory=list)
    artist: str = ""
    is_deleted: bool = Field(default=False, alias="isdeleted")
    # Upstream sends numtracks as a string; keep parity with the Go comment.
    num_tracks: str = Field(default="", alias="numtracks")
    release_date: Optional[datetime] = Field(default=None, alias="releasedate")
    can_delete_from_stores: bool = Field(default=False, alias="candeletefromstores")
    tracks: List[Track] = Field(default_factory=list)
    store_icons: Dict[str, Icon] = Field(default_factory=dict, alias="store_icons")
    upload_date: Optional[datetime] = Field(default=None, alias="uploaddate")
    is_priority: bool = Field(default=False, alias="ispriority")
    uuid: str = ""
    release_date_string: str = Field(default="", alias="releasedate_string")
    links: Optional[ReleaseLinks] = None
    track_count: int = Field(default=0, alias="trackcount")
    can_edit: bool = Field(default=False, alias="canedit")
    upload_date_string: str = Field(default="", alias="uploaddate_string")
    id: int = 0
    artwork: Optional[ReleaseArtwork] = None
    release_status: str = Field(default="", alias="release_status")
    single: bool = False
    upc: str = ""
    is_verified: bool = Field(default=False, alias="isverified")
    record_label: str = Field(default="", alias="recordlabel")
    title: str = ""
    alerts: List[object] = Field(default_factory=list)


class ReleaseStats(_Base):
    artist: str = ""
    tracks: List[Track] = Field(default_factory=list)
    stats: Dict[str, ServiceStats] = Field(default_factory=dict)
    id: int = 0
    artwork: Optional[ReleaseArtwork] = None
    title: str = ""


# --------------------------------------------------------------------------- #
# Videos (scraped, not from the JSON API)
# --------------------------------------------------------------------------- #
class VideoType(IntEnum):
    """Matches the iota constants in videos.go (order-significant)."""

    VIZY = 0
    MINIVIDEO = 1
    DISTROVID = 2


class VideoStore(IntEnum):
    """Matches the iota store constants in videos.go (order-significant)."""

    BOOMPLAY = 0
    APPLEMUSIC = 1
    TIDAL = 2
    TIKTOKMUSIC = 3
    VEVO = 4


# Maps the DistroKid DSP icon element id -> our store enum.
DSP_ID_TO_STORE: Dict[str, VideoStore] = {
    "dsp-87": VideoStore.BOOMPLAY,
    "dsp-41": VideoStore.APPLEMUSIC,
    "dsp-42": VideoStore.TIDAL,
    "dsp-79": VideoStore.TIKTOKMUSIC,
    "dsp-40": VideoStore.VEVO,
}


class Video(_Base):
    id: str = ""
    type: VideoType = VideoType.VIZY
    # Parallels the Go [5]bool array; indexed by VideoStore.
    stores: List[bool] = Field(default_factory=lambda: [False] * len(VideoStore))
    artist: str = ""
    uploader: str = ""
    title: str = ""
    description: str = ""
    upload_date: Optional[datetime] = None
    release_date: Optional[datetime] = None
    upload_date_string: str = ""
    release_date_string: str = ""
    distrokid_views: int = 0
    thumbnail: str = ""
    animated_thumbnail: str = ""
    source_url: str = ""
    recommended: List[str] = Field(default_factory=list)

    def available_stores(self) -> List[VideoStore]:
        """Convenience: the stores this video is actually available on."""
        return [store for store in VideoStore if self.stores[store]]
