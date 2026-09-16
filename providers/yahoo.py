"""Yahoo Finance provider (no API key required).

Uses the public chart API for quotes + history and the public
search API for instrument lookup. All responses are wrapped in
status envelopes (see providers/base.py).

Yahoo data is exchange-delayed; quotes are therefore labelled
"delayed" so the UI can display that honestly.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base import (
    CompanyProvider,
    MarketDataProvider,
    error_envelope,
    live_envelope,
    unavailable,
)

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}


class RateLimitedError(Exception):
    """Upstream answered 429 through all retries: back off + fall back."""


def rate_limited(source: str, detail: str) -> dict:
    return {
        "status": "rate_limited",
        "source": source,
        "as_of": None,
        "data": None,
        "message": f"RATE LIMITED: {detail} Cooling down and falling back.",
    }


# UI range -> Yahoo range param. NOTE: Yahoo uses "1mo" for one month;
# lowercase "1m" would mean a one-minute window.
RANGE_MAP = {
    "1D": "1d",
    "5D": "5d",
    "1M": "1mo",
    "3M": "3mo",
    "6M": "6mo",
    "1Y": "1y",
    "2Y": "2y",
    "5Y": "5y",
    "MAX": "max",
}
ALLOWED_RANGES = set(RANGE_MAP)
ALLOWED_INTERVALS = {"1m", "5m", "15m", "1h", "1d", "1wk", "1mo"}

_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 60.0  # seconds for quotes


def _http_get_json(url: str, timeout: float = 15.0) -> Any:
    # Retry transient rate-limits (HTTP 429) with backoff; anything else
    # raises immediately so callers can return honest error envelopes.
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code != 429 or attempt == 2:
                if exc.code == 429:
                    raise RateLimitedError(f"HTTP 429 from Yahoo for {url}")
                raise
            time.sleep(1.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def _cache_get(key: str):
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < CACHE_TTL:
        return hit[1]
    return None


def _cache_set(key: str, value: dict) -> None:
    _cache[key] = (time.time(), value)


class YahooMarketDataProvider(MarketDataProvider, CompanyProvider):
    name = "yahoo"
    capabilities: dict[str, bool] = {"quote": True, "history": True, "search": True}

    # -- search -----------------------------------------------------
    def search(self, query: str, limit: int = 10) -> dict:
        query = (query or "").strip()
        if not query:
            return unavailable("yahoo", "Empty search query.")
        n = max(1, min(limit, 25))
        url = (
            "https://query1.finance.yahoo.com/v1/finance/search?q="
            + urllib.parse.quote(query)
            + f"&quotesCount={n}&newsCount=0"
        )
        try:
            payload = _http_get_json(url)
        except RateLimitedError as exc:
            return rate_limited("yahoo", f"Search throttled: {exc}")
        except Exception as exc:  # network / auth
            return error_envelope("yahoo", f"Search failed: {exc}")
        results = []
        for q in (payload.get("quotes") or [])[:limit]:
            results.append(
                {
                    "symbol": q.get("symbol"),
                    "name": q.get("shortname") or q.get("longname"),
                    "exchange": q.get("exchDisp") or q.get("exchange"),
                    "type": q.get("quoteType"),
                    "sector": q.get("sector"),
                    "industry": q.get("industry"),
                }
            )
        if not results:
            return unavailable("yahoo", f"No instruments found for '{query}'.")
        return live_envelope("yahoo", {"results": results}, delayed=False)

    # -- quote ------------------------------------------------------
    def _chart(self, symbol: str, range_: str, interval: str) -> Any:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + urllib.parse.quote(symbol)
            + f"?interval={interval}&range={range_}"
        )
        return _http_get_json(url)

    def get_quote(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return unavailable("yahoo", "Empty symbol.")
        cached = _cache_get(f"q:{symbol}")
        if cached is not None:
            return cached
        try:
            payload = self._chart(symbol, "5d", "1d")
        except RateLimitedError as exc:
            return rate_limited("yahoo", f"Quote throttled for {symbol}: {exc}")
        except Exception as exc:
            return error_envelope("yahoo", f"Quote request failed for {symbol}: {exc}")
        try:
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                err = (payload.get("chart") or {}).get("error") or {}
                return unavailable(
                    "yahoo",
                    f"Invalid symbol or no data for '{symbol}': "
                    f"{err.get('description', 'unknown error')}",
                )
            meta = result[0].get("meta") or {}
            price = meta.get("regularMarketPrice")
            if price is None:
                return unavailable("yahoo", f"No price available for '{symbol}'.")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            quote = {
                "symbol": meta.get("symbol", symbol),
                "name": meta.get("longName") or meta.get("shortName"),
                "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
                "currency": meta.get("currency"),
                "instrument_type": meta.get("instrumentType"),
                "price": price,
                "previous_close": prev,
                "open": None,  # chart meta carries no session open; see history
                "day_high": meta.get("regularMarketDayHigh"),
                "day_low": meta.get("regularMarketDayLow"),
                "volume": meta.get("regularMarketVolume"),
                "change": None,
                "change_pct": meta.get("regularMarketChangePercent"),
                "fifty_two_week_high": meta.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": meta.get("fiftyTwoWeekLow"),
                "market_time": meta.get("regularMarketTime"),
                "timezone": meta.get("exchangeTimezoneName"),
                "delayed": True,
            }
            if prev:
                quote["change"] = price - prev
                if quote["change_pct"] is None:
                    quote["change_pct"] = (price - prev) / prev * 100.0
            env = live_envelope("yahoo", quote, delayed=True)
            # Yahoo's public feed is exchange-delayed. Never REAL-TIME.
            env["timeliness"] = "DELAYED"
            env["timeliness_note"] = (
                "Yahoo Finance public feed is exchange-delayed "
                "(typically ~15 min for NSE/BSE and US equities)."
            )
            _cache_set(f"q:{symbol}", env)
            return env
        except Exception as exc:
            return error_envelope("yahoo", f"Could not parse quote for {symbol}: {exc}")

    # -- history ----------------------------------------------------
    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        symbol = (symbol or "").strip().upper()
        range_ = (range_ or "1M").upper()
        interval = (interval or "1d").lower()
        if range_ not in ALLOWED_RANGES:
            return error_envelope("yahoo", f"Unsupported range '{range_}'.")
        if interval not in ALLOWED_INTERVALS:
            return error_envelope("yahoo", f"Unsupported interval '{interval}'.")
        yahoo_range = RANGE_MAP[range_]
        try:
            payload = self._chart(symbol, yahoo_range, interval)
        except RateLimitedError as exc:
            return rate_limited("yahoo", f"History throttled for {symbol}: {exc}")
        except Exception as exc:
            return error_envelope(
                "yahoo", f"History request failed for {symbol}: {exc}"
            )
        try:
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                return unavailable("yahoo", f"No history for '{symbol}'.")
            node = result[0]
            ts = node.get("timestamp") or []
            ind = node.get("indicators") or {}
            quote_leg = (ind.get("quote") or [{}])[0]
            adj = (ind.get("adjclose") or [{}])[0].get("adjclose") or []
            bars = []
            for i, t in enumerate(ts):
                try:
                    bars.append(
                        {
                            "t": t,
                            "o": _num_at(quote_leg.get("open"), i),
                            "h": _num_at(quote_leg.get("high"), i),
                            "l": _num_at(quote_leg.get("low"), i),
                            "c": _num_at(quote_leg.get("close"), i),
                            "adj": _num_at(adj, i),
                            "v": _num_at(quote_leg.get("volume"), i, is_int=True),
                        }
                    )
                except IndexError:
                    continue
            bars = [b for b in bars if b["c"] is not None]
            if not bars:
                return unavailable(
                    "yahoo", f"Insufficient history data for '{symbol}'."
                )
            meta = node.get("meta") or {}
            return live_envelope(
                "yahoo",
                {
                    "symbol": symbol,
                    "range": range_,
                    "interval": interval,
                    "currency": meta.get("currency"),
                    "delayed": True,
                    "bars": bars,
                },
                delayed=True,
            )
        except Exception as exc:
            return error_envelope(
                "yahoo", f"Could not parse history for {symbol}: {exc}"
            )

    # -- company ----------------------------------------------------
    def get_company_profile(self, symbol: str) -> dict:
        quote_env = self.get_quote(symbol)
        if quote_env["status"] != "delayed" and quote_env["status"] != "live":
            return quote_env
        q = quote_env["data"] or {}
        return {
            "status": quote_env["status"],
            "source": "yahoo",
            "as_of": quote_env.get("as_of"),
            "data": {
                "symbol": q.get("symbol"),
                "name": q.get("name"),
                "exchange": q.get("exchange"),
                "currency": q.get("currency"),
                "instrument_type": q.get("instrument_type"),
                "timezone": q.get("timezone"),
                # Sector/industry/business description require a
                # fundamentals provider; never invent them here.
                "sector": None,
                "industry": None,
                "description": None,
                "profile_note": (
                    "Detailed profile (sector, industry, business description) "
                    "requires a fundamentals provider. "
                    "Set FUNDAMENTALS_API_KEY to enable."
                ),
            },
            "message": None,
        }


def _num_at(seq, i, is_int: bool = False):
    if not seq:
        return None
    try:
        v = seq[i]
    except (IndexError, TypeError):
        return None
    if v is None:
        return None
    try:
        return int(v) if is_int else float(v)
    except (ValueError, TypeError):
        return None
