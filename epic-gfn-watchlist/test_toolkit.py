#!/usr/bin/env python3
"""Offline tests for the GFN freebie toolkit.

Every fixture is a literal and no test touches the network, so this runs in a
second and works with no credentials. Run with:

    python3 -m unittest -v test_toolkit

Three things are covered that manual runs cannot reach:

  * the GOG giveaway branch, which only fires while a 100%-off promotion is
    live -- so in practice it had never executed;
  * slug matching, which once produced false positives by substring matching
    ("SOLAS 128" -> "2", "Dungeon Drafters" -> "raft");
  * store parsing, including NVIDIA Bundle titles that used to look store-less.
"""

import unittest

import gog_watchlist as gog
import watchlist as epic


def gog_product(title="Some Game", slug="some_game", base="0.00", final="0.00",
                link="https://www.gog.com/en/game/some_game"):
    """A product shaped the way catalog.gog.com/v1/catalog returns them."""
    return {
        "title": title,
        "slug": slug,
        "storeLink": link,
        "price": {
            "baseMoney": {"amount": base, "currency": "USD"},
            "finalMoney": {"amount": final, "currency": "USD"},
        },
    }


# Tag-stripped GFN pages, trimmed to the block parse_game_detail reads.
GFN_NVIDIA_BUNDLE = """\
Blind Fate: Edo no Yami - Dojo
Available
Membership Free tier
Last verified 3 Nov 2026
NVIDIA Bundle \u00b7 101XP.Com Open store
"""

GFN_STEAM_ONLY = """\
Crusader Kings II
Available
Membership Free tier
Last verified 2 Nov 2026
Steam \u00b7 Paradox Interactive AB Open store
"""

GFN_MULTI_STORE = """\
The Witcher 3: Wild Hunt
Available
Membership Free tier
Last verified 3 Nov 2026
Battle.net \u00b7 CD PROJEKT RED Open store
Epic Games \u00b7 CD PROJEKT RED Open store
GOG \u00b7 CD PROJEKT RED Open store
Steam \u00b7 CD PROJEKT RED Open store
Xbox \u00b7 CD PROJEKT RED Open store
"""

GFN_UNAVAILABLE = """\
Some Old Game
Unavailable
Membership Premium required
"""


class SlugMatching(unittest.TestCase):
    """Guards against the substring matching that caused false positives."""

    def test_substring_is_not_a_match(self):
        self.assertIsNone(epic.match("SOLAS 128", {"2"}))
        self.assertIsNone(epic.match("Dungeon Drafters", {"raft"}))
        self.assertIsNone(epic.match("2", {"solas-128"}))

    def test_exact_match(self):
        self.assertEqual(
            epic.match("The Witcher 3: Wild Hunt", {"the-witcher-3-wild-hunt"}),
            "the-witcher-3-wild-hunt",
        )

    def test_apostrophe_forms_are_both_tried(self):
        catalog = {"sorry-were-closed"}
        self.assertEqual(epic.match("Sorry We're Closed", catalog), "sorry-were-closed")
        # curly apostrophe, as Epic writes it
        self.assertEqual(epic.match("Sorry We\u2019re Closed", catalog), "sorry-were-closed")

    def test_leading_article_variant(self):
        self.assertEqual(epic.match("Hades", {"the-hades"}), "the-hades")

    def test_edition_suffix_is_stripped(self):
        self.assertEqual(epic.match("Hades: Definitive Edition", {"hades"}), "hades")


class StoreParsing(unittest.TestCase):
    """The store column decides playability, so it must not misreport."""

    def test_nvidia_bundle_is_named(self):
        detail = epic.parse_game_detail(GFN_NVIDIA_BUNDLE)
        self.assertEqual(detail["stores"], ["NVIDIA Bundle"])
        self.assertEqual(detail["status"], "Available")

    def test_steam_only(self):
        detail = epic.parse_game_detail(GFN_STEAM_ONLY)
        self.assertEqual(detail["stores"], ["Steam"])

    def test_multiple_stores_are_sorted_and_complete(self):
        detail = epic.parse_game_detail(GFN_MULTI_STORE)
        self.assertEqual(
            detail["stores"],
            ["Battle.net", "Epic", "GOG", "Steam", "Xbox"],
        )
        self.assertIn("GOG", detail["stores"])

    def test_metadata_is_parsed(self):
        detail = epic.parse_game_detail(GFN_MULTI_STORE)
        self.assertEqual(detail["tier"], "Free tier")
        self.assertEqual(detail["verified"], "3 Nov 2026")

    def test_unavailable_page_without_stores(self):
        detail = epic.parse_game_detail(GFN_UNAVAILABLE)
        self.assertEqual(detail["status"], "Unavailable")
        self.assertEqual(detail["stores"], [])


