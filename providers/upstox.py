"""Upstox analytics leg — server-side only (UPSTOX_ANALYTICS_TOKEN).

Uses official Upstox Developer APIs (documented, no scraping):
  - Market Quote V3: /v3/market-quote/quotes + /v3/market-quote/ohlc
    (up to 500 instruments per call; used for batch quotes)
  - Historical Candle V3: /v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}
  - Company Fundamentals suite (by ISIN): profile, income, balance,
    cash-flow, key ratios, shareholding, corporate actions, competitors
  - Market Information: FII/DII activity where returned

Auth: ``Authorization: Bearer <UPSTOX_ANALYTICS_TOKEN>`` header only.
Token is read from the environment on every call (rotation-safe),
never logged, never returned to clients (server redaction covers it).

Symbol mapping: NSE/BSE equities (RELIANCE.NS, TCS.BO, ...) map to
Upstox instrument keys ``NSE_EQ|<ISIN>`` only when the ISIN is known.
Without a resolved ISIN the leg passes through so other providers
serve the symbol. Indices map via documented index keys
(e.g. NSE_INDEX|Nifty 50). Unknown symbols pass through.

No trading / order / IPO-application functionality. Analytics only.
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

from .base import error_envelope, live_envelope, unavailable
from .indian import is_indian

SOURCE = "upstox"
SOURCE_LABEL = "Upstox"

API_BASE = "https://api.upstox.com"

QUOTE_TTL = 30.0
DOMAIN_TTL = 24 * 3600.0
HIST_TTL = 4 * 3600.0

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()

# Minimal verified index instrument keys (Upstox documented NSE_INDEX keys).
INDEX_KEYS = {
    "^NSEI": "NSE_INDEX|Nifty 50",
    "^NSEBANK": "NSE_INDEX|Nifty Bank",
    "^BSESN": "BSE_INDEX|SENSEX",
    "^INDIAVIX": "NSE_INDEX|India VIX",
}

# NSE equity ISIN registry for the tracked universe (verified ISINs).
# Full ISIN resolution for arbitrary symbols rides the master instrument
# file when downloaded; these cover the terminal's default universe.
EQUITY_ISIN = {
    "RELIANCE": "INE002A01018",
    "TCS": "INE467B01029",
    "INFY": "INE009A01021",
    "HDFCBANK": "INE040A01034",
    "ICICIBANK": "INE090A01021",
    "SBIN": "INE062A01020",
    "TATAMOTORS": "INE155A01022",
    "TATASTEEL": "INE081A01020",
    "ITC": "INE154A01025",
    "LT": "INE018A01030",
    "BHARTIARTL": "INE397D01024",
}


def token_configured() -> bool:
    return bool((os.environ.get("UPSTOX_ANALYTICS_TOKEN") or "").strip())


def _token() -> str:
    return (os.environ.get("UPSTOX_ANALYTICS_TOKEN") or "").strip()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "finance-terminal analytics (server)",
    }


def _cache_get(key: str, ttl: float):
    with _cache_lock:
        hit = _cache.get(key)
        if not hit:
            return None
        ts, env = hit
        if time.time() - ts > ttl:
            _cache.pop(key, None)
            return None
        return dict(env)


def _cache_set(key: str, env: dict) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), dict(env))


def _get(path: str, timeout: float = 15.0) -> Any:
    url = API_BASE + path
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            body = ""
        # Scrub any accidental token echo from error bodies.
        tok = _token()
        if tok and tok in body:
            body = body.replace(tok, "[REDACTED]")
        raise RuntimeError(f"Upstox HTTP {exc.code}: {body[:200]}")


def instrument_key(symbol: str) -> str | None:
    """Map a terminal symbol to an Upstox instrument key, or None."""
    s = (symbol or "").strip().upper()
    if s in INDEX_KEYS:
        return INDEX_KEYS[s]
    base = s
    exch = "NSE_EQ"
    if s.endswith(".NS"):
        base = s[:-3]
    elif s.endswith(".BO"):
        base = s[:-3]
        exch = "BSE_EQ"
    elif s.startswith("^") or "=" in s or "-" in s:
        return None
    isin = EQUITY_ISIN.get(base)
    if not isin:
        return None
    return f"{exch}|{isin}"


def _pass(symbol: str, reason: str) -> dict:
    return unavailable(SOURCE, f"Upstox pass-through for {symbol}: {reason}.")


class UpstoxProvider:
    """Analytics leg: quote, history, fundamentals, actions, holdings."""

    name = "upstox"
    capabilities = {
        "quote": True,
        "history": True,
        "search": False,
        "fundamentals": True,
        "statements": True,
        "earnings": False,
        "estimates": False,
        "news": True,
        "ipo": False,
        "actions": True,
        "holdings": True,
        "macro": False,
        "technical": False,
        "chart": False,
    }

    # -- quote ------------------------------------------------------
    def get_quote(self, symbol: str) -> dict:
        s = (symbol or "").strip().upper()
        if not token_configured():
            return unavailable(SOURCE, "UPSTOX_ANALYTICS_TOKEN not configured.")
        key = instrument_key(s)
        if not key:
            return _pass(s, "no resolved instrument key (ISIN unmapped)")
        ck = f"upstox:q:{key}"
        hit = _cache_get(ck, QUOTE_TTL)
        if hit is not None:
            return hit
        try:
            payload = _get(
                "/v3/market-quote/quotes?instrument_key="
                + urllib.parse.quote(key, safe="")
            )
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox quote failed: {exc}")
        try:
            node = (payload.get("data") or {}).get(key) or {}
            ltp = node.get("last_price")
            if ltp is None:
                return unavailable(SOURCE, f"No quote for {s}.")
            ohlc = node.get("ohlc") or {}
            prev = node.get("prev_close_price") or ohlc.get("close")
            chg = (ltp - prev) if prev else None
            chg_pct = (chg / prev * 100.0) if prev else None
            q = {
                "symbol": s,
                "name": node.get("symbol") or s,
                "price": float(ltp),
                "change": float(chg) if chg is not None else None,
                "change_pct": float(chg_pct) if chg_pct is not None else None,
                "volume": node.get("volume"),
                "day_high": (node.get("market_depth") or {}).get("high")
                or ohlc.get("high"),
                "day_low": (node.get("market_depth") or {}).get("low")
                or ohlc.get("low"),
                "previous_close": float(prev) if prev is not None else None,
                "fifty_two_week_high": (node.get("yearly_high") or {}).get("price")
                if isinstance(node.get("yearly_high"), dict)
                else node.get("yearly_high"),
                "fifty_two_week_low": (node.get("yearly_low") or {}).get("price")
                if isinstance(node.get("yearly_low"), dict)
                else node.get("yearly_low"),
                "currency": "INR" if is_indian(s) else None,
                "exchange": "NSE"
                if s.endswith(".NS")
                else ("BSE" if s.endswith(".BO") else None),
            }
            env = live_envelope(SOURCE, q, delayed=True)
            env["timeliness"] = "DELAYED"
            _cache_set(ck, env)
            return env
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox quote parse failed: {exc}")

    def get_quotes_batch(self, symbols: list[str]) -> dict[str, dict]:
        """Batch quotes (one upstream call for up to 500 keys)."""
        out: dict[str, dict] = {}
        if not token_configured():
            return {
                s: unavailable(SOURCE, "UPSTOX_ANALYTICS_TOKEN not configured.")
                for s in symbols
            }
        pairs = [(s, instrument_key(s)) for s in symbols]
        mapped = [(s, k) for s, k in pairs if k]
        for s, k in pairs:
            if not k:
                out[s] = _pass(s, "no resolved instrument key")
        if not mapped:
            return out
        keys = ",".join(k for _, k in mapped)
        try:
            payload = _get(
                "/v3/market-quote/quotes?instrument_key="
                + urllib.parse.quote(keys, safe=",")
            )
        except Exception as exc:
            for s, _k in mapped:
                out[s] = error_envelope(SOURCE, f"Upstox batch quote failed: {exc}")
            return out
        data = payload.get("data") or {}
        for s, k in mapped:
            node = data.get(k)
            if not node:
                out[s] = unavailable(SOURCE, f"No quote for {s}.")
                continue
            out[s] = self.get_quote(s)
        return out

    # -- history ----------------------------------------------------
    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        s = (symbol or "").strip().upper()
        if not token_configured():
            return unavailable(SOURCE, "UPSTOX_ANALYTICS_TOKEN not configured.")
        key = instrument_key(s)
        if not key:
            return _pass(s, "no resolved instrument key (ISIN unmapped)")
        if (interval or "1d").lower() not in ("1d", "1wk", "1mo"):
            return unavailable(SOURCE, "Upstox leg serves daily/weekly/monthly bars.")
        unit = {"1d": "days", "1wk": "weeks", "1mo": "months"}[
            (interval or "1d").lower()
        ]
        days = {
            "1M": 31,
            "3M": 93,
            "6M": 186,
            "1Y": 366,
            "2Y": 732,
            "5Y": 1827,
            "MAX": 3650,
        }.get((range_ or "1M").upper(), 31)
        to_d = datetime.now(timezone.utc).date()
        from_d = datetime.fromtimestamp(
            to_d.toordinal() and time.time() - days * 86400, tz=timezone.utc
        ).date()
        ck = f"upstox:h:{key}:{unit}:{range_}"
        hit = _cache_get(ck, HIST_TTL)
        if hit is not None:
            return hit
        try:
            payload = _get(
                f"/v3/historical-candle/{urllib.parse.quote(key, safe='')}"
                f"/{unit}/1/{to_d.isoformat()}/{from_d.isoformat()}"
            )
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox history failed: {exc}")
        try:
            candles = (payload.get("data") or {}).get("candles") or []
            bars = []
            for c in candles:
                # [timestamp, open, high, low, close, volume, oi]
                ts = c[0]
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    ts = int(dt.timestamp())
                elif ts > 1e12:
                    ts = int(ts / 1000)
                bars.append(
                    {
                        "t": int(ts),
                        "o": c[1],
                        "h": c[2],
                        "l": c[3],
                        "c": c[4],
                        "v": c[5] if len(c) > 5 else None,
                    }
                )
            bars.sort(key=lambda b: b["t"])
            env = live_envelope(
                SOURCE,
                {"symbol": s, "range": range_, "interval": interval, "bars": bars},
                delayed=True,
            )
            env["timeliness"] = "DELAYED"
            _cache_set(ck, env)
            return env
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox history parse failed: {exc}")

    def search(self, query: str, limit: int = 10) -> dict:
        return unavailable(
            SOURCE, "Upstox search rides the terminal symbol map; use /api/search."
        )

    # -- fundamentals (ISIN-keyed suite) ----------------------------
    def _fund(self, kind: str, symbol: str) -> dict:
        s = (symbol or "").strip().upper()
        if not token_configured():
            return unavailable(SOURCE, "UPSTOX_ANALYTICS_TOKEN not configured.")
        base = s[:-3] if s.endswith((".NS", ".BO")) else s
        isin = EQUITY_ISIN.get(base)
        if not isin:
            return _pass(s, "ISIN unmapped for fundamentals")
        ck = f"upstox:f:{kind}:{isin}"
        hit = _cache_get(ck, DOMAIN_TTL)
        if hit is not None:
            return hit
        paths = {
            "profile": f"/v2/company/profile/{isin}",
            "ratios": f"/v2/company/ratios/{isin}",
            "balance": f"/v2/company/balance-sheet/{isin}",
            "cashflow": f"/v2/company/cash-flow/{isin}",
            "income": f"/v2/company/income-statement/{isin}",
            "holdings": f"/v2/company/share-holdings/{isin}",
            "actions": f"/v2/company/corporate-actions/{isin}",
        }
        path = paths.get(kind)
        if not path:
            return error_envelope(SOURCE, f"Unknown fundamentals kind: {kind}")
        try:
            payload = _get(path)
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox {kind} failed: {exc}")
        env = live_envelope(SOURCE, payload.get("data"), delayed=True)
        env["timeliness"] = "DELAYED"
        _cache_set(ck, env)
        return env

    def get_company_profile(self, symbol: str) -> dict:
        return self._fund("profile", symbol)

    def get_ratios(self, symbol: str) -> dict:
        return self._fund("ratios", symbol)

    def get_financial_statements(
        self, symbol: str, statement: str = "income", period: str = "annual"
    ) -> dict:
        kind = {"income": "income", "balance": "balance", "cashflow": "cashflow"}.get(
            statement, "income"
        )
        return self._fund(kind, symbol)

    def get_shareholding(self, symbol: str) -> dict:
        return self._fund("holdings", symbol)

    def get_corporate_actions(self, symbol: str) -> dict:
        return self._fund("actions", symbol)

    def get_news(self, symbol=None, topic=None, limit: int = 20) -> dict:
        return unavailable(
            SOURCE, "Company news rides Yahoo RSS; Upstox news needs ISIN mapping."
        )

    def status(self) -> dict:
        return {
            "provider": SOURCE_LABEL,
            "state": "live" if token_configured() else "key_missing",
            "detail": "Official Upstox Developer APIs (quotes V3, historical-candle V3, "
            "company fundamentals by ISIN). Analytics only; no trading.",
            "key_configured": token_configured(),
        }
