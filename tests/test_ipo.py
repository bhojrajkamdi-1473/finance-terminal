"""IPO layer tests: classification, GMP rules, honest unavailable states."""

import os
import unittest
from datetime import date

from providers import ipo as I
from providers import ipoguru as G


class IpoClassifyTest(unittest.TestCase):
    def test_buckets_by_dates(self):
        rows = [
            {"symbol": "FUT", "offerDate": "2099-01-05", "closeDate": "2099-01-08"},
            {"symbol": "NOW", "offerDate": "2000-01-05", "closeDate": "2099-01-08"},
            {"symbol": "OLD", "offerDate": "2000-01-05", "closeDate": "2000-01-08"},
            {"symbol": "LST", "offerDate": "2000-01-05", "listingDate": "2000-01-20"},
            {"symbol": "NODATES", "name": "Mystery Ltd"},
            "junk-row",
        ]
        out = I.classify(rows, today=date(2026, 9, 24))
        self.assertEqual([r["symbol"] for r in out["upcoming"]], ["FUT"])
        self.assertEqual([r["symbol"] for r in out["open"]], ["NOW"])
        self.assertEqual([r["symbol"] for r in out["closed"]], ["OLD"])
        self.assertEqual([r["symbol"] for r in out["listed"]], ["LST"])
        self.assertEqual([r["symbol"] for r in out["unclassified"]], ["NODATES"])
        # bucket tag recorded; no dates invented on the row
        self.assertEqual(out["unclassified"][0]["_bucket"], "unclassified")
        self.assertNotIn("offerDate", out["unclassified"][0])

    def test_gmp_rules_present(self):
        g = I.gmp_unavailable("DEMO.NS")
        self.assertEqual(g["status"], "unavailable")
        self.assertIsNone(g["data"])
        self.assertIn("UNOFFICIAL", g["label"])
        self.assertIn("never investment advice", g["message"])
        s = I.subscription_unavailable()
        self.assertEqual(s["status"], "unavailable")
        self.assertIsNone(s["data"])

    def test_ipoguru_verdict(self):
        st = I.ipoguru_status()
        self.assertEqual(st["state"], "unverified")
        self.assertIn("key_configured", st)


class IpoGuruTest(unittest.TestCase):
    def test_normalize_schema_and_gmp_math(self):
        row = {
            "name": "Demo Industries", "type": "mainboard",
            "open_date": "2026-10-01", "close_date": "2026-10-03",
            "allotment_date": "2026-10-06", "listing_date": "2026-10-08",
            "price_band": "163-172", "issue_price": "172",
            "lot_size": "87", "issue_size": "Rs 74 Cr",
            "sale_type": "Fresh capital only", "listing_on": "BSE, NSE",
            "registrar": "KFintech",
            "subscription": {"qib": "1.53", "nii": "0.60", "retail": "1.29",
                             "total": "0.90",
                             "updated_at": "23 Apr 2026, 05:10 PM IST"},
            "gmp": {"price": "34", "percentage": "19.8",
                    "updated_at": "23 Apr 2026, 04:53 PM IST"},
        }
        n = G.normalize(row)
        self.assertEqual(n["company_name"], "Demo Industries")
        self.assertEqual((n["price_low"], n["price_high"]), (163.0, 172.0))
        self.assertEqual(n["gmp_value"], 34.0)
        # indicative listing = issue price + GMP, never guaranteed
        self.assertEqual(n["estimated_listing_price"], 206.0)
        self.assertEqual(n["subscription_qib"], 1.53)
        self.assertIsNone(n["symbol"])  # never guessed pre-listing
        self.assertEqual(n["source"], "ipo-guru")

    def test_gmp_percent_derived_when_missing(self):
        n = G.normalize({"name": "X", "issue_price": "100",
                         "gmp": {"price": "25"}})
        self.assertEqual(n["gmp_percent"], 25.0)
        self.assertEqual(n["estimated_listing_price"], 125.0)

    def test_missing_key_honest(self):
        old = os.environ.pop("IPOGURU_API_KEY", None)
        try:
            env = G.get_ipos()
            self.assertEqual(env["status"], "unavailable")
            self.assertIsNone(env["data"])
        finally:
            if old is not None:
                os.environ["IPOGURU_API_KEY"] = old

    def test_classify_guru_rows(self):
        rows = [G.normalize({
            "name": "A", "open_date": "2099-01-05", "close_date": "2099-01-08",
            "gmp": {"price": "10"}})]
        out = I.classify(rows, today=date(2026, 9, 24))
        self.assertEqual(len(out["upcoming"]), 1)


if __name__ == "__main__":
    unittest.main()
