#!/usr/bin/env python3
"""Resolve a hero-image URL from Unsplash. Runs DEV-side, stdlib only (no httpx needed).

Reads the access key from $UNSPLASH_ACCESS_KEY (never passed on argv, so it can't leak
into the process list). Prints the final 800x400 crop URL to STDOUT; all diagnostics go
to STDERR, so `url=$(fetch_unsplash.py "query")` captures just the URL.

Pass a photo_id to pin an exact image (reproducible); omit it to take the top search hit.
Mirrors the app's own _fetch_unsplash_image() so scripted images match generated ones.

Usage: UNSPLASH_ACCESS_KEY=... fetch_unsplash.py "<query>" [photo_id]
"""
import json
import os
import sys
import urllib.parse
import urllib.request


def _get(url: str) -> dict:
    key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not key:
        sys.exit("UNSPLASH_ACCESS_KEY not set in the environment")
    req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {key}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    query = sys.argv[1]
    photo_id = sys.argv[2] if len(sys.argv) > 2 else None

    if photo_id:
        photo = _get(f"https://api.unsplash.com/photos/{photo_id}")
    else:
        qs = urllib.parse.urlencode(
            {"query": query, "per_page": 1, "orientation": "landscape",
             "content_filter": "high"}
        )
        results = _get("https://api.unsplash.com/search/photos?" + qs).get("results", [])
        if not results:
            sys.exit(f"no Unsplash results for {query!r}")
        photo = results[0]

    print(f"picked: {photo.get('alt_description')!r}  id={photo['id']}", file=sys.stderr)
    print(f"{photo['urls']['raw']}&w=800&h=400&fit=crop&q=80")


if __name__ == "__main__":
    main()
