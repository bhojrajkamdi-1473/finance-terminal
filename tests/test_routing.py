"""Unit tests: capability-based routing for company domains.

No network. Stub legs simulate Yahoo / Alpha Vantage / Twelve Data /
Indian API for TCS.NS (Indian) and MSFT (non-Indian). Fake key VALUES
only flip the configured-flags so stubs dispatch; stubs never touch
the network. Run: python -m unittest discover -s tests -v
"""

import os
import unittest

from providers.base import live_envelope
from providers.orchestrator import CAPABILITIES, ProviderManager


def _stmt(source, revenue=1000.0):
    return live_envelope(
        source,
        {
            "symbol": "TCS.NS",
            "statement": "income",
            "period": "annual",
            "currency": "INR",
            "reports": [{"fiscalDateEnding": "2025-03-31", "totalRevenue": revenue}],
        },
        delayed=True,
    )


class Stub:
    def __init__(self, **methods):
        self._methods = methods
        self.calls: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def fn(*a, **k):
            self.calls.append(name)
            return self._methods[name](*a, **k)

        return fn


def _manager(yahoo=None, indian=None, td=None, av=None, rss=None, acts=None):
    return ProviderManager(
        yahoo=yahoo,
        indian=indian,
        twelvedata=td,
        alphavantage=av,
        news_rss=rss,
        actions_yahoo=acts,
    )


class _EnvGuard(unittest.TestCase):
    KEYS = (
        "ALPHA_VANTAGE_API_KEY",
        "TWELVE_DATA_API_KEY",
        "INDIAN_STOCK_MARKET_API_KEY",
    )

    def setUp(self):
        self._old = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestCapabilitiesRegistry(_EnvGuard):
    def test_registry_matches_implementation(self):
        self.assertTrue(CAPABILITIES["yahoo"]["quote"])
        self.assertTrue(CAPABILITIES["yahoo"]["history"])
        self.assertFalse(CAPABILITIES["yahoo"]["statements"])
        self.assertFalse(CAPABILITIES["yahoo"]["valuation"])
        self.assertTrue(CAPABILITIES["alphavantage"]["statements"])
        self.assertTrue(CAPABILITIES["twelvedata"]["valuation"])
        self.assertFalse(CAPABILITIES["twelvedata"]["estimates"])
        self.assertTrue(CAPABILITIES["indian-api"]["holdings"])
        self.assertFalse(CAPABILITIES["indian-api"]["history"])
        self.assertFalse(CAPABILITIES["stooq"]["quote"])
        self.assertTrue(CAPABILITIES["stooq"]["history"])


class TestYahooOnlyTCS(_EnvGuard):
    """Yahoo only: market data works, fundamentals-family is honest."""

    def test_statements_honest_miss_names_all_providers(self):
        # Legs wired (as in production) but no keys: every provider is
        # named with its key reason; stubs are never dispatched.
        av, td, indian = Stub(), Stub(), Stub()
        m = _manager(av=av, td=td, indian=indian)
        env = m.get_statements("TCS.NS", "income", "annual")
        self.assertEqual(env["status"], "unavailable")
        self.assertIsNone(env["data"])
        self.assertEqual(av.calls, [])
        self.assertEqual(td.calls, [])
        self.assertEqual(indian.calls, [])
        providers = {p["provider"] for p in env.get("provider_status", [])}
        self.assertEqual(providers, {"alphavantage", "twelvedata", "indian-api"})
        for p in env["provider_status"]:
            self.assertEqual(p["state"], "KEY_REQUIRED")
        # never a single-provider key message as the domain answer
        self.assertNotIn("Set INDIAN_STOCK_MARKET_API_KEY", env["message"])
        self.assertIn("ALPHA_VANTAGE_API_KEY", env["message"])
        self.assertIn("TWELVE_DATA_API_KEY", env["message"])
        self.assertIn("INDIAN_STOCK_MARKET_API_KEY", env["message"])

    def test_valuation_earnings_estimates_honest_miss(self):
        m = _manager()
        for fn in ("get_valuation", "get_earnings", "get_estimates"):
            env = getattr(m, fn)("TCS.NS")
            self.assertEqual(env["status"], "unavailable", fn)
            self.assertIsNone(env["data"], fn)
            self.assertTrue(env.get("provider_status"), fn)
            self.assertNotIn("Set INDIAN_STOCK_MARKET_API_KEY", env.get("message") or "")

    def test_key_gated_indian_leg_never_dispatched(self):
        indian = Stub(get_financial_statements=lambda *a: _stmt("indian-api"))
        m = _manager(indian=indian)
        env = m.get_statements("TCS.NS", "income", "annual")
        self.assertEqual(indian.calls, [])
        self.assertEqual(env["status"], "unavailable")

    def test_news_and_actions_still_live_from_yahoo(self):
        rss = Stub(
            get_news=lambda *a: live_envelope(
                "yahoo-rss", {"items": [{"title": "T", "url": "http://x/1"}]}
            )
        )
        acts = Stub(
            get_corporate_actions=lambda s: live_envelope(
                "yahoo-events", {"dividends": [], "splits": []}, delayed=True
            )
        )
        m = _manager(rss=rss, acts=acts)
        news = m.get_news(symbol="TCS.NS", limit=5)
        self.assertEqual(news["status"], "live")
        self.assertEqual(news["data"]["items"][0]["via"], "yahoo-rss")


