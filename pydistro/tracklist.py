"""Parse a YouTube mix description into its individual songs.

Your YouTube content is long-form mixes; the constituent songs live in the
description as a timestamped tracklist. This module turns that free-text block
into structured items so each song can be checked against DistroKid.

It tolerates the common tracklist shapes seen in the wild::

    0:00 Song Title
    00:00 - Song Title
    0:00 Artist - Song Title
    1. Song Title 0:00
    [1:02:33] Song Title
    0:00 | Song Title

If your descriptions use a different convention, paste an example and the
regexes here can be tuned — parsing is deliberately isolated from matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# A timestamp like 0:00, 00:00, or 1:02:33 (optional hours).
_TIMESTAMP = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})")
# Leading track number: "1.", "01)", "1 -", "#1".
_LEADING_INDEX = re.compile(r"^\s*#?\d+\s*[\.\)\-:]?\s*")
# Separators left dangling around a removed timestamp. Brackets are handled
# separately (only stripped when they actually wrapped the timestamp), so a
# legitimate "(Official Audio)" / "(Live)" in the title is preserved.
_EDGE_JUNK = re.compile(r"^[\s\-–—|:\.]+|[\s\-–—|:\.]+$")


@dataclass
class TracklistItem:
    """One song parsed from a description."""

    raw_title: str
    seconds: Optional[int] = None
    timestamp: Optional[str] = None
    line: str = ""


def _to_seconds(h: Optional[str], m: str, s: str) -> int:
    return (int(h) if h else 0) * 3600 + int(m) * 60 + int(s)


def parse_tracklist(description: str) -> List[TracklistItem]:
    """Extract song entries from a mix description.

    Lines containing a timestamp are treated as tracklist entries. The song
    title is whatever remains on the line after removing the timestamp, any
    leading track number, and dangling separators. Order is preserved.
    """
    items: List[TracklistItem] = []
    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _TIMESTAMP.search(line)
        if not m:
            continue

        seconds = _to_seconds(m.group(1), m.group(2), m.group(3))
        # Remove the timestamp wherever it sits. If it was wrapped in brackets
        # (e.g. "[1:02:33]" or "(0:00)"), consume those too so they don't leak.
        start, end = m.start(), m.end()
        if start > 0 and line[start - 1] in "([" and end < len(line) and line[end] in ")]":
            start -= 1
            end += 1
        # Then strip a leading track index and any separator junk at the edges.
        title = line[:start] + " " + line[end:]
        title = _LEADING_INDEX.sub("", title.strip())
        title = _EDGE_JUNK.sub("", title)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        items.append(
            TracklistItem(
                raw_title=title,
                seconds=seconds,
                timestamp=m.group(0),
                line=line,
            )
        )
    return items
