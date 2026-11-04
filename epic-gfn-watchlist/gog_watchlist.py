#!/usr/bin/env python3
"""GOG freebies vs GeForce NOW.

Companion to watchlist.py, which covers Epic. Same rules apply: strict slug
matching, the store column decides playability, and nothing is called playable
unless GFN actually lists GOG for that title.

GOG gives away two different things and they are not the same:

  giveaway      a paid game, free for a limited window (base price above zero,
                final price zero). These are announced on the store front page
                and typically run 48-72 hours.
  free-to-keep  a game whose base price is zero - permanently free, no window.

Both are worth claiming, but only the first disappears if you wait.

Stdlib only, no API keys. Usage:

    python3 gog_watchlist.py
    python3 gog_watchlist.py --all          # include titles not useful on GFN
    python3 gog_watchlist.py --links        # store URLs only
    python3 gog_watchlist.py --json
    python3 gog_watchlist.py --refresh      # ignore the 12h cache
"""

import argparse
import datetime
import json
import os
import re
import sys
import time

from watchlist import (
    CACHE_DIR,
    CACHE_TTL,
    fetch_json,
    find_owned_file,
    game_detail,
    load_catalog,
    load_owned,
    match,
    variants,
)

CATALOG_URL = (
    "https://catalog.gog.com/v1/catalog?limit=48&page={page}"
    "&countryCode=US&locale=en-US&currencyCode=USD"
    "&productType=in:game&price=between:0,0"
)
PAGE_LIMIT = 12

# The free catalog is dominated by demos and prologues -- 307 of 434 on the day
# this was written -- which are not giveaways and are useless on a watchlist.
NOISE_RE = re.compile(
    r"(?i)\b(demo|prologue|tech demo|playtest|beta|soundtrack|ost|"
    r"artbook|art book|wallpaper|season pass|trial|benchmark)\b"
)


