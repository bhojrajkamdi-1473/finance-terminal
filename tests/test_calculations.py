"""Unit tests: financial calculations. Run: python -m unittest discover -s tests -v"""

import unittest

from services.calculations import (
    dividend_yield,
    ev_enterprise_value,
    ev_multiple,
    margin,
    pb_ratio,
    pct_change,
    pe_ratio,
    portfolio_position,
    portfolio_summary,
    sma,
)


class TestGrowth(unittest.TestCase):
    def test_basic_yoy(self):
        self.assertAlmostEqual(pct_change(120, 100), 20.0)

    def test_negative(self):
        self.assertAlmostEqual(pct_change(80, 100), -20.0)

    def test_zero_base_returns_none(self):
        self.assertIsNone(pct_change(100, 0))

    def test_none_inputs(self):
        self.assertIsNone(pct_change(None, 100))
        self.assertIsNone(pct_change(100, None))

    def test_negative_base_uses_abs(self):
        # -50 -> -100 is a -100% move on |base|
        self.assertAlmostEqual(pct_change(-100, -50), -100.0)


class TestMargins(unittest.TestCase):
    def test_ebitda_margin(self):
        self.assertAlmostEqual(margin(30, 100), 30.0)

    def test_zero_revenue_none(self):
        self.assertIsNone(margin(10, 0))

    def test_none(self):
        self.assertIsNone(margin(None, 100))


class TestRatios(unittest.TestCase):
    def test_pe(self):
        self.assertAlmostEqual(pe_ratio(100, 5), 20.0)

    def test_pe_nonpositive_eps_none(self):
        self.assertIsNone(pe_ratio(100, 0))
        self.assertIsNone(pe_ratio(100, -5))

    def test_pb(self):
        self.assertAlmostEqual(pb_ratio(100, 25), 4.0)

    def test_pb_nonpositive_none(self):
        self.assertIsNone(pb_ratio(100, 0))

    def test_ev(self):
        self.assertAlmostEqual(ev_enterprise_value(1000, 200, 100), 1100.0)

    def test_ev_no_market_cap_none(self):
        self.assertIsNone(ev_enterprise_value(None, 200, 100))

    def test_ev_multiple(self):
        self.assertAlmostEqual(ev_multiple(1100, 110), 10.0)

    def test_ev_multiple_nonpositive_none(self):
        self.assertIsNone(ev_multiple(1100, 0))

    def test_div_yield(self):
        self.assertAlmostEqual(dividend_yield(2, 100), 2.0)

    def test_div_yield_zero_price_none(self):
        self.assertIsNone(dividend_yield(2, 0))


class TestSMA(unittest.TestCase):
    def test_warmup_none(self):
        self.assertEqual(sma([1, 2, 3], 3), [None, None, 2.0])

    def test_missing_input_propagates_none(self):
        self.assertEqual(sma([1, None, 3, 4], 2), [None, None, None, 3.5])

    def test_bad_window(self):
        self.assertEqual(sma([1, 2], 0), [None, None])


class TestPortfolio(unittest.TestCase):
    def test_position_math(self):
        p = portfolio_position(10, 100.0, 120.0)
        self.assertEqual(p["invested_value"], 1000.0)
        self.assertEqual(p["current_value"], 1200.0)
        self.assertEqual(p["unrealized_pnl"], 200.0)
        self.assertAlmostEqual(p["pnl_pct"], 20.0)

    def test_position_no_quote(self):
        p = portfolio_position(10, 100.0, None)
        self.assertIsNone(p["current_value"])
        self.assertIsNone(p["unrealized_pnl"])

    def test_summary_allocation(self):
        s = portfolio_summary(
            [
                portfolio_position(10, 100.0, 120.0),
                portfolio_position(10, 100.0, 80.0),
            ]
        )
        self.assertEqual(s["invested_value"], 2000.0)
        self.assertEqual(s["current_value"], 2000.0)
        self.assertAlmostEqual(s["positions"][0]["allocation_pct"], 60.0)


if __name__ == "__main__":
    unittest.main()
