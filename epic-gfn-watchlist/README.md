# Epic freebie → GeForce NOW watchlist

Every Thursday Epic gives away one or two games. Most of them are useless on
GeForce NOW, because **GFN support is per-title *and* per-store**: a game can be
fully supported but listed Steam-only, in which case claiming it on Epic does
nothing at all.

This script answers one question each week: *which freebies will actually show
up in my GFN library?*

## Run it

```bash
python3 watchlist.py
```

No dependencies, no API keys. Python 3.8+.

Output looks like:

```
Epic freebie watchlist -- 2026-11-04
GFN catalog: 6,247 titles

*** CLAIM THESE TODAY: Ghostrunner 2

FREE RIGHT NOW
----------------------------------------------------------------------------------------------
Sorry We're Closed      until 2026-11-05    NOT FOR GFN  GFN lists Steam only -- Epic claim won't appear
    store: Steam | tier: Premium required | verified: 3 Nov 2026
```

Other modes:

```bash
python3 watchlist.py --json    # feed it to something else
python3 watchlist.py --all     # don't hide the SKIP rows
```

## Check what you already own

Once you have an Epic export (see `audit_epic_library.py`, or `legendary list-games --csv`), pass it in and the watchlist stops recommending games you already have:

```bash
python3 watchlist.py --owned epic-games.csv
```

It also auto-detects `owned.txt`, `epic-games.csv`, `legendary.csv` or `library.csv` sitting next to the script, so the flag is optional once the file exists. Plain text (one title per line) works as well as CSV — `owned.example.txt` shows the format.

Ownership is matched on the same normalised slugs used for the catalog, so `Ghostrunner 2`, `Ghostrunner 2: Standard Edition` and an apostrophe-heavy title like `Sorry We're Closed` all resolve correctly.

An owned freebie still gets checked against GFN, because the useful question changes from *should I claim this* to *can I play the copy I already have*:

```
Ghostrunner 2              2026-12-10 -> 2027-01-07 OWNED       already yours and playable on GFN
    store: Epic, Steam | tier: Free tier | verified: 3 Nov 2026
```

### Where the owned list comes from

Epic emails a "Your Epic Games Receipt" for every redemption, free ones included,
with `TOTAL: $0.00 USD` and a line per game. So the mailbox already holds the
record — no Epic login or library export needed.

Two ways to use it:

**One title at a time (fastest).** Search your mail for a receipt containing the
title. A hit means you already own it. This is how the Ghostrunner 2 entry above
was caught: a 26 Dec 2024 receipt mentions the game, so it is already in the
library even though it is advertised as an upcoming freebie.