def load_free(force=False):
    """Every GOG product currently priced at zero, cached for CACHE_TTL."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "gog-free.json")

    if not force and os.path.exists(cache):
        if time.time() - os.path.getmtime(cache) < CACHE_TTL:
            with open(cache, encoding="utf-8") as fh:
                return json.load(fh)

    raw, page = [], 1
    while page <= PAGE_LIMIT:
        data = fetch_json(CATALOG_URL.format(page=page), timeout=35)
        batch = data.get("products") or []
        raw.extend(batch)
        if len(batch) < 48:
            break
        page += 1
        time.sleep(0.3)  # be polite; this endpoint is not a public API

    items = []
    for product in raw:
        price = product.get("price") or {}
        base = ((price.get("baseMoney") or {}).get("amount") or "0.00")
        final = ((price.get("finalMoney") or {}).get("amount") or "0.00")
        if final not in ("0.00", "0", None):
            continue

        title = (product.get("title") or "").strip()
        if not title:
            continue
        try:
            base_value = float(base)
        except (TypeError, ValueError):
            base_value = 0.0

        items.append({
            "title": title,
            "slug": product.get("slug") or "",
            "url": product.get("storeLink") or "",
            # A non-zero base price that has fallen to zero is a 100%-off
            # promotion, i.e. a real giveaway with an expiry.
            "giveaway": base_value > 0,
            "base_price": base_value,
        })

    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(items, fh)
    return items


def load_detail_cache():
    path = os.path.join(CACHE_DIR, "gog-details.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_detail_cache(details):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "gog-details.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(details, fh)
    except OSError:
        pass


def evaluate(item, slug_set, owned_slugs, details):
    """Same verdict vocabulary as the Epic watchlist, with GOG as the store."""
    row = dict(item)
    owned = any(v in owned_slugs for v in variants(item["title"]))
    row["owned"] = owned

    slug = match(item["title"], slug_set)
    if not slug:
        row.update(slug=None, status="not in catalog", stores=[], tier="-", verified="-")
        if owned:
            row["verdict"], row["why"] = "OWNED", "already yours; no GFN entry"
        else:
            row["verdict"], row["why"] = "SKIP", "no GFN entry at all"
        return row

    detail = details.get(slug)
    if detail is None:
        detail = game_detail(slug)
        details[slug] = detail
    row.update(slug=slug, **detail)

    streams = detail["status"] == "Available" and "GOG" in detail["stores"]
    row["playable"] = streams
    only = ", ".join(detail["stores"]) or "no store listed"

    if owned:
        row["verdict"] = "OWNED"
        if detail["status"] != "Available":
            row["why"] = f"already yours; GFN status is {detail['status']}"
        elif streams:
            row["why"] = "already yours and playable on GFN"
        else:
            row["why"] = f"already yours, but GFN lists {only} only"
    elif detail["status"] != "Available":
        row["verdict"], row["why"] = "SKIP", f"GFN status is {detail['status']}"
    elif streams:
        row["verdict"] = "CLAIM"
        row["why"] = ("free giveaway and streams on GFN via GOG" if item.get("giveaway")
                      else "free to keep and streams on GFN via GOG")
    else:
        row["verdict"] = "NOT FOR GFN"
        row["why"] = f"GFN lists {only} only -- a GOG copy won't appear"

    return row


def print_rows(rows):
    for r in rows:
        label = "GIVEAWAY" if r.get("giveaway") else "free"
        print(f"{r['title'][:40]:40s} {r['verdict']:11s} {r['why']}  [{label}]")
        stores = ", ".join(r["stores"]) if r["stores"] else "-"
        print(f"    store: {stores} | tier: {r['tier']} | verified: {r['verified']}")


def main():
    ap = argparse.ArgumentParser(description="GOG freebies vs GeForce NOW")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--all", action="store_true", help="also show rows that are not useful on GFN")
    ap.add_argument("--links", action="store_true", help="print GOG store URLs only")
    ap.add_argument("--include-demos", action="store_true",
                    help="keep demos, prologues and soundtracks (filtered by default)")
    ap.add_argument("--owned", metavar="PATH", help="library export to flag titles you own")
    ap.add_argument("--refresh", action="store_true", help="ignore the cached free catalog")
    args = ap.parse_args()

    try:
        free = load_free(force=args.refresh)
    except Exception as exc:  # noqa: BLE001 - report, do not traceback at the user
        print(f"GOG catalog unreachable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not args.include_demos:
        free = [i for i in free if not NOISE_RE.search(i["title"])]

    giveaways = [i for i in free if i["giveaway"]]
    keepers = [i for i in free if not i["giveaway"]]

    if args.links:
        print(f"GOG free -- {datetime.date.today().isoformat()}")
        if giveaways:
            print("\nLIMITED-TIME GIVEAWAYS")
            for i in giveaways:
                print(f"  {i['title']}\n    {i['url']}")
        else:
            print("\nNo limited-time giveaway running right now.")
        print(f"\n{len(keepers)} permanently free titles -- see --all for the full list.")
        return 0

    slug_set = set(load_catalog())
    owned_path = find_owned_file(args.owned)
    if args.owned and not owned_path:
        print(f"owned-library file not found: {args.owned}", file=sys.stderr)
    owned_slugs, owned_count = load_owned(owned_path)

    details = load_detail_cache()
    rows = [evaluate(i, slug_set, owned_slugs, details) for i in giveaways + keepers]
    save_detail_cache(details)

    worth = [r for r in rows if r["verdict"] in ("CLAIM", "OWNED")]

    if args.json:
        print(json.dumps({
            "generated": datetime.date.today().isoformat(),
            "catalog_size": len(slug_set),
            "owned_file": owned_path,
            "owned_titles": owned_count,
            "giveaways": len(giveaways),
            "free_to_keep": len(keepers),
            "rows": rows,
        }, indent=2))
        return 0

    print(f"GOG free -- {datetime.date.today().isoformat()}")
    print(f"GFN catalog: {len(slug_set):,} titles")
    print(f"Owned library: {owned_count} titles from {os.path.basename(owned_path)}"
          if owned_path else "Owned library: not loaded")
    print(f"Limited-time giveaways: "
          f"{', '.join(i['title'] for i in giveaways) if giveaways else 'none right now'}")
    print(f"Permanently free titles: {len(keepers)}")

    if worth:
        print("\nWORTH CLAIMING -- STREAMS ON THE CHROMEBOOK")
        print("-" * 100)
        print_rows(worth)
    else:
        print("\nNothing in the free list is currently playable on GFN via GOG.")

    hidden = len(rows) - len(worth)
    if hidden and not args.all:
        print(f"\n{hidden} more free titles are not useful on GFN (use --all to see them)")
    elif args.all:
        rest = [r for r in rows if r["verdict"] not in ("CLAIM", "OWNED")]
        if rest:
            print("\nEVERYTHING ELSE")
            print("-" * 100)
            print_rows(rest)

    return 0


if __name__ == "__main__":
    sys.exit(main())
