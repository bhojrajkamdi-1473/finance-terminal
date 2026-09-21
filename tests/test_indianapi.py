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

    def test_market_cap_fallback_from_shares_labeled_calculated(self):
        result = _fixture()
        result["price"]["marketCap"] = {"raw": None}
        result["summaryDetail"]["marketCap"] = {"raw": None}
        result["defaultKeyStatistics"]["sharesOutstanding"] = {"raw": 3618087518}
        p, _ = self._prov(result=result)
        env = p.get_ratios("TCS.NS")
        d = env["data"]
        # 3140.50 × 3618087518 ≈ 11.36T — definitional, labeled CALCULATED
        self.assertAlmostEqual(
            d["MarketCapitalization"], 3140.50 * 3618087518, places=0
        )
        self.assertEqual(d["MarketCapKind"], "CALCULATED")

    def test_market_cap_absent_without_shares(self):
        result = _fixture()
        result["price"]["marketCap"] = {"raw": None}
        result["summaryDetail"]["marketCap"] = {"raw": None}
        result["defaultKeyStatistics"]["sharesOutstanding"] = {"raw": None}
        p, _ = self._prov(result=result)
        d = p.get_ratios("TCS.NS")["data"]
        self.assertIsNone(d["MarketCapitalization"])

    def test_roe_never_present(self):
        p, _ = self._prov()
        d = p.get_ratios("TCS.NS")["data"]
        self.assertNotIn("ROE", d)
        self.assertNotIn("ReturnOnEquity", d)


class TestUnsupportedDomains(NoAuthTestCase):
    def test_statements_estimates_earnings_holdings_news_actions(self):
        # Keyless: keyed-only domains explain they need the key (with the
        # NOT_CONFIGURED code) instead of pretending to be unsupported.
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
            self.assertIn("INDIAN_STOCK_MARKET_API_KEY", env["message"])
            self.assertEqual(env.get("code"), "NOT_CONFIGURED")

    def test_history_and_search_pass_through(self):
        p, _ = self._prov()
        self.assertEqual(
            p.get_historical_prices("TCS.NS")["status"], "unavailable"
        )
        self.assertEqual(p.search("tcs")["status"], "unavailable")


def _krow(key, value, display=""):
    return {"key": key, "displayName": display or (key + " "), "value": value}


def _kstock() -> dict:
    """Official /stock payload subset (shape verified live, Sep 2026)."""
    return {
        "companyName": "Tata Consultancy Services Limited",
        "industry": "Information Technology",
        "companyProfile": {
            "companyDescription": "TCS is an IT services company.",
            "mgIndustry": "Information Technology Services",
            "isInId": "INE467B01029",
            "exchangeCodeBse": "532540",
            "exchangeCodeNse": "TCS",
        },
        "currentPrice": {"BSE": "2101.00", "NSE": "2105.00"},
        "stockDetailsReusableData": {
            "price": "2105.00",
            "date": "16 Sep 2026",
            "time": "10:28:24",
            "percentChange": "1.20",
            "high": "2110.00",
            "low": "2090.00",
            "yhigh": "3400.00",
            "ylow": "2800.00",
        },
        "financials": [
            {
                "FiscalYear": 2026,
                "EndDate": "2026-03-31",
                "stockFinancialMap": {
                    "INC": [
                        _krow("NetIncome", "48000.00", "Net Income "),
                        _krow(
                            "DilutedWeightedAverageShares",
                            "362.00",
                            "Diluted Weighted Average Shares ",
                        ),
                        _krow("TotalRevenue", "255000.00", "Total Revenue "),
                    ],
                    "BAL": [
                        _krow(
                            "TotalCommonSharesOutstanding",
                            "362.00",
                            "Total Common Shares Outstanding ",
                        ),
                    ],
                    "CAS": [],
                },
            }
        ],
        "keyMetrics": {
            "valuation": [_krow("pPerEBasicExcludingExtraordinaryItemsTTM", "15.29")],
            "persharedata": [
                _krow("ePSBasicExcludingExtraordinaryItemsMostRecentFiscalYear", "137.67"),
                _krow("bookValuePerShareMostRecentFiscalYear", "303.01"),
            ],
            "mgmtEffectiveness": [
                _krow("returnOnAverageEquityMostRecentFiscalYear", "45.10"),
            ],
            "margins": [_krow("netProfitMarginPercentTrailing12Month", "18.80")],
            "financialstrength": [],
            "priceandVolume": [_krow("marketCap", "761000.00")],
        },
        "analystView": [
            {"ratingName": "Buy", "ratingValue": 2, "numberOfAnalystsLatest": "18"},
        ],
        "recosBar": {
            "meanValue": "2.10",
            "noOfRecommendations": "34",
            "tickerPercentage": "83.82",
            "tickerRatingValue": "2.10",
        },
        "shareholding": [
            {
                "displayName": "Promoter",
                "categories": [{"holdingDate": "2026-06-30", "percentage": "72.10"}],
            },
        ],
        "stockCorporateActionData": {
            "dividend": [
                {
                    "xdDate": "2026-06-12",
                    "recordDate": "2026-06-12",
                    "value": 12,
                    "remarks": "Rs.12 final",
                    "interimOrFinal": "Final",
                    "dateOfAnnouncement": "2026-05-15",
                }
            ],
            "splits": [],
            "bonus": [],
            "rights": [],
            "annualGeneralMeeting": [],
            "boardMeetings": [],
        },
        "recentNews": [
            {
                "headline": "TCS wins deal",
                "date": "2026-09-15T04:29:02+0000",
                "url": "/market/news/tcs-1.html",
                "summary": "TCS announced a deal.",
            }
        ],
    }


