"""Unit tests: technicals, Indian/Stooq parsing, capabilities, rawness.

No network. Run: python -m unittest discover -s tests -v
"""

import unittest

from providers import indian, stooq
from providers.base import describe
from providers.indian import IndianMarketApiProvider
from providers.stooq import StooqProvider
from providers.yahoo import YahooMarketDataProvider
from services import technicals as t


class TestRSI(unittest.TestCase):
    # Investopedia 14-period reference closes -> first RSI = 70.46
    REF = [
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        45.90,
        46.19,
        46.25,
        46.03,
        45.61,
        46.28,
    ]

    def test_reference_vector(self):
        # Hand-verified Wilder smoothing: closes [10,11,12,11], window 2:
        # changes +1,+1 -> avg_gain 1, avg_loss 0 -> RSI 100 at index 2;
        # next change -1 -> avg_gain 0.5, avg_loss 0.5 -> RSI 50.
        out = t.rsi([10, 11, 12, 11], 2)
        self.assertEqual(out[2], 100.0)
        self.assertEqual(out[3], 50.0)

    def test_investopedia_shape(self):
        # 14-period reference closes: first RSI must be strongly bullish.
        out = t.rsi(self.REF, 14)
        self.assertIsNone(out[13])
        self.assertIsNotNone(out[14])
        self.assertGreater(out[14], 65)
        self.assertLess(out[14], 80)

    def test_bounds(self):
        out = t.rsi(list(range(1, 60)), 14)
        self.assertTrue(all(v is None or 0 <= v <= 100 for v in out))

    def test_flat_series(self):
        out = t.rsi([10.0] * 30, 14)
        self.assertEqual(out[-1], 100.0)  # no losses -> 100 by Wilder

    def test_insufficient(self):
        self.assertEqual(t.rsi([1, 2, 3], 14), [None, None, None])


class TestEMA_MACD(unittest.TestCase):
    def test_ema_constant(self):
        out = t.ema([5.0] * 40, 12)
        self.assertAlmostEqual(out[-1], 5.0)

    def test_macd_relations(self):
        series = [float(100 + i + (i % 5)) for i in range(80)]
        m = t.macd(series)
        self.assertEqual(len(m["macd"]), 80)
        last = -1
        self.assertIsNotNone(m["macd"][last])
        self.assertIsNotNone(m["signal"][last])
        self.assertAlmostEqual(
            m["histogram"][last], m["macd"][last] - m["signal"][last]
        )


class TestATRVolDrawdownBeta(unittest.TestCase):
    def test_atr_positive(self):
        n = 40
        h = [100 + i * 0.5 + 1 for i in range(n)]
        low = [100 + i * 0.5 - 1 for i in range(n)]
        c = [100 + i * 0.5 for i in range(n)]
        out = t.atr(h, low, c, 14)
        self.assertIsNotNone(out[-1])
        self.assertGreater(out[-1], 0)

    def test_volatility(self):
        closes = [100 * (1.01**i) for i in range(60)]
        v = t.volatility_ann(closes, 20)
        self.assertIsNotNone(v)
        self.assertGreaterEqual(v, 0)

    def test_drawdown(self):
        self.assertAlmostEqual(t.max_drawdown([100, 120, 90, 110]), -25.0)
        self.assertEqual(t.max_drawdown([100, 110, 120]), 0.0)
        self.assertIsNone(t.max_drawdown([]))

    def test_beta_market(self):
        bench = [float(100 + i) for i in range(60)]
        self.assertAlmostEqual(t.beta(bench, bench), 1.0, places=6)

    def test_beta_needs_history(self):
        self.assertIsNone(t.beta([1, 2, 3], [1, 2, 3]))

    def test_compute_all_provenance(self):
        closes = [float(50 + i * 0.3 + (i % 7)) for i in range(260)]
        snap = t.compute_all(closes, closes, closes, source="history:yahoo")
        self.assertIsNotNone(snap["sma200"])
        self.assertIsNotNone(snap["rsi14"])
        self.assertEqual(snap["calculated_from"], "history:yahoo")
        self.assertIn("calculated_at", snap)


class TestStooqParse(unittest.TestCase):
    GOOD = (
        "Date,Open,High,Low,Close,Volume\n"
        "2026-09-10,100,101,99,100.5,1000\n"
        "2026-09-11,100.5,102,100,101.5,1200\n"
    )

    def test_valid_csv(self):
        bars = stooq.parse_daily_csv(self.GOOD)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["c"], 100.5)
        self.assertEqual(bars[1]["v"], 1200)

    def test_botwall_rejected(self):
        html = "<!DOCTYPE html><html><body>challenge</body></html>"
        self.assertIsNone(stooq.parse_daily_csv(html))

    def test_limit_text_rejected(self):
        self.assertIsNone(stooq.parse_daily_csv("Exceeded the daily hits limit."))

    def test_mapping_rules(self):
        self.assertEqual(stooq.to_stooq_symbol("AAPL"), "aapl.us")
        self.assertIsNone(stooq.to_stooq_symbol("RELIANCE.NS"))
        self.assertIsNone(stooq.to_stooq_symbol("^NSEI"))
        self.assertIsNone(stooq.to_stooq_symbol(""))

    def test_quote_and_search_unavailable(self):
        p = StooqProvider()
        self.assertEqual(p.get_quote("AAPL")["status"], "unavailable")
        self.assertEqual(p.search("x")["status"], "unavailable")


