"""Catalog + title-matching layer for verifying YouTube posts against DistroKid.

This is the "source of truth" piece: pull your whole catalog once (own account),
index it by a *normalized* title, and check a YouTube video's title against it.

Design notes:
  * Matching is title-based because the YouTube side has no ISRC yet. That's
    workable because your own catalog is bounded. Every CheckResult still hands
    back the matched track's ISRC so you can backfill it onto your YouTube
    records and migrate to bulletproof ISRC matching over time.
  * The normalizer strips the promotional noise YouTube adds (``(Official
    Video)``, ``feat.`` clauses, an ``Artist - `` prefix, etc.) that DistroKid's
    bare ``track.title`` does not have. It deliberately does NOT strip version
    markers (live / acoustic / remix / remaster) so distinct versions stay
    distinct. Tune NOISE_KEYWORDS or pass your own normalizer if needed.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Tuple

from .client import DistroKid
from .models import Release, Track
from .tracklist import TracklistItem, parse_tracklist

# Words that, when found inside a bracketed group, mark the whole group as
# promotional noise to drop. Intentionally excludes version markers.
NOISE_KEYWORDS = {
    "official", "video", "audio", "lyric", "lyrics", "lyrical",
    "visualizer", "visualiser", "mv", "hd", "hq", "4k", "8k",
    "explicit", "clean", "prod", "prod.", "color", "colour",
    "music", "vertical", "performance",
}

_BRACKETS = re.compile(r"[\(\[\{]([^\(\)\[\]\{\}]*)[\)\]\}]")
_FEAT = re.compile(r"\b(feat|ft|featuring|with)\b\.?\s.*$", re.IGNORECASE)
_NONALNUM = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")

# Confidence at/above which a fuzzy (non-exact) match is accepted.
DEFAULT_FUZZY_THRESHOLD = 0.85
# Below the accept threshold but at/above this, we surface it as a suggestion.
SUGGEST_THRESHOLD = 0.6


def normalize_title(text: str, *, noise: Optional[set] = None) -> str:
    """Reduce a title to a comparable key.

    Lowercases, drops bracketed promotional groups, strips ``feat.`` clauses,
    and removes punctuation/whitespace differences.
    """
    if not text:
        return ""
    noise = noise if noise is not None else NOISE_KEYWORDS
    s = text.lower().strip()

    # Drop bracketed groups that look promotional; keep substantive ones.
    def _bracket(m: "re.Match") -> str:
        inner = m.group(1)
        words = set(_NONALNUM.sub(" ", inner).split())
        return "" if words & noise else f" {inner} "

    s = _BRACKETS.sub(_bracket, s)

    # Strip "feat. X" / "ft X" / "featuring X" / "with X" to end of string.
    s = _FEAT.sub("", s)

    s = s.replace("&", " and ")
    s = _NONALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


def _title_candidates(youtube_title: str) -> List[str]:
    """Possible song-title strings inside a raw YouTube title.

    Channels structure titles differently, so we offer several candidates and
    let matching pick the best-scoring one. Covers:
      * pipe-delimited (e.g. ``Title | Brand | Genre | Mix #5``) — each segment,
        first segment first since that's usually the real title;
      * ``Artist - Title`` — the part after the first ``-``;
      * the whole string, as a fallback.
    Non-title segments (brand/genre) simply won't match anything in the catalog.
    """
    candidates: List[str] = [youtube_title]
    if "|" in youtube_title:
        candidates.extend(seg.strip() for seg in youtube_title.split("|") if seg.strip())
    if " - " in youtube_title:
        candidates.append(youtube_title.split(" - ", 1)[1])
    # Preserve order, drop duplicates and empties.
    seen, ordered = set(), []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


@dataclass
class CatalogEntry:
    """One track paired with its parent release (for artist/date/artwork)."""

    track: Track
    release: Release

    @property
    def norm_title(self) -> str:
        return normalize_title(self.track.title)

    @property
    def norm_artist(self) -> str:
        return normalize_title(self.release.artist)

    @property
    def hyperfollow(self) -> str:
        """The release's HyperFollow smart link, if DistroKid provided one.

        DistroKid's API exposes a single smart link (not per-store deep links),
        so this is the universal "listen everywhere" CTA.
        """
        links = self.release.links
        if links and links.hyperfollow:
            return links.hyperfollow.href
        return ""


@dataclass
class CheckResult:
    """Verdict for checking one YouTube title against the catalog."""

    query: str
    matched: bool = False
    confidence: float = 0.0
    entry: Optional[CatalogEntry] = None
    issues: List[str] = field(default_factory=list)
    suggestions: List[Tuple[str, float]] = field(default_factory=list)

    # -- convenience accessors the YouTube app reads ----------------------- #
    @property
    def track(self) -> Optional[Track]:
        return self.entry.track if self.entry else None

    @property
    def release(self) -> Optional[Release]:
        return self.entry.release if self.entry else None

    @property
    def official_title(self) -> str:
        return self.entry.track.title if self.entry else ""

    @property
    def official_artist(self) -> str:
        return self.entry.release.artist if self.entry else ""

    @property
    def isrc(self) -> str:
        return self.entry.track.isrc if self.entry else ""

    @property
    def release_date(self) -> Optional[datetime]:
        return self.entry.release.release_date if self.entry else None


@dataclass
class TrackCheck:
    """A single tracklist item paired with its check verdict."""

    item: TracklistItem
    result: "CheckResult"


@dataclass
class MixCheckResult:
    """Aggregate verdict for checking a whole mix tracklist against DistroKid."""

    checks: List[TrackCheck] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def matched(self) -> List[TrackCheck]:
        return [c for c in self.checks if c.result.matched]

    @property
    def unmatched(self) -> List[TrackCheck]:
        """Songs in the mix that aren't in your DistroKid catalog."""
        return [c for c in self.checks if not c.result.matched]

    @property
    def fuzzy(self) -> List[TrackCheck]:
        """Matched, but the title differs enough to be worth eyeballing."""
        return [c for c in self.checks if c.result.matched and c.result.confidence < 1.0]

    @property
    def missing_isrc(self) -> List[TrackCheck]:
        return [c for c in self.matched if not c.result.isrc]

    def summary(self) -> str:
        return (
            f"{len(self.matched)}/{self.total} matched"
            f" — {len(self.unmatched)} unmatched"
            f", {len(self.fuzzy)} fuzzy"
            f", {len(self.missing_isrc)} missing ISRC"
        )


class Catalog:
    """An indexed snapshot of a DistroKid account's releases and tracks."""

    def __init__(self, entries: List[CatalogEntry]) -> None:
        self.entries = entries
        # normalized title -> entries (a title can recur across releases)
        self._index: Dict[str, List[CatalogEntry]] = {}
        # ISRC -> entry (ISRCs are unique per track)
        self._by_isrc: Dict[str, CatalogEntry] = {}
        for e in entries:
            self._index.setdefault(e.norm_title, []).append(e)
            if e.track.isrc:
                self._by_isrc[e.track.isrc.upper()] = e

    # -- lookups (the DJ Metaverse pipeline / chat agent consume these) ---- #
    def find_by_isrc(self, isrc: str) -> Optional[CatalogEntry]:
        """Exact ISRC lookup (case-insensitive). O(1); ideal for the chat agent."""
        return self._by_isrc.get(isrc.upper()) if isrc else None

    def find_by_title(
        self, query: str, *, fuzzy: bool = True, limit: int = 5
    ) -> List[CatalogEntry]:
        """Find catalog entries matching a title or filename slug.

        Accepts messy input (``golden_chalice_riddim``, ``Golden Chalice
        (Official Video)``) and normalizes it. Exact normalized matches come
        first; when ``fuzzy`` is set, near matches follow, ranked by similarity.
        Returns up to ``limit`` entries (best first).
        """
        nq = normalize_title(query)
        if not nq:
            return []

        exact = self._index.get(nq, [])
        if exact and not fuzzy:
            return exact[:limit]

        scored: List[Tuple[float, CatalogEntry]] = [(1.0, e) for e in exact]
        if fuzzy:
            seen_titles = {e.norm_title for e in exact}
            for norm, group in self._index.items():
                if norm in seen_titles:
                    continue
                score = SequenceMatcher(None, nq, norm).ratio()
                if score >= SUGGEST_THRESHOLD:
                    scored.append((score, group[0]))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:limit]]

    # -- construction ------------------------------------------------------ #
    @classmethod
    def from_client(cls, client: DistroKid) -> "Catalog":
        """Pull every release and its tracks from the authenticated account."""
        entries: List[CatalogEntry] = []
        for release in client.get_releases():
            tracks = release.tracks or client.get_tracks(release.id)
            for track in tracks:
                entries.append(CatalogEntry(track=track, release=release))
        return cls(entries)

    @classmethod
    def load(
        cls,
        client: DistroKid,
        *,
        cache_path: Optional[str] = None,
        max_age: float = 86_400.0,
    ) -> "Catalog":
        """Load the catalog, using an on-disk cache when fresh.

        Own catalogs change slowly, so caching keeps repeated checks cheap and
        is courteous to DistroKid (this is an unofficial API). Pass
        ``cache_path=None`` to always fetch live.
        """
        if cache_path and os.path.exists(cache_path):
            age = time.time() - os.path.getmtime(cache_path)
            if age < max_age:
                return cls.from_cache(cache_path)

        catalog = cls.from_client(client)
        if cache_path:
            catalog.save(cache_path)
        return catalog

    # -- (de)serialization ------------------------------------------------- #
    def save(self, path: str) -> None:
        payload = {
            "entries": [
                {
                    "track": e.track.model_dump(mode="json", by_alias=True),
                    "release": e.release.model_dump(mode="json", by_alias=True),
                }
                for e in self.entries
            ]
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    @classmethod
    def from_cache(cls, path: str) -> "Catalog":
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        entries = [
            CatalogEntry(
                track=Track.model_validate(item["track"]),
                release=Release.model_validate(item["release"]),
            )
            for item in payload.get("entries", [])
        ]
        return cls(entries)

    # -- matching ---------------------------------------------------------- #
    def check(self, youtube_title: str, artist: Optional[str] = None) -> CheckResult:
        """Check a YouTube video title against the catalog.

        Returns a CheckResult describing whether it matches a known track, the
        official metadata, and any issues (mismatch / ambiguous / missing ISRC).
        """
        result = CheckResult(query=youtube_title)
        norm_artist = normalize_title(artist) if artist else None

        # 1) Exact normalized match on any title candidate.
        for cand in _title_candidates(youtube_title):
            hits = self._index.get(normalize_title(cand))
            if not hits:
                continue
            if norm_artist:
                narrowed = [h for h in hits if h.norm_artist == norm_artist]
                hits = narrowed or hits
            if len(hits) == 1:
                result.matched = True
                result.confidence = 1.0
                result.entry = hits[0]
                self._annotate(result)
                return result
            # Multiple tracks share this title and artist didn't disambiguate.
            result.issues.append(
                f"ambiguous: {len(hits)} tracks titled '{hits[0].track.title}'"
                + (" — pass artist= to disambiguate" if not artist else "")
            )
            result.suggestions = [(h.track.title, 1.0) for h in hits]
            return result

        # 2) Fuzzy fallback against all indexed titles.
        best_entry: Optional[CatalogEntry] = None
        best_score = 0.0
        scored: List[Tuple[str, float]] = []
        for cand in _title_candidates(youtube_title):
            ncand = normalize_title(cand)
            if not ncand:
                continue
            for norm, group in self._index.items():
                score = SequenceMatcher(None, ncand, norm).ratio()
                if score > best_score:
                    best_score, best_entry = score, group[0]
                if score >= SUGGEST_THRESHOLD:
                    scored.append((group[0].track.title, round(score, 3)))

        result.confidence = round(best_score, 3)
        if best_entry and best_score >= DEFAULT_FUZZY_THRESHOLD:
            result.matched = True
            result.entry = best_entry
            result.issues.append(
                f"fuzzy match ({best_score:.0%}); verify title: "
                f"'{youtube_title}' vs '{best_entry.track.title}'"
            )
            self._annotate(result)
        else:
            result.issues.append("no catalog match found")
            # Dedup + sort suggestions by score desc.
            result.suggestions = sorted(
                {t: s for t, s in scored}.items(), key=lambda x: -x[1]
            )[:5]
        return result

    def check_tracklist(
        self, description: "str | List[TracklistItem]", artist: Optional[str] = None
    ) -> MixCheckResult:
        """Check every song in a mix tracklist against the catalog.

        Accepts either a raw description string (parsed via ``parse_tracklist``)
        or pre-parsed items. Runs :meth:`check` per song and aggregates, so you
        can see at a glance how many songs matched, which are unknown, and which
        are missing an ISRC to backfill.
        """
        items = parse_tracklist(description) if isinstance(description, str) else description
        checks = [TrackCheck(item=it, result=self.check(it.raw_title, artist=artist)) for it in items]
        return MixCheckResult(checks=checks)

    def _annotate(self, result: CheckResult) -> None:
        """Attach non-fatal advisories (e.g. missing ISRC for backfill)."""
        if result.entry and not result.entry.track.isrc:
            result.issues.append("DistroKid track has no ISRC")

    def missing_posts(self, posted_titles: List[str]) -> List[CatalogEntry]:
        """Catalog tracks with no matching YouTube post yet (coverage gaps).

        Pass the titles of videos already on your channel; returns the catalog
        entries that don't appear to be posted, so you know what still needs
        uploading.
        """
        posted_norm = set()
        for title in posted_titles:
            for cand in _title_candidates(title):
                posted_norm.add(normalize_title(cand))

        missing: List[CatalogEntry] = []
        for entry in self.entries:
            nt = entry.norm_title
            if nt in posted_norm:
                continue
            # Fuzzy guard so a near-match post isn't counted as missing.
            if any(
                SequenceMatcher(None, nt, p).ratio() >= DEFAULT_FUZZY_THRESHOLD
                for p in posted_norm
            ):
                continue
            missing.append(entry)
        return missing