class GogClassification(unittest.TestCase):
    """Free-to-keep and giveaway are different things; only one expires."""

    def test_free_to_keep_is_not_a_giveaway(self):
        items = gog.classify_products([gog_product(base="0.00", final="0.00")])
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["giveaway"])
        self.assertEqual(items[0]["base_price"], 0.0)

    def test_discounted_to_zero_is_a_giveaway(self):
        items = gog.classify_products([gog_product(base="29.99", final="0.00")])
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["giveaway"])
        self.assertAlmostEqual(items[0]["base_price"], 29.99)

    def test_paid_title_is_excluded(self):
        self.assertEqual(gog.classify_products([gog_product(base="29.99", final="19.99")]), [])

    def test_title_less_and_priceless_products_survive(self):
        self.assertEqual(gog.classify_products([{"title": "   "}]), [])
        # missing price block is treated as free rather than crashing
        items = gog.classify_products([{"title": "No Price", "slug": "no_price"}])
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["giveaway"])

    def test_link_and_slug_are_carried_through(self):
        items = gog.classify_products([gog_product(slug="x", link="https://example.test/x")])
        self.assertEqual(items[0]["slug"], "x")
        self.assertEqual(items[0]["url"], "https://example.test/x")

    def test_demo_noise_is_recognised(self):
        for title in ("Foo Demo", "Bar Prologue", "Baz Soundtrack", "Quux Tech Demo"):
            self.assertIsNotNone(gog.NOISE_RE.search(title), title)
        for title in ("Deltarune", "Painkiller RTX", "Demon's Tilt"):
            self.assertIsNone(gog.NOISE_RE.search(title), title)


class GogVerdicts(unittest.TestCase):
    """The verdict path, driven by an injected detail so no HTTP happens."""

    @staticmethod
    def detail(stores, status="Available"):
        return {"status": status, "tier": "Free tier", "verified": "3 Nov 2026",
                "stores": stores}

    def evaluate(self, stores, giveaway=True, status="Available", owned=set()):
        item = {"title": "Some Game", "slug": "some-game", "url": "",
                "giveaway": giveaway, "base_price": 29.99 if giveaway else 0.0}
        return gog.evaluate(item, {"some-game"}, owned, {"some-game": self.detail(stores, status)})

    def test_giveaway_streamable_is_claimed(self):
        row = self.evaluate(["GOG"], giveaway=True)
        self.assertEqual(row["verdict"], "CLAIM")
        self.assertIn("giveaway", row["why"])

    def test_free_to_keep_streamable_is_claimed(self):
        row = self.evaluate(["GOG"], giveaway=False)
        self.assertEqual(row["verdict"], "CLAIM")
        self.assertIn("free to keep", row["why"])

    def test_steam_only_is_not_claimable_via_gog(self):
        row = self.evaluate(["Steam"])
        self.assertEqual(row["verdict"], "NOT FOR GFN")
        self.assertIn("Steam only", row["why"])

    def test_nvidia_bundle_is_not_claimable_via_gog(self):
        row = self.evaluate(["NVIDIA Bundle"], giveaway=False)
        self.assertEqual(row["verdict"], "NOT FOR GFN")
        self.assertIn("NVIDIA Bundle only", row["why"])

    def test_unavailable_title_is_skipped(self):
        row = self.evaluate(["GOG"], status="Unavailable")
        self.assertEqual(row["verdict"], "SKIP")
        self.assertIn("Unavailable", row["why"])

    def test_owned_overrides_claim(self):
        row = self.evaluate(["GOG"], owned={"some-game"})
        self.assertEqual(row["verdict"], "OWNED")

    def test_absent_from_catalog_is_skip(self):
        item = {"title": "Nowhere Game", "slug": "", "url": "",
                "giveaway": False, "base_price": 0.0}
        row = gog.evaluate(item, set(), set(), {})
        self.assertEqual(row["verdict"], "SKIP")
        self.assertEqual(row["stores"], [])


if __name__ == "__main__":
    unittest.main()
