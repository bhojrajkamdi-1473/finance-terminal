"""Upstox leg + centralized KPI engine. No network.

- Upstox without token -> honest unavailable (pass-through, never error).
- Upstox instrument-key mapping covers tracked ISINs + NSE indices.
- KPI bundle omits missing metrics (no None/placeholder keys).
- ROE hierarchy: reported wins, else NI/avg-equity calc.
- /api/kpi + /api/data-matrix routes exist on the Handler.
- UPSTOX_ANALYTICS_TOKEN is redacted from JSON responses.
"""

import os
import unittest

from providers import upstox as _ux
from providers.base import live_envelope
from providers.orchestrator import ProviderManager
from services import kpi as _kpi


class _EnvGuard(unittest.TestCase):
    KEYS = ("UPSTOX_ANALYTICS_TOKEN",)

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.KEYS}
        os.environ.pop("UPSTOX_ANALYTICS_TOKEN", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class UpstoxLegTests(_EnvGuard):
    def test_no_token_is_unavailable(self):
        p = _ux.UpstoxProvider()
        env = p.get_quote("TCS.NS")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("UPSTOX_ANALYTICS_TOKEN", env["message"])

    def test_instrument_keys(self):
        self.assertEqual(_ux.instrument_key("TCS.NS"), "NSE_EQ|INE467B01029")
        self.assertEqual(_ux.instrument_key("^NSEI"), "NSE_INDEX|Nifty 50")
        self.assertIsNone(_ux.instrument_key("MSFT"))
        self.assertIsNone(_ux.instrument_key("BTC-USD"))

    def test_quote_primary_order_prefers_upstox(self):
        up = type("U", (), {})()
        up.get_quote = lambda s: live_envelope("upstox", {"price": 100.0}, delayed=True)
        yh = type("Y", (), {})()
        yh.get_quote = lambda s: live_envelope("yahoo", {"price": 100.5}, delayed=True)
        m = ProviderManager(yahoo=yh, upstox=up)
        env = m.get_quote("TCS.NS")
        self.assertEqual(env["reconciliation"]["primary"], "upstox")
        self.assertIn("upstox", str(env.get("providers_queried")))

    def test_token_redaction(self):
        import server as _srv

        os.environ["UPSTOX_ANALYTICS_TOKEN"] = "sekret-token-12345678"
        try:
            out = _srv._redact({"msg": "echo sekret-token-12345678 here"})
            self.assertNotIn("sekret-token-12345678", str(out))
            self.assertIn("[REDACTED]", str(out))
        finally:
            os.environ.pop("UPSTOX_ANALYTICS_TOKEN", None)


class KpiEngineTests(unittest.TestCase):
    def test_omission(self):
        bundle = _kpi.build_kpi_bundle(
            symbol="X.NS",
            quote={"currency": "INR"},
            overview={"PERatio": "22.5", "ROE": None, "EPS": "-"},
            computed={},
        )
        self.assertIn("pe", bundle["kpis"])
        self.assertNotIn("roe", bundle["kpis"])
        self.assertNotIn("eps", bundle["kpis"])

    def test_roe_reported_wins(self):
        r = _kpi.roe_reported_or_calc("18.5", 100.0, 400.0, 600.0)
        self.assertEqual(r["kind"], "REPORTED")
        self.assertAlmostEqual(r["value"], 18.5)

    def test_roe_calculated(self):
        r = _kpi.roe_reported_or_calc(None, 100.0, 400.0, 600.0)
        self.assertEqual(r["kind"], "CALCULATED")
        self.assertAlmostEqual(r["value"], 20.0)  # 100/500*100

    def test_roe_invalid_omitted(self):
        self.assertIsNone(_kpi.roe_reported_or_calc(None, None, 400.0, 600.0))
        self.assertIsNone(_kpi.roe_reported_or_calc(None, 100.0, 0.0, 0.0))

    def test_roe_single_sided_equity_omitted(self):
        # One equity point is not an average — never stand in silently.
        self.assertIsNone(_kpi.roe_reported_or_calc(None, 100.0, None, 600.0))
        self.assertIsNone(_kpi.roe_reported_or_calc(None, 100.0, 400.0, None))

    def test_field_matrix_covers_required_domains(self):
        for domain in (
            "indian_quotes",
            "history_indian",
            "ratios",
            "shareholding",
            "actions",
            "ipo",
            "gmp",
            "technicals",
        ):
            self.assertIn(domain, _kpi.FIELD_PROVIDERS)
            row = _kpi.FIELD_PROVIDERS[domain]
            for col in ("primary", "secondary", "why", "fallback", "status"):
                self.assertIn(col, row)

    def test_kpi_bundle_single_source_of_truth(self):
        q = {"price": 3000.0, "currency": "INR"}
        ov = {
            "PERatio": "28.0",
            "MarketCapitalization": "1000000000000",
            "Currency": "INR",
        }
        b1 = _kpi.build_kpi_bundle(symbol="TCS.NS", quote=q, overview=ov, computed={})
        b2 = _kpi.build_kpi_bundle(symbol="TCS.NS", quote=q, overview=ov, computed={})
        self.assertEqual(b1, b2)


class RouteTests(unittest.TestCase):
    def test_routes_registered(self):
        import inspect

        import server as _srv

        src = inspect.getsource(_srv.Handler.do_GET)
        self.assertIn("/api/kpi", src)
        self.assertIn("/api/data-matrix", src)


if __name__ == "__main__":
    unittest.main()
