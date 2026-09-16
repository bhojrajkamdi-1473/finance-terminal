"""Optional fundamentals provider.

Reads an API key from the environment (ALPHA_VANTAGE_API_KEY or
FUNDAMENTALS_API_KEY). When no key is configured, every method returns
an explicit "unavailable / provider not configured" envelope instead
of fabricated numbers — per the terminal's non-negotiable data rule.

When a key IS configured, uses Alpha Vantage's free endpoints
(OVERVIEW, INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW) with
server-side key handling (key never leaves the backend).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from .base import (
    EstimatesProvider,
    FundamentalsProvider,
    error_envelope,
    live_envelope,
    unavailable,
)

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}
BASE = "https://www.alphavantage.co/query"


def _api_key() -> str:
    return (
        os.environ.get("ALPHA_VANTAGE_API_KEY")
        or os.environ.get("FUNDAMENTALS_API_KEY")
        or ""
    ).strip()


def _av_get(params: dict, timeout: float = 20.0) -> dict:
    params = dict(params)
    params["apikey"] = _api_key()
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _not_configured() -> dict:
    return unavailable(
        "fundamentals",
        "Provider not configured. Set ALPHA_VANTAGE_API_KEY "
        "(or FUNDAMENTALS_API_KEY) to enable financial statements, "
        "ratios and estimates.",
    )


class AlphaVantageFundamentalsProvider(FundamentalsProvider):
    name = "alphavantage"

    def get_financial_statements(
        self, symbol: str, statement: str = "income", period: str = "annual"
    ) -> dict:
        if not _api_key():
            return _not_configured()
        statement = (statement or "income").lower()
        fn_map = {
            "income": "INCOME_STATEMENT",
            "balance": "BALANCE_SHEET",
            "cashflow": "CASH_FLOW",
        }
        fn = fn_map.get(statement)
        if not fn:
            return error_envelope(
                "alphavantage",
                f"Unknown statement '{statement}'. Use income|balance|cashflow.",
            )
        try:
            payload = _av_get({"function": fn, "symbol": symbol})
        except Exception as exc:
            return error_envelope("alphavantage", f"Request failed: {exc}")
        if "Note" in payload or "Information" in payload:
            return error_envelope(
                "alphavantage",
                str(
                    payload.get("Note")
                    or payload.get("Information")
                    or "Rate limit / service notice."
                ),
            )
        key = "annualReports" if period != "quarterly" else "quarterlyReports"
        reports = payload.get(key)
        if not reports:
            return unavailable(
                "alphavantage", f"No {period} {statement} data for '{symbol}'."
            )
        return live_envelope(
            "alphavantage",
            {
                "symbol": symbol,
                "statement": statement,
                "period": period,
                "currency": payload.get("currency") or "USD",
                "reports": reports[:12],
            },
        )

    def get_ratios(self, symbol: str) -> dict:
        if not _api_key():
            return _not_configured()
        try:
            payload = _av_get({"function": "OVERVIEW", "symbol": symbol})
        except Exception as exc:
            return error_envelope("alphavantage", f"Request failed: {exc}")
        if not payload or "Symbol" not in payload:
            return unavailable(
                "alphavantage",
                payload.get("Note")
                or payload.get("Information")
                or f"No overview data for '{symbol}'.",
            )
        keep = [
            "Symbol",
            "Name",
            "Exchange",
            "Currency",
            "Sector",
            "Industry",
            "MarketCapitalization",
            "EBITDA",
            "PERatio",
            "ForwardPE",
            "PEGRatio",
            "BookValue",
            "PriceToBookRatio",
            "PriceToSalesRatioTTM",
            "EVToRevenue",
            "EVToEBITDA",
            "EPS",
            "ROE",
            "ROA",
            "ROIC",
            "ReturnOnEquityTTM",
            "ReturnOnAssetsTTM",
            "ProfitMargin",
            "OperatingMarginTTM",
            "DividendYield",
            "DividendPerShare",
            "Beta",
            "52WeekHigh",
            "52WeekLow",
        ]
        return live_envelope(
            "alphavantage",
            {k: payload.get(k) for k in keep if k in payload},
        )


class NoEstimatesProvider(EstimatesProvider):
    """Estimates require a paid/approved estimates feed; never invent them."""

    name = "none"

    def get_estimates(self, symbol: str) -> dict:
        return unavailable(
            "estimates",
            "Estimates provider not configured. Analyst estimates are not "
            "available — they are never synthesised by this terminal.",
        )
