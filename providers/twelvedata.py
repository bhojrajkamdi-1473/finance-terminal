"""Twelve Data provider (free Basic tier, API key required).

Verified free-tier facts (twelvedata.com/pricing, Sep 2026):
- 8 API credits / minute, 800 credits / day.
- Basic plan claims real-time US equities/ETFs, forex and crypto.
- Only a few markets are covered on free; anything uncovered returns
  an API error, which becomes an honest "unavailable" envelope so the
  fallback chain can continue — never fabricated.

Timeliness labels used here:
- REAL-TIME for US-exchange equities/ETFs, forex and crypto
  (Twelve Data's published free-plan claim).
- DELAYED for anything else that returns data.
- The plan claim is surfaced in the payload note; the terminal never
  upgrades this to exchange-certified real-time.

Rate protection: a process-wide token bucket (8 credits / 60 s) plus a
UTC-day counter (800/day). When exhausted the provider reports
"unavailable (rate budget exhausted)" without calling upstream.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .base import MarketDataProvider, error_envelope, live_envelope, unavailable

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}
BASE = "https://api.twelvedata.com"

CREDITS_PER_MINUTE = 8
CREDITS_PER_DAY = 800

_bucket_lock = threading.Lock()
_minute_window_start = 0.0
_minute_used = 0
_day_key = ""
_day_used = 0

# Exchanges Twelve Data advertises as real-time on the free plan.
_REALTIME_US_EXCHANGES = {
    "NASDAQ",
    "NYSE",
    "NYSE American",
    "NYSE Arca",
}


def _api_key() -> str:
    return (os.environ.get("TWELVE_DATA_API_KEY") or "").strip()


def _budget_take(credits: int = 1) -> str | None:
    """Take credits from the free-tier budget. Returns None if allowed,
    otherwise a human-readable exhaustion reason."""
    global _minute_window_start, _minute_used, _day_key, _day_used
    now = time.time()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _bucket_lock:
        if today != _day_key:
            _day_key, _day_used = today, 0
            _minute_window_start, _minute_used = now, 0
        if now - _minute_window_start >= 60:
            _minute_window_start, _minute_used = now, 0
        if _minute_used + credits > CREDITS_PER_MINUTE:
            return "per-minute budget exhausted (8 credits/min on free tier)"
        if _day_used + credits > CREDITS_PER_DAY:
            return "daily budget exhausted (800 credits/day on free tier)"
        _minute_used += credits
        _day_used += credits
        return None


def budget_snapshot() -> dict:
    with _bucket_lock:
        return {
            "per_minute_limit": CREDITS_PER_MINUTE,
            "per_minute_used": _minute_used,
            "daily_limit": CREDITS_PER_DAY,
            "daily_used": _day_used,
            "day": _day_key,
        }


def to_td_symbol(symbol: str) -> str | None:
    """Map a Yahoo-style symbol to Twelve Data's symbol/exchange format."""
    s = (symbol or "").strip().upper()
    if not s:
        return None
    if s.startswith("^"):
        return None  # indices are not covered by the stock quote endpoint
    if s.endswith(".NS"):
        return s[:-3] + "/NSE"
    if s.endswith(".BO"):
        return s[:-3] + "/BSE"
    if "/" in s or " " in s:
        return None
    return s


def _is_rate_limit(exc: Exception) -> bool:
    return isinstance(exc, urllib.error.HTTPError) and exc.code == 429


def _rate_limited(detail: str) -> dict:
    return {
        "status": "rate_limited",
        "source": "twelvedata",
        "as_of": None,
        "data": None,
        "code": "RATE_LIMIT",
        "message": f"RATE LIMITED: {detail} Cooling down and falling back.",
    }


