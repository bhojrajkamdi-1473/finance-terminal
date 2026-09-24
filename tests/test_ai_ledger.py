"""AI run ledger tests: audit trail, budget guard, runs endpoint."""

import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from services.ai_research import ledger as L


def _memdb():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


class LedgerTest(unittest.TestCase):
    def test_record_and_recent(self):
        conn = _memdb()
        rid = L.record_run(conn, ticker="tcs.ns", depth="standard", sections=["a"],
                           model="m", provider="p", context_hash="h",
                           stages={"market": "done"}, grounding={"market": "grounded"},
                           provider_count=3, llm_backed=False)
        self.assertIsNotNone(rid)
        runs = L.recent_runs(conn, "TCS.NS")
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual(r["ticker"], "TCS.NS")
        self.assertEqual(r["sections"], ["a"])
        self.assertFalse(r["llm_backed"])
        # metadata only: no report bodies, no secrets
        blob = json.dumps(runs)
        self.assertNotIn("sk-", blob)
        self.assertNotIn("summary", blob)

    def test_budget_counts_today(self):
        conn = _memdb()
        self.assertEqual(L.count_today(conn), 0)
        L.record_run(conn, ticker="A", depth="standard", sections=[], model="",
                     provider="", context_hash="", stages={}, grounding={},
                     provider_count=0, llm_backed=False)
        self.assertEqual(L.count_today(conn), 1)

    def test_record_never_raises(self):
        class Broken:
            def executescript(self, *a):
                raise RuntimeError("disk gone")

            def execute(self, *a):
                raise RuntimeError("disk gone")

            def commit(self):
                raise RuntimeError("disk gone")

        self.assertIsNone(L.record_run(Broken(), ticker="A", depth="s", sections=[],
                                       model="", provider="", context_hash="",
                                       stages={}, grounding={}, provider_count=0,
                                       llm_backed=False))


class BudgetEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(prefix="ledger-test-")
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
            with urllib.request.urlopen(self.base + path, timeout=20) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_runs_endpoint_shape(self):
        status, body = self._get("/api/ai/runs?ticker=TCS.NS&limit=5")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("runs", body)
        self.assertIn("budget", body)
        self.assertIn("used_today", body["budget"])
        self.assertNotIn("AI_API_KEY", json.dumps(body))

    def test_budget_exhausted_is_429(self):
        from services.ai_research import orchestrator as O

        fake_adapter = mock.Mock()
        for method in ("get_quote", "get_fundamentals", "get_valuation",
                       "get_technicals", "get_ratio_sheet", "get_financials",
                       "get_earnings", "get_estimates", "get_news",
                       "get_actions", "get_ownership"):
            getattr(fake_adapter, method).return_value = {"ok": False, "reason": "UNAVAILABLE"}
        with mock.patch.object(L, "budget_exhausted", return_value=True), \
             mock.patch.object(L, "daily_budget", return_value=1):
            with self.assertRaises(Exception) as cm:
                O.run_research("TCS.NS", "standard", adapter=fake_adapter, force=True)
            self.assertEqual(getattr(cm.exception, "kind", ""), "RATE_LIMIT")


if __name__ == "__main__":
    unittest.main()
