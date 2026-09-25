"""Ratio engine tests: formulas, ROE hierarchy, aliases, no fabrication."""

import unittest

from services.analytics import ratios as R


def av_income(rev=1000.0, ni=100.0, ebitda=200.0, ebit=150.0, interest=10.0,
              eps=10.0, period="2026-03-31"):
    return {
        "fiscalDateEnding": period, "totalRevenue": str(rev),
        "costOfRevenue": str(rev * 0.6), "grossProfit": str(rev * 0.4),
        "ebitda": str(ebitda), "operatingIncome": str(ebit),
        "interestExpense": str(interest), "netIncome": str(ni),
        "dilutedEPS": str(eps),
    }


def av_balance(eq=1000.0, assets=2500.0, ca=800.0, cl=400.0, cash=200.0,
               inv=150.0, debt=500.0, period="2026-03-31"):
    return {
        "fiscalDateEnding": period, "totalAssets": str(assets),
        "totalCurrentAssets": str(ca), "cashAndCashEquivalentsAtCarryingValue": str(cash),
        "inventory": str(inv), "totalCurrentLiabilities": str(cl),
        "totalDebt": str(debt), "totalShareholderEquity": str(eq),
    }


def av_cash(cfo=180.0, capex=60.0, div=20.0, period="2026-03-31"):
    return {
        "fiscalDateEnding": period, "operatingCashflow": str(cfo),
        "capitalExpenditures": str(capex), "dividendPayout": str(div),
    }


class RatioEngineTest(unittest.TestCase):
    def sheet(self, **kw):
        inc = [av_income(), av_income(rev=900.0, ni=90.0, ebitda=180.0, ebit=135.0, eps=9.0, period="2025-03-31")]
        bal = [av_balance(), av_balance(eq=900.0, assets=2300.0, period="2025-03-31")]
        cf = [av_cash()]
        return R.compute_all(inc, bal, cf, source="alphavantage", currency="INR", **kw)

    def test_roe_average_equity(self):
        out = self.sheet()
        roe = out.get("roe")
        self.assertIsNotNone(roe)
        self.assertAlmostEqual(roe["value"], 100.0 / 950.0 * 100, places=2)
        self.assertIsNone(roe["variant"])
        self.assertEqual(roe["kind"], "CALCULATED")
        self.assertTrue(roe["formula"])
        self.assertGreaterEqual(len(roe["inputs"]), 2)
        self.assertIn("calculated_at", roe)

    def test_roe_ending_equity_fallback(self):
        out = R.compute_all([av_income()], [av_balance()], [], source="t")
        roe = out.get("roe")
        self.assertIsNotNone(roe)
        self.assertEqual(roe["variant"], "ending equity approximation")
        self.assertAlmostEqual(roe["value"], 10.0, places=2)

    def test_roe_missing_without_inputs(self):
        self.assertNotIn("roe", R.compute_all([], [], []))
        self.assertNotIn("roe", R.compute_all([{"fiscalDateEnding": "2026"}], [], []))

    def test_margins_leverage_cashflow(self):
        out = self.sheet()
        self.assertAlmostEqual(out["gross_margin"]["value"], 40.0, places=2)
        self.assertAlmostEqual(out["net_margin"]["value"], 10.0, places=2)
        self.assertAlmostEqual(out["current_ratio"]["value"], 2.0, places=2)
        self.assertAlmostEqual(out["quick_ratio"]["value"], (800 - 150) / 400, places=2)
        self.assertAlmostEqual(out["debt_equity"]["value"], 0.5, places=2)
        self.assertAlmostEqual(out["fcf"]["value"], 120.0, places=2)
        self.assertAlmostEqual(out["cfo_pat"]["value"], 1.8, places=2)
        self.assertAlmostEqual(out["interest_coverage"]["value"], 15.0, places=2)
        self.assertAlmostEqual(out["roce"]["value"], 150.0 / 1500.0 * 100, places=2)

    def test_cagr(self):
        inc = [av_income(rev=1210.0, period="2026"), av_income(rev=1100.0, period="2025"),
               av_income(rev=1000.0, period="2024")]
        out = R.compute_all(inc, [], [])
        self.assertAlmostEqual(out["revenue_cagr"]["value"], 10.0, places=1)

    def test_indian_plain_labels(self):
        inc = [{"period": "FY26", "Revenue": "5000", "Net Profit": "500", "EPS": "50"}]
        bal = [{"period": "FY26", "Shareholders Funds": "4000", "Total Assets": "9000",
                "Current Assets": "2000", "Current Liabilities": "1000",
                "Borrowings": "1000", "Cash and Bank Balances": "300"}]
        out = R.compute_all(inc, bal, [], source="indian-api")
        self.assertAlmostEqual(out["roe"]["value"], 12.5, places=2)
        self.assertAlmostEqual(out["debt_equity"]["value"], 0.25, places=2)

    def test_pe_from_price(self):
        out = R.compute_all([av_income()], [], [], price=280.0)
        self.assertAlmostEqual(out["pe_calc"]["value"], 28.0, places=2)
        self.assertNotIn("pe_calc", R.compute_all([av_income()], [], []))

    def test_placeholders_never_fabricate(self):
        inc = [{"totalRevenue": "None", "netIncome": "-", "fiscalDateEnding": "2026"}]
        out = R.compute_all(inc, [{"totalShareholderEquity": "N/A"}], [])
        self.assertNotIn("roe", out)
        self.assertNotIn("net_margin", out)

    def test_zero_division_safe(self):
        out = R.compute_all([av_income()], [av_balance(eq=0.0)], [])
        self.assertNotIn("roe", out)

    def test_dividends_paid_sign_convention(self):
        # Yahoo signs cash outflows negative; payout uses magnitude.
        cf = [dict(av_cash(), dividendPayout="-20.0")]
        out = R.compute_all([av_income()], [av_balance()], cf, source="t")
        self.assertAlmostEqual(out["payout_ratio"]["value"], 20.0, places=2)

    def test_new_ratios(self):
        inc = [dict(av_income(), costOfRevenue="600")]
        bal = [dict(av_balance(), inventory="150",
                    currentnetreceivables="200")]
        out = R.compute_all(inc, bal, [av_cash()],
                            price=280.0, market_cap=280000.0)
        self.assertAlmostEqual(out["ebitda_margin"]["value"], 20.0, places=2)
        self.assertAlmostEqual(out["pb_calc"]["value"], 280.0, places=2)
        self.assertAlmostEqual(out["fcf_yield"]["value"], 120.0 / 280000.0 * 100,
                               places=4)
        self.assertAlmostEqual(out["inventory_turnover"]["value"], 600.0 / 150.0,
                               places=2)
        self.assertAlmostEqual(out["receivables_turnover"]["value"], 1000.0 / 200.0,
                               places=2)
        for key in ("ebitda_margin", "pb_calc", "fcf_yield",
                    "inventory_turnover", "receivables_turnover"):
            node = out[key]
            self.assertEqual(node["kind"], "CALCULATED")
            self.assertTrue(node["formula"])
            self.assertTrue(node["inputs"])
            self.assertIn("calculated_at", node)


if __name__ == "__main__":
    unittest.main()
