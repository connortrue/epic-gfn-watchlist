#!/usr/bin/env python3
"""
Epic library -> GeForce NOW audit.

Takes a list of the Epic games you own and sorts them into what you can actually
stream on the Chromebook:

    PLAY NOW         owned on Epic, available on GFN with Epic as a store
    STEAM/SOTHER     on GFN, but not via an Epic entitlement -- the Epic copy
                     will never appear in your GFN library
    NOT ON GFN       no catalog entry
    UNKNOWN          catalog page could not be read

Input: a plain text file with one title per line, or a CSV (Legendary's
`list-games --csv`, or any CSV with a title/name column).

    python3 audit_epic_library.py epic-games.txt
    python3 audit_epic_library.py legendary.csv --json
    python3 audit_epic_library.py --titles "Alan Wake 2, Control, Temtem"

Requires nothing but the standard library and network access.
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import urllib.error

from watchlist import game_detail, load_catalog, read_titles, variants

HERE = os.path.dirname(os.path.abspath(__file__))
DETAIL_CACHE = os.path.join(HERE, ".cache", "details.json")
MAX_WORKERS = 6


# ---------------------------------------------------------------- input

# ---------------------------------------------------------------- matching

def match(title, slug_set):
    for v in variants(title):
        if v in slug_set:
            return v
    return None


def load_detail_cache():
    try:
        with open(DETAIL_CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_detail_cache(cache):
    os.makedirs(os.path.dirname(DETAIL_CACHE), exist_ok=True)
    with open(DETAIL_CACHE, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1)


# ---------------------------------------------------------------- audit

def audit(titles, slug_set, cache):
    todo = []
    for t in titles:
        slug = match(t, slug_set)
        if slug and slug not in cache:
            todo.append(slug)

    todo = sorted(set(todo))
    if todo:
        print(f"checking {len(todo)} catalog page(s)...", file=sys.stderr)
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {}
            for slug in todo:
                futures[pool.submit(game_detail, slug)] = slug
            for fut in concurrent.futures.as_completed(futures):
                slug = futures[fut]
                try:
                    cache[slug] = fut.result()
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    cache[slug] = {"status": "error", "tier": "?", "verified": "?",
                                   "stores": [], "error": str(exc)}

    rows = []
    for t in titles:
        slug = match(t, slug_set)
        if not slug:
            rows.append({"title": t, "slug": None, "bucket": "NOT ON GFN",
                         "status": "-", "tier": "-", "verified": "?", "stores": []})
            continue

        d = cache.get(slug) or {}
        status = d.get("status", "?")
        stores = d.get("stores", [])

        if status == "error" or status == "?":
            bucket = "UNKNOWN"
        elif status != "Available":
            bucket = "NOT ON GFN"
        elif "Epic" in stores:
            bucket = "PLAY NOW"
        else:
            bucket = "STEAM/SOTHER"

        rows.append({"title": t, "slug": slug, "bucket": bucket, "status": status,
                     "tier": d.get("tier", "?"), "verified": d.get("verified", "?"),
                     "stores": stores})

    return rows


BUCKETS = ["PLAY NOW", "STEAM/SOTHER", "NOT ON GFN", "UNKNOWN"]


def report(rows):
    total = len(rows)
    playable = [r for r in rows if r["bucket"] == "PLAY NOW"]

    print(f"\nEpic library audit -- {total} title(s) checked\n")

    # Rank playable: free tier first, then alphabetically.
    def rank(r):
        return (0 if r["tier"] == "Free tier" else 1, r["title"].lower())

    if playable:
        print("PLAY NOW ON THE CHROMEBOOK")
        print("-" * 96)
        for r in sorted(playable, key=rank):
            print(f"  {r['title'][:44]:44s} {r['tier']:17s} verified {r['verified']}")
        print()

    for bucket in BUCKETS:
        group = [r for r in rows if r["bucket"] == bucket]
        if not group:
            continue
        if bucket == "PLAY NOW":
            continue
        print(f"{bucket} ({len(group)})")
        print("-" * 96)
        for r in sorted(group, key=lambda x: x["title"].lower()):
            extra = ""
            if bucket == "STEAM/SOTHER":
                extra = "GFN lists " + (", ".join(r["stores"]) or "another store") + " only"
            elif bucket == "UNKNOWN":
                extra = "catalog page unreadable -- check by hand"
            print(f"  {r['title'][:44]:44s} {extra}")
        print()

    print("SUMMARY")
    print("-" * 96)
    for bucket in BUCKETS:
        n = sum(1 for r in rows if r["bucket"] == bucket)
        if n:
            pct = 100.0 * n / total if total else 0
            print(f"  {bucket:14s} {n:4d}  ({pct:.0f}%)")
    print()


def main():
    ap = argparse.ArgumentParser(description="Audit your Epic library against GeForce NOW")
    ap.add_argument("path", nargs="?", help="txt (one title per line) or CSV export")
    ap.add_argument("--titles", help="comma-separated titles instead of a file")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    titles = read_titles(args.path, args.titles)
    if not titles:
        print("No titles found.", file=sys.stderr)
        return 2

    try:
        slugs = load_catalog()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"GFN catalog unreachable: {exc}", file=sys.stderr)
        return 2

    cache = load_detail_cache()
    rows = audit(titles, set(slugs), cache)
    save_detail_cache(cache)

    if args.json:
        print(json.dumps({"catalog_size": len(slugs), "results": rows}, indent=2))
        return 0

    report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
