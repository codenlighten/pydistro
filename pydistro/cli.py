"""Command-line interface for pydistro.

Lets you (or your YouTube app, by shelling out) check mixes and inspect your
catalog without writing Python. Examples::

    export DISTROKID_TOKEN=...                       # for catalog commands
    pydistro check-mix --file mix_description.txt    # verify a mix's tracklist
    pydistro check "Lions Roar"                      # check one song title
    pydistro missing --file posted_titles.txt        # catalog coverage gaps
    pydistro releases --json                          # list releases as JSON
    pydistro video Rc92Mqy6SWr                        # scrape a video (no token)

Catalog commands cache the pulled catalog (default ~/.cache/pydistro), so
repeated checks are fast and can even run ``--offline`` against the cache with
no token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .catalog import Catalog, MixCheckResult
from .client import DistroKid
from .exceptions import DistroKidError
from .videos import get_video

DEFAULT_CACHE = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
    "pydistro",
    "catalog.json",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _read_text_input(args: argparse.Namespace) -> str:
    """Resolve text from --text, --file, or stdin (in that order)."""
    if getattr(args, "text", None):
        return args.text
    if getattr(args, "file", None):
        with open(args.file, "r", encoding="utf-8") as fh:
            return fh.read()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("error: provide input via --text, --file, or stdin")


def _load_catalog(args: argparse.Namespace) -> Catalog:
    """Load the catalog from cache when possible, else fetch with a token."""
    cache = None if args.no_cache else args.cache

    if cache and os.path.exists(cache):
        import time

        fresh = (time.time() - os.path.getmtime(cache)) < args.max_age
        if args.offline or fresh:
            return Catalog.from_cache(cache)

    if args.offline:
        raise SystemExit(
            f"error: --offline set but no usable cache at {cache!r}. "
            "Run a catalog command online once to populate it."
        )

    token = args.token or os.environ.get("DISTROKID_TOKEN")
    if not token:
        raise SystemExit(
            "error: a DistroKid token is required. Pass --token or set "
            "DISTROKID_TOKEN (or use --offline with a populated --cache)."
        )

    with DistroKid(token) as dk:
        catalog = Catalog.from_client(dk)
    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        catalog.save(cache)
    return catalog


def _status(result) -> str:
    if not result.matched:
        return "MISS"
    return "OK" if result.confidence >= 1.0 else "FUZZY"


def _mix_to_dict(mix: MixCheckResult) -> dict:
    return {
        "summary": mix.summary(),
        "total": mix.total,
        "matched": len(mix.matched),
        "unmatched": len(mix.unmatched),
        "fuzzy": len(mix.fuzzy),
        "missing_isrc": len(mix.missing_isrc),
        "tracks": [
            {
                "timestamp": c.item.timestamp,
                "seconds": c.item.seconds,
                "query": c.item.raw_title,
                "status": _status(c.result),
                "matched": c.result.matched,
                "confidence": c.result.confidence,
                "official_title": c.result.official_title,
                "official_artist": c.result.official_artist,
                "isrc": c.result.isrc,
                "issues": c.result.issues,
                "suggestions": [t for t, _ in c.result.suggestions],
            }
            for c in mix.checks
        ],
    }


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_check_mix(args: argparse.Namespace) -> int:
    description = _read_text_input(args)
    catalog = _load_catalog(args)
    mix = catalog.check_tracklist(description, artist=args.artist)

    if args.json:
        print(json.dumps(_mix_to_dict(mix), indent=2))
    else:
        print(mix.summary())
        print("-" * 70)
        for c in mix.checks:
            r = c.result
            ts = c.item.timestamp or "--"
            print(f"[{ts:>7}] {_status(r):<5} {c.item.raw_title}")
            if r.matched:
                isrc = r.isrc or "(none — backfill)"
                print(f"          -> {r.official_title}  | ISRC={isrc} | conf={r.confidence}")
                for issue in r.issues:
                    print(f"          ! {issue}")
            elif r.suggestions:
                print(f"          ? did you mean: {', '.join(t for t, _ in r.suggestions)}")

    # Exit nonzero in --strict mode if anything needs attention.
    if args.strict and (mix.unmatched or mix.fuzzy or mix.missing_isrc):
        return 1
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    catalog = _load_catalog(args)
    r = catalog.check(args.title, artist=args.artist)
    if args.json:
        print(json.dumps({
            "query": r.query,
            "status": _status(r),
            "matched": r.matched,
            "confidence": r.confidence,
            "official_title": r.official_title,
            "official_artist": r.official_artist,
            "isrc": r.isrc,
            "issues": r.issues,
            "suggestions": [t for t, _ in r.suggestions],
        }, indent=2))
    else:
        print(f"{_status(r)}  {r.query}")
        if r.matched:
            print(f"  -> {r.official_title} — {r.official_artist} | ISRC={r.isrc or '(none)'} | conf={r.confidence}")
        for issue in r.issues:
            print(f"  ! {issue}")
        if r.suggestions:
            print(f"  ? {', '.join(t for t, _ in r.suggestions)}")
    if args.strict and not r.matched:
        return 1
    return 0


def cmd_missing(args: argparse.Namespace) -> int:
    posted = [ln.strip() for ln in _read_text_input(args).splitlines() if ln.strip()]
    catalog = _load_catalog(args)
    missing = catalog.missing_posts(posted)
    if args.json:
        print(json.dumps([
            {"title": e.track.title, "artist": e.release.artist, "isrc": e.track.isrc}
            for e in missing
        ], indent=2))
    else:
        print(f"{len(missing)} catalog song(s) with no matching post:")
        for e in missing:
            print(f"  - {e.track.title} — {e.release.artist}")
    return 0


def cmd_releases(args: argparse.Namespace) -> int:
    token = args.token or os.environ.get("DISTROKID_TOKEN")
    if not token:
        raise SystemExit("error: --token or DISTROKID_TOKEN required")
    with DistroKid(token) as dk:
        releases = dk.get_releases()
    if args.json:
        print(json.dumps([r.model_dump(mode="json", by_alias=True) for r in releases], indent=2))
    else:
        for r in releases:
            print(f"{r.id}\t{r.title} — {r.artist} ({r.track_count} tracks)")
    return 0


def cmd_tracks(args: argparse.Namespace) -> int:
    token = args.token or os.environ.get("DISTROKID_TOKEN")
    if not token:
        raise SystemExit("error: --token or DISTROKID_TOKEN required")
    with DistroKid(token) as dk:
        tracks = dk.get_tracks(args.release_id)
    if args.json:
        print(json.dumps([t.model_dump(mode="json", by_alias=True) for t in tracks], indent=2))
    else:
        for t in tracks:
            print(f"{t.id}\t{t.title}\t{t.duration_seconds}s\tISRC={t.isrc or '-'}")
    return 0


def cmd_video(args: argparse.Namespace) -> int:
    video = get_video(args.id)
    if args.json:
        print(video.model_dump_json(indent=2))
    else:
        print(f"Title : {video.title}")
        print(f"Artist: {video.artist}")
        print(f"Views : {video.distrokid_views}")
        print(f"Stores: {', '.join(s.name for s in video.available_stores()) or '-'}")
        if video.description:
            print(f"Desc  : {video.description[:200]}")
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pydistro", description="Unofficial DistroKid CLI.")
    p.add_argument("--version", action="version", version=f"pydistro {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_token_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--token", help="DistroKid bearer token (or $DISTROKID_TOKEN)")

    def add_catalog_opts(sp: argparse.ArgumentParser) -> None:
        add_token_opts(sp)
        sp.add_argument("--cache", default=DEFAULT_CACHE, help="catalog cache path")
        sp.add_argument("--no-cache", action="store_true", help="ignore/skip the cache")
        sp.add_argument("--offline", action="store_true", help="use cache only; never fetch")
        sp.add_argument("--max-age", type=float, default=86_400.0, help="cache TTL seconds")
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.add_argument("--strict", action="store_true", help="nonzero exit if issues found")
        sp.add_argument("--artist", help="expected artist, to disambiguate matches")

    def add_text_input(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--text", help="inline input text")
        sp.add_argument("--file", help="read input from a file")

    sp = sub.add_parser("check-mix", help="check a mix description's tracklist vs DistroKid")
    add_catalog_opts(sp)
    add_text_input(sp)
    sp.set_defaults(func=cmd_check_mix)

    sp = sub.add_parser("check", help="check a single song title vs DistroKid")
    add_catalog_opts(sp)
    sp.add_argument("title", help="the title to check")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("missing", help="catalog songs with no matching YouTube post")
    add_catalog_opts(sp)
    add_text_input(sp)
    sp.set_defaults(func=cmd_missing)

    sp = sub.add_parser("releases", help="list releases")
    add_token_opts(sp)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_releases)

    sp = sub.add_parser("tracks", help="list tracks for a release")
    add_token_opts(sp)
    sp.add_argument("release_id", type=int)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_tracks)

    sp = sub.add_parser("video", help="scrape public video metadata (no token)")
    sp.add_argument("id", help="video watch id, e.g. Rc92Mqy6SWr")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_video)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DistroKidError as exc:
        _eprint(f"error: {exc}")
        return 2
    except (OSError, FileNotFoundError) as exc:
        _eprint(f"error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
