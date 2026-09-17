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


def _validate(payload: object, function: str) -> tuple[str, str]:
    """Classify an Alpha Vantage response.

    Returns (kind, message) with kind in:
    ok | rate_limited | premium | error | empty.
    Control messages are NEVER treated as financial data.
    """
    if not isinstance(payload, dict) or not payload:
        return ("empty", f"{function} returned an empty payload.")
    if payload.get("Error Message"):
        return ("error", str(payload.get("Error Message"))[:300])
    info = str(payload.get("Information") or "")
    if info:
        lowered = info.lower()
        if "premium" in lowered or "entitlement" in lowered:
            return ("premium", info[:300])
        return ("rate_limited", info[:300])
    if payload.get("Note"):
        return ("rate_limited", str(payload.get("Note"))[:300])
    return ("ok", "")


def _invalid_envelope(function: str, kind: str, message: str) -> dict:
    if kind == "rate_limited":
        return {
            "status": "rate_limited",
            "source": "alphavantage",
            "as_of": None,
            "data": None,
            "message": f"RATE LIMITED ({function}): {message}",
        }
    if kind == "premium":
        return unavailable(
            "alphavantage",
            f"{function} requires a premium entitlement: {message}",
        )
    if kind == "empty":
        return unavailable("alphavantage", message)
    return error_envelope("alphavantage", f"{function}: {message}")


def _av_symbol(symbol: str) -> dict:
    """Resolve the Alpha Vantage symbol (cached discovery)."""
    from . import symbols as _sym

    def _search(query: str) -> list[dict]:
        try:
            payload = _av_get({"function": "SYMBOL_SEARCH", "keywords": query})
        except Exception:
            return []
        matches = payload.get("bestMatches") or []
        out = []
        for m in matches:
            if isinstance(m, dict) and m.get("1. symbol"):
                out.append({"symbol": m.get("1. symbol"), "name": m.get("2. name")})
        return out

    return _sym.resolve_alphavantage(symbol, _search)


