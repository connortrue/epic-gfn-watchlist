#!/usr/bin/env python3
"""
Epic freebies -> GeForce NOW watchlist.

Pulls Epic's current and upcoming free games, then checks each one against the
GeForce NOW catalog (gfndb.info, ~6,200 titles) and reports whether claiming it
on Epic will actually make it appear in your GFN library.

Optionally takes your own Epic library export and flags freebies you already
own, so the "claim this" list only contains things that are actually new to you.

Key rule: GFN support is per-title AND per-store. A game can be on GFN but
listed Steam-only -- an Epic claim then does nothing.

No API keys. Standard library only.

Usage:
    python3 watchlist.py                        # current + upcoming freebies
    python3 watchlist.py --owned epic.csv       # also flag titles you own
    python3 watchlist.py --json                 # machine-readable
    python3 watchlist.py --all                  # include SKIP rows
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

EPIC_URL = (
    "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
    "?locale=en-US&country=US&allowCountries=US"
)
SITEMAP_URL = "https://gfndb.info/sitemap.xml"
GAME_URL = "https://gfndb.info/game/{slug}/"
UA = {"User-Agent": "Mozilla/5.0 (compatible; epic-gfn-watchlist/1.1)"}

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")
CACHE_TTL = 12 * 3600  # catalog changes slowly; refresh twice a day

# Auto-detected library exports, checked in order when --owned isn't given.
OWNED_CANDIDATES = ("owned.txt", "epic-games.csv", "legendary.csv", "library.csv")


# ---------------------------------------------------------------- http helpers

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", "replace")


def fetch_json(url, timeout=30):
    return json.loads(fetch(url, timeout=timeout))


# ---------------------------------------------------------------- title input

def read_titles(path=None, inline=None):
    """Read titles from a txt list or a CSV with a recognisable title column."""
    if inline:
        return [t.strip() for t in inline.split(",") if t.strip()]
    if not path:
        return []

    with open(path, encoding="utf-8", errors="replace") as fh:
        # Full-line comments let an exported list carry its provenance instead
        # of turning "# from the Oct receipt" into a title that never matches.
        raw = [ln.strip() for ln in fh
               if ln.strip() and not ln.lstrip().startswith("#")]
    if not raw:
        return []

    header = raw[0].split(",")
    lowered = [h.strip().strip('"').lower() for h in header]
    idx = None
    for i, h in enumerate(lowered):
        if h in ("app title", "title", "name", "game", "game title"):
            idx = i
            break

    if idx is not None and len(header) > 1:
        out = []
        for line in raw[1:]:
            parts = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', line)
            if idx < len(parts):
                t = parts[idx].strip().strip('"')
                if t:
                    out.append(t)
        return out

    return raw


# ---------------------------------------------------------------- epic parsing

def parse_dt(s):
    if not s:
        return None
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _windows(groups):
    out = []
    for g in groups or []:
        for o in (g or {}).get("promotionalOffers") or []:
            out.append((o.get("startDate"), o.get("endDate")))
    return out


def parse_epic(payload):
    now = datetime.datetime.now(datetime.timezone.utc)
    els = payload["data"]["Catalog"]["searchStore"]["elements"]
    current, upcoming, seen = [], [], set()

    for el in els:
        title = (el.get("title") or "").strip()
        if not title or title.lower() in seen:
            continue

        price = ((el.get("price") or {}).get("totalPrice") or {}).get("discountPrice")
        promos = el.get("promotions") or {}

        active = []
        for start, end in _windows(promos.get("promotionalOffers")):
            s, e = parse_dt(start), parse_dt(end)
            if s and e and s <= now <= e:
                active.append((s, e))

        soon = _windows(promos.get("upcomingPromotionalOffers"))

        if active and price == 0:
            seen.add(title.lower())
            current.append({
                "title": title,
                "until": active[0][1].strftime("%Y-%m-%d"),
                "epic_slug": el.get("productSlug") or "",
            })
        elif soon:
            seen.add(title.lower())
            s, e = parse_dt(soon[0][0]), parse_dt(soon[0][1])
            upcoming.append({
                "title": title,
                "from": s.strftime("%Y-%m-%d") if s else "?",
                "to": e.strftime("%Y-%m-%d") if e else "?",
                "epic_slug": el.get("productSlug") or "",
            })

    return current, upcoming


# ---------------------------------------------------------------- gfn catalog

def load_catalog():
    """Return [slug, ...] for every GFN game, cached to disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "gfn-slugs.json")

    if os.path.exists(cache):
        age = time.time() - os.path.getmtime(cache)
        if age < CACHE_TTL:
            with open(cache, encoding="utf-8") as fh:
                return json.load(fh)

    xml = fetch(SITEMAP_URL, timeout=60)
    slugs = sorted({
        m.rstrip("/").rsplit("/", 1)[-1]
        for m in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
        if "/game/" in m
    })
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(slugs, fh)
    return slugs


