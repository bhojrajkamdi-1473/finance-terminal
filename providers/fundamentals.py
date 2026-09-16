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


def _premium_block(payload: dict) -> str | None:
    """Detect premium/entitlement notices. Never call premium endpoints
    and pretend they are free: surface the block honestly."""
    info = str(payload.get("Information") or "")
    if "premium" in info.lower() or "entitlement" in info.lower():
        return info[:300]
    return None


class AlphaVantageFundamentalsProvider(FundamentalsProvider):
    name = "alphavantage"
    capabilities: dict[str, bool] = {
        "fundamentals": True,
        "statements": True,
        "earnings": True,
        "estimates": False,
        "news": True,
        "ipo": True,
        "macro": True,
        "history": True,
        "quote": True,
    }

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

    def get_quote(self, symbol: str) -> dict:
        """Last-resort quote leg (GLOBAL_QUOTE).

        Free tier: 25 requests/day TOTAL, delayed data. The fallback
        chain only reaches this leg when Yahoo and Twelve Data both
        fail, and results are cached server-side for hours.
        """
        if not _api_key():
            return _not_configured()
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return unavailable("alphavantage", "Empty symbol.")
        try:
            payload = _av_get({"function": "GLOBAL_QUOTE", "symbol": symbol})
        except Exception as exc:
            return error_envelope("alphavantage", f"Quote failed: {exc}")
        q = payload.get("Global Quote") or {}
        if not q:
            return unavailable(
                "alphavantage",
                str(
                    payload.get("Note")
                    or payload.get("Information")
                    or f"No quote for '{symbol}'."
                ),
            )

        def num(key: str):
            try:
                return float(str(q.get(key, "")).strip().rstrip("%"))
            except (TypeError, ValueError):
                return None

        price = num("05. price")
        if price is None:
            return unavailable("alphavantage", f"No price for '{symbol}'.")
        prev = num("08. previous close")
        quote = {
            "symbol": symbol,
            "name": None,
            "exchange": None,
            "currency": None,
            "instrument_type": None,
            "price": price,
            "previous_close": prev,
            "open": num("02. open"),
            "day_high": num("03. high"),
            "day_low": num("04. low"),
            "volume": num("06. volume"),
            "change": num("09. change"),
            "change_pct": num("10. change percent"),
            "fifty_two_week_high": None,
            "fifty_two_week_low": None,
            "market_time": q.get("07. latest trading day"),
            "timezone": None,
        }
        env = live_envelope("alphavantage", quote, delayed=True)
        env["timeliness"] = "DELAYED"
        env["timeliness_note"] = (
            "Alpha Vantage free tier serves delayed data "
            "(25 requests/day shared across all endpoints)."
        )
        return env

    # -- free-tier domain methods (each costs 1 of 25 daily calls) ------
    def _domain(self, function: str, symbol: str = "") -> dict:
        """Shared fetch for earnings/news/ipo/macro/history domains."""
        if not _api_key():
            return _not_configured()
        params: dict[str, str] = {"function": function}
        if symbol:
            params["symbol"] = symbol
        try:
            payload = _av_get(params)
        except Exception as exc:
            return error_envelope("alphavantage", f"{function} failed: {exc}")
        blocked = _premium_block(payload)
        if blocked:
            return unavailable(
                "alphavantage",
                f"{function} requires a premium entitlement: {blocked}",
            )
        if payload.get("Note"):
            return error_envelope("alphavantage", str(payload.get("Note"))[:300])
        return live_envelope("alphavantage", payload, delayed=True)

    def get_earnings(self, symbol: str) -> dict:
        """Annual + quarterly earnings (reported EPS, estimated EPS where
        the feed provides it, surprise, dates). Periods kept separate."""
        env = self._domain("EARNINGS", symbol)
        if env.get("status") != "live":
            return env
        payload = env["data"] or {}
        out = {
            "symbol": (symbol or "").strip().upper(),
            "annual": (payload.get("annualEarnings") or [])[:8],
            "quarterly": (payload.get("quarterlyEarnings") or [])[:12],
            "note": "Periods are never mixed: annual vs quarterly stay "
            "separate. Estimated EPS appears only when the feed reports it.",
        }
        env["data"] = out
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_av_news(self, symbol: str = "", topics: str = "", limit: int = 20) -> dict:
        """NEWS_SENTIMENT (free). Falls back gracefully when uncovered."""
        if not _api_key():
            return _not_configured()
        params: dict[str, str] = {"function": "NEWS_SENTIMENT", "limit": str(limit)}
        if symbol:
            params["tickers"] = symbol
        if topics:
            params["topics"] = topics
        try:
            payload = _av_get(params)
        except Exception as exc:
            return error_envelope("alphavantage", f"NEWS_SENTIMENT failed: {exc}")
        blocked = _premium_block(payload)
        if blocked:
            return unavailable("alphavantage", f"News requires premium: {blocked}")
        if payload.get("Note"):
            return error_envelope("alphavantage", str(payload.get("Note"))[:300])
        items = []
        for a in (payload.get("feed") or [])[:limit]:
            items.append(
                {
                    "title": a.get("title"),
                    "url": a.get("url"),
                    "published_at": a.get("time_published"),
                    "source": a.get("source"),
                    "summary": (a.get("summary") or "")[:400],
                    "sentiment": a.get("overall_sentiment_label"),
                    "symbol": symbol or None,
                }
            )
        if not items:
            return unavailable(
                "alphavantage",
                payload.get("Information")
                or payload.get("Note")
                or "No news items returned.",
            )
        return live_envelope("alphavantage", {"items": items}, delayed=False)

    def get_ipo_calendar(self) -> dict:
        """IPO_CALENDAR returns CSV. Parsed to rows; premium notices and
        empty calendars become honest unavailable states."""
        if not _api_key():
            return _not_configured()
        try:
            params = {"function": "IPO_CALENDAR", "apikey": _api_key()}
            url = BASE + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return error_envelope("alphavantage", f"IPO_CALENDAR failed: {exc}")
        lowered = text.lower()
        if "premium" in lowered or "entitlement" in lowered:
            return unavailable(
                "alphavantage",
                "IPO calendar requires a premium entitlement: "
                + text[:200].replace("\n", " "),
            )
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2 or not lines[0].lower().startswith("symbol"):
            return unavailable(
                "alphavantage",
                "No IPO calendar data returned: " + text[:200].replace("\n", " "),
            )
        header = [h.strip() for h in lines[0].split(",")]
        rows = []
        for ln in lines[1:51]:
            cells = [c.strip() for c in ln.split(",")]
            rows.append(
                {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}
            )
        env = live_envelope(
            "alphavantage",
            {
                "rows": rows,
                "columns": header,
                "note": "Free IPO calendar feed; empty when no window data.",
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_economic(self, indicator: str) -> dict:
        """Free economic indicators: GDP, INFLATION, UNEMPLOYMENT,
        FEDERAL_FUNDS_RATE, CPI, RETAIL_SALES, DURABLES, ..."""
        allowed = {
            "GDP",
            "REAL_GDP",
            "REAL_GDP_PER_CAPITA",
            "INFLATION",
            "UNEMPLOYMENT",
            "FEDERAL_FUNDS_RATE",
            "CPI",
            "RETAIL_SALES",
            "DURABLES",
            "TREASURY_YIELD",
            "NONFARM_PAYROLL",
        }
        indicator = (indicator or "").strip().upper()
        if indicator not in allowed:
            return error_envelope(
                "alphavantage",
                f"Unknown indicator '{indicator}'. Supported: "
                + ", ".join(sorted(allowed)),
            )
        env = self._domain(indicator)
        if env.get("status") != "live":
            return env
        payload = env["data"] or {}
        env["data"] = {
            "indicator": indicator,
            "unit": payload.get("unit"),
            "points": (payload.get("data") or [])[:40],
        }
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_daily_history(self, symbol: str) -> dict:
        """TIME_SERIES_DAILY (free, end-of-day). Last leg of HISTORY."""
        env = self._domain("TIME_SERIES_DAILY", symbol)
        if env.get("status") != "live":
            return env
        payload = env["data"] or {}
        series = payload.get("Time Series (Daily)") or {}
        bars = []
        for day in sorted(series.keys(), reverse=True)[:260]:
            v = series[day] or {}
            try:
                from datetime import datetime, timezone

                ts = int(
                    datetime.strptime(day, "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
                c = float(v["4. close"])
            except (ValueError, KeyError, TypeError):
                continue

            def num(k: str):
                try:
                    return float(v[k])
                except (ValueError, KeyError, TypeError):
                    return None

            bars.append(
                {
                    "t": ts,
                    "o": num("1. open"),
                    "h": num("2. high"),
                    "l": num("3. low"),
                    "c": c,
                    "adj": c,
                    "v": num("5. volume"),
                }
            )
        bars.sort(key=lambda b: b["t"])
        if not bars:
            return unavailable("alphavantage", f"No daily history for '{symbol}'.")
        env["data"] = {
            "symbol": (symbol or "").strip().upper(),
            "range": "1Y",
            "interval": "1d",
            "currency": None,
            "bars": bars,
        }
        env["timeliness"] = "END-OF-DAY"
        return env


class NoEstimatesProvider(EstimatesProvider):
    """Estimates require a paid/approved estimates feed; never invent them."""

    name = "none"

    def get_estimates(self, symbol: str) -> dict:
        return unavailable(
            "estimates",
            "Estimates provider not configured. Analyst estimates are not "
            "available — they are never synthesised by this terminal.",
        )
