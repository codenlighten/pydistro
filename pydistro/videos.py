"""Video metadata scraper (no auth required).

Ports videos.go. DistroKid's public video pages aren't backed by the JSON API,
so we parse the rendered HTML with BeautifulSoup. The selectors mirror the Go
``colly`` handlers one-for-one; if DistroKid changes their markup these are the
lines that will need updating.

The parsing is split from the fetching (`_parse_video`) so the scraper can be
unit-tested offline against saved HTML fixtures.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup, Tag

from . import endpoints
from .exceptions import VideoUnavailableError
from .models import DSP_ID_TO_STORE, Video, VideoStore, VideoType

DEFAULT_TIMEOUT = 10.0
_WS = re.compile(r"\s+")


def _video_type(video_id: str) -> VideoType:
    if video_id.startswith("mv-"):
        return VideoType.MINIVIDEO
    if video_id.startswith("dv-"):
        return VideoType.DISTROVID
    return VideoType.VIZY


def _clean(text: Optional[str]) -> str:
    """Collapse internal whitespace and strip, like colly's text extraction."""
    if not text:
        return ""
    return _WS.sub(" ", text).strip()


def _child_text(el: Optional[Tag], selector: str) -> str:
    """Equivalent of colly's ChildText: text of the first matching descendant."""
    if el is None:
        return ""
    match = el.select_one(selector)
    return _clean(match.get_text()) if match else ""


def _parse_dk_date(value: str) -> Optional[datetime]:
    """Parse DistroKid's 'Jan _2, 2006' style dates; return None if unparseable.

    Unlike the Go version (which let a parse error leak into the shared error
    variable), an unrecognized date simply yields None.
    """
    value = _clean(value)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%b %d, %Y")
    except ValueError:
        return None


def _parse_video(html: str, video: Video) -> Video:
    """Populate ``video`` from the page HTML. ``video.id``/``video.type`` preset."""
    soup = BeautifulSoup(html, "html.parser")

    # Window <title> sanity check: no " - " means the page isn't a real video.
    title_tag = soup.find("title")
    if title_tag is None or " - " not in title_tag.get_text():
        raise VideoUnavailableError("Video unavailable.")

    # --- main metadata block --------------------------------------------- #
    meta = soup.select_one("div.videoMetadataContainer")
    if meta is not None:
        title_div = meta.select_one('div[style*="line-height: 1.5"]')
        if title_div is not None:
            # colly used the first child node's text specifically.
            first = next(iter(title_div.children), None)
            raw_title = first if isinstance(first, str) else (
                first.get_text() if isinstance(first, Tag) else title_div.get_text()
            )
            video.title = _clean(raw_title)
        video.uploader = _child_text(meta, "div.vUsername")

        if video.type == VideoType.DISTROVID:
            video.artist = _child_text(meta, 'div[style*="font-weight: 400"]')
        elif video.type == VideoType.MINIVIDEO:
            # Trim the constant " Mini Video" suffix; artist comes from related.
            if video.title.endswith(" Mini Video"):
                video.title = video.title[: -len(" Mini Video")]
        else:  # VIZY: title is "Artist - Title"
            parts = video.title.split(" - ", 1)
            if len(parts) > 1:
                video.artist, video.title = _clean(parts[0]), _clean(parts[1])

    # --- related videos (and minivideo artist fallback) ------------------ #
    related = soup.select_one("div.relatedVideosContainer")
    if related is not None:
        for link in related.find_all("a"):
            if video.type == VideoType.MINIVIDEO and not video.artist:
                video.artist = _child_text(link, 'div[style*="font-weight: 700"]')
            href = link.get("href", "")
            video.recommended.append(href.replace("/videos/watch/", "", 1))

    # --- member-since block: views + upload date ------------------------- #
    member = soup.select_one("div.vMemberSince")
    if member is not None:
        info_divs = member.find_all("div")
        if len(info_divs) > 1:
            views_text = _clean(info_divs[1].get_text())
            if views_text.endswith(" views"):
                views_text = views_text[: -len(" views")]
            try:
                video.distrokid_views = int(views_text.replace(",", ""))
            except ValueError:
                pass
        if len(info_divs) > 3:
            raw = _clean(info_divs[3].get_text())
            if raw.startswith("since "):
                raw = raw[len("since "):]
            video.upload_date_string = raw
            video.upload_date = _parse_dk_date(raw)

    # --- description ----------------------------------------------------- #
    video.description = _child_text(soup, "div.vDescription pre")

    # --- store availability ---------------------------------------------- #
    for icon in soup.select("div.vDspContent img.store-icon"):
        classes = icon.get("class", [])
        if "hidden" in classes:
            continue
        store = DSP_ID_TO_STORE.get(icon.get("id", ""))
        if store is not None:
            video.stores[store] = True

    # --- distrovid release date ------------------------------------------ #
    dv_meta = soup.select_one("div.dvMetadataSection")
    if dv_meta is not None:
        inner = dv_meta.select_one("div")
        text = _clean(inner.get_text()) if inner else ""
        if text.startswith("Release date:"):
            text = text[len("Release date:"):].strip()
        if text:
            video.release_date_string = text
            video.release_date = _parse_dk_date(text)

    # --- player thumbnails ----------------------------------------------- #
    player = soup.select_one("video#my-player")
    if player is not None:
        poster = player.get("poster", "")
        video.thumbnail = poster
        if "/" in poster:
            video.animated_thumbnail = poster[: poster.rfind("/")] + "/animated.gif"

    # --- HLS source url -------------------------------------------------- #
    source = soup.select_one('source[type="application/x-mpegURL"]')
    if source is not None:
        video.source_url = source.get("src", "")

    # Fallback: if we never found an artist, use the uploader's username.
    if not video.artist:
        video.artist = video.uploader

    return video


def get_video(
    video_id: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    client: Optional[httpx.Client] = None,
) -> Video:
    """Scrape metadata for a single DistroKid video by its watch id.

    Raises:
        VideoUnavailableError: if the page redirects (private/removed) or the
            content indicates the video isn't available.
    """
    url = endpoints.VIDEO_WATCH_URL.format(id=video_id)
    video = Video(id=video_id, type=_video_type(video_id))

    owns = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=False)
    try:
        resp = client.get(url)
    finally:
        if owns:
            client.close()

    # A redirect away from the watch page means the video is unavailable.
    if resp.is_redirect or 300 <= resp.status_code < 400:
        raise VideoUnavailableError("Video unavailable (redirected).")

    return _parse_video(resp.text, video)


def get_videos(
    video_ids: List[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> List[Video]:
    """Scrape several videos. Reuses one HTTP connection across all ids.

    Mirrors the Go behavior: stops and raises on the first unavailable video.
    """
    results: List[Video] = []
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for vid in video_ids:
            results.append(get_video(vid, client=client))
    return results
