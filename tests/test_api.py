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
        self.assertIn("not configured", body["message"].lower())

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

    def test_live_search_shape(self):
        if not _network_ok():
            self.skipTest("no network to upstream provider")
        status, body = _get(self.base, "/api/search?q=reliance")
        self.assertEqual(status, 200)
        self.assertTrue(body["data"]["results"])


if __name__ == "__main__":
    unittest.main()
