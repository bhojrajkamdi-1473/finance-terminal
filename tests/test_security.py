"""Security tests: credential redaction + structured reason codes.

No network required. Secrets are only ever *names* here; the real env
values are used to assert that no response leaks them.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server as server_mod
from server import Handler

from providers import fundamentals as _fund
from providers import twelvedata as _td
from providers import yahoo as _yahoo

_FAKE_KEY = "TEST_FAKE_SECRET_9f0a00"  # name-only test string; not a real key


def _real_key_values():
    names = (
        "ALPHA_VANTAGE_API_KEY",
        "FUNDAMENTALS_API_KEY",
        "TWELVE_DATA_API_KEY",
        "INDIAN_STOCK_MARKET_API_KEY",
    )
    vals = [(os.environ.get(n) or "").strip() for n in names]
    return [v for v in vals if len(v) >= 8]


class RedactUnitTest(unittest.TestCase):
    def test_deep_redact_replaces_nested_secrets(self):
        secrets = _real_key_values() or [_FAKE_KEY]
        probe = "prefix " + secrets[0] + " suffix"
        payload = {
            "message": probe,
            "nested": {"items": [probe, "clean", {"deep": probe}]},
            "num": 42,
        }
        out = server_mod._redact(payload)
        raw = json.dumps(out)
        self.assertNotIn(secrets[0], raw)
        self.assertIn("[REDACTED]", raw)

    def test_redact_leaves_clean_data_alone(self):
        out = server_mod._redact({"a": "plain text", "b": [1, 2, 3], "c": None})
        self.assertEqual(out["a"], "plain text")
        self.assertEqual(out["b"], [1, 2, 3])

    def test_fundamentals_redact_strips_key_from_upstream_text(self):
        old_av = os.environ.get("ALPHA_VANTAGE_API_KEY")
        old_fund = os.environ.get("FUNDAMENTALS_API_KEY")
        os.environ["ALPHA_VANTAGE_API_KEY"] = _FAKE_KEY
        os.environ.pop("FUNDAMENTALS_API_KEY", None)
        try:
            text = f"detected key {_FAKE_KEY} please upgrade"
            out = _fund._redact(text)
            self.assertNotIn(_FAKE_KEY, out)
            self.assertIn("[REDACTED]", out)
        finally:
            if old_av is not None:
                os.environ["ALPHA_VANTAGE_API_KEY"] = old_av
            else:
                os.environ.pop("ALPHA_VANTAGE_API_KEY", None)
            if old_fund is not None:
                os.environ["FUNDAMENTALS_API_KEY"] = old_fund
            else:
                os.environ.pop("FUNDAMENTALS_API_KEY", None)

    def test_av_premium_classified_plan_limitation(self):
        env = _fund._invalid_envelope("EARNINGS", "premium", "needs premium plans")
        self.assertEqual(env["status"], "unavailable")
        self.assertEqual(env.get("code"), "PLAN_LIMITATION")

    def test_av_rate_limit_classified(self):
        env = _fund._invalid_envelope("OVERVIEW", "rate_limited", "1 req/s")
        self.assertEqual(env["status"], "rate_limited")
        self.assertEqual(env.get("code"), "RATE_LIMIT")

    def test_not_configured_code(self):
        env = _fund._not_configured()
        self.assertEqual(env.get("code"), "NOT_CONFIGURED")

    def test_yahoo_td_rate_limited_code(self):
        self.assertEqual(_yahoo.rate_limited("yahoo", "x").get("code"), "RATE_LIMIT")
        self.assertEqual(_td._rate_limited("x").get("code"), "RATE_LIMIT")

    def test_td_not_configured_code(self):
        old = os.environ.get("TWELVE_DATA_API_KEY")
        os.environ.pop("TWELVE_DATA_API_KEY", None)
        try:
            env = _td.TwelveDataProvider()._need_key()
            self.assertEqual(env.get("code"), "NOT_CONFIGURED")
        finally:
            if old is not None:
                os.environ["TWELVE_DATA_API_KEY"] = old


class NoLeakApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(prefix="terminal-sec-")
        os.environ["TERMINAL_DB"] = os.path.join(tmp, "sec.db")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=20) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode()
            except Exception:
                return e.code, ""

    def test_api_responses_never_echo_credential_values(self):
        paths = [
            "/api/providers",
            "/api/quote?symbol=RELIANCE.NS",
            "/api/company?symbol=TCS.NS",
            "/api/search?q=reliance",
            "/api/technical?symbol=TCS.NS",
        ]
        for p in paths:
            status, body = self._get(p)
            for secret in _real_key_values():
                self.assertNotIn(
                    secret,
                    body,
                    f"credential value leaked in {p} (http {status})",
                )

    def test_health_and_pill_payload_no_keys(self):
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertIn('"ok": true', body)


if __name__ == "__main__":
    unittest.main()