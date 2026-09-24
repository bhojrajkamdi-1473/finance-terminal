"""Ratio consistency: one fixture, every surface, identical normalized values.

Overview / Research / Screener / Compare all read the same provider
overview + the same canonical ratio engine. If any surface diverges,
this test fails.
"""

import unittest

from server import _apply_op, _reported_num
from services.ai_research import context as C
from services.analytics import ratios as R

OVERVIEW = {
    "ROE": "14.8", "PERatio": "22.4", "EPS": "91.16",
    "MarketCapitalization": "903000000000", "BookValue": "642.84",
    "DividendYield": "1.75",
}

INCOME = [
    {"fiscalDateEnding": "2026-03-31", "totalRevenue": "100000",
     "netIncome": "14800", "dilutedEPS": "91.16", "ebitda": "25000",
     "operatingIncome": "20000", "interestExpense": "1000"},
    {"fiscalDateEnding": "2025-03-31", "totalRevenue": "90000",
     "netIncome": "13000", "dilutedEPS": "80.00", "ebitda": "22000",
     "operatingIncome": "18000", "interestExpense": "1000"},
]

BALANCE = [
    {"fiscalDateEnding": "2026-03-31", "totalShareholderEquity": "100000",
     "totalAssets": "250000", "totalCurrentAssets": "80000",
     "totalCurrentLiabilities": "40000", "inventory": "10000",
     "totalDebt": "42000", "cashAndCashEquivalentsAtCarryingValue": "20000"},
    {"fiscalDateEnding": "2025-03-31", "totalShareholderEquity": "90000",
     "totalAssets": "230000"},
]


class FakeLegs:
    def __init__(self):
        self.calls = []

    def _ok(self, name, data, source="alphavantage"):
        self.calls.append(name)
        return {"ok": True, "data": data, "source": source,
                "as_of": "2026-09-24T00:00:00+00:00", "status": "live",
                "timeliness": "DELAYED"}

    def get_quote(self, symbol):
        return self._ok("quote", {"price": 2035.0, "change_pct": 1.0,
                                  "currency": "INR", "volume": 100})

    def get_fundamentals(self, symbol):
        return self._ok("profile", {"Name": symbol})

    def get_valuation(self, symbol):
        return self._ok("valuation", {
            "metrics": {"pe": {"value": 22.4}, "pb": {"value": 3.1},
                        "eps": {"value": 91.16},
                        "dividend_yield": {"value": 1.75},
                        "market_cap": {"value": 903000000000.0},
                        "beta": {"value": 1.1}},
            "overview": dict(OVERVIEW, Name=symbol, Currency="INR")})

    def get_financials(self, symbol, statement="income", period="annual"):
        data = {"income": INCOME, "balance": BALANCE, "cashflow": []}[statement]
        return self._ok("fin", {"reports": data, "currency": "INR"})

    def get_earnings(self, symbol):
        return {"ok": False, "reason": "UNAVAILABLE"}

    def get_estimates(self, symbol):
        return {"ok": False, "reason": "UNAVAILABLE"}

    def get_news(self, symbol, limit=8):
        return {"ok": False, "reason": "UNAVAILABLE"}

    def get_actions(self, symbol):
        return {"ok": False, "reason": "UNAVAILABLE"}

    def get_ownership(self, symbol):
        return {"ok": False, "reason": "UNAVAILABLE"}

    def get_technicals(self, symbol, bench=""):
        return {"ok": False, "reason": "UNAVAILABLE"}

    def get_ratio_sheet(self, symbol):
        computed = R.compute_all(INCOME, BALANCE, [], source="alphavantage",
                                 currency="INR")
        return self._ok("sheet", {"display": {
            "roe": computed["roe"], "roce": computed["roce"],
            "debt_equity": computed["debt_equity"],
            "net_margin": computed["net_margin"]}})


class ConsistencyTest(unittest.TestCase):
    def test_engine_roe(self):
        out = R.compute_all(INCOME, BALANCE, [], source="t")
        self.assertAlmostEqual(out["roe"]["value"], 14800 / 95000 * 100, places=2)

    def test_surfaces_agree(self):
        bundle = C.build_context("TCS.NS", FakeLegs(),
                                 ["fundamentals", "valuation", "technical",
                                  "news", "bull", "bear", "risk"])
        facts = bundle["facts"]
        engine = R.compute_all(INCOME, BALANCE, [], source="t")
        # Research facts (reported PE/EPS/mcap) match provider overview.
        self.assertAlmostEqual(facts["pe"], float(OVERVIEW["PERatio"]))
        self.assertAlmostEqual(facts["eps"], float(OVERVIEW["EPS"]))
        self.assertAlmostEqual(facts["market_cap"], float(OVERVIEW["MarketCapitalization"]))
        # Research ratio facts match the canonical engine exactly.
        for key in ("roe", "roce", "debt_equity", "net_margin"):
            self.assertAlmostEqual(facts[key], engine[key]["value"], places=3,
                                   msg=key)
        # Screener passthrough (server._reported_num) is identity.
        self.assertEqual(_reported_num(OVERVIEW["ROE"]), 14.8)
        self.assertEqual(_reported_num(OVERVIEW["PERatio"]), 22.4)
        self.assertEqual(_reported_num(OVERVIEW["EPS"]), 91.16)
        self.assertEqual(_reported_num(OVERVIEW["BookValue"]), 642.84)
        self.assertEqual(_reported_num(OVERVIEW["DividendYield"]), 1.75)
        self.assertTrue(_apply_op(14.8, "gte", 10, None))

    def test_no_placeholders_leak(self):
        for key in ("ROE", "PERatio", "EPS", "BookValue", "DividendYield"):
            self.assertIsNotNone(_reported_num(OVERVIEW[key]))
        self.assertIsNone(_reported_num("None"))
        self.assertIsNone(_reported_num("-"))


if __name__ == "__main__":
    unittest.main()
