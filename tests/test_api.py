"""Integration tests: API routes, validation, storage, static serving.

Local-only tests run without network. Live-provider tests are skipped
when the upstream is unreachable (they assert envelope shape only —
never specific prices).
Run: python -m unittest discover -s tests -v
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from server import Handler


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def _post(base, path, data):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read().decode())


def _delete(base, path):
    req = urllib.request.Request(base + path, method="DELETE")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read().decode())


def _network_ok():
    try:
        urllib.request.urlopen("https://query1.finance.yahoo.com/", timeout=8)
        return True
    except Exception:
        return False


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(prefix="terminal-test-")
        os.environ["TERMINAL_DB"] = os.path.join(tmp, "test.db")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    # -- health / static ---------------------------------------------
    def test_health(self):
        status, body = _get(self.base, "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_terminal_index_served(self):
        with urllib.request.urlopen(self.base + "/terminal/", timeout=10) as r:
            self.assertEqual(r.status, 200)
            html = r.read().decode()
        self.assertIn("FINANCE TERMINAL", html)

    def test_terminal_redirect(self):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/terminal")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 302)

    # -- validation without network -----------------------------------
    def test_search_empty_query_unavailable(self):
        status, body = _get(self.base, "/api/search?q=")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unavailable")

    def test_history_bad_range(self):
        status, body = _get(self.base, "/api/history?symbol=AAPL&range=9Z")
        self.assertEqual(status, 502)
        self.assertEqual(body["status"], "error")

    def test_range_map_uses_yahoo_month_codes(self):
        # Regression: "1M" must map to Yahoo "1mo" (month), NOT "1m"
        # (one minute) — previously returned a single bar for 1M windows.
        from providers.yahoo import ALLOWED_RANGES, RANGE_MAP

        self.assertEqual(
            set(RANGE_MAP),
            {"1D", "5D", "1M", "3M", "6M", "1Y", "2Y", "5Y", "MAX"},
        )
        self.assertEqual(ALLOWED_RANGES, set(RANGE_MAP))
        for ui, yahoo in RANGE_MAP.items():
            self.assertIn(
                yahoo,
                {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"},
                f"UI range {ui} maps to invalid Yahoo range '{yahoo}'",
            )

    def test_history_empty_symbol(self):
        status, body = _get(self.base, "/api/history?symbol=&range=1M")
        # empty symbol -> upstream error envelope or unavailable; never 500
        self.assertIn(status, (200, 502))
        self.assertIn(body["status"], ("unavailable", "error"))

    def test_fundamentals_no_key_unless_configured(self):
        if os.environ.get("ALPHA_VANTAGE_API_KEY") or os.environ.get(
            "FUNDAMENTALS_API_KEY"
        ):
            self.skipTest("fundamentals key configured; stub test N/A")
        status, body = _get(self.base, "/api/ratios?symbol=AAPL")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unavailable")
        self.assertIn("alpha_vantage_api_key", body["message"].lower())

    def test_estimates_always_unavailable(self):
        status, body = _get(self.base, "/api/estimates?symbol=AAPL")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unavailable")

    # -- watchlist CRUD -------------------------------------------------
    def test_watchlist_crud(self):
        status, body = _post(
            self.base, "/api/watchlist", {"symbol": "TCS.NS", "name": "TCS"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        status, body = _get(self.base, "/api/watchlist")
        self.assertTrue(any(i["symbol"] == "TCS.NS" for i in body["items"]))
        status, body = _delete(self.base, "/api/watchlist?symbol=TCS.NS")
        self.assertTrue(body["ok"])
        status, body = _get(self.base, "/api/watchlist")
        self.assertFalse(any(i["symbol"] == "TCS.NS" for i in body["items"]))

    def test_watchlist_rejects_empty(self):
        try:
            _post(self.base, "/api/watchlist", {"symbol": ""})
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
        else:
            self.fail("expected 400")

    # -- portfolio --------------------------------------------------------
    def test_portfolio_upsert_and_math(self):
        _post(
            self.base,
            "/api/portfolio",
            {"symbol": "TEST.NS", "quantity": 10, "avg_price": 100},
        )
        status, body = _get(self.base, "/api/portfolio")
        self.assertEqual(status, 200)
        holding = next((p for p in body["positions"] if p["symbol"] == "TEST.NS"), None)
        self.assertIsNotNone(holding)
        self.assertEqual(holding["invested_value"], 1000.0)
        _delete(self.base, "/api/portfolio?symbol=TEST.NS")

    def test_portfolio_rejects_negative(self):
        try:
            _post(
                self.base,
                "/api/portfolio",
                {"symbol": "X", "quantity": -1, "avg_price": 5},
            )
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
        else:
            self.fail("expected 400")

    # -- research ----------------------------------------------------------
    def test_research_save_list_delete(self):
        status, body = _post(
            self.base,
            "/api/research",
            {"symbol": "INFY.NS", "section": "thesis", "title": "t", "body": "b"},
        )
        self.assertTrue(body["ok"])
        nid = body["item"]["id"]
        status, body = _get(self.base, "/api/research?symbol=INFY.NS")
        self.assertEqual(status, 200)
        self.assertTrue(any(n["id"] == nid for n in body["notes"]))
        _delete(self.base, f"/api/research?id={nid}")

    def test_research_rejects_bad_section(self):
        try:
            _post(
                self.base,
                "/api/research",
                {"symbol": "X", "section": "nope", "title": "", "body": ""},
            )
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
        else:
            self.fail("expected 400")

    # -- live provider shape (network-gated) ---------------------------------
    def test_live_quote_envelope_shape(self):
        if not _network_ok():
            self.skipTest("no network to upstream provider")
        status, body = _get(self.base, "/api/quote?symbol=AAPL")
        self.assertEqual(status, 200)
        self.assertIn(body["status"], ("live", "delayed"))
        self.assertIsInstance(body["data"]["price"], (int, float))

    def test_quote_carries_timeliness_and_extended_fields(self):
        if not _network_ok():
            self.skipTest("no network to upstream provider")
        _status, body = _get(self.base, "/api/quote?symbol=RELIANCE.NS")
        self.assertIn(
            body.get("timeliness"),
            ("REAL-TIME", "DELAYED", "END-OF-DAY", "CALCULATED", "UNAVAILABLE"),
        )
        for field in ("volume", "day_high", "day_low", "previous_close"):
            self.assertIn(field, body.get("data", {}))
        self.assertIn(body.get("served_from"), ("provider", "cache"))

    def test_providers_endpoint_structure(self):
        status, body = _get(self.base, "/api/providers")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        ids = [p["id"] for p in body["providers"]]
        for want in (
            "yahoo",
            "indian-api",
            "alphavantage",
            "twelvedata",
            "stooq",
            "nse",
            "tradingview",
        ):
            self.assertIn(want, ids)
        # key values must never leak
        raw = json.dumps(body)
        self.assertNotIn("TWELVE_DATA_API_KEY=", raw)
        # capabilities declared for every provider
        for p in body["providers"]:
            self.assertIn("capabilities", p)
        # chain routing published
        self.assertIn("quote", body.get("chain", {}))
        self.assertIn("history", body.get("chain", {}))

    def test_root_serves_terminal_portfolio_preserved(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("FINANCE TERMINAL", r.read().decode())
        with urllib.request.urlopen(self.base + "/portfolio/", timeout=10) as r:
            self.assertEqual(r.status, 200)

    def test_unknown_paths_404(self):
        for path in ("/nope-xyz", "/api/nope-xyz"):
            try:
                urllib.request.urlopen(self.base + path, timeout=10)
            except urllib.error.HTTPError as e:
                self.assertIn(e.code, (404,))
            else:
                self.fail(f"expected 404 for {path}")

    def test_research_links_endpoint(self):
        import json as _json

        status, body = _get(self.base, "/api/research-links?symbol=TATASTEEL.NS")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        by_id = {x["id"]: x for x in body["official"] + body["research"]}
        self.assertIn("screener.in/company/TATASTEEL/", by_id["screener"]["url"])
        for x in body["official"] + body["research"]:
            if x["url"]:
                self.assertTrue(x["url"].startswith("https://"))
        raw = _json.dumps(body)
        for token in ("API_KEY", "apikey", "secret"):
            self.assertNotIn(token, raw)

    def test_research_links_requires_symbol(self):
        status, _body = _get(self.base, "/api/research-links?symbol=")
        self.assertEqual(status, 400)

    def test_earnings_ipo_macro_technical_unavailable_without_key(self):
        if os.environ.get("ALPHA_VANTAGE_API_KEY") or os.environ.get(
            "FUNDAMENTALS_API_KEY"
        ):
            self.skipTest("fundamentals key configured")
        for path in (
            "/api/earnings?symbol=AAPL",
            "/api/ipo",
            "/api/macro?indicator=GDP",
        ):
            status, body = _get(self.base, path)
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "unavailable")
        # technical needs history; bogus symbol -> unavailable, never fake
        status, body = _get(self.base, "/api/technical?symbol=ZZZ_NOPE_123")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unavailable")

    def test_technical_missing_symbol_400(self):
        status, _body = _get(self.base, "/api/technical")
        self.assertEqual(status, 400)

    def test_screener_new_filters_validate(self):
        status, _body = _get(self.base, "/api/screener?above_sma=99")
        self.assertEqual(status, 400)
        status, body = _get(self.base, "/api/screener?symbols=AAPL&min_volume=1")
        self.assertEqual(status, 200)
        self.assertIn("volume", body.get("backed_by", []))

    def test_screener_rule_ops_and_sort(self):
        base = "/api/screener?symbols=AAPL,MSFT,NVDA,TCS.NS,INFY.NS"
        _, plain = _get(self.base, base)
        n_plain = len(plain.get("results", []))
        self.assertGreater(n_plain, 0)
        # a restrictive rule set must shrink (never grow) the result set
        _, filt = _get(self.base, base + "&f=price:gt:100000")
        self.assertLessEqual(len(filt.get("results", [])), n_plain)
        # invalid operator rejected, not silently ignored
        status, _body = _get(self.base, base + "&f=price:approx:10")
        self.assertEqual(status, 400)
        # sort changes order deterministically
        _, asc = _get(self.base, base + "&sort_by=price&sort_dir=asc")
        _, desc = _get(self.base, base + "&sort_by=price&sort_dir=desc")
        if len(asc.get("results", [])) >= 2:
            a = [r["symbol"] for r in asc["results"]]
            d = [r["symbol"] for r in desc["results"]]
            self.assertEqual(a, list(reversed(d)))
        # coverage is stated honestly
        self.assertIn("coverage", plain)
        self.assertIn("universe", plain)

    def test_compare_matrix_real_values(self):
        for s in ("TCS.NS", "INFY.NS", "HDFCBANK.NS", "RELIANCE.NS"):
            status, body = _get(self.base, "/api/quote?symbol=" + s)
            self.assertEqual(status, 200)
            if body.get("status") in ("live", "delayed"):
                self.assertIsInstance(
                    (body.get("data") or {}).get("price"), (int, float)
                )
        status, body = _get(self.base, "/api/ratios?symbol=TCS.NS")
        self.assertEqual(status, 200)
        # No-auth Indian leg covers NSE ratios without keys: live with
        # real reported fields, never fabricated. (Alpha Vantage key
        # only gates AV-specific domains now.)
        if body.get("status") in ("live", "delayed"):
            data = body.get("data") or {}
            for key in ("MarketCapitalization", "PERatio", "EPS"):
                self.assertIsInstance(data.get(key), (int, float))

    def test_macro_rejects_unknown_indicator(self):
        status, body = _get(self.base, "/api/macro?indicator=NOPE")
        # without key: unavailable (key gate first); with key: 502 error
        self.assertIn(status, (200, 502))
        self.assertIn(body["status"], ("unavailable", "error"))

    def test_live_search_shape(self):
        if not _network_ok():
            self.skipTest("no network to upstream provider")
        status, body = _get(self.base, "/api/search?q=reliance")
        self.assertEqual(status, 200)
        self.assertTrue(body["data"]["results"])

    def test_analytics_endpoint_shape(self):
        # NETWORK_GATED: needs Yahoo history; asserts shape, never values.
        if not _network_ok():
            self.skipTest("no network to upstream provider")
        status, body = _get(self.base, "/api/analytics?symbol=RELIANCE.NS")
        self.assertEqual(status, 200)
        if body.get("status") != "live":
            self.assertEqual(body["status"], "unavailable")
            return
        self.assertEqual(body.get("timeliness"), "CALCULATED")
        d = body.get("data") or {}
        for key in (
            "phase",
            "relative_strength",
            "vcp",
            "breakout",
            "trend_template",
            "risk_reward",
            "score",
            "regime",
        ):
            self.assertIn(key, d, key)
        self.assertEqual(d["relative_strength"].get("benchmark"), "^NSEI")

    def test_analytics_missing_symbol_400(self):
        status, _body = _get(self.base, "/api/analytics")
        self.assertEqual(status, 400)

    def test_tradingview_adapter_gated(self):
        from providers.tradingview import TradingViewProvider, authorization_scope

        p = TradingViewProvider()
        self.assertTrue(p.capabilities.get("chart"))
        self.assertFalse(p.capabilities.get("quote"))
        env = p.get_quote("AAPL")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("TRADINGVIEW_ENABLED", env["message"])
        env = p.search("x")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("visualization", authorization_scope())

    def test_failure_isolation_quote_survives_dead_legs(self):
        # Bogus symbol: every leg misses honestly, server stays 200,
        # envelope explains — never a crash, never fake data.
        status, body = _get(self.base, "/api/quote?symbol=ZZZ_NOPE_123")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unavailable")
        self.assertTrue(body.get("message"))


if __name__ == "__main__":
    unittest.main()
