"""Yahoo fundamentals leg (free, no key) + market classifier + MF provider.

HTTP is stubbed: no network. Run: python -m unittest tests.test_freelegs -v
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from providers import mutualfunds as mf
from providers import yahoo_fundamentals as yf
from providers.orchestrator import _classify_market


def _ts_point(date, raw):
    return {"asOfDate": date, "periodType": "12M",
            "reportedValue": {"raw": raw, "fmt": str(raw)}}


def _ts_payload(entries):
    # entries: [(datakey, [(date, raw), ...]), ...]
    result = []
    for key, points in entries:
        result.append(
            {
                "meta": {},
                "timestamp": [p[0] for p in points],
                key: [{"asOfDate": d, "periodType": "12M",
                       "reportedValue": {"raw": v, "fmt": str(v)}}
                      for d, v in points],
            }
        )
    return {"timeseries": {"result": result}}


class YahooStatementsTest(unittest.TestCase):
    def test_income_maps_to_av_keys(self):
        payload = _ts_payload([
            ("annualTotalRevenue", [("2026-03-31", 1000.0), ("2025-03-31", 900.0)]),
            ("annualNetIncome", [("2026-03-31", 100.0), ("2025-03-31", 90.0)]),
            ("annualDilutedEPS", [("2026-03-31", 10.0)]),
        ])
        with mock.patch.object(yf, "_http_json", return_value=payload):
            with mock.patch.object(
                yf.YahooFundamentalsProvider, "_currency",
                return_value="INR",
            ):
                env = yf.YahooFundamentalsProvider().get_financial_statements(
                    "TCS.NS", "income", "annual"
                )
        self.assertEqual(env["status"], "live")
        reps = env["data"]["reports"]
        self.assertEqual(len(reps), 2)
        self.assertEqual(reps[0]["fiscalDateEnding"], "2026-03-31")
        self.assertEqual(reps[0]["totalRevenue"], 1000.0)
        self.assertEqual(reps[0]["netIncome"], 100.0)
        self.assertEqual(env["data"]["currency"], "INR")

    def test_empty_timeseries_is_honest(self):
        with mock.patch.object(yf, "_http_json", return_value={"timeseries": {"result": []}}):
            env = yf.YahooFundamentalsProvider().get_financial_statements(
                "ZZZ.NS", "income", "annual"
            )
        self.assertEqual(env["status"], "unavailable")
        self.assertIsNone(env["data"])

    def test_ratios_percent_convention(self):
        qs = {
            "price": {"longName": "TCS", "exchangeName": "NSE",
                      "currency": "INR", "marketCap": {"raw": 1000.0}},
            "summaryDetail": {"trailingPE": {"raw": 28.0},
                              "dividendYield": {"raw": 0.0175},
                              "fiftyTwoWeekHigh": {"raw": 120.0},
                              "fiftyTwoWeekLow": {"raw": 80.0}},
            "defaultKeyStatistics": {"trailingEps": {"raw": 10.0},
                                     "bookValue": {"raw": 5.0}},
            "financialData": {"returnOnEquity": {"raw": 0.148},
                              "profitMargins": {"raw": 0.10}},
        }
        with mock.patch.object(
            yf.YahooFundamentalsProvider, "_quote_summary", return_value=qs
        ):
            env = yf.YahooFundamentalsProvider().get_ratios("TCS.NS")
        self.assertEqual(env["status"], "live")
        self.assertEqual(env["data"]["PERatio"], 28.0)
        self.assertEqual(env["data"]["ROE"], 14.8)  # fraction -> AV percent
        self.assertEqual(env["data"]["DividendYield"], 1.75)

    def test_earnings_chart_rows(self):
        qs = {"earnings": {"earningsChart": {"quarterly": [
            {"date": "4Q2025", "actual": {"raw": 2.1}, "estimate": {"raw": 2.0}},
            {"date": "1Q2026", "actual": {"raw": 2.5}, "estimate": {"raw": 2.4}},
        ]}}}
        with mock.patch.object(
            yf.YahooFundamentalsProvider, "_quote_summary", return_value=qs
        ):
            env = yf.YahooFundamentalsProvider().get_earnings("AAPL")
        self.assertEqual(env["status"], "live")
        self.assertEqual(len(env["data"]["quarterly"]), 2)
        self.assertEqual(env["data"]["quarterly"][0]["reportedEPS"], 2.5)


class MarketClassifierTest(unittest.TestCase):
    def test_indian(self):
        self.assertEqual(
            _classify_market("TCS.NS", {"currency": "INR"})["id"], "IN")
        self.assertEqual(
            _classify_market("^NSEI", {})["id"], "IN")
        self.assertEqual(
            _classify_market("RELIANCE.NS", {"exchange": "National Stock Exchange"})["id"],
            "IN",
        )

    def test_us(self):
        self.assertEqual(
            _classify_market("META", {"exchange": "NasdaqGS", "currency": "USD"})["id"],
            "US",
        )
        self.assertEqual(
            _classify_market("AAPL", {"exchange": "NYSE", "currency": "USD"})["id"], "US"
        )

    def test_global(self):
        self.assertEqual(_classify_market("GC=F", {"currency": "USD"})["id"], "GLOBAL")
        self.assertEqual(_classify_market("BTC-USD", {})["id"], "GLOBAL")
        self.assertEqual(_classify_market("INR=X", {})["id"], "GLOBAL")


class MutualFundTest(unittest.TestCase):
    def test_search_maps_symbols(self):
        payload = [{"schemeCode": 120847, "schemeName": "Quant Small Cap Fund"}]
        with mock.patch.object(mf, "_http_json", return_value=payload):
            env = mf.MutualFundProvider().search_schemes("quant small")
        self.assertIn(env["status"], ("live", "delayed"))
        self.assertEqual(env["data"]["results"][0]["symbol"], "MF:120847")

    def test_nav_history_sorted_and_stamped(self):
        payload = {
            "status": "SUCCESS",
            "meta": {"scheme_name": "Demo Fund", "fund_house": "Demo AMC"},
            "data": [
                {"date": "28-01-2026", "nav": "100.5"},
                {"date": "27-01-2026", "nav": "99.5"},
            ],
        }
        with mock.patch.object(mf, "_http_json", return_value=payload):
            env = mf.MutualFundProvider().get_nav_history(1)
        self.assertIn(env["status"], ("live", "delayed"))
        self.assertEqual(env["data"]["latest_nav"], 100.5)
        self.assertEqual(env["data"]["latest_date"], "28-01-2026")
        self.assertEqual(env["timeliness"], "END-OF-DAY")

    def test_bad_code_honest(self):
        env = mf.MutualFundProvider().get_nav_history("nope")
        self.assertEqual(env["status"], "unavailable")


class FreeEndpointsTest(unittest.TestCase):
    """Endpoint shapes for indicators + MF (tolerant of upstream)."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(prefix="freelegs-test-")
        os.environ["TERMINAL_DB"] = os.path.join(tmp, "test.db")
        from server import Handler

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=60) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_indicators_shape(self):
        status, body = self._get("/api/indicators")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        symbols = {i["symbol"] for i in body["items"]}
        for required in ("GC=F", "SI=F", "CL=F", "INR=X", "^INDIAVIX", "BTC-USD"):
            self.assertIn(required, symbols)
        for item in body["items"]:
            for key in ("symbol", "label", "kind", "status", "price",
                        "change_pct", "currency", "as_of", "market"):
                self.assertIn(key, item)
            self.assertIn(item["market"]["id"], ("IN", "US", "GLOBAL"))

    def test_quote_carries_market(self):
        for symbol, market in (("TCS.NS", "IN"), ("META", "US"), ("GC=F", "GLOBAL")):
            status, body = self._get(f"/api/quote?symbol={symbol}")
            self.assertEqual(status, 200)
            self.assertEqual((body.get("market") or {}).get("id"), market)

    def test_mf_search_contract(self):
        # limit validation would 400 on bad input; empty query is honest miss
        status, body = self._get("/api/mf/search?q=")
        self.assertEqual(status, 200)
        self.assertIn(body["status"], ("unavailable", "live", "delayed", "error"))

    def test_providers_status_lists_free_legs(self):
        status, body = self._get("/api/providers")
        self.assertEqual(status, 200)
        ids = {p["id"] for p in body["providers"]}
        self.assertIn("yahoo-fundamentals", ids)
        self.assertIn("mfapi", ids)


if __name__ == "__main__":
    unittest.main()
