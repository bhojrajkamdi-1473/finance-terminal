"""Brutal Upstox audit tests — hard mode, no network.

Covers: init/capabilities, missing-token rollback, request
construction + auth header, redaction, verified-schema parsing
(quote V3 keyed by EXCHANGE:SYMBOL, candles, key-ratios, statements,
holdings, actions, news), malformed responses, the full error matrix
(401/403/429/404/UDAPI1206/transport/parse), instrument resolution,
routing (upstox-wins / yahoo-wins / discrepancy / single-source),
technical-engine validation on normalized bars, and security
(token never in envelopes/logs/messages).

Run: python -m pytest tests/test_upstox_audit.py -q
"""

import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from providers import upstox as _ux
from providers.base import live_envelope
from providers.orchestrator import CAPABILITIES, ProviderManager

TOKEN = "audit-token-0123456789abcdef"


def _resp(payload, code=200):
    body = json.dumps(payload).encode()
    m = mock.MagicMock()
    m.read.return_value = body
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


QUOTE_FIXTURE = {
    "status": "success",
    "data": {
        # NOTE: V3 keys are EXCHANGE:SYMBOL, not instrument keys.
        "NSE_EQ:TCS": {
            "instrument_token": "NSE_EQ|INE467B01029",
            "symbol": "TCS",
            "last_price": 2080.3,
            "net_change": -6.7,
            "prev_close_price": 2087.0,
            "average_price": 2081.1,
            "volume": 1724191,
            "ohlc": {
                "open": 2085.0,
                "high": 2090.0,
                "low": 2075.0,
                "close": 2080.0,
                "volume": 1724191,
                "ts": 1757000100000,
            },
            "depth": {"buy": [], "sell": []},
            "timestamp": "2026-09-04T15:22:31.099+05:30",
            "last_trade_time": "1757000551130",
            "year_high": 3350.0,
            "year_low": 1976.8,
        }
    },
}

CANDLES_FIXTURE = {
    "status": "success",
    "data": {
        "candles": [
            [
                1757000100000 + i * 86400000,
                100.0 + i,
                101.0 + i,
                99.0 + i,
                100.5 + i,
                1000 + i,
                0,
            ]
            for i in range(10)
        ]
    },
}

RATIOS_FIXTURE = {
    "status": "success",
    "data": [
        {"name": "P/E", "company_value": "20.15", "sector_value": "12.46"},
        {"name": "P/B", "company_value": "2.13", "sector_value": "1.53"},
        {"name": "ROA", "company_value": "4.39%", "sector_value": "7.54%"},
        {"name": "ROE", "company_value": "8.94%", "sector_value": "16.46%"},
        {"name": "ROCE", "company_value": "10.39%", "sector_value": "16.9%"},
        {"name": "EV/EBITDA", "company_value": "10.25", "sector_value": "6.94"},
    ],
}

INCOME_FIXTURE = {
    "status": "success",
    "data": {
        "type": "consolidated",
        "time_period": "yearly",
        "units_in": "crore",
        "income_statement": [
            {
                "category": "revenue",
                "history": [
                    {"value": 1000, "period": "Mar 2025", "change": "+7.0%"},
                    {"value": 900, "period": "Mar 2024"},
                ],
            },
            {
                "category": "net_profit",
                "history": [
                    {"value": 200, "period": "Mar 2025"},
                    {"value": 180, "period": "Mar 2024"},
                ],
            },
        ],
        "full_statement": [
            {
                "particular": "Total Revenue",
                "history": [
                    {"period": "Mar 2025", "value": 1000},
                    {"period": "Mar 2024", "value": 900},
                ],
            },
            {
                "particular": "Profit After Tax",
                "history": [
                    {"period": "Mar 2025", "value": 200},
                    {"period": "Mar 2024", "value": 180},
                ],
            },
            {
                "particular": "EPS - Basic",
                "history": [
                    {"period": "Mar 2025", "value": 51.47},
                    {"period": "Mar 2024", "value": 51.45},
                ],
            },
        ],
    },
}

HOLDINGS_FIXTURE = {
    "status": "success",
    "data": [
        {
            "category": "promoters",
            "history": [
                {"period": "Mar 2026", "value": 50.0},
                {"period": "Dec 2025", "value": 50.01},
            ],
        },
        {"category": "fii", "history": [{"period": "Mar 2026", "value": 18.67}]},
    ],
}

