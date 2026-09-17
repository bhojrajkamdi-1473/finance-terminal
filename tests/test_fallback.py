"""Unit tests: fallback chain, Twelve Data mapping/budget, freshness.

No network. Stub legs simulate Yahoo/TwelveData/AlphaVantage behavior.
Run: python -m unittest discover -s tests -v
"""

import time
import unittest

from providers import twelvedata as td
from providers.base import error_envelope, live_envelope, unavailable
from providers.fallback import FallbackMarketData
from services import refresh


def _live(source, price=100.0):
    env = live_envelope(source, {"price": price}, delayed=True)
    env["timeliness"] = "DELAYED"
    return env


class StubLeg:
    """Scripted leg: script is a list of envelopes (or Exceptions)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def _next(self):
        self.calls += 1
        item = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    def get_quote(self, symbol):
        return self._next()

    def get_historical_prices(self, symbol, range_="1M", interval="1d"):
        return self._next()

    def search(self, query, limit=10):
        return self._next()


class TestFallbackOrder(unittest.TestCase):
    def test_first_live_leg_wins(self):
        a = StubLeg([_live("yahoo", 10)])
        b = StubLeg([_live("twelvedata", 11)])
        chain = FallbackMarketData([("yahoo", a), ("twelvedata", b)])
        env = chain.get_quote("X")
        self.assertEqual(env["data"]["price"], 10)
        self.assertEqual(env["served_from"], "provider")
        self.assertEqual(env["fallback_path"], ["yahoo"])
        self.assertEqual(b.calls, 0)

    def test_error_falls_to_next_leg(self):
        a = StubLeg([error_envelope("yahoo", "boom")])
        b = StubLeg([_live("twelvedata", 11)])
        chain = FallbackMarketData([("yahoo", a), ("twelvedata", b)])
        env = chain.get_quote("X")
        self.assertEqual(env["data"]["price"], 11)
        self.assertEqual(env["source"], "twelvedata")
        self.assertEqual(env["fallback_path"], ["yahoo:error", "twelvedata"])

    def test_unavailable_falls_through_with_last_envelope(self):
        a = StubLeg([unavailable("yahoo", "bad symbol")])
        b = StubLeg([unavailable("twelvedata", "not covered")])
        chain = FallbackMarketData([("yahoo", a), ("twelvedata", b)])
        env = chain.get_quote("NOPE")
        self.assertEqual(env["status"], "unavailable")
        self.assertFalse(env["stale"])

    def test_cache_serves_without_upstream(self):
        a = StubLeg([_live("yahoo", 10)])
        chain = FallbackMarketData([("yahoo", a)])
        first = chain.get_quote("X")
        second = chain.get_quote("X")
        self.assertEqual(first["served_from"], "provider")
        self.assertEqual(second["served_from"], "cache")
        self.assertEqual(a.calls, 1)

    def test_stale_cache_served_when_all_fail(self):
        a = StubLeg([_live("yahoo", 10)])
        chain = FallbackMarketData([("yahoo", a)])
        chain.get_quote("X")
        # force expiry then fail upstream
        key = "q:X"
        chain._cache[key].ttl = 0
        a.script = [error_envelope("yahoo", "down")]
        env = chain.get_quote("X")
        self.assertTrue(env["stale"])
        self.assertEqual(env["data"]["price"], 10)
        self.assertIn("STALE", env["message"])

    def test_cooling_leg_is_skipped(self):
        a = StubLeg([error_envelope("yahoo", "down")])
        b = StubLeg([_live("twelvedata", 11)])
        chain = FallbackMarketData([("yahoo", a), ("twelvedata", b)])
        chain.get_quote("X")  # error 1
        chain._cache.clear()
        chain.get_quote("X")  # error 2 -> cooling
        chain._cache.clear()
        env = chain.get_quote("X")  # yahoo skipped
        self.assertIn("yahoo:cooling", env["fallback_path"])
        self.assertEqual(env["source"], "twelvedata")

    def test_unavailable_never_cools_down(self):
        # Definitive unavailable (no key / bad symbol) must not penalize:
        # regression test from live incident where keyless legs cooled.
        a = StubLeg([unavailable("twelvedata", "no key")])
        b = StubLeg([_live("yahoo", 11)])
        chain = FallbackMarketData([("twelvedata", a), ("yahoo", b)])
        for _ in range(4):
            chain._cache.clear()
            env = chain.get_quote("X")
            self.assertEqual(env["source"], "yahoo")
        health = chain.health()["twelvedata"]
        self.assertEqual(health["consecutive_errors"], 0)
        self.assertNotEqual(health["state"], "cooling")

    def test_scarce_leg_gets_long_ttl(self):
        a = StubLeg([error_envelope("yahoo", "down")])
        b = StubLeg([_live("alphavantage", 12)])
        chain = FallbackMarketData(
            [("yahoo", a), ("alphavantage", b)], scarce_legs={"alphavantage"}
        )
        chain.get_quote("X")
        entry = chain._cache["q:X"]
        self.assertGreaterEqual(entry.ttl, 6 * 3600 - 1)

    def test_history_capability_filtering(self):
        class QuoteOnly:
            def get_quote(self, symbol):
                return _live("av", 1)

        y = StubLeg([live_envelope("yahoo", {"bars": [1]}, delayed=True)])
        chain = FallbackMarketData([("av", QuoteOnly()), ("yahoo", y)])
        env = chain.get_historical_prices("X")
        self.assertEqual(env["source"], "yahoo")


class TestTwelveDataMapping(unittest.TestCase):
    def test_nse_bse_mapping(self):
        self.assertEqual(td.to_td_symbol("RELIANCE.NS"), "RELIANCE/NSE")
        self.assertEqual(td.to_td_symbol("RELIANCE.BO"), "RELIANCE/BSE")
        self.assertEqual(td.to_td_symbol("AAPL"), "AAPL")

    def test_indices_unaddressable(self):
        self.assertIsNone(td.to_td_symbol("^NSEI"))
        self.assertIsNone(td.to_td_symbol(""))

    def test_no_key_means_unavailable_not_error(self):
        import os

        old = os.environ.pop("TWELVE_DATA_API_KEY", None)
        try:
            env = td.TwelveDataProvider().get_quote("AAPL")
            self.assertEqual(env["status"], "unavailable")
            self.assertIn("NOT CONFIGURED", env["message"])
        finally:
            if old is not None:
                os.environ["TWELVE_DATA_API_KEY"] = old

    def test_budget_guard(self):
        # drain the minute bucket, then restore globals
        saved = (td._minute_window_start, td._minute_used, td._day_key, td._day_used)
        try:
            td._minute_window_start = time.time()
            td._minute_used = 0
            for _ in range(td.CREDITS_PER_MINUTE):
                self.assertIsNone(td._budget_take(1))
            self.assertIsNotNone(td._budget_take(1))
            snap = td.budget_snapshot()
            self.assertEqual(snap["per_minute_used"], td.CREDITS_PER_MINUTE)
        finally:
            (
                td._minute_window_start,
                td._minute_used,
                td._day_key,
                td._day_used,
            ) = saved


class TestRefresh(unittest.TestCase):
    def test_ist_clock(self):
        self.assertTrue(refresh.now_ist_str().endswith("IST"))

    def test_as_of_ist(self):
        self.assertEqual(refresh.as_of_ist_str(None), "unavailable")
        out = refresh.as_of_ist_str("2026-09-16T13:00:00+00:00")
        self.assertTrue(out.endswith("IST"))
        self.assertIn("18:30", out)  # 13:00 UTC == 18:30 IST

    def test_stale_logic(self):
        self.assertTrue(refresh.is_stale(None))
        self.assertTrue(refresh.is_stale("2020-01-01T00:00:00+00:00"))
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        self.assertFalse(refresh.is_stale(now))


if __name__ == "__main__":
    unittest.main()