**The whole list (durable).** Open a receipt's "view in browser" link, save it
(Google Takeout's `.eml` exports work too), and parse the pile:

```bash
python3 parse_receipts.py --dir ~/epic-receipts > owned.txt
python3 watchlist.py            # picked up automatically
```

Name it `owned.txt` and no flag is needed — it is one of the auto-detected
filenames. Both list formats accept `#` comment lines, so a file can record
where each title came from:

`owned.txt` is in `.gitignore` and stays on your machine. It is your library, so
it has no business in a public repository; `owned.example.txt` is the committed
template that shows the format.

The parser keeps `$0.00` receipts, drops paid ones unless you pass
`--include-paid`, reads either rendered text or raw HTML, and collapses the
duplicate rows Epic writes when a game has several editions (`Home - A Unique
Horror Adventure` appears three times in one receipt). Files with no order block
are reported and skipped rather than guessed at.

## What the verdicts mean

| Verdict | Meaning |
|---|---|
| `CLAIM` | New to you, on GFN **and** Epic is a listed store. Claim it and it appears in your library. |
| `OWNED` | Already in your Epic library. Nothing to claim; the note says whether that copy streams. |
| `NOT FOR GFN` | On GFN, but Steam/other-store only. An Epic claim is dead weight. |
| `SKIP` | Not in the GFN catalog at all (and not owned). |

## Claim without Reddit

Waiting for someone to comment a link is a race you don't have to run — the store URLs come from Epic's own feed:

```bash
python3 watchlist.py --links
```

About 0.2s, no GFN lookup. It prints the direct `/p/...` page for each current and upcoming freebie, falling back to a store search for the titles whose API slug is a bare hash (`Sorry We're Closed` is one).

To have it fire at the rotation rather than whenever you remember:

```bash
python3 watchlist.py --wait --links
```

That sleeps until the next Thursday 11:00 US Eastern plus a 90-second grace period, then prints. The time is resolved through `America/New_York` rather than hardcoded, because 11:00 ET is 15:00 UTC under daylight time and 16:00 UTC in winter — picking one constant is wrong for half the year. (10am Central is the faithful conversion of 11am Eastern year-round, so your current habit is already at the right hour.)

Cron alternative for a machine that stays on:

```bash
# Thursdays, just after the switch and again that evening (times are your
# machine's local zone -- cron does not know about Eastern)
5 11,17 * * 4  cd ~/epic-gfn-watchlist && python3 watchlist.py --links
```

Scope worth knowing: this feed carries **PC** freebies only. Epic's Android and iOS free games are separate claim items and don't appear in `freeGamesPromotions`, which is why third-party "everything at once" links sometimes list more rows than this does.

## Tests

```bash
python3 -m unittest -v test_toolkit
```

30 offline tests, stdlib `unittest` only — no network, no fixture files, runs in about 2ms. They cover the three places a manual run cannot reach:

- **The GOG giveaway branch.** It only fires while a 100%-off promotion is live, so in practice it had never executed.
- **Slug matching.** The `SOLAS 128` → `2` and `Dungeon Drafters` → `raft` false positives that forced strict matching in the first place.
- **Store parsing**, including `NVIDIA Bundle` titles, which used to report as "no store listed" when they are simply not claimable via Epic or GOG.

One known limitation is documented rather than tested: status is matched against flattened page text, so a title that itself contains a status word can win over the real badge. That is harmless because only the exact value `Available` can enable a `CLAIM` — every misparse resolves to a not-playable status.

## One combined weekly run

Both stores, one command, one digest:

```bash
python3 weekly.py
```

```
WEEKLY DIGEST -- Wednesday 04 November 2026
GFN catalog: 6,247 titles | owned library: 4 titles

CLAIM NOW -- free and streams on the Chromebook (0)
  nothing today

WORTH GRABBING, NO DEADLINE (0)
  nothing today

ALREADY YOURS (1)
  [Epic] Ghostrunner 2   OWNED   ends 2026-11-05
```

It sorts into four buckets, in the order that matters: **claim now** (free and expiring), **worth grabbing** (free with no deadline), **already yours**, and **ignored** (on a store GFN doesn't list for that title, hidden unless `--all`).

Both feeds are checked against one catalog load, and if one store's endpoint is down the other still prints — you get a `PARTIAL RUN` banner instead of a traceback. Flags: `--links`, `--json`, `--all`, `--owned`, `--refresh`, `--include-demos`, `--wait` (sleep until the Thursday rotation).

### Making it run itself

One command installs the schedule:

```bash
./install_cron.sh
```

It deliberately does **not** schedule "Thursday at 11:00". A laptop asleep at
11am would simply miss the week, and a fixed local hour drifts against Eastern
time at every daylight-saving change. Instead it schedules a daily check plus one
at boot, and `weekly.py --if-due` decides whether anything is actually due: once
per Epic rotation, never twice for the same week, and never before the feed has
caught up (there is a 15-minute grace after 11:00 Eastern, otherwise an 11:01 run
logs last week's games and marks the week done).

Each run appends to `weekly.log` with a timestamp and its exit status, so
`tail -n 40 weekly.log` shows you Thursday's digest whenever you look. A failed
or `PARTIAL RUN` week is not marked done, so the next day retries it.

```bash
./run_weekly.sh              # run only if a rotation is unhandled
./run_weekly.sh --force      # run now anyway
./install_cron.sh --show     # what is scheduled
./install_cron.sh --remove   # undo it
```

The installer prefers `crontab`, falls back to a systemd user timer (which
survives sleep via `Persistent=true`), and tells you the one-line `apt install
cron` if a ChromeOS container has neither. Re-running it replaces the entries
rather than duplicating them.

## GOG freebies

GOG is covered too, by a separate script that reuses the same catalog and the same strict matching:

```bash
python3 gog_watchlist.py
```

GOG gives away two different things and the difference matters:

| Kind | How it is detected | Expires? |
|---|---|---|
| **Limited-time giveaway** | base price above zero, final price zero | Yes, usually 48–72 hours |
| **Free to keep** | base price is already zero | No |

Both are claimable, but only the first disappears if you wait, so giveaways are listed first and tagged `[GIVEAWAY]`.

Two practical notes. The GOG free catalog is mostly noise — on 4 Nov 2026 there were 434 free products and 307 were demos, prologues or soundtracks — so those are filtered by title unless you pass `--include-demos`. And GOG's public API no longer honours its own price and discount filters, so the script pages the whole free catalog and classifies locally rather than trusting the query.

Flags mirror the Epic script: `--all` (show titles that aren't useful on GFN), `--links` (store URLs), `--json`, `--owned`, `--refresh`.

Remember the store rule still applies: a GOG freebie only streams if GFN lists **GOG** for that title. A game on GFN via Steam alone will say `NOT FOR GFN` even though it is free on GOG.

Prime Gaming is deliberately not included.

## Fully automatic claiming

Two honest points before the options. Epic publishes no bulk claim-all endpoint — every claim is an authenticated web checkout — and its Terms of Service prohibits using bot software to automate use of the store. No maintained project reports a confirmed ban, but the real failure mode is captcha lockout and Epic trust-loss over your IP, not quiet success forever. A claimer also needs your Epic session sitting on a machine that stays on.

If you still want zero clicks, the two that are actually maintained (as of Nov 2026):

| Tool | Status | Claims |
|---|---|---|
| [claabs/epicgames-freegames-node](https://github.com/claabs/epicgames-freegames-node) | v6.0.0, 25 Oct 2026 — Docker, built-in cron, device-code login, Discord/Telegram/ntfy alerts | PC only |
| [P-Adamiec/Free-Games-Claimer-Remaster](https://github.com/P-Adamiec/Free-Games-Claimer-Remaster) | v1.18, 21 Oct 2026 — Docker, built-in scheduler, `EG_OTP_KEY` handles 2FA | PC + Android + iOS |

Avoid `Revadike/epicgames-freebies-claimer` (openly captcha-broken) and note that `legendary` cannot claim free games at all — it only lists, installs and launches what you already own. Run either tool about once a day, not hourly; hammering the checkout is the fastest way to get challenged.

The script also prints membership tier (`Free tier` vs `Premium required`) and
the catalog's `last verified` date, so a stale entry is visible rather than
assumed correct.

## Run it every Thursday

Epic rotates on Thursdays at 11:00 US Eastern, which is 10:00 Central year-round
because both zones shift together. Rather than hand-write a crontab line -- and
get either the daylight-saving arithmetic or the sleeping-laptop case wrong --
run `./install_cron.sh`, described under **Making it run itself** above. It
schedules the combined `weekly.py` digest, not this script alone.

The per-store variant, if you want it on its own clock:

```
5 12 * * 4 cd /path/to/epic-gfn-watchlist && /usr/bin/python3 watchlist.py >> watchlist.log 2>&1
```

That 12:05 is local noon -- fine on a Central-time box, skewed anywhere else, and
still skipped entirely by a closed lid. If you would rather not do that
arithmetic, let the script wait for the real rotation instead:

```bash
python3 watchlist.py --wait --links >> claim-links.log 2>&1
```

To have the full comparison land in your inbox:

```
5 12 * * 4 cd /path/to/epic-gfn-watchlist && /usr/bin/python3 watchlist.py | mail -s "Epic freebies vs GFN" you@example.com
```

## Notes and caveats

- **Catalog source.** `gfndb.info` — a GeForce NOW-only catalog (~6,200 titles)
  with per-game availability, stores and a verification date. It is fetched from
  the site's sitemap and cached for 12 hours in `.cache/`.
- **Matching is strict on purpose.** Exact slug plus a few conservative variants
  only. Loose substring matching previously produced false positives
  (`SOLAS 128` matched a slug called `2`, `Dungeon Drafters` matched `raft`).
  If a title is genuinely on GFN under an odd slug, the script will say
  `not in catalog` — check by hand before trusting a SKIP.
- **Epic's API returns only what is currently promoted**, not your owned
  library. This checks freebies, not purchases.
- Being on this list does not mean a title is playable on your hardware beyond
  the normal GFN limits; Chromebooks cap at 1080p60 unless you're on Ultimate.