class AlphaVantageFundamentalsProvider(FundamentalsProvider):
    name = "alphavantage"
    capabilities: dict[str, bool] = {
        "fundamentals": True,
        "statements": True,
        "earnings": True,
        "estimates": True,
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

    # -- corporate actions / shares / estimates / calendars --------------
    def _resolved(self, symbol: str) -> tuple[str | None, dict | None]:
        """Resolve AV symbol; returns (av_symbol, error_envelope|None)."""
        if not _api_key():
            return None, _not_configured()
        res = _av_symbol(symbol)
        if "symbol" not in res:
            return None, unavailable(
                "alphavantage",
                str(res.get("unresolved") or "Symbol resolution failed."),
            )
        return str(res["symbol"]), None

    def _checked_domain(
        self, function: str, av_symbol: str, requested: str
    ) -> tuple[dict | None, dict | None]:
        """Fetch + validate + mismatch-guard. Returns (payload, err_env)."""
        from . import symbols as _sym

        try:
            payload = _av_get({"function": function, "symbol": av_symbol})
        except Exception as exc:
            return None, error_envelope("alphavantage", f"{function} failed: {exc}")
        kind, message = _validate(payload, function)
        if kind != "ok":
            return None, _invalid_envelope(function, kind, message)
        echoed = None
        if isinstance(payload, dict):
            echoed = payload.get("Symbol") or (payload.get("Meta Data") or {}).get(
                "2. Symbol"
            )
        if echoed and not _sym.symbols_match(requested, str(echoed)):
            return None, unavailable(
                "alphavantage",
                f"Symbol mismatch: requested '{requested}' but provider "
                f"returned '{echoed}'. Refusing to attribute.",
            )
        assert isinstance(payload, dict)
        return payload, None

    def get_dividends(self, symbol: str) -> dict:
        av_symbol, err = self._resolved(symbol)
        if err:
            return err
        assert av_symbol is not None
        payload, err = self._checked_domain("DIVIDENDS", av_symbol, symbol)
        if err:
            return err
        assert payload is not None
        rows = [
            {
                "date": (d or {}).get("ex_dividend_date") or (d or {}).get("date"),
                "amount": (d or {}).get("amount"),
                "currency": (d or {}).get("currency") or payload.get("currency"),
            }
            for d in (payload.get("data") or [])
            if isinstance(d, dict)
        ]
        env = live_envelope(
            "alphavantage",
            {"symbol": (symbol or "").strip().upper(), "dividends": rows},
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_splits(self, symbol: str) -> dict:
        av_symbol, err = self._resolved(symbol)
        if err:
            return err
        assert av_symbol is not None
        payload, err = self._checked_domain("SPLITS", av_symbol, symbol)
        if err:
            return err
        assert payload is not None
        rows = [
            {
                "date": (s or {}).get("effective_date") or (s or {}).get("date"),
                "numerator": (s or {}).get("split_from") or (s or {}).get("numerator"),
                "denominator": (s or {}).get("split_to")
                or (s or {}).get("denominator"),
            }
            for s in (payload.get("data") or [])
            if isinstance(s, dict)
        ]
        env = live_envelope(
            "alphavantage",
            {"symbol": (symbol or "").strip().upper(), "splits": rows},
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_shares_outstanding(self, symbol: str) -> dict:
        av_symbol, err = self._resolved(symbol)
        if err:
            return err
        assert av_symbol is not None
        payload, err = self._checked_domain("SHARES_OUTSTANDING", av_symbol, symbol)
        if err:
            return err
        assert payload is not None
        rows = [
            {"date": (r or {}).get("date"), "shares": (r or {}).get("shares")}
            for r in (payload.get("data") or [])
            if isinstance(r, dict)
        ][:8]
        env = live_envelope(
            "alphavantage",
            {"symbol": (symbol or "").strip().upper(), "rows": rows},
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_earnings_estimates(self, symbol: str) -> dict:
        """EARNINGS_ESTIMATES. Returns estimates only as reported; when the
        feed has nothing, UNAVAILABLE with the exact reason."""
        av_symbol, err = self._resolved(symbol)
        if err:
            return err
        assert av_symbol is not None
        payload, err = self._checked_domain("EARNINGS_ESTIMATES", av_symbol, symbol)
        if err:
            return err
        assert payload is not None
        annual = payload.get("annualEstimates") or []
        quarterly = payload.get("quarterlyEstimates") or []
        if not annual and not quarterly:
            return unavailable(
                "alphavantage",
                "UNAVAILABLE. Reason: Provider returned no estimate data "
                f"for this symbol (EARNINGS_ESTIMATES empty for '{symbol}').",
            )
        env = live_envelope(
            "alphavantage",
            {
                "symbol": (symbol or "").strip().upper(),
                "annual": annual[:8],
                "quarterly": quarterly[:12],
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_estimates(self, symbol: str) -> dict:
        if not _api_key():
            return unavailable(
                "estimates",
                "Estimates provider not configured. Analyst estimates are "
                "never synthesised by this terminal.",
            )
        return self.get_earnings_estimates(symbol)

    def get_earnings_calendar(self, symbol: str = "") -> dict:
        if not _api_key():
            return _not_configured()
        try:
            params: dict[str, str] = {"function": "EARNINGS_CALENDAR"}
            if symbol:
                params["symbol"] = symbol
            payload = _av_get(params)
        except Exception as exc:
            return error_envelope("alphavantage", f"EARNINGS_CALENDAR failed: {exc}")
        kind, message = _validate(payload, "EARNINGS_CALENDAR")
        if kind != "ok":
            return _invalid_envelope("EARNINGS_CALENDAR", kind, message)
        assert isinstance(payload, dict)
        rows = payload.get("data") or []
        env = live_envelope(
            "alphavantage",
            {"rows": rows[:60] if isinstance(rows, list) else rows},
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def symbol_search(self, query: str) -> dict:
        if not _api_key():
            return _not_configured()
        try:
            payload = _av_get({"function": "SYMBOL_SEARCH", "keywords": query})
        except Exception as exc:
            return error_envelope("alphavantage", f"SYMBOL_SEARCH failed: {exc}")
        kind, message = _validate(payload, "SYMBOL_SEARCH")
        if kind != "ok":
            return _invalid_envelope("SYMBOL_SEARCH", kind, message)
        assert isinstance(payload, dict)
        results = [
            {
                "symbol": m.get("1. symbol"),
                "name": m.get("2. name"),
                "exchange": m.get("4. region"),
                "type": m.get("3. type"),
                "sector": None,
                "industry": None,
            }
            for m in (payload.get("bestMatches") or [])
            if isinstance(m, dict) and m.get("1. symbol")
        ]
        if not results:
            return unavailable("alphavantage", f"No symbols found for '{query}'.")
        return live_envelope("alphavantage", {"results": results}, delayed=False)


class NoEstimatesProvider(EstimatesProvider):
    """Estimates require a paid/approved estimates feed; never invent them."""

    name = "none"

    def get_estimates(self, symbol: str) -> dict:
        return unavailable(
            "estimates",
            "Estimates provider not configured. Analyst estimates are not "
            "available — they are never synthesised by this terminal.",
        )
