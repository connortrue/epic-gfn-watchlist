#!/usr/bin/env python3
"""One weekly run across Epic and GOG.

Runs both store feeds, checks everything against the single GeForce NOW catalog,
and prints one digest split by what you can act on right now versus what is
merely coming. This is the script to put in cron; the per-store scripts stay
useful for drilling into one source.

    python3 weekly.py
    python3 weekly.py --links     # just the claim URLs
    python3 weekly.py --json
    python3 weekly.py --all       # include the skips
    python3 weekly.py --wait      # sleep until the Thursday rotation first

Stdlib only, no API keys.
"""

import argparse
import datetime
import json
import os
import sys
import time

import gog_watchlist as gog
import watchlist as epic


def epic_rows(catalog, owned_slugs):
    payload = epic.fetch_json(epic.EPIC_URL, timeout=35)
    current, upcoming = epic.parse_epic(payload)

    rows = []
    for item in current:
        row = epic.evaluate(item, catalog, owned_slugs)
        row.update(store="Epic", phase="now", window=f"ends {item['until']}",
                   link=epic.product_url(item))
        rows.append(row)
    for item in upcoming:
        row = epic.evaluate(item, catalog, owned_slugs)
        row.update(store="Epic", phase="later",
                   window=f"{item['from']} -> {item['to']}",
                   link=epic.product_url(item))
        rows.append(row)
    return rows


def gog_rows(catalog, owned_slugs, refresh=False, include_demos=False):
    free = gog.load_free(force=refresh)
    if not include_demos:
        free = [i for i in free if not gog.NOISE_RE.search(i["title"])]

    details = gog.load_detail_cache()
    rows = []
    for item in free:
        row = gog.evaluate(item, catalog, owned_slugs, details)
        row.update(
            store="GOG",
            # A giveaway has a deadline; free-to-keep titles never expire, so
            # they belong in the relaxed pile rather than the urgent one.
            phase="now" if item["giveaway"] else "later",
            window="limited-time giveaway" if item["giveaway"] else "free to keep",
            link=item["url"],
        )
        rows.append(row)
    gog.save_detail_cache(details)
    return rows


def print_block(title, rows):
    print(f"\n{title}")
    print("-" * 100)
    if not rows:
        print("  nothing today")
        return
    for r in rows:
        print(f"  [{r['store']:4s}] {r['title'][:40]:40s} {r['verdict']:11s} {r['window']}")
        print(f"         {r['why']}")
        stores = ", ".join(r.get("stores") or []) or "-"
        print(f"         store: {stores} | tier: {r.get('tier', '-')} | "
              f"verified: {r.get('verified', '-')}")
        if r.get("link"):
            print(f"         {r['link']}")


def main():
    ap = argparse.ArgumentParser(description="Weekly Epic + GOG freebies vs GeForce NOW")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--all", action="store_true", help="also list titles not worth claiming")
    ap.add_argument("--links", action="store_true", help="print claim URLs only")
    ap.add_argument("--owned", metavar="PATH", help="library export to flag titles you own")
    ap.add_argument("--refresh", action="store_true", help="ignore the cached GOG catalog")
    ap.add_argument("--include-demos", action="store_true", help="keep GOG demos and prologues")
    ap.add_argument("--wait", action="store_true",
                    help="sleep until the next Thursday 11:00 US Eastern rotation")
    args = ap.parse_args()

    if args.wait:
        target = epic.next_rotation()
        delay = (target - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        print(f"Waiting {int(delay // 60)} min for the {target:%Y-%m-%d %H:%M} UTC rotation...")
        time.sleep(max(delay, 0) + 90)

    catalog = set(epic.load_catalog())
    owned_path = epic.find_owned_file(args.owned)
    if args.owned and not owned_path:
        print(f"owned-library file not found: {args.owned}", file=sys.stderr)
    owned_slugs, owned_count = epic.load_owned(owned_path)

    rows, failures = [], []
    for label, builder in (
        ("Epic", lambda: epic_rows(catalog, owned_slugs)),
        ("GOG", lambda: gog_rows(catalog, owned_slugs, args.refresh, args.include_demos)),
    ):
        try:
            rows.extend(builder())
        except Exception as exc:  # noqa: BLE001 - one dead store should not kill the digest
            failures.append(f"{label}: {type(exc).__name__}: {exc}")

    # Claims that expire beat claims that can wait; owned is its own bucket.
    urgent = [r for r in rows if r["verdict"] == "CLAIM" and r["phase"] == "now"]
    later = [r for r in rows if r["verdict"] == "CLAIM" and r["phase"] == "later"]
    owned = [r for r in rows if r["verdict"] == "OWNED"]
    ignored = [r for r in rows if r["verdict"] not in ("CLAIM", "OWNED")]

    if args.links:
        for r in urgent + later:
            print(f"[{r['store']}] {r['title']}\n  {r['link']}")
        if not urgent and not later:
            print("Nothing to claim today.")
        return 0

    if args.json:
        def clean(rs):
            keep = ("store", "title", "verdict", "why", "window", "stores",
                    "tier", "verified", "link", "owned", "giveaway")
            return [{k: r.get(k) for k in keep if k in r} for r in rs]
        print(json.dumps({
            "generated": datetime.date.today().isoformat(),
            "catalog_size": len(catalog),
            "owned_titles": owned_count,
            "failures": failures,
            "claim_now": clean(urgent),
            "later": clean(later),
            "owned": clean(owned),
            "ignored": clean(ignored),
        }, indent=2))
        return 0 if not failures else 1

    print("=" * 100)
    print(f"WEEKLY DIGEST -- {datetime.date.today():%A %d %B %Y}")
    print(f"GFN catalog: {len(catalog):,} titles | "
          + (f"owned library: {owned_count} titles" if owned_path else "owned library: not loaded"))
    if failures:
        print("PARTIAL RUN:")
        for f in failures:
            print(f"  ! {f}")
    print("=" * 100)

    print_block(f"CLAIM NOW -- free and streams on the Chromebook ({len(urgent)})", urgent)
    print_block(f"WORTH GRABBING, NO DEADLINE ({len(later)})", later)
    print_block(f"ALREADY YOURS ({len(owned)})", owned)

    if args.all:
        print_block(f"IGNORED -- not playable via the store giving it away ({len(ignored)})", ignored)
    elif ignored:
        print(f"\n{len(ignored)} more entries are not playable via the store giving them away "
              f"(use --all to see them)")

    print("\nReminder: a store's giveaway only helps where GFN lists that same store.")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