ACTIONS_FIXTURE = {
    "status": "success",
    "data": [
        {
            "name": "Dividend",
            "expiry_date": "14 Aug 2025",
            "amount": 5.5,
            "ratio": None,
            "event_details": [
                {"name": "Announcement date", "value": "25 Apr 2025"},
                {"name": "Dividend type", "value": "Final"},
            ],
        },
        {
            "name": "Split",
            "expiry_date": "01 Jan 2024",
            "amount": None,
            "ratio": "1:1",
            "event_details": [],
        },
    ],
}

NEWS_FIXTURE = {
    "status": "success",
    "data": {
        "NSE_EQ|INE467B01029": [
            {
                "heading": "TCS wins deal",
                "summary": "summary text",
                "thumbnail": "https://x/y.webp",
                "article_link": "https://upstox.com/news/a/article-1/",
                "published_time": 1776251261821,
            }
        ]
    },
    "metadata": {"page": {"page_number": 1}},
}


class _EnvGuard(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("UPSTOX_ANALYTICS_TOKEN")
        os.environ.pop("UPSTOX_ANALYTICS_TOKEN", None)
        # Provider cache is module-global: clear per test so mocked
        # transports are actually exercised (never mask errors as hits).
        with _ux._cache_lock:
            _ux._cache.clear()

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("UPSTOX_ANALYTICS_TOKEN", None)
        else:
            os.environ["UPSTOX_ANALYTICS_TOKEN"] = self._saved

    def _keyed(self):
        os.environ["UPSTOX_ANALYTICS_TOKEN"] = TOKEN


def _http_error(code, body=b"{}"):
    return urllib.error.HTTPError(
        "https://api.upstox.com/x", code, "err", {}, io.BytesIO(body)
    )


class ProviderContractTests(_EnvGuard):
    def test_capabilities(self):
        p = _ux.UpstoxProvider()
        for cap in ("quote", "history", "statements", "actions", "holdings", "news"):
            self.assertTrue(p.capabilities[cap], cap)
        for cap in ("estimates", "ipo", "macro", "technical", "chart", "search"):
            self.assertFalse(p.capabilities[cap], cap)
        self.assertTrue(CAPABILITIES["upstox"]["quote"])
        self.assertFalse(CAPABILITIES["upstox"]["estimates"])

    def test_missing_token_all_domains_unavailable(self):
        p = _ux.UpstoxProvider()
        for fn in (
            "get_quote",
            "get_historical_prices",
            "get_ratios",
            "get_shareholding",
            "get_corporate_actions",
        ):
            env = getattr(p, fn)("TCS.NS")
            self.assertEqual(env["status"], "unavailable", fn)
            self.assertIsNone(env["data"], fn)
        self.assertEqual(p.get_news("TCS.NS")["status"], "unavailable")
        self.assertEqual(p.get_financial_statements("TCS.NS")["status"], "unavailable")

    def test_request_construction_and_auth(self):
        self._keyed()
        seen = {}

        def fake_open(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            seen["accept"] = req.get_header("Accept")
            return _resp(QUOTE_FIXTURE)

        with mock.patch.object(_ux.urllib.request, "urlopen", fake_open):
            env = _ux.UpstoxProvider().get_quote("TCS.NS")
        self.assertEqual(env["status"], "delayed")
        self.assertIn("/v3/market-quote/quotes?instrument_key=", seen["url"])
        self.assertIn("NSE_EQ%7CINE467B01029", seen["url"])
        self.assertEqual(seen["auth"], f"Bearer {TOKEN}")
        self.assertEqual(seen["accept"], "application/json")

    def test_quote_parses_exchange_symbol_keying(self):
        self._keyed()
        with mock.patch.object(
            _ux.urllib.request, "urlopen", lambda *a, **k: _resp(QUOTE_FIXTURE)
        ):
            env = _ux.UpstoxProvider().get_quote("TCS.NS")
        q = env["data"]
        self.assertEqual(q["price"], 2080.3)
        self.assertEqual(q["change"], -6.7)  # authoritative net_change
        self.assertAlmostEqual(q["change_pct"], -6.7 / 2087.0 * 100)
        self.assertEqual(q["previous_close"], 2087.0)
        self.assertEqual(q["day_high"], 2090.0)
        self.assertEqual(q["day_low"], 2075.0)
        self.assertEqual(q["fifty_two_week_high"], 3350.0)
        self.assertEqual(q["fifty_two_week_low"], 1976.8)
        self.assertEqual(q["currency"], "INR")
        self.assertEqual(q["exchange"], "NSE")
        # Freshness pair: retrieval vs venue timestamps.
        self.assertIn("retrieved_at", env)
        self.assertEqual(env["source_timestamp"], "2026-09-04T15:22:31.099+05:30")

    def test_batch_parses_single_call(self):
        self._keyed()
        calls = []

        def fake_open(req, timeout=None):
            calls.append(req.full_url)
            return _resp(QUOTE_FIXTURE)

        with mock.patch.object(_ux.urllib.request, "urlopen", fake_open):
            out = _ux.UpstoxProvider().get_quotes_batch(["TCS.NS", "MSFT"])
        self.assertEqual(len(calls), 1)  # one upstream call, not N+1
        self.assertEqual(out["TCS.NS"]["data"]["price"], 2080.3)
        self.assertEqual(out["MSFT"]["status"], "unavailable")  # unmapped

    def test_history_normalizes_to_terminal_bars(self):
        self._keyed()
        with mock.patch.object(
            _ux.urllib.request, "urlopen", lambda *a, **k: _resp(CANDLES_FIXTURE)
        ):
            env = _ux.UpstoxProvider().get_historical_prices("TCS.NS", "1M", "1d")
        bars = env["data"]["bars"]
        self.assertEqual(len(bars), 10)
        self.assertEqual(set(bars[0]), {"t", "o", "h", "l", "c", "v"})
        self.assertLess(bars[0]["t"], bars[-1]["t"])  # sorted ascending
        self.assertEqual(bars[0]["c"], 100.5)

    def test_key_ratios_definitions(self):
        self._keyed()
        with mock.patch.object(
            _ux.urllib.request, "urlopen", lambda *a, **k: _resp(RATIOS_FIXTURE)
        ):
            env = _ux.UpstoxProvider().get_ratios("TCS.NS")
        d = env["data"]
        self.assertEqual(d["PERatio"], 20.15)
        self.assertEqual(d["ROE"], 8.94)  # % stripped to number
        self.assertEqual(d["ROCE"], 10.39)
        self.assertEqual(d["Currency"], "INR")
        self.assertIn("ROE", d["definitions"])
        self.assertEqual(d["sector_benchmarks"]["P/E"], 12.46)

    def test_income_statement_absolute_inr(self):
        self._keyed()
        with mock.patch.object(
            _ux.urllib.request, "urlopen", lambda *a, **k: _resp(INCOME_FIXTURE)
        ):
            env = _ux.UpstoxProvider().get_financial_statements("TCS.NS")
        d = env["data"]
        self.assertEqual(d["currency"], "INR")
        self.assertEqual(d["scope"], "consolidated")
        r25 = [r for r in d["reports"] if r["fiscalDateEnding"] == "2025-03-31"][0]
        self.assertEqual(r25["totalRevenue"], 1000 * 1e7)  # crore -> absolute
        self.assertEqual(r25["netIncome"], 200 * 1e7)
        self.assertEqual(r25["basicEPS"], 51.47)

    def test_holdings_canonical(self):
        self._keyed()
        with mock.patch.object(
            _ux.urllib.request, "urlopen", lambda *a, **k: _resp(HOLDINGS_FIXTURE)
        ):
            env = _ux.UpstoxProvider().get_shareholding("TCS.NS")
        own = env["data"]["ownership"]
        by_cat = {o["category"]: o for o in own}
        self.assertEqual(by_cat["Promoters"]["percentage"], 50.0)
        self.assertEqual(by_cat["FII"]["percentage"], 18.67)
        self.assertEqual(by_cat["Promoters"]["holding_date"], "Mar 2026")

    def test_actions_canonical(self):
        self._keyed()
        with mock.patch.object(
            _ux.urllib.request, "urlopen", lambda *a, **k: _resp(ACTIONS_FIXTURE)
        ):
            env = _ux.UpstoxProvider().get_corporate_actions("TCS.NS")
        self.assertEqual(env["data"]["dividends"][0]["amount"], 5.5)
        self.assertEqual(env["data"]["dividends"][0]["date"], "14 Aug 2025")
        sp = env["data"]["splits"][0]
        self.assertEqual((sp["numerator"], sp["denominator"]), (1.0, 1.0))

    def test_news_canonical_and_window(self):
        self._keyed()
        with mock.patch.object(
            _ux.urllib.request, "urlopen", lambda *a, **k: _resp(NEWS_FIXTURE)
        ):
            env = _ux.UpstoxProvider().get_news("TCS.NS")
        it = env["data"]["items"][0]
        self.assertEqual(it["title"], "TCS wins deal")
        self.assertEqual(it["url"], "https://upstox.com/news/a/article-1/")
        self.assertTrue(it["published_at"].startswith("2026-"))
        self.assertIn("7 days", env["window"])
        # positions/holdings categories are account-bound: never requested.
        # (get_news only ever calls category=instrument_keys.)


class ErrorMatrixTests(_EnvGuard):
    def _quote_with(self, side_effect):
        self._keyed()
        with mock.patch.object(_ux.urllib.request, "urlopen", side_effect=side_effect):
            return _ux.UpstoxProvider().get_quote("TCS.NS")

    def test_401_is_auth_error(self):
        env = self._quote_with(_http_error(401, b'{"status":"error"}'))
        self.assertEqual(env["status"], "error")
        self.assertEqual(env["code"], "AUTH")
        self.assertNotIn(TOKEN, json.dumps(env))

    def test_403_is_auth_error(self):
        env = self._quote_with(_http_error(403, b"forbidden"))
        self.assertEqual(env["code"], "AUTH")

    def test_429_is_rate_limited(self):
        env = self._quote_with(_http_error(429, b"slow down"))
        self.assertEqual(env["status"], "rate_limited")
        self.assertEqual(env["code"], "RATE_LIMIT")

    def test_404_is_unavailable(self):
        env = self._quote_with(_http_error(404, b"nope"))
        self.assertEqual(env["status"], "unavailable")

    def test_udapi_invalid_isin_is_unavailable(self):
        payload = {
            "status": "error",
            "errors": [{"errorCode": "UDAPI1206"}],
            "message": "Invalid ISIN",
        }
        with mock.patch.object(
            _ux.urllib.request, "urlopen", return_value=_resp(payload)
        ):
            self._keyed()
            env = _ux.UpstoxProvider().get_ratios("TCS.NS")
        self.assertEqual(env["status"], "unavailable")

    def test_transport_failure_is_error_not_crash(self):
        env = self._quote_with(urllib.error.URLError("connection reset"))
        self.assertEqual(env["status"], "error")
        self.assertNotIn(TOKEN, json.dumps(env))

    def test_malformed_json_is_error(self):
        m = mock.MagicMock()
        m.read.return_value = b"not json{{"
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        env = self._quote_with(m)
        self.assertEqual(env["status"], "error")

    def test_empty_quote_is_unavailable(self):
        self._keyed()
        with mock.patch.object(
            _ux.urllib.request,
            "urlopen",
            lambda *a, **k: _resp({"status": "success", "data": {}}),
        ):
            env = _ux.UpstoxProvider().get_quote("TCS.NS")
        self.assertEqual(env["status"], "unavailable")

    def test_failures_are_not_cached(self):
        self._keyed()
        calls = []

        def flaky(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.URLError("down")
            return _resp(QUOTE_FIXTURE)

        with mock.patch.object(_ux.urllib.request, "urlopen", flaky):
            p = _ux.UpstoxProvider()
            # unique cache key per symbol variant avoided: same symbol,
            # failure first (uncached) then success.
            e1 = p.get_quote("TCS.NS")
            e2 = p.get_quote("TCS.NS")
        self.assertEqual(e1["status"], "error")
        self.assertEqual(e2["status"], "delayed")
        self.assertEqual(len(calls), 2)


class InstrumentResolutionTests(unittest.TestCase):
    def test_nse_bse_index(self):
        self.assertEqual(_ux.instrument_key("TCS.NS"), "NSE_EQ|INE467B01029")
        self.assertEqual(_ux.instrument_key("tcs.ns"), "NSE_EQ|INE467B01029")
        self.assertEqual(_ux.instrument_key("TCS.BO"), "BSE_EQ|INE467B01029")
        self.assertEqual(_ux.instrument_key("^NSEI"), "NSE_INDEX|Nifty 50")
        self.assertEqual(_ux.instrument_key("^BSESN"), "BSE_INDEX|SENSEX")

    def test_unknown_and_global_pass_through(self):
        for s in (
            "MSFT",
            "AAPL",
            "BTC-USD",
            "INR=X",
            "UNKNOWNCO.NS",
            "^GSPC",
            "FOO.BAR",
        ):
            self.assertIsNone(_ux.instrument_key(s), s)
            self.assertIsNone(_ux.isin_for(s), s)

    def test_isin_format_validated(self):
        self.assertEqual(_ux.isin_for("RELIANCE.NS"), "INE002A01018")
        with mock.patch.dict(_ux.EQUITY_ISIN, {"BAD": "NOTANISIN"}):
            self.assertIsNone(_ux.instrument_key("BAD.NS"))

    def test_period_labels(self):
        self.assertEqual(_ux.period_label_to_date("Mar 2025"), "2025-03-31")
        self.assertEqual(_ux.period_label_to_date("Feb 2024"), "2024-02-29")
        self.assertIsNone(_ux.period_label_to_date("FY25"))
        self.assertIsNone(_ux.period_label_to_date(""))


class _Stub:
    def __init__(self, **methods):
        self._methods = methods
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def fn(*a, **k):
            self.calls.append(name)
            return self._methods[name](*a, **k)

        return fn


class RoutingTests(_EnvGuard):
    def _manager(self, **legs):
        return ProviderManager(
            yahoo=legs.get("yahoo"),
            indian=legs.get("indian"),
            twelvedata=legs.get("td"),
            alphavantage=legs.get("av"),
            upstox=legs.get("upstox"),
            news_rss=legs.get("rss"),
            actions_yahoo=legs.get("acts"),
            yahoo_fund=legs.get("yf"),
        )

    def _q(self, source, price):
        return live_envelope(source, {"price": price, "currency": "INR"}, delayed=True)

    def test_upstox_wins_quote_when_live(self):
        m = self._manager(
            upstox=_Stub(get_quote=lambda s: self._q("upstox", 100.0)),
            yahoo=_Stub(get_quote=lambda s: self._q("yahoo", 100.5)),
        )
        env = m.get_quote("TCS.NS")
        self.assertEqual(env["reconciliation"]["primary"], "upstox")
        self.assertEqual(env["data"]["price"], 100.0)  # never averaged

    def test_yahoo_wins_when_upstox_passes_through(self):
        from providers.base import unavailable as _un

        m = self._manager(
            upstox=_Stub(get_quote=lambda s: _un("upstox", "pass")),
            yahoo=_Stub(get_quote=lambda s: self._q("yahoo", 50.0)),
        )
        env = m.get_quote("MSFT")
        self.assertEqual(env["data"]["price"], 50.0)
        self.assertEqual(env["reconciliation"]["primary"], "yahoo")

    def test_discrepancy_preserved_not_averaged(self):
        m = self._manager(
            upstox=_Stub(get_quote=lambda s: self._q("upstox", 100.0)),
            yahoo=_Stub(get_quote=lambda s: self._q("yahoo", 110.0)),
        )
        env = m.get_quote("TCS.NS")
        summary = env["reconciliation"]["summary"]
        self.assertEqual(summary["discrepancies"], 1)
        self.assertNotEqual(env["data"]["price"], 105.0)

    def test_single_source_when_only_upstox(self):
        m = self._manager(upstox=_Stub(get_quote=lambda s: self._q("upstox", 100.0)))
        env = m.get_quote("TCS.NS")
        comps = {c["field"]: c["status"] for c in env["reconciliation"]["comparisons"]}
        self.assertEqual(comps["price"], "SINGLE_SOURCE")

    def test_rollback_no_token_yahoo_serves(self):
        # UPSTOX_ANALYTICS_TOKEN absent: real provider passes through,
        # orchestrator still answers from Yahoo (app keeps working).
        m = self._manager(
            upstox=_ux.UpstoxProvider(),
            yahoo=_Stub(get_quote=lambda s: self._q("yahoo", 77.0)),
        )
        env = m.get_quote("TCS.NS")
        self.assertIn(env["status"], ("live", "delayed"))
        self.assertEqual(env["data"]["price"], 77.0)

    def test_upstox_news_merges_into_pipeline(self):
        # Merge loop only consumes status=live legs (matches real legs).
        rss = _Stub(
            get_news=lambda s, t, lim: live_envelope(
                "yahoo-rss",
                {
                    "items": [
                        {"title": "TCS results", "url": "https://x/1", "summary": "s"}
                    ]
                },
            )
        )
        # Distinct story so the same-story dedup keeps both rows.
        up = _Stub(
            get_news=lambda s, t, lim: live_envelope(
                "upstox",
                {
                    "items": [
                        {
                            "title": "TCS opens European innovation hub",
                            "url": "https://x/2",
                            "summary": "s",
                        }
                    ]
                },
            )
        )
        # Readiness gate needs a configured token (boolean only).
        os.environ["UPSTOX_ANALYTICS_TOKEN"] = TOKEN
        try:
            m = self._manager(rss=rss, upstox=up)
            env = m.get_news("TCS.NS", None, 10)
        finally:
            os.environ.pop("UPSTOX_ANALYTICS_TOKEN", None)
        self.assertEqual(env["status"], "live")
        urls = [i["url"] for i in env["data"]["items"]]
        self.assertIn("https://x/2", urls)
        self.assertIn("upstox", str(env["providers_queried"]))


class TechnicalValidationTests(unittest.TestCase):
    def test_engine_consumes_upstox_bars(self):
        from services import technicals as _t

        closes = [100.0 + i for i in range(10)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        snap = _t.compute_all(closes, highs, lows, None, source="test")
        self.assertIn("sma20", snap)
        # Identical inputs -> identical outputs (provider never computes).
        snap2 = _t.compute_all(closes, highs, lows, None, source="other")
        self.assertEqual(snap["sma20"], snap2["sma20"])
        self.assertEqual(snap["rsi14"], snap2["rsi14"])

    def test_upstox_bars_shape_matches_engine_input(self):
        bars = [
            {"t": 1 + i, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10}
            for i in range(250)
        ]
        closes = [b["c"] for b in bars]
        self.assertEqual(len(closes), 250)
        from services import technicals as _t

        self.assertIn("phase", _t.phase(closes))


class SecurityTests(_EnvGuard):
    def test_token_never_in_envelopes(self):
        self._keyed()
        with mock.patch.object(
            _ux.urllib.request, "urlopen", lambda *a, **k: _resp(QUOTE_FIXTURE)
        ):
            p = _ux.UpstoxProvider()
            for env in (
                p.get_quote("TCS.NS"),
                p.get_historical_prices("TCS.NS"),
                p.get_ratios("TCS.NS"),
                p.get_shareholding("TCS.NS"),
                p.get_corporate_actions("TCS.NS"),
                p.get_news("TCS.NS"),
            ):
                self.assertNotIn(TOKEN, json.dumps(env))

    def test_safe_headers_carry_no_credential(self):
        h = _ux._headers()
        self.assertNotIn(TOKEN, json.dumps(h))
        self.assertEqual(h["Authorization"], "Bearer REDACTED")

    def test_error_bodies_scrubbed(self):
        self._keyed()
        leak = _http_error(500, f"oops {TOKEN} leaked".encode())
        with mock.patch.object(_ux.urllib.request, "urlopen", side_effect=leak):
            env = _ux.UpstoxProvider().get_quote("TCS.NS")
        self.assertNotIn(TOKEN, json.dumps(env))

    def test_status_exposes_boolean_only(self):
        self._keyed()
        st = _ux.UpstoxProvider().status()
        self.assertNotIn(TOKEN, json.dumps(st))
        self.assertTrue(st["key_configured"])


if __name__ == "__main__":
    unittest.main()