def _get(path: str, params: dict, timeout: float = 15.0) -> Any:
    params = dict(params)
    params["apikey"] = _api_key()
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class TwelveDataProvider(MarketDataProvider):
    name = "twelvedata"
    capabilities: dict[str, bool] = {
        "quote": True,
        "history": True,
        "search": True,
        "fundamentals": True,
        "statements": True,
        "earnings": True,
        "actions": True,
    }

    def _need_key(self) -> dict | None:
        if _api_key():
            return None
        return unavailable(
            "twelvedata",
            "API KEY NOT CONFIGURED. Set TWELVE_DATA_API_KEY "
            "to enable this fallback leg.",
            code="NOT_CONFIGURED",
        )

    # -- search -----------------------------------------------------
    def search(self, query: str, limit: int = 10) -> dict:
        missing = self._need_key()
        if missing:
            return missing
        blocked = _budget_take(1)
        if blocked:
            return unavailable("twelvedata", f"Rate budget exhausted: {blocked}.")
        try:
            payload = _get("/symbol_search", {"symbol": query})
        except Exception as exc:
            if _is_rate_limit(exc):
                return _rate_limited(f"Search throttled: {exc}")
            return error_envelope("twelvedata", f"Search failed: {exc}")
        data = payload.get("data") or []
        results = [
            {
                "symbol": d.get("symbol"),
                "name": d.get("instrument_name"),
                "exchange": d.get("exchange"),
                "type": d.get("instrument_type"),
                "sector": None,
                "industry": None,
            }
            for d in data[:limit]
            if d.get("symbol")
        ]
        if not results:
            return unavailable(
                "twelvedata",
                payload.get("message") or f"No instruments found for '{query}'.",
            )
        return live_envelope("twelvedata", {"results": results}, delayed=False)

    # -- quote ------------------------------------------------------
    def get_quote(self, symbol: str) -> dict:
        missing = self._need_key()
        if missing:
            return missing
        td_symbol = to_td_symbol(symbol)
        if td_symbol is None:
            return unavailable(
                "twelvedata",
                f"Symbol '{symbol}' is not addressable on Twelve Data "
                "(indices and suffixed instruments excluded).",
            )
        blocked = _budget_take(1)
        if blocked:
            return unavailable("twelvedata", f"Rate budget exhausted: {blocked}.")
        try:
            payload = _get("/quote", {"symbol": td_symbol, "interval": "1day"})
        except Exception as exc:
            if _is_rate_limit(exc):
                return _rate_limited(f"Quote throttled for {symbol}: {exc}")
            return error_envelope("twelvedata", f"Quote failed for {symbol}: {exc}")
        if payload.get("status") == "error" or "code" in payload:
            return unavailable(
                "twelvedata",
                str(payload.get("message") or "Symbol not covered on this plan."),
            )
        price = _num(payload.get("close"))
        if price is None:
            return unavailable("twelvedata", f"No price in response for '{symbol}'.")
        prev = _num(payload.get("previous_close"))
        quote = {
            "symbol": (symbol or "").strip().upper(),
            "name": payload.get("name"),
            "exchange": payload.get("exchange"),
            "currency": payload.get("currency"),
            "instrument_type": payload.get("type"),
            "price": price,
            "previous_close": prev,
            "open": _num(payload.get("open")),
            "day_high": _num(payload.get("high")),
            "day_low": _num(payload.get("low")),
            "volume": _num(payload.get("volume")),
            "change": _num(payload.get("change")),
            "change_pct": _num(payload.get("percent_change")),
            "fifty_two_week_high": _num(
                (payload.get("fifty_two_week") or {}).get("high")
            ),
            "fifty_two_week_low": _num(
                (payload.get("fifty_two_week") or {}).get("low")
            ),
            "market_time": payload.get("datetime"),
            "timezone": payload.get("exchange_timezone"),
        }
        exchange = (payload.get("exchange") or "").strip()
        # Twelve Data's published free-plan claim: real-time US
        # equities/ETFs, forex and crypto. Everything else is DELAYED.
        realtime = exchange in _REALTIME_US_EXCHANGES or "/" in td_symbol
        timeliness = "REAL-TIME" if realtime else "DELAYED"
        env = live_envelope("twelvedata", quote, delayed=(timeliness != "REAL-TIME"))
        env["timeliness"] = timeliness
        env["timeliness_note"] = (
            "Twelve Data Basic plan claims real-time US equities/ETFs, "
            "forex and crypto; other markets are delayed or uncovered."
        )
        return env

    # -- history ----------------------------------------------------
    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        missing = self._need_key()
        if missing:
            return missing
        td_symbol = to_td_symbol(symbol)
        if td_symbol is None:
            return unavailable(
                "twelvedata", f"Symbol '{symbol}' not addressable on Twelve Data."
            )
        td_interval = {"1d": "1day", "1wk": "1week", "1mo": "1month"}.get(
            (interval or "1d").lower()
        )
        if td_interval is None:
            return error_envelope(
                "twelvedata",
                f"Interval '{interval}' not supported on this leg (1d/1wk/1mo).",
            )
        outputsize = {
            "1D": 5,
            "5D": 10,
            "1M": 30,
            "3M": 90,
            "6M": 180,
            "1Y": 260,
            "2Y": 500,
            "5Y": 1200,
            "MAX": 5000,
        }.get((range_ or "1M").upper(), 30)
        blocked = _budget_take(1)
        if blocked:
            return unavailable("twelvedata", f"Rate budget exhausted: {blocked}.")
        try:
            payload = _get(
                "/time_series",
                {
                    "symbol": td_symbol,
                    "interval": td_interval,
                    "outputsize": outputsize,
                    "order": "ASC",
                },
            )
        except Exception as exc:
            if _is_rate_limit(exc):
                return _rate_limited(f"History throttled for {symbol}: {exc}")
            return error_envelope("twelvedata", f"History failed for {symbol}: {exc}")
        if payload.get("status") == "error" or "code" in payload:
            return unavailable(
                "twelvedata",
                str(payload.get("message") or "History not covered on this plan."),
            )
        values = payload.get("values") or []
        bars = []
        for v in values:
            try:
                dt = datetime.fromisoformat(
                    str(v.get("datetime")).replace("Z", "+00:00")
                )
                ts = int(dt.timestamp())
            except (ValueError, TypeError):
                continue
            c = _num(v.get("close"))
            if c is None:
                continue
            bars.append(
                {
                    "t": ts,
                    "o": _num(v.get("open")),
                    "h": _num(v.get("high")),
                    "l": _num(v.get("low")),
                    "c": c,
                    "adj": c,
                    "v": _num(v.get("volume")),
                }
            )
        if not bars:
            return unavailable("twelvedata", f"Insufficient history for '{symbol}'.")
        env = live_envelope(
            "twelvedata",
            {
                "symbol": (symbol or "").strip().upper(),
                "range": range_,
                "interval": interval,
                "currency": payload.get("meta", {}).get("currency"),
                "bars": bars,
            },
            delayed=True,
        )
        env["timeliness"] = "DELAYED"
        return env

    # -- fundamentals / earnings / actions (free-tier, budget-guarded) --
    def _domain(self, endpoint: str, td_symbol: str, cost: int = 2) -> dict:
        """Fetch a TD domain endpoint. Returns (payload | error-envelope)."""
        blocked = _budget_take(cost)
        if blocked:
            return unavailable("twelvedata", f"Rate budget exhausted: {blocked}.")
        try:
            payload = _get(endpoint, {"symbol": td_symbol})
        except Exception as exc:
            if _is_rate_limit(exc):
                return _rate_limited(f"{endpoint} throttled: {exc}")
            return error_envelope("twelvedata", f"{endpoint} failed: {exc}")
        if isinstance(payload, dict) and (
            payload.get("status") == "error" or "code" in payload
        ):
            return unavailable(
                "twelvedata",
                str(payload.get("message") or f"{endpoint} not covered."),
            )
        return live_envelope("twelvedata", payload, delayed=True)

    def _prep(self, symbol: str) -> tuple[str | None, dict | None]:
        missing = self._need_key()
        if missing:
            return None, missing
        td_symbol = to_td_symbol(symbol)
        if td_symbol is None:
            return None, unavailable(
                "twelvedata",
                f"Symbol '{symbol}' is not addressable on Twelve Data.",
            )
        return td_symbol, None

    def get_statistics(self, symbol: str) -> dict:
        """Company statistics: valuation metrics where the plan covers."""
        from .schema import field, num, text

        td_symbol, err = self._prep(symbol)
        if err:
            return err
        assert td_symbol is not None
        env = self._domain("/statistics", td_symbol)
        if env.get("status") != "live":
            return env
        p = env["data"] or {}
        stats = p.get("statistics") or p
        if not isinstance(stats, dict):
            return unavailable("twelvedata", "Statistics payload malformed.")

        def pick(*ks: str):
            return next(
                (stats.get(k) for k in ks if stats.get(k) is not None),
                None,
            )

        as_of = env.get("as_of")
        out = {
            "symbol": (symbol or "").strip().upper(),
            "market_cap": field(
                num(pick("market_capitalization", "market_cap")), "twelvedata", as_of
            ),
            "pe": field(
                num(pick("pe_ratio", "trailing_pe", "pe")), "twelvedata", as_of
            ),
            "pb": field(num(pick("pb_ratio", "price_book", "pb")), "twelvedata", as_of),
            "eps": field(
                num(pick("eps", "eps_ttm", "trailing_eps")), "twelvedata", as_of
            ),
            "dividend_yield": field(
                num(pick("dividend_yield", "dividend_yield_ttm")), "twelvedata", as_of
            ),
            "beta": field(num(pick("beta")), "twelvedata", as_of),
            "week_52_high": field(
                num(pick("week_52_high", "fifty_two_week_high")), "twelvedata", as_of
            ),
            "week_52_low": field(
                num(pick("week_52_low", "fifty_two_week_low")), "twelvedata", as_of
            ),
            "shares_outstanding": field(
                num(pick("shares_outstanding", "shares_float")), "twelvedata", as_of
            ),
            "company_name": field(
                text(pick("name", "company_name", "short_name")), "twelvedata", as_of
            ),
            "exchange": field(text(pick("exchange")), "twelvedata", as_of),
        }
        env["data"] = out
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_earnings_td(self, symbol: str) -> dict:
        td_symbol, err = self._prep(symbol)
        if err:
            return err
        assert td_symbol is not None
        env = self._domain("/earnings", td_symbol)
        if env.get("status") != "live":
            return env
        p = env["data"] or {}
        rows: list = []
        _earn = p.get("earnings")
        if isinstance(_earn, list):
            rows = _earn
        elif isinstance(p, list):
            rows = p
        clean = [
            {
                "date": r.get("date") or r.get("fiscal_date"),
                "reported_eps": r.get("eps_actual") or r.get("reported_eps"),
                "estimated_eps": r.get("eps_estimate") or r.get("estimated_eps"),
                "surprise": r.get("surprise"),
                "source": "twelvedata",
            }
            for r in rows
            if isinstance(r, dict)
        ][:12]
        if not clean:
            return unavailable(
                "twelvedata", f"No earnings rows for '{symbol}' on this plan."
            )
        env["data"] = {"symbol": (symbol or "").strip().upper(), "rows": clean}
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_actions_td(self, symbol: str) -> dict:
        """Dividends + splits with per-row sources."""
        td_symbol, err = self._prep(symbol)
        if err:
            return err
        assert td_symbol is not None
        dividends: list[dict] = []
        splits: list[dict] = []
        notes: list[str] = []
        for endpoint, bucket, keys in (
            ("/dividends", dividends, ("ex_date", "date")),
            ("/splits", splits, ("effective_date", "date")),
        ):
            env = self._domain(endpoint, td_symbol)
            if env.get("status") != "live":
                notes.append(f"{endpoint}: {env.get('message')}")
                continue
            p = env["data"] or {}
            items: list = []
            if isinstance(p, list):
                items = p
            elif isinstance(p, dict):
                cand = p.get("dividends") or p.get("splits") or p.get("data")
                if isinstance(cand, list):
                    items = cand
            for it in items:
                if not isinstance(it, dict):
                    continue
                date = next((it.get(k) for k in keys if it.get(k) is not None), None)
                if endpoint == "/dividends":
                    bucket.append(
                        {
                            "date": date,
                            "amount": it.get("amount"),
                            "currency": it.get("currency"),
                            "source": "twelvedata",
                        }
                    )
                else:
                    bucket.append(
                        {
                            "date": date,
                            "numerator": it.get("split_from") or it.get("numerator"),
                            "denominator": it.get("split_to") or it.get("denominator"),
                            "source": "twelvedata",
                        }
                    )
        if not dividends and not splits:
            return unavailable(
                "twelvedata",
                "No TD actions rows. " + " ".join(notes),
            )
        out = live_envelope(
            "twelvedata",
            {
                "symbol": (symbol or "").strip().upper(),
                "dividends": dividends[:40],
                "splits": splits[:40],
                "note": " ".join(notes),
            },
            delayed=True,
        )
        out["timeliness"] = "END-OF-DAY"
        return out

    def get_statement_td(
        self, symbol: str, statement: str = "income", period: str = "annual"
    ) -> dict:
        """Income/balance/cashflow statements (weight ~100 credits each).
        Only called on explicit user request; results cached 7 days."""
        from .schema import text

        td_symbol, err = self._prep(symbol)
        if err:
            return err
        assert td_symbol is not None
        fn = {
            "income": "/income_statement",
            "balance": "/balance_sheet",
            "cashflow": "/cash_flow",
        }.get((statement or "income").lower())
        if not fn:
            return error_envelope("twelvedata", f"Unknown statement '{statement}'.")
        env = self._domain(fn, td_symbol, cost=100)
        if env.get("status") != "live":
            return env
        p = env["data"] or {}
        key = "annual" if period != "quarterly" else "quarter"
        reports = (
            p.get(f"{key}_reports")
            or p.get(f"{key}Reports")
            or p.get("financials")
            or p.get("data")
            or []
        )
        if not isinstance(reports, list) or not reports:
            return unavailable(
                "twelvedata", f"No {period} {statement} rows on this plan."
            )
        normalized = []
        for rep in reports[:8]:
            if not isinstance(rep, dict):
                continue
            normalized.append({str(k): v for k, v in rep.items()})
        currency = text(
            (reports[0] or {}).get("reportedCurrency")
            or (reports[0] or {}).get("currency")
            or p.get("currency")
        )
        env["data"] = {
            "symbol": (symbol or "").strip().upper(),
            "statement": statement,
            "period": period,
            "currency": currency,
            "reports": normalized,
        }
        env["timeliness"] = "END-OF-DAY"
        return env
