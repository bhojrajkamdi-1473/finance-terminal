"""Open (no-key) public feeds leg. No network — transport is mocked.

Covers: FX mapping + latest/history parsing, crypto mapping, treasury
points, EDGAR link construction, unmapped pass-through, malformed
responses, failure non-caching, capabilities + status honesty.
"""

import json
import unittest
from unittest import mock

from providers import openfeeds as _of


def _resp(payload):
    body = json.dumps(payload).encode()
    m = mock.MagicMock()
    m.read.return_value = body
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


class MappingTests(unittest.TestCase):
    def setUp(self):
        with _of._cache_lock:
            _of._cache.clear()

    def test_fx_pair_keys(self):
        self.assertEqual(_of.fx_pair_key("USDINR"), ("USD", "INR"))
        self.assertEqual(_of.fx_pair_key("USDINR=X"), ("USD", "INR"))
        self.assertEqual(_of.fx_pair_key("INR=X"), ("USD", "INR"))
        self.assertIsNone(_of.fx_pair_key("RELIANCE.NS"))
        self.assertIsNone(_of.fx_pair_key("AAPL"))

    def test_unmapped_pass_through(self):
        self.assertEqual(_of.fx_latest("RELIANCE.NS")["status"], "unavailable")
        self.assertEqual(_of.crypto_quote("AAPL")["status"], "unavailable")
        self.assertEqual(_of.fx_history("MSFT")["status"], "unavailable")
        self.assertEqual(_of.edgar_search("x")["status"], "unavailable")


class FxTests(unittest.TestCase):
    def setUp(self):
        with _of._cache_lock:
            _of._cache.clear()

    def test_latest_parses(self):
        payload = {"amount": 1.0, "base": "USD", "date": "2026-09-25",
                   "rates": {"INR": 95.82}}
        with mock.patch.object(_of.urllib.request, "urlopen", lambda *a, **k: _resp(payload)):
            env = _of.fx_latest("USDINR")
        self.assertEqual(env["status"], "delayed")
        self.assertEqual(env["data"]["price"], 95.82)
        self.assertEqual(env["data"]["currency"], "INR")
        self.assertEqual(env["source_timestamp"], "2026-09-25")

    def test_history_bars(self):
        payload = {"rates": {"2026-09-24": {"INR": 95.0}, "2026-09-25": {"INR": 95.82}}}
        with mock.patch.object(_of.urllib.request, "urlopen", lambda *a, **k: _resp(payload)):
            env = _of.fx_history("USDINR", 30)
        bars = env["data"]["bars"]
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[-1]["c"], 95.82)
        self.assertIsNone(bars[-1]["v"])  # no intraday range published
        self.assertIn("mirror close", env["data"]["adjustment_note"])

    def test_malformed_is_error(self):
        m = mock.MagicMock()
        m.read.return_value = b"not json{{"
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        with mock.patch.object(_of.urllib.request, "urlopen", lambda *a, **k: m):
            env = _of.fx_latest("USDINR")
        self.assertEqual(env["status"], "error")

    def test_failures_not_cached(self):
        import urllib.error
        calls = []

        def flaky(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.URLError("down")
            return _resp({"amount": 1.0, "base": "USD", "date": "2026-09-25", "rates": {"INR": 1.0}})

        with mock.patch.object(_of.urllib.request, "urlopen", flaky):
            e1 = _of.fx_latest("USDINR")
            e2 = _of.fx_latest("USDINR")
        self.assertEqual(e1["status"], "error")
        self.assertEqual(e2["data"]["price"], 1.0)
        self.assertEqual(len(calls), 2)


class CryptoTests(unittest.TestCase):
    def setUp(self):
        with _of._cache_lock:
            _of._cache.clear()

    def test_markets_parses(self):
        payload = [{"id": "bitcoin", "name": "Bitcoin", "current_price": 84469,
                    "price_change_percentage_24h_in_currency": 0.66,
                    "market_cap": 1697013203691, "last_updated": "2026-09-27T06:02:30.000Z"}]
        with mock.patch.object(_of.urllib.request, "urlopen", lambda *a, **k: _resp(payload)):
            env = _of.crypto_quote("BTC-USD")
        self.assertEqual(env["data"]["price"], 84469)
        self.assertEqual(env["data"]["currency"], "USD")
        self.assertAlmostEqual(env["data"]["change_pct"], 0.66)


class TreasuryTests(unittest.TestCase):
    def setUp(self):
        with _of._cache_lock:
            _of._cache.clear()

    def test_points(self):
        payload = {"data": [
            {"record_date": "2026-08-31", "security_desc": "Treasury Notes",
             "avg_interest_rate_amt": "3.345"},
            {"record_date": "2026-08-31", "security_desc": "Treasury Bills",
             "avg_interest_rate_amt": "bad"},
        ]}
        with mock.patch.object(_of.urllib.request, "urlopen", lambda *a, **k: _resp(payload)):
            env = _of.treasury_rates(6)
        pts = env["data"]["points"]
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0]["value"], 3.345)
        self.assertEqual(env["timeliness"], "END-OF-DAY")


class EdgarTests(unittest.TestCase):
    def setUp(self):
        with _of._cache_lock:
            _of._cache.clear()

    def test_links_built(self):
        payload = {"hits": {"hits": [{
            "_id": "0001628280-24-002390:tsla-2023x12x31xex211.htm",
            "_source": {"ciks": ["0001318605"], "root_forms": ["10-K"],
                        "display_names": ["Tesla, Inc. (TSLA)"],
                        "file_date": "2024-01-29"},
        }, {
            "_id": "nocolon", "_source": {},
        }]}}
        with mock.patch.object(_of.urllib.request, "urlopen", lambda *a, **k: _resp(payload)):
            env = _of.edgar_search("Tesla", 5)
        items = env["data"]["items"]
        self.assertEqual(len(items), 1)  # linkless hit dropped
        self.assertIn("10-K", items[0]["title"])
        self.assertTrue(items[0]["url"].startswith("https://www.sec.gov/Archives/edgar/data/1318605/"))
        self.assertEqual(items[0]["source"], "SEC EDGAR")


class ProviderTests(unittest.TestCase):
    def test_capabilities_and_status(self):
        p = _of.OpenFeedsProvider()
        for cap in ("quote", "history", "macro", "filings"):
            self.assertTrue(p.capabilities[cap], cap)
        for cap in ("search", "ipo", "estimates", "chart"):
            self.assertFalse(p.capabilities[cap], cap)
        st = p.status()
        self.assertEqual(st["state"], "live")
        self.assertFalse(st["key_required"])
        self.assertNotIn("token", json.dumps(st).lower())

    def test_provider_routing(self):
        p = _of.OpenFeedsProvider()
        with _of._cache_lock:
            _of._cache.clear()
        with mock.patch.object(_of.urllib.request, "urlopen",
                               lambda *a, **k: _resp({"amount": 1.0, "base": "USD", "date": "2026-09-25", "rates": {"INR": 1.0}})):
            self.assertEqual(p.get_quote("USDINR")["status"], "delayed")
        self.assertEqual(p.get_quote("RELIANCE.NS")["status"], "unavailable")
        self.assertEqual(p.get_historical_prices("AAPL")["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