class KeyedTestCase(unittest.TestCase):
    def setUp(self):
        self._old = dict(os.environ)
        os.environ["INDIAN_STOCK_MARKET_API_KEY"] = "test-key-never-sent"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old)

    def _kprov(self, payload=None, fail=None, free_detail=None):
        from providers.indianapi import _UpstreamError
        from providers.indianapi import unavailable as _unav

        p = IndianApiProvider()
        calls = []

        def kget(path, params):
            calls.append((path, params))
            if fail is not None:
                raise fail
            if payload is not None:
                return payload
            return _kstock()

        p._kget = kget  # keyed transport seam (no network, no key sent)
        if free_detail is None:
            # No-auth leg stubbed to fail closed: no network in unit tests.
            p._detail = lambda s: (_ for _ in ()).throw(
                _UpstreamError(_unav("indian-api", "free leg stubbed off"))
            )
        else:
            p._detail = lambda s: free_detail
        return p, calls


class TestKeyedQuote(KeyedTestCase):
    def test_nse_bse_choice(self):
        p, calls = self._kprov()
        env = p.get_quote("TCS.NS")
        self.assertEqual(env["status"], "delayed")
        self.assertEqual(env["data"]["price"], 2105.00)
        self.assertEqual(env["data"]["exchange"], "NSE")
        env = p.get_quote("TCS.BO")
        self.assertEqual(env["data"]["price"], 2101.00)
        self.assertEqual(env["data"]["exchange"], "BSE")
        # x-api-key header path used, never the key value in params
        self.assertTrue(all(c[0] == "/stock" for c in calls))
        self.assertNotIn("test-key-never-sent", str(calls))

    def test_non_indian_passes_through(self):
        p, calls = self._kprov()
        env = p.get_quote("META")
        self.assertEqual(env["status"], "unavailable")
        self.assertEqual(calls, [])

    def test_401_falls_back_to_free_leg(self):
        from providers.indianapi import _UpstreamError

        p, _ = self._kprov(
            fail=_UpstreamError(
                {
                    "status": "error",
                    "source": "indian-api",
                    "code": "AUTH_ERROR",
                    "message": "rejected the key",
                    "data": None,
                    "as_of": None,
                }
            )
        )
        marker = {"status": "delayed", "source": "indian-api", "data": {"price": 1.0}}
        p._free_quote = lambda symbol, key_note=None: marker
        env = p.get_quote("TCS.NS")
        # falls back rather than failing the page with AUTH_ERROR
        self.assertIs(env, marker)


