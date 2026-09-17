"""Unit tests: IndianApiProvider (stock.indianapi.in) normalization.

No network: every test monkeypatches the provider's `_fetch` seam with a
local fixture copied from the shape of a live, saved TATASTEEL payload.
`INDIAN_STOCK_MARKET_API_KEY` is set to a fake value only so the config
flag flips; nothing touches the upstream.

Run: python -m unittest discover -s tests -v
"""

import os
import unittest
from datetime import datetime, timezone
from datetime import timedelta

from providers.indianapi import IndianApiProvider


def _fixture() -> dict:
    """Realistic payload (subset of a live TATASTEEL response)."""
    def row(key, value, display="") -> dict:
        return {"key": key, "displayName": display or (key + " "), "value": value}

    return {
        "companyName": "Tata Steel Ltd",
        "industry": "Metals & Mining",
        "companyProfile": {
            "companyDescription": "Tata Steel is an integrated steel producer.",
            "mgIndustry": "Steel",
        },
        "percentChange": "-0.30",
        "yearHigh": "224.40",
        "yearLow": "160.00",
        "currentPrice": {"BSE": "182.85", "NSE": "183.00"},
        "stockDetailsReusableData": {
            "price": "183.00",
            "close": "183.00",
            "date": "16 Sep 2026",
            "time": "10:28:24",
            "percentChange": "-0.30",
            "high": "184.00",
            "low": "181.00",
            "yhigh": "224.40",
            "ylow": "160.06",
            "marketCap": "228447.00",
            "pPerEBasicExcludingExtraordinaryItemsTTM": "21.24",
            "currentDividendYieldCommonStockPrimaryIssueLTM": "2.18",
        },
        "financials": [
            {
                "FiscalYear": 2026,
                "EndDate": "2026-03-31",
                "stockFinancialMap": {
                    "INC": [
                        row("NetIncome", "10793.87", "Net Income "),
                        row("DilutedWeightedAverageShares", "1247.18",
                            "Diluted Weighted Average Shares "),
                        row("DilutedEPSExcludingExtraOrdItems", "8.65",
                            "Diluted EPS Excluding Extra Ord Items "),
                        row("TotalRevenue", "236395.00", "Total Revenue "),
                    ],
                    "BAL": [
                        row("TotalCommonSharesOutstanding", "1247.18",
                            "Total Common Shares Outstanding "),
                    ],
                    "CAS": [
                        row("NetIncomeStartingLine", "10793.87",
                            "Net Income/Starting Line "),
                    ],
                },
            },
            {
                "FiscalYear": 2025,
                "EndDate": "2025-03-31",
                "stockFinancialMap": {
                    "INC": [
                        row("DilutedEPSExcludingExtraOrdItems", "6.10",
                            "Diluted EPS Excluding Extra Ord Items "),
                    ],
                    "BAL": [],
                    "CAS": [],
                },
            },
        ],
        "keyMetrics": {
            "valuation": [
                row("pPerEBasicExcludingExtraordinaryItemsTTM", "21.24"),
                row("priceToBookMostRecentFiscalYear", "2.24"),
                row("pegRatio", "3.21"),
                row("priceToSalesTrailing12Month", "0.96"),
                row("currentDividendYieldCommonStockPrimaryIssueLTM", "2.18"),
            ],
            "persharedata": [
                row("ePSBasicExcludingExtraordinaryItemsMostRecentFiscalYear", "8.65"),
                row("bookValuePerShareMostRecentFiscalYear", "65.13"),
                row("dividendPerShareMostRecentFiscalYear", "4.00"),
            ],
            "mgmtEffectiveness": [
                row("returnOnAverageEquityMostRecentFiscalYear", "11.17"),
                row("returnOnAverageAssetsMostRecenFiscalYear", "3.75"),
            ],
            "margins": [
                row("netProfitMarginPercentTrailing12Month", "4.70"),
                row("operatingMarginTrailing12Month", "8.83"),
                row("grossMarginTrailing12Month", "59.96"),
            ],
            "financialstrength": [
                row("totalDebtPerTotalEquityMostRecentFiscalYear", "0.90"),
            ],
            "priceandVolume": [
                row("marketCap", "228447.00"),
                row("beta", "1.18"),
                row("52WeekHigh", "224.40"),
                row("52WeekLow", "160.06"),
            ],
        },
        "analystView": [
            {"ratingName": "Strong Buy", "ratingValue": 1, "numberOfAnalystsLatest": "10"},
            {"ratingName": "Buy", "ratingValue": 2, "numberOfAnalystsLatest": "8"},
            {"ratingName": "Hold", "ratingValue": 3, "numberOfAnalystsLatest": "9"},
            {"ratingName": "Sell", "ratingValue": 4, "numberOfAnalystsLatest": "4"},
            {"ratingName": "Strong Sell", "ratingValue": 5, "numberOfAnalystsLatest": "3"},
        ],
        "recosBar": {
            "stockAnalyst": [
                {"ratingName": "Strong Buy", "ratingValue": 1, "numberOfAnalysts": 10,
                 "minValue": 1, "maxValue": 1.8},
                {"ratingName": "Buy", "ratingValue": 2, "numberOfAnalysts": 8,
                 "minValue": 1.8, "maxValue": 2.6},
            ],
            "tickerRatingValue": "2.47",
            "noOfRecommendations": "34",
            "meanValue": "2.47",
            "tickerPercentage": "83.82",
        },
        "shareholding": [
            {
                "displayName": "Promoter",
                "categoryName": "Shareholding of Promoter and Promoter Group",
                "categories": [
                    {"holdingDate": "2025-09-30", "percentage": "33.19"},
                    {"holdingDate": "2026-06-30", "percentage": "32.94"},
                ],
            },
            {
                "displayName": "FII",
                "categoryName": "FII",
                "categories": [
                    {"holdingDate": "2025-09-30", "percentage": "17.29"},
                    {"holdingDate": "2026-06-30", "percentage": "18.90"},
                ],
            },
        ],
        "stockCorporateActionData": {
            "dividend": [
                {
                    "remarks": "Rs.4 per share(400%)Final Dividend",
                    "recordDate": "2026-06-12",
                    "xdDate": "2026-06-12",
                    "interimOrFinal": "Final",
                    "value": 4,
                    "percentage": 400,
                    "dateOfAnnouncement": "2026-05-15",
                }
            ],
            "splits": [
                {
                    "remarks": "Stock split from Rs. 10/- to Re. 1/-.",
                    "recordDate": "2022-07-29",
                    "xsDate": "2022-07-28",
                    "oldFaceValue": 10,
                    "newFaceValue": 1,
                }
            ],
            "bonus": [],
            "rights": [],
            "annualGeneralMeeting": [{"agmDate": "2026-08-10", "purpose": "AGM"}],
            "boardMeetings": [{"boardMeetDate": "2026-09-01", "purpose": "Board mtg"}],
        },
        "recentNews": [
            {
                "headline": "Tata Group stocks surge; RBI rejects Tata Sons move",
                "date": "2026-09-15T04:29:02+0000",
                "url": "/market/stock-market-news/tata-12345678901234.html",
                "summary": "Most Tata Group stocks surged on Tuesday.",
            }
        ],
    }


