#!/usr/bin/env python3
"""Turn Epic Games receipts into a plain owned-titles list.

Epic emails a receipt for every redemption, including $0.00 free claims, so the
mailbox is a record of what is already in the library. This parses those
receipts -- either the rendered text from the "view in browser" page, or raw
.html / .eml files -- and emits one title per line, ready for:

    python3 watchlist.py --owned owned-epic.txt

Usage:
    python3 parse_receipts.py receipt1.txt receipt2.html
    python3 parse_receipts.py --dir receipts/
    python3 parse_receipts.py --dir receipts/ --json > owned.json

Stdlib only. No network, no API keys.
"""

import argparse
import glob
import html
import json
import os
import re
import sys

# A price line: "$19.99 USD", "$1,234.00 USD", "€9.99 EUR", "$0.00"
PRICE_RE = re.compile(r"^[$€£]\s?[\d,]+\.\d{2}\s*([A-Z]{3})?$")
TAG_RE = re.compile(r"<[^>]+>")
BLOCK_START = re.compile(r"HERE'?S WHAT YOU ORDERED", re.IGNORECASE)
BLOCK_END = re.compile(r"^(Discounts:|TOTAL:|Please keep a copy)", re.IGNORECASE)
TOTAL_RE = re.compile(r"^TOTAL:\s*[$€£]?\s*([\d,]+\.\d{2})\s*([A-Z]{3})?", re.IGNORECASE)
ORDER_RE = re.compile(r"\bF(\d{17,20})\b")
DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2}),\s+(\d{4})\b"
)


def _amount(text):
    """Pull a number out of "$1,234.00 USD"; None if there isn't one."""
    digits = re.sub(r"[^0-9.]", "", text)
    try:
        return float(digits)
    except ValueError:
        return None


def to_lines(raw):
    """Normalise rendered text or raw HTML into a list of trimmed lines."""
    if "<" in raw and ">" in raw:
        # Drop script/style bodies first, then all remaining tags.
        raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
        raw = TAG_RE.sub("\n", raw)
        raw = html.unescape(raw)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw.splitlines()]
    return [ln for ln in lines if ln]


def parse_receipt(raw):
    """Return (titles, meta) for a single receipt document.

    Epic's order block repeats a title/publisher/price triple per line item, and
    the same game can appear several times (one row per edition or platform
    SKU), so titles are de-duplicated in first-seen order.
    """
    lines = to_lines(raw)

    start = None
    for i, ln in enumerate(lines):
        if BLOCK_START.search(ln):
            start = i + 1
            break
    if start is None:
        return [], {}

    # Skip the "Description: / Publisher: / Price:" header labels.
    head = [ln.rstrip(":") for ln in lines[start:start + 3]]
    if [h.lower() for h in head] == ["description", "publisher", "price"]:
        start += 3

    titles, seen = [], set()
    i = start
    while i < len(lines):
        line = lines[i]
        if BLOCK_END.search(line):
            break
        # A title is followed by a publisher and then a price line.
        if i + 2 < len(lines) and PRICE_RE.match(lines[i + 2]):
            title = line
            if title and title.lower() not in seen:
                seen.add(title.lower())
                titles.append(title)
            i += 3
            continue
        i += 1

    # Epic renders a bare "TOTAL:" label with the amount on the next line, so
    # look past the label rather than expecting it inline. Getting this wrong
    # silently defeats the free/paid filter, which is the whole point here.
    total = None
    for j in range(i, min(i + 8, len(lines))):
        m = TOTAL_RE.match(lines[j])
        if m:
            total = _amount(m.group(1))
            break
        if lines[j].rstrip(":").strip().upper() == "TOTAL" and j + 1 < len(lines):
            if PRICE_RE.match(lines[j + 1]):
                total = _amount(lines[j + 1])
                break

    meta = {"titles": titles, "total": total}
    order = ORDER_RE.search(" ".join(lines))
    if order:
        meta["order_id"] = "F" + order.group(1)
    date = DATE_RE.search(" ".join(lines))
    if date:
        meta["date"] = f"{date.group(1)} {date.group(2)}, {date.group(3)}"
    return titles, meta


def collect_files(paths, directory):
    found = [p for p in paths if os.path.isfile(p)]
    if directory:
        for pattern in ("*.txt", "*.html", "*.htm", "*.eml"):
            found.extend(sorted(glob.glob(os.path.join(directory, "**", pattern), recursive=True)))
    # Stable de-duplication across mixed arguments.
    return list(dict.fromkeys(found))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract owned game titles from Epic receipts")
    ap.add_argument("files", nargs="*", help="receipt .txt/.html/.eml files")
    ap.add_argument("--dir", metavar="PATH", help="scan a folder recursively for receipts")
    ap.add_argument("--json", action="store_true", help="emit structured output with dates and totals")
    ap.add_argument("--include-paid", action="store_true",
                    help="keep receipts whose total is above $0.00")
    args = ap.parse_args(argv)

    files = collect_files(args.files, args.dir)
    if not files:
        print("No receipt files given. Pass files or --dir PATH.", file=sys.stderr)
        return 2

    receipts, owned, skipped = [], set(), 0
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError as exc:
            print(f"skip {path}: {exc}", file=sys.stderr)
            continue

        titles, meta = parse_receipt(raw)
        if not titles:
            print(f"skip {os.path.basename(path)}: no order block found", file=sys.stderr)
            continue
        if meta.get("total") not in (None, 0.0) and not args.include_paid:
            skipped += 1
            continue

        meta["file"] = os.path.basename(path)
        receipts.append(meta)
        owned.update(titles)

    if args.json:
        print(json.dumps(
            {"owned": sorted(owned, key=str.lower), "count": len(owned),
             "receipts": receipts, "paid_skipped": skipped},
            indent=2,
        ))
        return 0 if receipts else 1

    for title in sorted(owned, key=str.lower):
        print(title)
    print(f"\n{len(owned)} owned titles from {len(receipts)} free receipts "
          f"({skipped} paid receipts skipped)", file=sys.stderr)
    # Nothing parsed is a failure, not an empty library -- otherwise a broken
    # export silently yields an empty owned list and every freebie looks new.
    return 0 if receipts else 1


if __name__ == "__main__":
    sys.exit(main())
