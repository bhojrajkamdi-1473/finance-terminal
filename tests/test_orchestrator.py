"""Unit tests: reconciliation + ProviderManager fan-out.

No network. Stub legs simulate Yahoo/Indian/AlphaVantage/TwelveData.
Fake key VALUES only flip the configured-flags so stubs dispatch;
stubs never touch the network.
Run: python -m unittest discover -s tests -v
"""

import os
import unittest

from providers.base import live_envelope
from providers.orchestrator import ProviderManager
from providers.schema import field
from services import reconcile as rec


class KeyedTestCase(unittest.TestCase):
    def setUp(self):
        self._old = {
            k: os.environ.get(k)
            for k in ("ALPHA_VANTAGE_API_KEY", "TWELVE_DATA_API_KEY")
        }
        os.environ["ALPHA_VANTAGE_API_KEY"] = "test-key"
        os.environ["TWELVE_DATA_API_KEY"] = "test-key"

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _q(source, price=100.0, as_of="2026-09-16T10:00:00+00:00", **kw):
    q = {
        "symbol": "X",
        "price": price,
        "previous_close": 99.0,
        "change": 1.0,
        "change_pct": 1.01,
        "volume": 1000,
        "day_high": 101.0,
        "day_low": 98.0,
        "currency": "INR",
    }
    q.update(kw)
    env = live_envelope(source, q, delayed=True)
    env["timeliness"] = "DELAYED"
    return env


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


class TestReconcile(unittest.TestCase):
    def test_agreement(self):
        a = field(100.0, "alphavantage", "t", "FY25", "INR")
        b = field(100.5, "twelvedata", "t", "FY25", "INR")
        c = rec.compare("revenue", a, [b])
        self.assertEqual(c["status"], "CROSS_CHECK_OK")
        self.assertAlmostEqual(c["difference_pct"], 0.5)

    def test_discrepancy_never_averaged(self):
        a = field(100.0, "alphavantage", "t", "FY25", "INR")
        b = field(120.0, "twelvedata", "t", "FY25", "INR")
        c = rec.compare("revenue", a, [b])
        self.assertEqual(c["status"], "PROVIDER_DISCREPANCY")
        # both raw values preserved, no combined number
        self.assertEqual(c["primary"]["value"], 100.0)
        self.assertEqual(c["cross_check"][0]["value"], 120.0)
        self.assertAlmostEqual(c["difference_pct"], 20.0)

    def test_currency_guard(self):
        a = field(100.0, "alphavantage", "t", "FY25", "INR")
        b = field(100.0, "twelvedata", "t", "FY25", "USD")
        c = rec.compare("revenue", a, [b])
        self.assertEqual(c["status"], "NOT_COMPARABLE")
        self.assertIn("Currency", c["reason"])

    def test_period_guard(self):
        a = field(100.0, "alphavantage", "t", "FY25", "INR")
        b = field(100.0, "twelvedata", "t", "Q1-FY25", "INR")
        c = rec.compare("revenue", a, [b])
        self.assertEqual(c["status"], "NOT_COMPARABLE")
        self.assertIn("Period", c["reason"])

    def test_single_source(self):
        a = field(100.0, "alphavantage", "t", "FY25", "INR")
        c = rec.compare("revenue", a, [])
        self.assertEqual(c["status"], "SINGLE_SOURCE")

    def test_missing_primary(self):
        a = field(None, "alphavantage", "t", "FY25", "INR")
        b = field(100.0, "twelvedata", "t", "FY25", "INR")
        c = rec.compare("revenue", a, [b])
        self.assertEqual(c["status"], "NOT_COMPARABLE")

    def test_summarize(self):
        s = rec.summarize(
            [
                {"field": "a", "status": "CROSS_CHECK_OK"},
                {"field": "b", "status": "PROVIDER_DISCREPANCY"},
                {"field": "c", "status": "SINGLE_SOURCE"},
            ]
        )
        self.assertEqual(s["fields_compared"], 3)
        self.assertEqual(s["discrepancies"], 1)
        self.assertEqual(s["discrepancy_fields"], ["b"])


class TestManagerQuote(unittest.TestCase):
    def test_primary_yahoo_crosscheck_others(self):
        yahoo = Stub(get_quote=lambda s: _q("yahoo", price=100.0))
        indian = Stub(get_quote=lambda s: _q("indian-api", price=100.4))
        m = _manager(yahoo=yahoo, indian=indian)
        env = m.get_quote("TATASTEEL.NS")
        self.assertEqual(env["source"], "yahoo")
        # primary value untouched (never averaged with 100.4)
        self.assertEqual(env["data"]["price"], 100.0)
        comp = next(
            c for c in env["reconciliation"]["comparisons"] if c["field"] == "price"
        )
        self.assertEqual(comp["status"], "CROSS_CHECK_OK")
        self.assertEqual(env["reconciliation"]["primary"], "yahoo")

    def test_discrepancy_flagged(self):
        yahoo = Stub(get_quote=lambda s: _q("yahoo", price=100.0))
        indian = Stub(get_quote=lambda s: _q("indian-api", price=130.0))
        m = _manager(yahoo=yahoo, indian=indian)
        env = m.get_quote("X.NS")
        comp = next(
            c for c in env["reconciliation"]["comparisons"] if c["field"] == "price"
        )
        self.assertEqual(comp["status"], "PROVIDER_DISCREPANCY")
        self.assertEqual(env["data"]["price"], 100.0)

    def test_non_indian_skips_indian_leg(self):
        yahoo = Stub(get_quote=lambda s: _q("yahoo", price=10.0))
        indian = Stub(get_quote=lambda s: _q("indian-api", price=10.0))
        m = _manager(yahoo=yahoo, indian=indian)
        env = m.get_quote("AAPL")
        self.assertEqual(indian.calls, [])
        skipped = env["reconciliation"]["skipped"]
        self.assertTrue(any(s["provider"] == "indian-api" for s in skipped))

    def test_cache_and_coalescing(self):
        yahoo = Stub(get_quote=lambda s: _q("yahoo", price=10.0))
        m = _manager(yahoo=yahoo)
        m.get_quote("AAPL")
        env = m.get_quote("AAPL")
        self.assertEqual(env["served_from"], "cache")
        self.assertEqual(yahoo.calls, ["get_quote"])


