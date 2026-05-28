# pydistro

**Unofficial Python API wrapper for [DistroKid](https://distrokid.com).** A
Python port of [`distrogo`](https://github.com/szerookii/distrogo), reverse-
engineered from the DistroKid iOS app and public video pages.

> ⚠️ This is an independent, unofficial tool. It is **not** affiliated with,
> authorized, or endorsed by DistroKid. The endpoints and page markup it relies
> on can change at any time and may break without notice. Use responsibly and in
> accordance with DistroKid's terms of service. **Use at your own risk.**

## Features

- **Releases / Tracks / Stats** (requires a bearer token): list releases, fetch
  a release or its tracks, and read per-service play-count stats.
- **Videos** (no token required): scrape title, artist, views, description,
  thumbnails, store availability, and recommended videos from public video pages.
- Typed [pydantic](https://docs.pydantic.dev) models, a real exception
  hierarchy, automatic retries, and an offline-testable scraper.

## Installation

The import package is `pydistro`; the PyPI distribution name is `pydistrokid`
(the name `pydistro` was already taken on PyPI).

```bash
pip install pydistrokid          # once published
# or, from a checkout:
pip install -e ".[dev]"
```

Requires Python 3.9+. Depends on `httpx`, `pydantic>=2`, and `beautifulsoup4`.

## Usage

### Authenticated API (releases, tracks, stats)

You need the bearer token used by the DistroKid iOS app. You can obtain it by
inspecting the app's network requests (e.g. with a proxy). Then:

```python
from pydistro import DistroKid

with DistroKid("your-bearer-token") as dk:
    releases = dk.get_releases()
    print(f"Found {len(releases)} releases")

    first = dk.get_release(releases[0].id)
    print(f"{first.title} — {first.track_count} tracks")

    for track in dk.get_tracks(first.id):
        print(f"{track.title}: {track.duration_seconds}s (ISRC {track.isrc})")

    stats = dk.get_track_stats(first.tracks[0].id)
    for service, s in stats.stats.items():
        print(f"{service}: {s.data.total} plays ({s.data.period})")
```

### Videos (no token)

```python
from pydistro import get_video, get_videos, VideoStore

video = get_video("Rc92Mqy6SWr")
print(video.title, "by", video.artist, "—", video.distrokid_views, "views")
print("Available on:", [s.name for s in video.available_stores()])

videos = get_videos(["Rc92Mqy6SWr", "mv-K0ye9T6Xv", "dv-5yW2dTd8N"])
```

### Verifying YouTube mixes against your catalog

If your YouTube videos are long-form mixes whose songs are listed (timestamped)
in the description, pull your catalog once and check the whole tracklist:

```python
from pydistro import DistroKid, Catalog

with DistroKid("your-bearer-token") as dk:
    catalog = Catalog.load(dk, cache_path="~/.cache/pydistro/catalog.json")

mix = catalog.check_tracklist(description_text)   # description from YouTube
print(mix.summary())                              # "12/14 matched — 2 unmatched, ..."
for c in mix.unmatched:
    print("Not in catalog:", c.item.raw_title)
for c in mix.missing_isrc:
    print("Backfill ISRC for:", c.result.official_title, "->", c.result.isrc)
```

Every match returns the official title, artist, and **ISRC**, so you can backfill
ISRCs onto your YouTube records and move from title-matching to ISRC-matching.

## CLI

Installing the package puts a `pydistro` command on your PATH. Catalog commands
read `$DISTROKID_TOKEN` (or `--token`) and cache the pulled catalog, so repeated
checks are fast and can even run `--offline` against the cache with no token.

```bash
export DISTROKID_TOKEN=your-bearer-token

pydistro check-mix --file mix_description.txt     # verify a mix's tracklist
cat description.txt | pydistro check-mix          # or pipe via stdin
pydistro check-mix --file mix.txt --json          # machine-readable
pydistro check-mix --file mix.txt --strict        # nonzero exit if issues found

pydistro check "Lions Roar"                       # check one song title
pydistro missing --file posted_titles.txt         # catalog coverage gaps
pydistro releases --json                          # list releases
pydistro tracks 12345                             # list a release's tracks
pydistro video Rc92Mqy6SWr                        # scrape a video (no token)
```

Useful flags on catalog commands: `--cache PATH`, `--no-cache`, `--offline`,
`--max-age SECONDS`, `--artist NAME` (to disambiguate), `--json`, `--strict`.

## Errors

```python
from pydistro import APIError, AuthError, VideoUnavailableError, DistroKidError
```

- `AuthError` — 401/403 (missing/expired token); subclass of `APIError`.
- `APIError` — any other non-2xx JSON API response (`.status_code`, `.url`).
- `VideoUnavailableError` — a video page is private, removed, or redirected.
- `DistroKidError` — base class for all of the above.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The video scraper splits parsing from fetching, so the test suite runs fully
offline against saved HTML fixtures (no network calls).

## Relationship to the Go version

This repository also contains the original Go library (`distrogo`, in the `*.go`
files). The Python package is a clean reimplementation with the same surface
area, plus pydantic models, retries, a typed exception hierarchy, and tests.

## Credits & License

Ported from [`distrogo`](https://github.com/szerookii/distrogo) by
**szerookii**, with the videos API contributed by **Vankata453**. MIT licensed —
see [LICENSE](LICENSE).
