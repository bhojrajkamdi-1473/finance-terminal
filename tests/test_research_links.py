"""Tests: external research destinations (links only, never scraped).

No network. URL patterns were verified live once by the author;
these tests pin the resolver contract (shape, classification,
no guessed deep links, no secrets).
Run: python -m unittest discover -s tests -v
"""

import re
import unittest

from services import research_links as rl

ALLOWED_HOSTS = (
    "www.nseindia.com",
    "www.bseindia.com",
    "www.screener.in",
    "trendlyne.com",
    "www.tickertape.in",
    "www.sec.gov",
)


class TestIndianDestinations(unittest.TestCase):
    def test_tatasteel_full_set(self):
        d = rl.destinations("TATASTEEL.NS", "Tata Steel")
        self.assertEqual(d["country"], "IN")
        self.assertEqual(d["bare"], "TATASTEEL")
        by_id = {x["id"]: x for x in d["official"] + d["research"]}
        self.assertEqual(
            by_id["screener"]["url"], "https://www.screener.in/company/TATASTEEL/"
        )
        self.assertIn("symbol=TATASTEEL", by_id["nse"]["url"])
        self.assertIn("query=TATASTEEL", by_id["bse"]["url"])
        self.assertTrue(by_id["trendlyne"]["url"].startswith("https://trendlyne.com/"))
        self.assertTrue(
            by_id["tickertape"]["url"].startswith("https://www.tickertape.in/")
        )

    def test_bo_suffix_stripped(self):
        d = rl.destinations("RELIANCE.BO")
        by_id = {x["id"]: x for x in d["official"] + d["research"]}
        self.assertEqual(
            by_id["screener"]["url"], "https://www.screener.in/company/RELIANCE/"
        )

    def test_ir_never_guessed(self):
        d = rl.destinations("TCS.NS", "TCS")
        ir = next(x for x in d["official"] if x["id"] == "ir")
        self.assertIsNone(ir["url"])
        self.assertIn("never guessed", (ir["reason"] or "").lower())

    def test_all_urls_allowlisted_hosts(self):
        for sym in (
            "TATASTEEL.NS",
            "RELIANCE.NS",
            "HDFCBANK.NS",
            "INFY.NS",
            "TCS.NS",
            "SBIN.NS",
            "AAPL",
            "MSFT",
        ):
            d = rl.destinations(sym, "X")
            for x in d["official"] + d["research"]:
                if x["url"] is None:
                    continue
                host = re.sub(r"^https?://", "", x["url"]).split("/")[0]
                self.assertIn(host, ALLOWED_HOSTS, x["url"])
                self.assertTrue(x["external"])
                self.assertTrue(x["opens_new_tab"])

    def test_classification(self):
        d = rl.destinations("INFY.NS")
        for x in d["official"]:
            self.assertEqual(x["category"], "official")
            self.assertEqual(x["badge"], "OFFICIAL")
        for x in d["research"]:
            self.assertEqual(x["category"], "external")
            self.assertEqual(x["badge"], "EXTERNAL")


class TestUSDestinations(unittest.TestCase):
    def test_no_indian_links_for_us(self):
        d = rl.destinations("MSFT", "Microsoft")
        self.assertEqual(d["country"], "US")
        ids = [x["id"] for x in d["official"] + d["research"]]
        self.assertNotIn("screener", ids)
        self.assertNotIn("trendlyne", ids)
        self.assertNotIn("tickertape", ids)
        self.assertNotIn("nse", ids)
        self.assertNotIn("bse", ids)
        sec = next(x for x in d["official"] if x["id"] == "sec")
        self.assertIn("sec.gov", sec["url"])
        self.assertIn("Microsoft", sec["url"])

    def test_apple_sec_link(self):
        d = rl.destinations("AAPL", "Apple Inc")
        sec = next(x for x in d["official"] if x["id"] == "sec")
        self.assertIn("browse-edgar", sec["url"])


class TestEdgeCases(unittest.TestCase):
    def test_index_gets_landings_not_company_pages(self):
        d = rl.destinations("^NSEI")
        self.assertTrue(d["is_index"])
        for x in d["official"] + d["research"]:
            if x["url"]:
                self.assertNotIn("company", x["url"])

    def test_empty_symbol_safe(self):
        d = rl.destinations("")
        self.assertEqual(d["country"], "??")

    def test_no_secrets_in_directory(self):
        import json

        raw = json.dumps(rl.describe_destinations())
        for token in ("API_KEY", "apikey", "secret", "token", "X-API-Key"):
            self.assertNotIn(token, raw)

    def test_no_fetch_logic_in_module(self):
        import inspect

        src = inspect.getsource(rl)
        for token in (
            "urlopen",
            "requests.get",
            "BeautifulSoup",
            'screener.in/company" + symbol',
            "http.client",
        ):
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()