class TestKeyedDomains(KeyedTestCase):
    def test_ratios_rich_with_roe(self):
        p, _ = self._kprov()
        d = p.get_ratios("TCS.NS")["data"]
        self.assertEqual(d["PERatio"], 15.29)
        self.assertEqual(d["EPS"], 137.67)
        self.assertEqual(d["ROE"], 45.10)
        self.assertEqual(d["_metric_source"], "indian-api keyMetrics")

    def test_statements_annual_and_quarterly_honest(self):
        p, _ = self._kprov()
        env = p.get_financial_statements("TCS.NS", "income", "annual")
        self.assertEqual(env["status"], "delayed")
        self.assertEqual(env["data"]["reports"][0]["Net Income"], "48000.00")
        # quarterly: /statement + stats seams absent -> honest miss
        p._kget = lambda path, params: {}
        env = p.get_financial_statements("TCS.NS", "income", "quarterly")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("quarterly", env["message"].lower())

    def test_earnings_reported_eps(self):
        p, _ = self._kprov()
        env = p.get_earnings("TCS.NS")
        annual = env["data"]["annual"]
        self.assertEqual(annual[0]["fiscalDateEnding"], "2026-03-31")
        # 48000 / 362 = 132.60
        self.assertAlmostEqual(annual[0]["reportedEPS"], 132.60, places=1)

    def test_estimates_ratings_plus_forecasts(self):
        p, _ = self._kprov()
        orig = p._kget

        def kget(path, params):
            if path == "/stock_forecasts":
                return [{"horizon": "FY27", "eps": 150.0}]
            if path == "/stock_target_price":
                return {"target_price": 2400.0}
            return orig(path, params)

        p._kget = kget
        env = p.get_estimates("TCS.NS")
        d = env["data"]
        self.assertEqual(d["analyst_ratings"]["no_of_recommendations"], 34)
        self.assertEqual(d["forecasts"], [{"horizon": "FY27", "eps": 150.0}])
        self.assertEqual(d["target_price"], {"value": 2400.0})

    def test_actions_news_holdings(self):
        p, _ = self._kprov()
        d = p.get_actions("TCS.NS")["data"]
        self.assertEqual(d["dividends"][0]["amount"], 12)
        items = p.get_news("TCS.NS")["data"]["items"]
        self.assertTrue(items[0]["url"].startswith("https://www.livemint.com/"))
        own = p.get_shareholding("TCS.NS")["data"]["ownership"]
        self.assertEqual(own[0]["category"], "Promoter")
        self.assertEqual(own[0]["percentage"], 72.10)

    def test_indian_history_and_stats(self):
        p, _ = self._kprov(
            payload={
                "data": [
                    {"date": "2026-09-01", "close": 2100.0, "volume": 1000},
                    {"date": "2026-09-02", "close": 2105.0, "volume": 1100},
                ]
            }
        )
        env = p.get_indian_history("TCS.NS", "1m", "price")
        self.assertEqual(env["status"], "delayed")
        self.assertEqual(len(env["data"]["bars"]), 2)
        self.assertEqual(env["data"]["bars"][0]["c"], 2100.0)
        env = p.get_historical_stats("TCS.NS", "ratios")
        self.assertEqual(env["status"], "delayed")
        self.assertEqual(env["data"]["stat"], "ratios")
        bad = p.get_indian_history("TCS.NS", "9Z", "price")
        self.assertEqual(bad["status"], "error")
        bad = p.get_historical_stats("TCS.NS", "nope")
        self.assertEqual(bad["status"], "error")

    def test_global_symbol_never_calls_keyed_api(self):
        p, calls = self._kprov()
        for fn in (
            lambda: p.get_ratios("MSFT"),
            lambda: p.get_earnings("MSFT"),
            lambda: p.get_actions("MSFT"),
        ):
            fn()
        self.assertEqual(calls, [])

    def test_field_fallback_fills_thin_keyed_rows(self):
        # Keyed payload with nulls + free detail with values (INR raw
        # market cap converted to ₹ Crore) — disclosed via _fallback_fields.
        thin = _kstock()
        thin["keyMetrics"] = {"valuation": [], "persharedata": []}
        free = {
            "market_cap": 7616073826304.0,
            "pe_ratio": 15.29,
            "eps": 137.67,
            "book_value": 303.01,
            "dividend_yield": 3.09,
            "year_high": 3400.0,
            "year_low": 2800.0,
            "sector": "Technology",
            "industry": "IT Services",
            "market_time": None,
            "company_name": "TCS",
            "currency": "INR",
        }
        p, _ = self._kprov(payload=thin, free_detail=free)
        d = p.get_ratios("TCS.NS")["data"]
        self.assertAlmostEqual(d["MarketCapitalization"], 761607.38, places=1)
        self.assertEqual(d["PERatio"], 15.29)
        self.assertIn("MarketCapitalization", d["_fallback_fields"])
        self.assertEqual(d["_fallback_source"], "indian-api quoteSummary (no-auth)")

    def test_history_and_search_pass_through(self):
        p, _ = self._kprov()
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
        # Dual-mode: never key_REQUIRED; key_configured reflects the env.
        self.assertFalse(ind_api["key_required"])
        self.assertFalse(ind_api["key_configured"])  # no key in test env
        self.assertTrue(ind_api["capabilities"]["quote"])
        self.assertTrue(ind_api["capabilities"]["fundamentals"])
        self.assertTrue(ind_api["capabilities"]["statements"])
        self.assertTrue(ind_api["capabilities"]["estimates"])
        self.assertTrue(ind_api["capabilities"]["holdings"])


if __name__ == "__main__":
    unittest.main()