class IndianApiTest(unittest.TestCase):
    def setUp(self):
        self._old = {
            k: os.environ.get(k)
            for k in ("INDIAN_STOCK_MARKET_API_KEY",)
        }
        os.environ["INDIAN_STOCK_MARKET_API_KEY"] = "test-key"

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _prov(self, payload=_fixture()):
        p = IndianApiProvider()
        calls = {"n": 0}

        def fetch(name):
            calls["n"] += 1
            return payload

        p._fetch = fetch  # transport seam override (no network)
        return p, calls


class TestQuote(IndianApiTest):
    def test_nse_quote_normalized(self):
        p, calls = self._prov()
        env = p.get_quote("TATASTEEL.NS")
        self.assertEqual(env["status"], "delayed")
        self.assertEqual(env["source"], "indian-api")
        self.assertEqual(env["timeliness"], "DELAYED")
        q = env["data"]
        self.assertEqual(q["price"], 183.0)
        self.assertEqual(q["currency"], "INR")
        self.assertEqual(q["exchange"], "NSE")
        self.assertEqual(q["name"], "Tata Steel Ltd")
        self.assertEqual(q["fifty_two_week_high"], 224.4)
        self.assertAlmostEqual(q["previous_close"], 183.55, places=2)
        self.assertAlmostEqual(q["change"], -0.55, places=2)
        self.assertAlmostEqual(q["change_pct"], -0.30, places=2)
        self.assertEqual(q["market_cap"], 228447.0)
        self.assertEqual(q["pe"], 21.24)
        self.assertEqual(q["dividend_yield"], 2.18)
        self.assertEqual(calls["n"], 1)

    def test_bse_quote_preferred_when_requested(self):
        p, _ = self._prov()
        env = p.get_quote("TATASTEEL.BO")
        self.assertEqual(env["data"]["price"], 182.85)
        self.assertEqual(env["data"]["exchange"], "BSE")

    def test_market_time_epoch(self):
        p, _ = self._prov()
        ts = p.get_quote("TATASTEEL.NS")["data"]["market_time"]
        self.assertIsInstance(ts, int)
        # 16 Sep 2026 10:28:24 IST
        ist = timezone(timedelta(hours=5, minutes=30))
        expected = datetime(2026, 9, 16, 10, 28, 24, tzinfo=ist).timestamp()
        self.assertEqual(ts, int(expected))

    def test_non_indian_passes_through_without_fetch(self):
        p, calls = self._prov()
        env = p.get_quote("MSFT")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("not an NSE/BSE symbol", env["message"])
        self.assertEqual(calls["n"], 0)

    def test_no_key_is_honest_unavailable(self):
        os.environ.pop("INDIAN_STOCK_MARKET_API_KEY", None)
        p, calls = self._prov()
        env = p.get_quote("TATASTEEL.NS")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("INDIAN_STOCK_MARKET_API_KEY", env["message"])
        self.assertEqual(calls["n"], 0)

    def test_upstream_err_message_surfaces(self):
        p = IndianApiProvider()

        def fetch(name):
            raise Exception("boom")

        p._fetch = fetch
        env = p.get_quote("TATASTEEL.NS")
        self.assertEqual(env["status"], "error")
        self.assertIn("boom", env["message"])

    def test_feed_err_key_returns_unavailable(self):
        from providers.base import unavailable as _unavailable
        from providers.indianapi import SOURCE, _UpstreamError

        p = IndianApiProvider()

        def fetch(name):
            raise _UpstreamError(
                _unavailable(SOURCE, "Stock not found (for 'NODATA.NS').")
            )

        p._fetch = fetch
        env = p.get_quote("NODATA.NS")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("Stock not found", env["message"])


