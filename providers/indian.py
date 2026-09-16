"""Indian Stock Market API (0xramm) — OPTIONAL Indian-market leg.

Repository docs (github.com/0xramm/Indian-Stock-Market-API):
- No API key required. Endpoints: /stock, /stock/list, /search, /symbols.
- The repository states its data comes through Yahoo Finance, so this
  leg is labelled "Indian Stock Market API -> Yahoo Finance" with
  DELAYED timeliness — NEVER as an independent NSE real-time feed.

Availability (verified by live probe, Sep 2026):
- Documented base http://65.0.104.9/ TIMES OUT on all tested ports;
  upstream issue #9 ("Base URL is not working") is open.
- This leg therefore reports honest "unavailable (host unreachable)"
  and the chain falls through to Yahoo. If the host recovers, the leg
  activates automatically (base URL overridable via INDIAN_API_BASE_URL).

Only .NS/.BO symbols are attempted; everything else passes through.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from .base import MarketDataProvider, error_envelope, live_envelope, unavailable

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}
SOURCE = "indian-api"
SOURCE_LABEL = "Indian Stock Market API → Yahoo Finance"


def base_url() -> str:
    return (os.environ.get("INDIAN_API_BASE_URL") or "http://65.0.104.9").rstrip("/")


def is_indian(symbol: str) -> bool:
    s = (symbol or "").strip().upper()
    return s.endswith(".NS") or s.endswith(".BO")


def _get(path: str, params: dict, timeout: float = 6.0) -> Any:
    url = base_url() + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _num(v: Any) -> float | None:
    # res=num returns plain numbers; res=val wraps {value, unit}
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick(payload: dict, *keys: str) -> Any:
    for k in keys:
        if payload.get(k) is not None:
            return payload.get(k)
    # case-insensitive fallback
    lowered = {str(k).lower(): v for k, v in payload.items()}
    for k in keys:
        if lowered.get(k.lower()) is not None:
            return lowered.get(k.lower())
    return None


class IndianMarketApiProvider(MarketDataProvider):
    name = "indian-api"
    capabilities: dict[str, bool] = {"quote": True, "search": True}

    def _guard(self, symbol: str) -> dict | None:
        if not is_indian(symbol):
            return unavailable(
                SOURCE,
                f"Symbol '{symbol}' is not an NSE/BSE symbol; "
                "Indian leg passes through.",
            )
        return None

    def search(self, query: str, limit: int = 10) -> dict:
        query = (query or "").strip()
        if not query:
            return unavailable(SOURCE, "Empty search query.")
        try:
            payload = _get("/search", {"q": query})
        except Exception as exc:
            return error_envelope(
                SOURCE,
                f"Indian API host unreachable ({base_url()}): {exc}. "
                "Falling back to Yahoo.",
            )
        items = payload if isinstance(payload, list) else payload.get("results", [])
        results = []
        for it in items[:limit]:
            if not isinstance(it, dict):
                continue
            sym = _pick(it, "symbol", "Symbol", "ticker")
            if not sym:
                continue
            results.append(
                {
                    "symbol": str(sym).upper(),
                    "name": _pick(it, "name", "companyName", "company"),
                    "exchange": _pick(it, "exchange"),
                    "type": _pick(it, "type", "instrumentType"),
                    "sector": _pick(it, "sector"),
                    "industry": _pick(it, "industry"),
                }
            )
        if not results:
            return unavailable(SOURCE, f"No Indian matches for '{query}'.")
        env = live_envelope(SOURCE, {"results": results}, delayed=True)
        env["timeliness"] = "DELAYED"
        env["timeliness_note"] = SOURCE_LABEL + " (delayed, Yahoo-derived)."
        return env

    def get_quote(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        try:
            payload = _get("/stock", {"symbol": symbol, "res": "num"})
        except Exception as exc:
            return error_envelope(
                SOURCE,
                f"Indian API host unreachable ({base_url()}): {exc}. "
                "Falling back to Yahoo.",
            )
        if not isinstance(payload, dict):
            return unavailable(SOURCE, f"Unexpected response for '{symbol}'.")
        price = _num(
            _pick(payload, "price", "currentPrice", "lastPrice", "ltp", "close")
        )
        if price is None:
            return unavailable(SOURCE, f"No price in response for '{symbol}'.")
        prev = _num(_pick(payload, "previousClose", "prevClose"))
        quote = {
            "symbol": symbol,
            "name": _pick(payload, "name", "companyName", "company", "longName"),
            "exchange": _pick(payload, "exchange"),
            "currency": _pick(payload, "currency") or "INR",
            "instrument_type": _pick(payload, "type", "instrumentType"),
            "price": price,
            "previous_close": prev,
            "open": _num(_pick(payload, "open")),
            "day_high": _num(_pick(payload, "dayHigh", "high")),
            "day_low": _num(_pick(payload, "dayLow", "low")),
            "volume": _num(_pick(payload, "volume")),
            "change": _num(_pick(payload, "change")),
            "change_pct": _num(_pick(payload, "changePercent", "changePct", "pChange")),
            "fifty_two_week_high": _num(
                _pick(payload, "fiftyTwoWeekHigh", "week52High")
            ),
            "fifty_two_week_low": _num(_pick(payload, "fiftyTwoWeekLow", "week52Low")),
            "market_time": _pick(payload, "timestamp", "lastUpdated", "datetime"),
            "timezone": "Asia/Kolkata",
            "market_cap": _num(_pick(payload, "marketCap", "marketcap")),
            "pe": _num(_pick(payload, "pe", "peRatio", "pE")),
            "dividend_yield": _num(_pick(payload, "dividendYield", "divYield")),
            "sector": _pick(payload, "sector"),
        }
        if prev is not None and quote["change_pct"] is None and prev:
            quote["change_pct"] = (price - prev) / abs(prev) * 100.0
        env = live_envelope(SOURCE, quote, delayed=True)
        env["timeliness"] = "DELAYED"
        env["timeliness_note"] = SOURCE_LABEL + " (delayed, Yahoo-derived)."
        return env

    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        return unavailable(
            SOURCE, "No history endpoint on the Indian API; use Yahoo/Stooq legs."
        )
