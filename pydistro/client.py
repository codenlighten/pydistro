"""Token-authenticated DistroKid client (releases, tracks, stats).

Ports distrokid.go / releases.go / track.go. Improvements over the Go version:
  * proper status-code checks (not string prefixes) and a real exception
    hierarchy, including AuthError for 401/403;
  * automatic retries with backoff on transient failures;
  * a reusable connection via a persisted httpx.Client (use as a context
    manager, or call close()).

The bearer token is the one used by the DistroKid iOS app; see README_PYTHON.md.
"""

from __future__ import annotations

import time
from typing import List, Optional

import httpx

from . import endpoints
from .exceptions import APIError, AuthError
from .models import Release, ReleaseStats, Track, TrackStats

DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRIES = 2
RETRY_BACKOFF = 0.5  # seconds, multiplied by attempt number


class DistroKid:
    """Client for the authenticated DistroKid JSON API.

    Example:
        >>> dk = DistroKid("your-bearer-token")
        >>> releases = dk.get_releases()
        >>> dk.close()

    Or as a context manager:
        >>> with DistroKid("token") as dk:
        ...     releases = dk.get_releases()
    """

    def __init__(
        self,
        auth_token: str,
        *,
        base_url: str = endpoints.BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        user_agent: str = endpoints.DEFAULT_USER_AGENT,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.auth_token = auth_token
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        # Sent on every request (like the Go DoRequest), so an injected client
        # is still authenticated without the caller wiring up headers.
        self._headers = {
            "Authorization": f"Bearer {auth_token}",
            "User-Agent": user_agent,
            "Content-Type": "application/json",
        }
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    # -- lifecycle --------------------------------------------------------- #
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DistroKid":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- low-level request ------------------------------------------------- #
    def _request(self, method: str, path: str) -> httpx.Response:
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(self.retries + 1):
            try:
                resp = self._client.request(method.upper(), url, headers=self._headers)
            except httpx.HTTPError as exc:
                last_exc = exc
            else:
                if resp.status_code in (401, 403):
                    raise AuthError(resp.status_code, url)
                # Retry on 5xx and 429; raise on other 4xx immediately.
                if resp.status_code >= 500 or resp.status_code == 429:
                    last_exc = APIError(resp.status_code, url)
                elif resp.status_code >= 400:
                    raise APIError(resp.status_code, url)
                else:
                    return resp

            if attempt < self.retries:
                time.sleep(RETRY_BACKOFF * (attempt + 1))

        if isinstance(last_exc, APIError):
            raise last_exc
        raise APIError(0, url, f"request failed: {last_exc}")

    def _get_json(self, path: str) -> dict:
        return self._request("GET", path).json()

    # -- releases ---------------------------------------------------------- #
    def get_releases(self) -> List[Release]:
        """All releases for the authenticated account."""
        payload = self._get_json(endpoints.RELEASES)
        items = payload.get("data", {}).get("items", [])
        return [Release.model_validate(item) for item in items]

    def get_release(self, release_id: int) -> Release:
        """A single release by id."""
        payload = self._get_json(endpoints.RELEASE.format(id=release_id))
        return Release.model_validate(payload.get("data", {}))

    def get_release_stats(self, release_id: int) -> ReleaseStats:
        """Play-count stats for a release, keyed by streaming service."""
        payload = self._get_json(endpoints.RELEASE_STATS.format(id=release_id))
        return ReleaseStats.model_validate(payload.get("data", {}))

    # -- tracks ------------------------------------------------------------ #
    def get_tracks(self, release_id: int) -> List[Track]:
        """All tracks belonging to a release."""
        payload = self._get_json(endpoints.TRACKS.format(id=release_id))
        tracks = payload.get("data", {}).get("tracks", [])
        return [Track.model_validate(t) for t in tracks]

    def get_track_stats(self, track_id: int) -> TrackStats:
        """Play-count stats for a single track, keyed by streaming service."""
        payload = self._get_json(endpoints.TRACK_STATS.format(id=track_id))
        return TrackStats.model_validate(payload.get("data", {}))
