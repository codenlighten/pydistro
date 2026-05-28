"""Exception hierarchy for pydistro.

A small, explicit set of errors so callers can distinguish "the network/API
misbehaved" from "this video isn't available" without string-matching messages.
"""

from __future__ import annotations


class DistroKidError(Exception):
    """Base class for every error raised by pydistro."""


class APIError(DistroKidError):
    """A non-2xx response from the DistroKid JSON API.

    Attributes:
        status_code: HTTP status code returned by the API.
        url: The request URL that produced the error.
    """

    def __init__(self, status_code: int, url: str, message: str | None = None) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message or f"API error: {status_code} for {url}")


class AuthError(APIError):
    """A 401/403 from the API, usually a missing or expired bearer token."""


class VideoUnavailableError(DistroKidError):
    """The requested video page is missing, private, or redirected away."""