class TestManagerDomains(KeyedTestCase):
    def test_profile_merges_av_td(self):
        av = Stub(
            get_ratios=lambda s: live_envelope(
                "alphavantage",
                {
                    "Name": "Acme",
                    "Sector": "Tech",
                    "Currency": "USD",
                    "MarketCapitalization": "1000",
                    "PERatio": "10",
                },
            )
        )

        # TD statistics shape: flat field dicts under data
        def stats(s):
            from providers.schema import field as _f

            env = live_envelope("twelvedata", {}, delayed=True)
            env["data"] = {
                "market_cap": _f(1010.0, "twelvedata", "t", None, "USD"),
                "pe": _f(10.2, "twelvedata", "t"),
            }
            env["timeliness"] = "END-OF-DAY"
            return env

        td2 = Stub(get_statistics=stats)
        m = _manager(av=av, td=td2)
        env = m.get_profile("ACME")
        self.assertEqual(env["status"], "live")
        self.assertEqual(env["data"]["sector"], "Tech")
        comp = next(
            c
            for c in env["reconciliation"]["comparisons"]
            if c["field"] == "market_cap"
        )
        # 1000 vs 1010 -> 1% -> CROSS_CHECK_OK
        self.assertEqual(comp["status"], "CROSS_CHECK_OK")

    def test_news_merges_and_dedupes(self):
        rss = Stub(
            get_news=lambda *a: live_envelope(
                "yahoo-rss",
                {
                    "items": [
                        {"title": "A", "url": "http://x/1"},
                        {"title": "B", "url": "http://x/2"},
                    ]
                },
            )
        )
        av = Stub(
            get_av_news=lambda *a: live_envelope(
                "alphavantage",
                {
                    "items": [
                        {"title": "B2", "url": "http://x/2"},
                        {"title": "C", "url": "http://x/3"},
                    ]
                },
            )
        )
        m = _manager(rss=rss, av=av)
        env = m.get_news(symbol="ACME", limit=10)
        urls = [i["url"] for i in env["data"]["items"]]
        self.assertEqual(urls, ["http://x/1", "http://x/2", "http://x/3"])
        self.assertEqual(env["data"]["items"][1]["via"], "yahoo-rss")

    def test_actions_merge_sources(self):
        acts = Stub(
            get_corporate_actions=lambda s: live_envelope(
                "yahoo-events",
                {"dividends": [{"date": 1, "amount": 2}], "splits": []},
                delayed=True,
            )
        )
        av = Stub(
            get_dividends=lambda s: live_envelope(
                "alphavantage",
                {"dividends": [{"date": "2024-01-01"}]},
                delayed=True,
            ),
            get_splits=lambda s: live_envelope(
                "alphavantage", {"splits": []}, delayed=True
            ),
        )
        m = _manager(acts=acts, av=av)
        env = m.get_actions("ACME")
        self.assertEqual(env["status"], "live")
        srcs = {d["source"] for d in env["data"]["dividends"]}
        self.assertEqual(srcs, {"yahoo-events", "alphavantage"})

    def test_all_missing_is_unavailable(self):
        m = _manager()
        env = m.get_quote("ZZZ")
        self.assertEqual(env["status"], "unavailable")
        env = m.get_earnings("ZZZ")
        self.assertEqual(env["status"], "unavailable")


class TestFailureIsolation(KeyedTestCase):
    """Phase 19: any single leg may die; the manager must stay honest.

    Fake key VALUES only flip the configured-flags so stub legs
    dispatch; stubs never touch the network.
    """

    def _boom(self, *a, **k):
        raise ConnectionError("upstream down")

    def test_yahoo_down_others_cover(self):
        yahoo = Stub(get_quote=self._boom)
        td = Stub(
            get_quote=lambda s: _q("twelvedata", price=50.0),
        )
        m = _manager(yahoo=yahoo, td=td)
        env = m.get_quote("X")
        self.assertIn(env["status"], ("live", "delayed"))
        self.assertEqual(env["data"]["price"], 50.0)

    def test_all_legs_raise_is_unavailable(self):
        yahoo = Stub(get_quote=self._boom)
        td = Stub(get_quote=self._boom)
        m = _manager(yahoo=yahoo, td=td)
        env = m.get_quote("X")
        # honest failure envelope: never a crash, never fake data
        self.assertIn(env["status"], ("unavailable", "error"))
        self.assertTrue(env.get("message"))
        self.assertIsNone(env.get("data"))

    def test_one_analytics_module_failure_isolated(self):
        # technicals functions degrade independently; compute_all still
        # returns what it can with Nones, never crashes.
        from services import technicals as t

        out = t.compute_all([None, None, None])
        self.assertIsNone(out["sma20"])
        self.assertIsNone(out["rsi14"])
        self.assertEqual(out["periods"], 0)


if __name__ == "__main__":
    unittest.main()