class TestIndianProvider(unittest.TestCase):
    def test_non_indian_passes_through(self):
        p = IndianMarketApiProvider()
        env = p.get_quote("AAPL")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("passes through", env["message"])

    def test_history_unsupported(self):
        p = IndianMarketApiProvider()
        self.assertEqual(
            p.get_historical_prices("RELIANCE.NS")["status"], "unavailable"
        )

    def test_is_indian(self):
        self.assertTrue(indian.is_indian("RELIANCE.NS"))
        self.assertTrue(indian.is_indian("sbin.bo"))
        self.assertFalse(indian.is_indian("AAPL"))
        self.assertFalse(indian.is_indian("^NSEI"))

    def test_num_unwraps(self):
        self.assertEqual(indian._num({"value": "28.45", "unit": "x"}), 28.45)
        self.assertEqual(indian._num(10), 10.0)
        self.assertIsNone(indian._num(None))


class TestCapabilities(unittest.TestCase):
    def test_yahoo_declares_market_data(self):
        caps = describe(YahooMarketDataProvider())
        self.assertTrue(caps["quote"] and caps["history"] and caps["search"])
        self.assertFalse(caps["estimates"])

    def test_stooq_history_only(self):
        caps = describe(StooqProvider())
        self.assertTrue(caps["history"])
        self.assertFalse(caps["quote"])
        self.assertFalse(caps["search"])

    def test_all_keys_present(self):
        from providers.base import CAPABILITIES

        caps = describe(IndianMarketApiProvider())
        self.assertEqual(set(caps), set(CAPABILITIES))


class TestSymbols(unittest.TestCase):
    def test_canonical(self):
        from providers import symbols as S

        self.assertEqual(S.canonical("  tatasteel.ns "), "TATASTEEL.NS")

    def test_match(self):
        from providers import symbols as S

        self.assertTrue(S.symbols_match("TATASTEEL.NS", "TATASTEEL.BSE"))
        self.assertTrue(S.symbols_match("AAPL", "AAPL"))
        self.assertFalse(S.symbols_match("TATASTEEL.NS", "RELIANCE.NS"))
        self.assertFalse(S.symbols_match("TATASTEEL.NS", None))
        self.assertFalse(S.symbols_match("AB", "AB"))

    def test_av_resolution_caches_discovery(self):
        from providers import symbols as S

        calls = []

        def fake_search(q):
            calls.append(q)
            return [{"symbol": "TATASTEEL.BSE", "name": "Tata Steel"}]

        out = S.resolve_alphavantage("TATASTEEL.NS", fake_search)
        self.assertEqual(out.get("symbol"), "TATASTEEL.BSE")
        out2 = S.resolve_alphavantage("TATASTEEL.NS", fake_search)
        self.assertEqual(out2.get("symbol"), "TATASTEEL.BSE")
        self.assertEqual(len(calls), 1)  # second hit from 7-day cache

    def test_av_resolution_rejects_foreign_match(self):
        from providers import symbols as S

        def fake_search(q):
            return [{"symbol": "AAPL", "name": "Apple"}]

        out = S.resolve_alphavantage("RELIANCE.NS", fake_search)
        self.assertIn("unresolved", out)


class TestAvValidation(unittest.TestCase):
    def test_states(self):
        from providers.fundamentals import _validate

        self.assertEqual(_validate({}, "X")[0], "empty")
        self.assertEqual(_validate({"Error Message": "bad"}, "X")[0], "error")
        self.assertEqual(_validate({"Information": "premium only"}, "X")[0], "premium")
        self.assertEqual(
            _validate({"Information": "25 per day"}, "X")[0], "rate_limited"
        )
        self.assertEqual(_validate({"Note": "frequency"}, "X")[0], "rate_limited")
        self.assertEqual(_validate({"Symbol": "AAPL"}, "X")[0], "ok")

    def test_no_key_paths(self):
        import os

        from providers.fundamentals import AlphaVantageFundamentalsProvider

        old = (
            os.environ.pop("ALPHA_VANTAGE_API_KEY", None),
            os.environ.pop("FUNDAMENTALS_API_KEY", None),
        )
        try:
            p = AlphaVantageFundamentalsProvider()
            for fn in (
                p.get_dividends,
                p.get_splits,
                p.get_shares_outstanding,
                p.get_earnings_estimates,
                p.get_estimates,
                p.get_earnings_calendar,
                p.symbol_search,
            ):
                env = fn("AAPL")
                self.assertEqual(env["status"], "unavailable")
        finally:
            if old[0] is not None:
                os.environ["ALPHA_VANTAGE_API_KEY"] = old[0]
            if old[1] is not None:
                os.environ["FUNDAMENTALS_API_KEY"] = old[1]

    def test_ttl_cache(self):
        import time

        from services.refresh import TTLCache

        c = TTLCache()
        self.assertIsNone(c.get("k"))
        c.set("k", {"v": 1}, 0.05)
        self.assertEqual(c.get("k"), {"v": 1})
        time.sleep(0.07)
        self.assertIsNone(c.get("k"))


if __name__ == "__main__":
    unittest.main()
