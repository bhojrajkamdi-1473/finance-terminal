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


class TestAnalyticsPhase(unittest.TestCase):
    def test_phase2_uptrend(self):
        # steady rise: price above rising long averages, within band
        closes = [100.0 + i * 0.35 + (i % 7) * 0.1 for i in range(260)]
        out = t.phase(closes)
        self.assertEqual(out["phase"], "Phase 2")
        self.assertTrue(out["checks"]["price_above_200_sma"])
        self.assertIn("Weinstein", out["method"])

    def test_phase4_downtrend(self):
        closes = [300.0 - i * 0.5 - (i % 5) * 0.1 for i in range(260)]
        out = t.phase(closes)
        self.assertEqual(out["phase"], "Phase 4")

    def test_phase_insufficient(self):
        out = t.phase([100.0] * 50)
        self.assertEqual(out["phase"], "UNKNOWN")
        self.assertIn("INSUFFICIENT_DATA", out["reason"])

    def test_sma_slope_sign(self):
        rising = [100.0 + i for i in range(60)]
        falling = [200.0 - i for i in range(60)]
        flat = [100.0] * 60
        self.assertGreater(t.sma_slope(rising, 20), 0)
        self.assertLess(t.sma_slope(falling, 20), 0)
        self.assertEqual(t.sma_slope(flat, 20), 0.0)
        self.assertIsNone(t.sma_slope([1.0, 2.0], 20))


class TestRelativeStrength(unittest.TestCase):
    def test_outperformance(self):
        asset = [100.0 * (1.002**i) for i in range(120)]
        bench = [100.0 * (1.001**i) for i in range(120)]
        out = t.relative_strength(asset, bench, "NIFTY 50", lookback=63)
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["benchmark"], "NIFTY 50")
        self.assertGreater(out["rs_pp"], 0)
        self.assertGreater(out["stock_return_pct"], out["benchmark_return_pct"])

    def test_no_benchmark(self):
        out = t.relative_strength([100.0] * 120, None)
        self.assertEqual(out["status"], "NO_BENCHMARK")

    def test_short_series(self):
        out = t.relative_strength([1.0, 2.0], [1.0, 2.0])
        self.assertEqual(out["status"], "INSUFFICIENT_DATA")


class TestVCPBreakout(unittest.TestCase):
    def test_insufficient(self):
        self.assertEqual(t.vcp([100.0] * 30)["status"], "INSUFFICIENT_DATA")
        self.assertEqual(t.breakout([100.0] * 10)["status"], "INSUFFICIENT_DATA")

    def test_vcp_constructed(self):
        # three successively shallower pullbacks off rising peaks
        closes = []
        base = 100.0
        for leg, drop in ((120.0, 12.0), (130.0, 8.0), (138.0, 4.0)):
            steps = 20
            for i in range(steps):
                closes.append(base + (leg - base) * (i + 1) / steps)
            base = leg
            for i in range(10):
                closes.append(leg - drop * (i + 1) / 10)
            base = leg - drop
        vols = [1000.0 - i * 2 for i in range(len(closes))]
        out = t.vcp(closes, volumes=vols)
        self.assertEqual(out["status"], "OK")
        self.assertGreaterEqual(out["contraction_count"], 2)
        self.assertTrue(out["detected"])

    def test_breakout_levels(self):
        flat = [100.0] * 100 + [130.0]
        out = t.breakout(flat)
        self.assertEqual(out["status"], "ABOVE_LEVEL")
        self.assertEqual(out["reference_level"], 100.0)
        low = [100.0] * 100 + [50.0]
        self.assertEqual(t.breakout(low)["status"], "BELOW_LEVEL")


class TestTrendTemplateBreadthRegime(unittest.TestCase):
    def test_template_full(self):
        closes = [100.0 + i * 0.3 for i in range(260)]
        out = t.trend_template(closes)
        self.assertIn("conditions", out)
        self.assertEqual(out["total"], 9)
        self.assertEqual(out["conditions"]["price_above_200_sma"], "pass")

    def test_template_short(self):
        out = t.trend_template([1.0, 2.0, 3.0])
        self.assertEqual(out["status"], "INSUFFICIENT_DATA")

    def test_breadth_explicit_universe(self):
        up = [100.0 + i * 0.35 for i in range(260)]
        dn = [300.0 - i * 0.5 for i in range(260)]
        out = t.breadth({"AAA": up, "BBB": dn, "CCC": [1.0, 2.0]})
        self.assertEqual(out["universe_size"], 3)
        self.assertEqual(out["scored"], 2)
        self.assertEqual(out["advancers"] + out["decliners"] + out["unchanged"], 2)
        self.assertIn("as_of", out)

    def test_regime(self):
        rising = [100.0 + i * 0.4 for i in range(260)]
        falling = [300.0 - i * 0.5 for i in range(260)]
        self.assertEqual(t.market_regime(rising)["status"], "RISK_ON")
        self.assertEqual(t.market_regime(falling)["status"], "RISK_OFF")
        self.assertEqual(t.market_regime([1.0, 2.0])["status"], "UNKNOWN")


class TestRiskRewardScoringFundamentals(unittest.TestCase):
    def test_risk_reward(self):
        out = t.risk_reward(100.0, 2.0, 110.0)
        self.assertEqual(out["status"], "OK")
        self.assertAlmostEqual(out["technical_stop"], 96.0)
        self.assertAlmostEqual(out["risk_pct"], 4.0)
        self.assertAlmostEqual(out["reward_pct"], 10.0)
        self.assertAlmostEqual(out["risk_reward_ratio"], 2.5)
        self.assertIn("not investment advice", out["label"].lower())

    def test_risk_reward_missing(self):
        self.assertEqual(
            t.risk_reward(100.0, None, 110.0)["status"], "INSUFFICIENT_DATA"
        )
        self.assertEqual(t.risk_reward(None, None, None)["status"], "INSUFFICIENT_DATA")

    def test_scoring_transparent(self):
        out = t.score_snapshot(
            {
                "components": {
                    "trend": {"value": 8, "max": 10},
                    "momentum": {"value": 3, "max": 10},
                    "missing": {"value": None, "max": 10},
                }
            }
        )
        self.assertEqual(out["components"]["trend"]["state"], "strong")
        self.assertEqual(out["components"]["momentum"]["state"], "weak")
        self.assertEqual(out["components"]["missing"]["state"], "UNKNOWN")
        self.assertIn("Technical Structure", out["overall"])

    def test_scoring_empty(self):
        out = t.score_snapshot({})
        self.assertIn("INSUFFICIENT_DATA", out["overall"])

    def test_fundamental_trends(self):
        reps = [
            {
                "_period": "FY25",
                "totalRevenue": "1100",
                "netIncome": "110",
                "eps": "11",
            },
            {
                "_period": "FY25",
                "totalRevenue": "1000",
                "netIncome": "100",
                "eps": "10",
            },
        ]
        out = t.fundamental_trends(reps)
        self.assertEqual(out["status"], "OK")
        self.assertAlmostEqual(out["revenue_growth_pct"], 10.0)
        self.assertAlmostEqual(out["net_margin_pct"], 10.0)

    def test_fundamental_mixed_period(self):
        reps = [
            {"_period": "FY25", "totalRevenue": "1100"},
            {"_period": "Q1", "totalRevenue": "300"},
        ]
        self.assertEqual(t.fundamental_trends(reps)["status"], "NOT_COMPARABLE")

    def test_fundamental_single(self):
        self.assertEqual(
            t.fundamental_trends([{"totalRevenue": "5"}])["status"],
            "INSUFFICIENT_DATA",
        )


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