class TestWithKeys(_EnvGuard):
    def _keys(self, *names):
        for n in names:
            os.environ[n] = "test-key"

    def test_av_statement_wins_for_tcs(self):
        self._keys("ALPHA_VANTAGE_API_KEY")
        av = Stub(
            get_financial_statements=lambda *a: _stmt("alphavantage", revenue=2000.0)
        )
        m = _manager(av=av)
        env = m.get_statements("TCS.NS", "income", "annual")
        self.assertEqual(env["status"], "live")
        self.assertEqual(env["source"], "alphavantage")
        self.assertEqual(env["data"]["reports"][0]["totalRevenue"], 2000.0)

    def test_td_statement_covers_when_av_absent(self):
        self._keys("TWELVE_DATA_API_KEY")
        import providers.twelvedata as _td_mod

        real_probe = _td_mod.budget_probe
        _td_mod.budget_probe = lambda cost: None  # budget stub: no network
        try:

            def td_stmt(s, st, p):
                env = live_envelope("twelvedata", {}, delayed=True)
                env["data"] = {
                    "symbol": s,
                    "statement": st,
                    "period": p,
                    "currency": "INR",
                    "reports": [
                        {"fiscalDateEnding": "2025-03-31", "totalRevenue": 3000.0}
                    ],
                }
                env["timeliness"] = "END-OF-DAY"
                return env

            td = Stub(get_statement_td=td_stmt)
            m = _manager(td=td)
            env = m.get_statements("TCS.NS", "income", "annual")
        finally:
            _td_mod.budget_probe = real_probe
        self.assertEqual(env["status"], "live")
        self.assertEqual(env["source"], "twelvedata")

    def test_indian_statement_covers_tcs_with_key(self):
        self._keys("INDIAN_STOCK_MARKET_API_KEY")
        indian = Stub(get_financial_statements=lambda *a: _stmt("indian-api"))
        m = _manager(indian=indian)
        env = m.get_statements("TCS.NS", "income", "annual")
        self.assertEqual(env["status"], "live")
        self.assertEqual(env["source"], "indian-api")
        self.assertEqual(indian.calls, ["get_financial_statements"])

    def test_msft_never_touches_indian_leg(self):
        self._keys(
            "ALPHA_VANTAGE_API_KEY",
            "TWELVE_DATA_API_KEY",
            "INDIAN_STOCK_MARKET_API_KEY",
        )
        indian = Stub(get_financial_statements=lambda *a: _stmt("indian-api"))
        m = _manager(indian=indian)
        env = m.get_statements("MSFT", "income", "annual")
        self.assertEqual(indian.calls, [])
        skipped = {s["provider"]: s["reason"] for s in env["reconciliation"]["skipped"]}
        self.assertIn("indian-api", skipped)


class TestYahooActionsEvents(_EnvGuard):
    """Yahoo only returns the events block when explicitly requested."""

    def test_events_param_requested_and_dividends_parsed(self):
        from providers.news import YahooCorporateActionsProvider
        from providers.yahoo import YahooMarketDataProvider

        seen = {}
        real = YahooMarketDataProvider._chart

        def fake(self, symbol, range_, interval, events=False):
            seen["events"] = events
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {"currency": "USD"},
                            "events": {
                                "dividends": {"1700000000": {"amount": 0.5}},
                                "splits": {},
                            },
                        }
                    ]
                }
            }

        YahooMarketDataProvider._chart = fake
        try:
            env = YahooCorporateActionsProvider().get_corporate_actions("MSFT")
        finally:
            YahooMarketDataProvider._chart = real
        self.assertTrue(seen.get("events"))
        self.assertEqual(env["status"], "delayed")
        self.assertEqual(len(env["data"]["dividends"]), 1)
        self.assertEqual(env["data"]["dividends"][0]["amount"], 0.5)

    def test_empty_events_is_live_empty_not_unavailable(self):
        from providers.news import YahooCorporateActionsProvider
        from providers.yahoo import YahooMarketDataProvider

        real = YahooMarketDataProvider._chart

        def fake(self, symbol, range_, interval, events=False):
            return {
                "chart": {
                    "result": [{"meta": {"currency": "USD"}, "events": {}}]
                }
            }

        YahooMarketDataProvider._chart = fake
        try:
            env = YahooCorporateActionsProvider().get_corporate_actions("MSFT")
        finally:
            YahooMarketDataProvider._chart = real
        # legitimately empty (e.g. never split): delayed envelope, empty
        # rows — the orchestrator reports "no actions", never fake rows.
        self.assertEqual(env["status"], "delayed")
        self.assertEqual(env["data"]["dividends"], [])


if __name__ == "__main__":
    unittest.main()