def slugify(title, drop_apostrophe=True):
    t = title.lower().replace("\u2019", "'").replace("&", "and")
    t = re.sub(r"[\u00ae\u2122\u00a9]", "", t)
    # Catalogs usually drop apostrophes entirely ("Sorry We're Closed" ->
    # sorry-were-closed) rather than turning them into a dash.
    if drop_apostrophe:
        t = t.replace("'", "")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


def variants(title):
    """Conservative alternate slugs. No substring matching -- that produced
    false positives (SOLAS 128 -> '2', Dungeon Drafters -> 'raft')."""
    out = []
    for drop_apostrophe in (True, False):
        base = slugify(title, drop_apostrophe)
        cands = [base]
        if base.startswith("the-"):
            cands.append(base[4:])
        else:
            cands.append("the-" + base)
        # edition suffixes Epic appends but catalogs sometimes drop
        for suffix in ("-definitive-edition", "-standard-edition", "-deluxe-edition"):
            if base.endswith(suffix):
                cands.append(base[: -len(suffix)])
        for c in cands:
            if c and c not in out:
                out.append(c)
    return out


def match(title, slug_set):
    for v in variants(title):
        if v in slug_set:
            return v
    return None


def product_url(item):
    """Direct store URL for a freebie, falling back to a store search.

    Epic's API returns a readable slug for most titles but a bare 32-char hash
    for some (e.g. Sorry We're Closed), and a hash is not a valid /p/ path.
    """
    slug = (item.get("epic_slug") or "").strip()
    if slug and not re.fullmatch(r"[0-9a-f]{32}", slug):
        return f"https://store.epicgames.com/en-US/p/{slug}"
    query = item["title"].replace(" ", "+")
    return f"https://store.epicgames.com/en-US/browse?q={query}"


def print_links(current, upcoming):
    """Skip the middleman: the claim URLs, straight from Epic's own feed."""
    print(f"Epic free games -- {datetime.date.today().isoformat()}")
    print("Hub: https://store.epicgames.com/en-US/free-games\n")

    if current:
        print("FREE NOW")
        for item in current:
            print(f"  {item['title']}  (until {item['until']})")
            print(f"    {product_url(item)}")
    else:
        print("Nothing free right now.")

    if upcoming:
        print("\nUPCOMING")
        for item in upcoming:
            print(f"  {item['title']}  {item['from']} -> {item['to']}")
            print(f"    {product_url(item)}")

    print("\nPC SKUs only: Epic's mobile (Android/iOS) items are separate claims and are not in this feed.")


def next_rotation(now=None):
    """Next Thursday 11:00 US Eastern, returned in UTC.

    Epic rotates at 11:00 ET, which is 15:00 UTC under EDT and 16:00 UTC under
    EST. Hardcoding either one is wrong for half the year, so resolve the zone
    instead of guessing the offset.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    eastern = ZoneInfo("America/New_York")
    local = now.astimezone(eastern)

    target = local.replace(hour=11, minute=0, second=0, microsecond=0)
    if target <= local:
        target += datetime.timedelta(days=1)
    while target.weekday() != 3:  # Thursday
        target += datetime.timedelta(days=1)
    return target.astimezone(datetime.timezone.utc)


def clean_html(text):
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def game_detail(slug):
    """Availability, tier, stores and verification date from the GFN game page."""
    body = clean_html(fetch(GAME_URL.format(slug=slug), timeout=25))

    status = re.search(r"\b(Available|Unavailable|Coming Soon|Delisted)\b", body)
    tier = re.search(r"Membership\s+(Free tier|Premium required|\w+)", body)
    verified = re.search(
        r"Last verified[^0-9]{0,15}([0-9]{1,2} [A-Z][a-z]{2} [0-9]{4})", body
    )
    stores = sorted(set(re.findall(
        r"\b(Steam|Epic|Ubisoft Connect|Xbox|EA App|GOG|Battle\.net)\b", body
    )))
    return {
        "status": status.group(1) if status else "?",
        "tier": tier.group(1) if tier else "?",
        "verified": verified.group(1) if verified else "?",
        "stores": stores,
    }


# ---------------------------------------------------------------- owned library

def find_owned_file(explicit=None):
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for name in OWNED_CANDIDATES:
        candidate = os.path.join(HERE, name)
        if os.path.exists(candidate):
            return candidate
    return None


def load_owned(path):
    """Return the set of slugs covered by the user's own games."""
    if not path:
        return set(), 0
    titles = read_titles(path)
    owned = set()
    for t in titles:
        owned.update(variants(t))
    return owned, len(titles)


# ---------------------------------------------------------------- verdicts

