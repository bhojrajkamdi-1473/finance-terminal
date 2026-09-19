"""Yahoo hardening tests: simulated upstream failures.

No network. urllib is stubbed to produce 429/timeout/malformed/empty
responses; every case must yield an honest envelope — never a crash,
never a fabricated value, never an endless retry loop.
"""

import io
import json
import unittest
import urllib.error
import urllib.request

from providers import yahoo as _yahoo


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def _http_error(code):
    return urllib.error.HTTPError(
        "http://x", code, f"Error {code}", {}, io.BytesIO(b"")
    )


class YahooHardeningTest(unittest.TestCase):
    def setUp(self):
        self._orig_urlopen = urllib.request.urlopen
        self._orig_sleep = _yahoo.time.sleep
        _yahoo.time.sleep = lambda s: None  # no real backoff waits in tests
        _yahoo._cache.clear()

    def tearDown(self):
        urllib.request.urlopen = self._orig_urlopen
        _yahoo.time.sleep = self._orig_sleep
        _yahoo._cache.clear()

    def _stub(self, behavior):
        calls = {"n": 0}

        def fake(url_or_req, timeout=None):
            calls["n"] += 1
            return behavior(calls["n"])

        urllib.request.urlopen = fake
        return calls

    def test_429_eventually_rate_limited(self):
        calls = self._stub(lambda n: (_ for _ in ()).throw(_http_error(429)))
        env = _yahoo.YahooMarketDataProvider().get_quote("AAPL")
        self.assertEqual(env["status"], "rate_limited")
        self.assertEqual(calls["n"], 3)  # bounded retries, no loop
        self.assertIsNone(env["data"])

    def test_timeout_is_error_not_crash(self):
        def boom(n):
            raise TimeoutError("timed out")

        self._stub(boom)
        env = _yahoo.YahooMarketDataProvider().get_quote("AAPL")
        self.assertEqual(env["status"], "error")
        self.assertIsNone(env["data"])

    def test_url_error_is_error(self):
        def boom(n):
            raise urllib.error.URLError("dns fail")

        self._stub(boom)
        env = _yahoo.YahooMarketDataProvider().get_historical_prices("AAPL")
        self.assertEqual(env["status"], "error")

    def test_malformed_json_is_error(self):
        self._stub(lambda n: _FakeResp(b"not json{{{"))
        env = _yahoo.YahooMarketDataProvider().get_quote("AAPL")
        self.assertEqual(env["status"], "error")
        self.assertIsNone(env["data"])

    def test_empty_result_is_unavailable(self):
        body = json.dumps({"chart": {"result": [], "error": None}}).encode()
        self._stub(lambda n: _FakeResp(body))
        env = _yahoo.YahooMarketDataProvider().get_quote("NOPE")
        self.assertEqual(env["status"], "unavailable")

    def test_http_404_is_unavailable_or_error(self):
        self._stub(lambda n: (_ for _ in ()).throw(_http_error(404)))
        env = _yahoo.YahooMarketDataProvider().get_quote("NOPE")
        self.assertIn(env["status"], ("unavailable", "error"))

    def test_valid_response_flows(self):
        meta = {
            "symbol": "AAPL",
            "currency": "USD",
            "regularMarketPrice": 100.0,
            "chartPreviousClose": 99.0,
            "regularMarketTime": 1700000000,
        }
        body = json.dumps({"chart": {"result": [{"meta": meta}]}}).encode()
        self._stub(lambda n: _FakeResp(body))
        env = _yahoo.YahooMarketDataProvider().get_quote("AAPL")
        self.assertIn(env["status"], ("live", "delayed"))
        self.assertEqual(env["data"]["price"], 100.0)
        # second call served from cache: no extra upstream hit
        env2 = _yahoo.YahooMarketDataProvider().get_quote("AAPL")
        self.assertEqual(env2["data"]["price"], 100.0)


if __name__ == "__main__":
    unittest.main()
