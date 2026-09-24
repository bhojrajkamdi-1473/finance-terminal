"""IPO layer tests: classification, GMP rules, honest unavailable states."""

import unittest
from datetime import date

from providers import ipo as I


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


if __name__ == "__main__":
    unittest.main()