def evaluate(item, slug_set, owned_slugs):
    slug = match(item["title"], slug_set)
    row = dict(item)
    owned = any(v in owned_slugs for v in variants(item["title"]))
    row["owned"] = owned

    if not slug:
        row.update(slug=None, status="not in catalog", stores=[], tier="-",
                   verified="-")
        if owned:
            row["verdict"] = "OWNED"
            row["why"] = "already in your library and not on GFN"
        else:
            row["verdict"] = "SKIP"
            row["why"] = "no GFN entry at all"
        return row

    detail = game_detail(slug)
    row.update(slug=slug, **detail)
    playable = detail["status"] == "Available" and "Epic" in detail["stores"]
    row["playable"] = playable

    if owned:
        row["verdict"] = "OWNED"
        if detail["status"] != "Available":
            row["why"] = f"already yours; GFN status is {detail['status']}"
        elif playable:
            row["why"] = "already yours and playable on GFN"
        else:
            only = ", ".join(detail["stores"]) or "no store listed"
            row["why"] = f"already yours, but GFN lists {only} only"
    elif detail["status"] != "Available":
        row["verdict"] = "SKIP"
        row["why"] = f"GFN status is {detail['status']}"
    elif playable:
        row["verdict"] = "CLAIM"
        row["why"] = "new to you and streams on GFN via Epic"
    else:
        only = ", ".join(detail["stores"]) or "no store listed"
        row["verdict"] = "NOT FOR GFN"
        row["why"] = f"GFN lists {only} only -- Epic claim won't appear"

    return row


# ---------------------------------------------------------------- output

def print_rows(label, rows):
    if not rows:
        print(f"\n{label}: none")
        return
    print(f"\n{label}")
    print("-" * 100)
    for r in rows:
        window = r.get("until") or f"{r.get('from','?')} -> {r.get('to','?')}"
        stores = ", ".join(r["stores"]) if r["stores"] else "-"
        print(f"{r['title'][:38]:38s} {window:23s} {r['verdict']:11s} {r['why']}")
        print(f"    store: {stores} | tier: {r['tier']} | verified: {r['verified']}")


def main():
    ap = argparse.ArgumentParser(description="Epic freebies vs GeForce NOW")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--all", action="store_true", help="include SKIP rows in detail")
    ap.add_argument("--owned", metavar="PATH",
                    help="your Epic library export (.txt or .csv) to flag titles you own")
    ap.add_argument("--links", action="store_true",
                    help="print direct claim URLs instead of the GFN table (no GFN lookup)")
    ap.add_argument("--wait", action="store_true",
                    help="sleep until the next Thursday 11:00 US Eastern rotation, then run")
    args = ap.parse_args()

    if args.wait:
        target = next_rotation()
        delay = (target - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        print(f"Waiting {int(delay // 60)} min for the {target:%Y-%m-%d %H:%M} UTC rotation...")
        time.sleep(max(delay, 0) + 90)  # small grace period for Epic to publish

    try:
        payload = fetch_json(EPIC_URL, timeout=35)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"Epic API unreachable: {exc}", file=sys.stderr)
        return 2

    current, upcoming = parse_epic(payload)

    if args.links:
        print_links(current, upcoming)
        return 0

    try:
        slugs = load_catalog()
    except urllib.error.URLError as exc:
        print(f"GFN catalog unreachable: {exc}", file=sys.stderr)
        return 2

    owned_path = find_owned_file(args.owned)
    if args.owned and not owned_path:
        print(f"owned-library file not found: {args.owned}", file=sys.stderr)
    owned_slugs, owned_count = load_owned(owned_path)

    slug_set = set(slugs)
    rows_current = [evaluate(i, slug_set, owned_slugs) for i in current]
    rows_upcoming = [evaluate(i, slug_set, owned_slugs) for i in upcoming]
    rows_all = rows_current + rows_upcoming

    if args.json:
        print(json.dumps({
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "catalog_size": len(slug_set),
            "owned_file": owned_path,
            "owned_titles": owned_count,
            "current": rows_current,
            "upcoming": rows_upcoming,
        }, indent=2))
        return 0

    print(f"Epic freebie watchlist -- {datetime.date.today().isoformat()}")
    print(f"GFN catalog: {len(slug_set):,} titles")
    if owned_path:
        print(f"Owned library: {owned_count:,} titles from {os.path.basename(owned_path)}")
    else:
        print("Owned library: not loaded (pass --owned PATH, or drop epic-games.csv here)")

    claims = [r for r in rows_all if r["verdict"] == "CLAIM"]
    if claims:
        print(f"\n*** NEW TO YOU + PLAYABLE: {', '.join(r['title'] for r in claims)}")

    print_rows("FREE RIGHT NOW", rows_current)
    print_rows("COMING UP", rows_upcoming)

    owned_rows = [r for r in rows_all if r["verdict"] == "OWNED"]
    if owned_rows:
        print(f"\nAlready yours, so nothing to claim: "
              f"{', '.join(r['title'] for r in owned_rows)}")

    if not args.all:
        skipped = sum(1 for r in rows_all if r["verdict"] == "SKIP")
        if skipped:
            print(f"\n({skipped} skipped -- pass --all to see why)")

    print("\nReminder: an Epic claim only helps where GFN lists Epic. "
          "Freebies rotate Thursdays, late morning US Eastern.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
