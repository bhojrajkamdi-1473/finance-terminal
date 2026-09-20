"""Unit tests: IndianApiProvider (free no-auth NSE/BSE leg).

No network: every test monkeypatches the provider's `_quote_summary`
seam with a local fixture shaped like Yahoo's quoteSummary result
(price/summaryDetail/defaultKeyStatistics/assetProfile with {raw}
fields). No API key is ever needed — tests assert the provider works
with an empty environment.

Run: python -m unittest discover -s tests -v
"""

import os
import unittest

from providers.indianapi import IndianApiProvider, _qsymbol


def _F(v):
    return {"raw": v}


def _fixture(symbol="TCS.NS") -> dict:
    """quoteSummary result[0] subset for an NSE equity."""
    return {
        "price": {
            "longName": "Tata Consultancy Services Limited",
            "currency": "INR",
            "regularMarketPrice": _F(3140.50),
            "regularMarketChange": _F(-12.30),
            "regularMarketChangePercent": _F(-0.3902),
            "regularMarketPreviousClose": _F(3152.80),
            "regularMarketOpen": _F(3145.00),
            "regularMarketDayHigh": _F(3160.00),
            "regularMarketDayLow": _F(3120.10),
            "regularMarketVolume": _F(2500000),
            "marketCap": _F(1140000000000),
            "regularMarketTime": _F(1784087100),
        },
        "summaryDetail": {
            "fiftyTwoWeekHigh": _F(3400.00),
            "fiftyTwoWeekLow": _F(2800.00),
            "trailingPE": _F(28.45),
            "dividendYield": _F(0.0218),
            "marketCap": _F(1140000000000),
            "open": _F(3145.00),
        },
        "defaultKeyStatistics": {
            "bookValue": _F(210.75),
            "trailingEps": _F(110.40),
        },
        "assetProfile": {
            "sector": "Technology",
            "industry": "Information Technology Services",
        },
    }


class NoAuthTestCase(unittest.TestCase):
    KEYS = ("INDIAN_STOCK_MARKET_API_KEY", "INDIAN_API_BASE_URL")

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

    def _prov(self, result=None, fail=None):
        p = IndianApiProvider()
        calls = {"n": 0}

        def qs(ticker):
            calls["n"] += 1
            if fail is not None:
                raise fail
            return result if result is not None else _fixture()

        p._quote_summary = qs  # transport seam override (no network)
        return p, calls


class TestNoAuth(NoAuthTestCase):
    def test_quote_works_without_any_key(self):
        p, calls = self._prov()
        env = p.get_quote("TCS.NS")
        self.assertEqual(env["status"], "delayed")
        self.assertEqual(env["source"], "indian-api")
        self.assertEqual(calls["n"], 1)

    def test_no_key_env_var_is_ignored(self):
        os.environ["INDIAN_STOCK_MARKET_API_KEY"] = "stale-value"
        p, _ = self._prov()
        env = p.get_quote("TCS.NS")
        self.assertEqual(env["status"], "delayed")
        self.assertNotIn("stale-value", str(env))


class TestQuote(NoAuthTestCase):
    def test_tcs_quote_normalized(self):
        p, _ = self._prov()
        env = p.get_quote("TCS.NS")
        q = env["data"]
        self.assertEqual(q["symbol"], "TCS.NS")
        self.assertEqual(q["price"], 3140.50)
        self.assertEqual(q["currency"], "INR")
        self.assertEqual(q["exchange"], "NSE")
        self.assertEqual(q["name"], "Tata Consultancy Services Limited")
        self.assertEqual(q["open"], 3145.00)
        self.assertEqual(q["day_high"], 3160.00)
        self.assertEqual(q["day_low"], 3120.10)
        self.assertEqual(q["volume"], 2500000)
        self.assertEqual(q["fifty_two_week_high"], 3400.00)
        self.assertEqual(q["fifty_two_week_low"], 2800.00)
        self.assertEqual(q["market_cap"], 1140000000000)
        self.assertEqual(q["pe"], 28.45)
        self.assertEqual(q["eps"], 110.40)
        self.assertEqual(q["book_value"], 210.75)
        self.assertAlmostEqual(q["dividend_yield"], 2.18, places=2)
        self.assertAlmostEqual(q["change_pct"], -39.02, places=2)
        self.assertEqual(q["sector"], "Technology")
        self.assertEqual(q["industry"], "Information Technology Services")
        self.assertEqual(env["timeliness"], "DELAYED")

    def test_bse_symbol_uses_bse_exchange(self):
        p, _ = self._prov()
        env = p.get_quote("TCS.BO")
        self.assertEqual(env["data"]["exchange"], "BSE")

    def test_bare_symbol_defaults_to_nse(self):
        self.assertEqual(_qsymbol("tcs"), "TCS.NS")
        self.assertEqual(_qsymbol("TCS.BO"), "TCS.BO")
        self.assertEqual(_qsymbol("TCS.NS"), "TCS.NS")

    def test_null_fields_stay_null(self):
        result = _fixture()
        result["summaryDetail"]["trailingPE"] = {"raw": None}
        result["assetProfile"] = {}
        p, _ = self._prov(result=result)
        q = p.get_quote("TCS.NS")["data"]
        self.assertIsNone(q["pe"])
        self.assertIsNone(q["sector"])
        self.assertIsNone(q["industry"])
        # everything else still populated — no wholesale failure
        self.assertEqual(q["price"], 3140.50)

    def test_non_indian_passes_through_without_fetch(self):
        p, calls = self._prov()
        env = p.get_quote("MSFT")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("not an NSE/BSE symbol", env["message"])
        self.assertEqual(calls["n"], 0)

    def test_no_price_is_honest_unavailable(self):
        result = _fixture()
        result["price"]["regularMarketPrice"] = {"raw": None}
        p, _ = self._prov(result=result)
        env = p.get_quote("TCS.NS")
        self.assertEqual(env["status"], "unavailable")
        self.assertIsNone(env["data"])

    def test_upstream_err_message_surfaces(self):
        from providers.indianapi import _UpstreamError

        p, _ = self._prov(fail=_UpstreamError({"status": "error", "message": "boom"}))
        env = p.get_quote("TCS.NS")
        self.assertEqual(env["status"], "error")
        self.assertIn("boom", env["message"])

    def test_timeout_is_error_not_crash(self):
        p, _ = self._prov(fail=TimeoutError("timed out"))
        env = p.get_quote("TCS.NS")
        self.assertEqual(env["status"], "error")
        self.assertIsNone(env["data"])

    def test_profile_carries_sector_industry(self):
        p, _ = self._prov()
        env = p.get_company_profile("INFY.NS")
        self.assertIn(env["status"], ("live", "delayed"))
        self.assertEqual(env["data"]["sector"], "Technology")
        self.assertEqual(env["data"]["industry"], "Information Technology Services")
        self.assertIsNone(env["data"]["description"])