class TestDomainData(IndianApiTest):
    def test_ratios_flat_av_shape(self):
        p, _ = self._prov()
        env = p.get_ratios("TATASTEEL.NS")
        self.assertEqual(env["status"], "delayed")
        d = env["data"]
        self.assertEqual(d["Symbol"], "TATASTEEL.NS")
        self.assertEqual(d["PERatio"], 21.24)
        self.assertEqual(d["EPS"], 8.65)
        self.assertEqual(d["MarketCapitalization"], 228447.0)
        self.assertEqual(d["MarketCapUnit"], "₹ Crore")
        self.assertEqual(d["SharesUnit"], "Crore shares")
        self.assertEqual(d["_metric_source"], "indian-api keyMetrics")
        self.assertIsNone(d["ForwardPE"])

    def test_statements_income_annual(self):
        p, _ = self._prov()
        env = p.get_financial_statements("TATASTEEL.NS", "income", "annual")
        self.assertEqual(env["status"], "delayed")
        d = env["data"]
        self.assertEqual(d["unit"], "₹ Crore")
        self.assertEqual(len(d["reports"]), 2)
        self.assertEqual(d["reports"][0]["Net Income"], "10793.87")
        self.assertIn("Diluted EPS Excluding Extra Ord Items",
                      d["reports"][0])

    def test_statements_quarterly_never_synthesised(self):
        p, calls = self._prov()
        env = p.get_financial_statements("TATASTEEL.NS", "income", "quarterly")
        self.assertEqual(env["status"], "unavailable")
        self.assertIn("fiscal-year", env["message"])
        self.assertEqual(calls["n"], 0)

    def test_earnings_reported_eps(self):
        p, _ = self._prov()
        env = p.get_earnings("TATASTEEL.NS")
        self.assertEqual(env["status"], "delayed")
        annual = env["data"]["annual"]
        self.assertEqual(len(annual), 2)
        self.assertEqual(annual[0]["reportedEPS"], 8.65)
        self.assertEqual(annual[0]["fiscalDateEnding"], "2026-03-31")
        self.assertEqual(env["data"]["quarterly"], [])

    def test_estimates_are_ratings_not_fabricated_eps(self):
        p, _ = self._prov()
        env = p.get_estimates("TATASTEEL.NS")
        self.assertEqual(env["status"], "delayed")
        d = env["data"]
        self.assertEqual(d["annual"], [])
        self.assertEqual(d["quarterly"], [])
        ar = d["analyst_ratings"]
        self.assertEqual(ar["no_of_recommendations"], 34)
        self.assertEqual(len(ar["distribution"]), 5)
        self.assertEqual(ar["distribution"][0]["rating"], "Strong Buy")
        self.assertEqual(ar["distribution"][0]["analysts"], 10)
        self.assertIsNotNone(ar["mean_rating"])
        self.assertIn("never synthesised", d["note"])

    def test_actions_dividends_and_splits(self):
        p, _ = self._prov()
        env = p.get_actions("TATASTEEL.NS")
        self.assertEqual(env["status"], "delayed")
        d = env["data"]
        self.assertEqual(d["dividends"][0]["amount"], 4)
        self.assertEqual(d["dividends"][0]["interim_or_final"], "Final")
        self.assertEqual(d["splits"][0]["numerator"], 10)
        self.assertEqual(d["extras"]["agm"][0]["date"], "2026-08-10")

    def test_holdings_latest_filing_picked(self):
        p, _ = self._prov()
        env = p.get_shareholding("TATASTEEL.NS")
        self.assertEqual(env["status"], "delayed")
        d = env["data"]
        self.assertEqual(d["symbol"], "TATASTEEL.NS")
        by_name = {o["category"]: o for o in d["ownership"]}
        # latest filing (2026-06-30) wins over 2025-09-30
        self.assertEqual(by_name["Promoter"]["percentage"], 32.94)
        self.assertEqual(by_name["Promoter"]["holding_date"], "2026-06-30")
        self.assertEqual(by_name["FII"]["percentage"], 18.90)

    def test_news_absolutized_url(self):
        p, _ = self._prov()
        env = p.get_news("TATASTEEL.NS")
        self.assertEqual(env["status"], "live")
        item = env["data"]["items"][0]
        self.assertTrue(item["url"].startswith("https://www.livemint.com/"))

    def test_history_and_search_pass_through(self):
        p, _ = self._prov()
        self.assertEqual(p.get_historical_prices("TATASTEEL.NS")["status"], "unavailable")
        self.assertEqual(p.search("tata")["status"], "unavailable")


class TestRegistryWiring(IndianApiTest):
    def test_registry_binds_manager_for_estimates_and_holdings(self):
        from providers import registry

        self.assertIs(registry.estimates, registry.manager)
        self.assertIs(registry.holdings, registry.manager)
        sourceless = registry.manager.get_shareholding("AAPL")
        self.assertEqual(sourceless["status"], "unavailable")
        self.assertIn("NSE/BSE", sourceless["message"])

    def test_registry_provider_status_capabilities(self):
        from providers import registry

        status = registry.providers_status()
        ind_api = next(p for p in status["providers"] if p["id"] == "indian-api")
        self.assertTrue(ind_api["key_required"])
        self.assertTrue(ind_api["key_configured"])  # fake key set in setUp
        self.assertTrue(ind_api["capabilities"]["holdings"])
        self.assertTrue(ind_api["capabilities"]["estimates"])
        # key value must never leak through the status endpoint
        self.assertNotIn("test-key", str(status))
        self.assertNotIn(os.environ["INDIAN_STOCK_MARKET_API_KEY"], str(status))

    def test_holdings_capability_registered_in_base(self):
        from providers.base import CAPABILITIES

        self.assertIn("holdings", CAPABILITIES)


if __name__ == "__main__":
    unittest.main()