class TestRatios(NoAuthTestCase):
    def test_ratios_flat_av_shape(self):
        p, _ = self._prov()
        env = p.get_ratios("RELIANCE.NS")
        self.assertEqual(env["status"], "delayed")
        d = env["data"]
        self.assertEqual(d["Symbol"], "RELIANCE.NS")
        self.assertEqual(d["MarketCapitalization"], 1140000000000)
        self.assertEqual(d["PERatio"], 28.45)
        self.assertEqual(d["EPS"], 110.40)
        self.assertEqual(d["BookValue"], 210.75)
        self.assertAlmostEqual(d["DividendYield"], 2.18, places=2)
        self.assertEqual(d["FiftyTwoWeekHigh"], 3400.00)
        self.assertEqual(d["FiftyTwoWeekLow"], 2800.00)
        self.assertEqual(d["_metric_source"], "indian-api quoteSummary")

    def test_roe_never_present(self):
        p, _ = self._prov()
        d = p.get_ratios("TCS.NS")["data"]
        self.assertNotIn("ROE", d)
        self.assertNotIn("ReturnOnEquity", d)


class TestUnsupportedDomains(NoAuthTestCase):
    def test_statements_estimates_earnings_holdings_news_actions(self):
        p, _ = self._prov()
        for fn in (
            lambda: p.get_financial_statements("TCS.NS", "income", "annual"),
            lambda: p.get_earnings("TCS.NS"),
            lambda: p.get_estimates("TCS.NS"),
            lambda: p.get_shareholding("TCS.NS"),
            lambda: p.get_news("TCS.NS"),
            lambda: p.get_actions("TCS.NS"),
        ):
            env = fn()
            self.assertEqual(env["status"], "unavailable")
            self.assertIsNone(env["data"])
            self.assertIn("not supplied", env["message"])

    def test_history_and_search_pass_through(self):
        p, _ = self._prov()
        self.assertEqual(
            p.get_historical_prices("TCS.NS")["status"], "unavailable"
        )
        self.assertEqual(p.search("tcs")["status"], "unavailable")


class TestRegistryWiring(NoAuthTestCase):
    def test_registry_binds_manager_for_estimates_and_holdings(self):
        from providers import registry

        self.assertIs(registry.estimates, registry.manager)
        self.assertIs(registry.holdings, registry.manager)
        sourceless = registry.manager.get_shareholding("AAPL")
        self.assertEqual(sourceless["status"], "unavailable")

    def test_registry_provider_status_no_auth(self):
        from providers import registry

        status = registry.providers_status()
        ind_api = next(p for p in status["providers"] if p["id"] == "indian-api")
        self.assertFalse(ind_api["key_required"])
        self.assertTrue(ind_api["key_configured"])
        self.assertTrue(ind_api["capabilities"]["quote"])
        self.assertTrue(ind_api["capabilities"]["fundamentals"])
        self.assertFalse(ind_api["capabilities"]["statements"])
        self.assertFalse(ind_api["capabilities"]["estimates"])
        self.assertFalse(ind_api["capabilities"]["holdings"])


if __name__ == "__main__":
    unittest.main()
