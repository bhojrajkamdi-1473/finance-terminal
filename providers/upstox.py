"""Upstox analytics leg — server-side only (UPSTOX_ANALYTICS_TOKEN).

Verified against the current official Upstox Developer documentation
(https://upstox.com/developer/api-documentation/):

  - Analytics Token: long-lived (1-year), read-only, GET-only, generated
    from Developer Apps > Analytics; no OAuth redirect; no static IP for
    market-data categories. Market Quote, Historical Data, Option Chain,
    Market Information, Fundamentals, News, IPO and WebSocket categories
    are eligible; account-specific read APIs need static IP (not used).
  - Market Quote V3: GET /v3/market-quote/quotes?instrument_key=<k,...>
    (max 500 keys). Response ``data`` is keyed by ``EXCHANGE:SYMBOL``
    (e.g. ``NSE_EQ:NHPC``); each node carries ``instrument_token``
    (the requested key), ``last_price``, ``net_change``,
    ``prev_close_price``, ``ohlc{open,high,low,close,volume,ts}``,
    ``volume``, ``year_high``/``year_low`` (numbers), ``timestamp``
    (ISO source time), ``depth{buy,sell}`` top-5, ``average_price``.
  - Historical Candle V3:
    GET /v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}
    units minutes|hours|days|weeks|months; days unit serves up to a
    decade. ``data.candles`` rows are
    [timestamp, open, high, low, close, volume, oi].
  - Fundamentals (all GET /v2/fundamentals/:isin/...):
    profile, balance-sheet, cash-flow, income-statement
    (?type=consolidated|standalone&time_period=yearly|quarterly&fs=true),
    share-holdings, key-ratios, corporate-actions, competitors.
    Monetary values are in INR crore; key ratios arrive as strings
    (``8.94%`` for ROE/ROA/ROCE); shareholding is quarterly % by
    category (promoters, fii, other_dii, mutual_funds, retail_and_other).
  - News: GET /v2/news?category=instrument_keys
    &instrument_keys=<up to 30>&page_number&page_size — past 7 days only.
    ``positions``/``holdings`` categories are account-bound and NOT used.
  - Rate limits (standard APIs): 50 req/s, 500 req/min. This leg stays
    far below via 30 s quote TTLs, 4 h history TTLs, 24 h domain TTLs,
    batch quotes (one call per 500 keys) and orchestrator fan-out.

Auth: ``Authorization: Bearer <UPSTOX_ANALYTICS_TOKEN>`` header only
(docs show Accept + Authorization; no Content-Type on GET). The token is
read from the environment on every call (rotation-safe) and NEVER
logged, cached, committed, or returned to clients. Error bodies are
scrubbed before being surfaced.

Out of scope (deliberately): OAuth trading-app flow, orders/trading,
IPO application, WebSocket streaming (REST snapshots satisfy the
terminal), option chain (no derivatives need), market-information and
competitors endpoints (unverified need), positions/holdings news
(account-bound + static IP).

Instrument resolution: NSE/BSE equities map to ``NSE_EQ|<ISIN>`` /
``BSE_EQ|<ISIN>`` only for verified ISINs in EQUITY_ISIN; indices via
documented ``NSE_INDEX|``/``BSE_INDEX|`` keys. Anything unmapped passes
through so other providers serve the symbol. ISINs are validated
(``^INE`` + 12 chars) before any request; UDAPI1206 (invalid ISIN)
surfaces as honest unavailable.
"""

from __future__ import annotations

import calendar
import json
import os
import re
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
NEWS_TTL = 10 * 60.0

# Bounded in-memory cache: successful responses only, oldest evicted.
_CACHE_MAX = 2000
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()

# Documented index keys (pattern confirmed: ``NSE_INDEX|India VIX``).
INDEX_KEYS = {
    "^NSEI": "NSE_INDEX|Nifty 50",
    "^NSEBANK": "NSE_INDEX|Nifty Bank",
    "^BSESN": "BSE_INDEX|SENSEX",
    "^INDIAVIX": "NSE_INDEX|India VIX",
}

# NSE equity ISIN registry for the tracked universe. These are
# exchange-published identifiers; an invalid entry surfaces as
# UDAPI1206 (invalid ISIN) and the leg passes through — never guessed
# at request time.
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

_ISIN_RE = re.compile(r"^INE[A-Z0-9]{9}$")

# Upstox fundamental error codes that mean "bad identifier", not outage.
_INVALID_CODES = frozenset(
    {"UDAPI1009", "UDAPI1011", "UDAPI100011", "UDAPI100095", "UDAPI1206"}
)


def token_configured() -> bool:
    return bool((os.environ.get("UPSTOX_ANALYTICS_TOKEN") or "").strip())


def _token() -> str:
    return (os.environ.get("UPSTOX_ANALYTICS_TOKEN") or "").strip()


def _headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer REDACTED",
        "Accept": "application/json",
        "User-Agent": "finance-terminal analytics (server)",
    }


def _auth_headers() -> dict[str, str]:
    h = _headers()
    h["Authorization"] = f"Bearer {_token()}"
    return h


def _scrub(text: str) -> str:
    tok = _token()
    if tok and tok in text:
        text = text.replace(tok, "[REDACTED]")
    return text


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
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)), None)
        _cache[key] = (time.time(), dict(env))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UpstoxAuthError(Exception):
    """401/403: token invalid, expired or revoked. Never retried blindly."""


class UpstoxRateLimited(Exception):
    """HTTP 429: back off; envelope carries status=rate_limited."""


class UpstoxBadIdentifier(Exception):
    """400/404 or UDAPI invalid-key/ISIN codes: honest unavailable."""


def _get(path: str, timeout: float = 15.0) -> Any:
    """GET an Upstox path. Returns the decoded body for status=success.

    Raises UpstoxAuthError / UpstoxRateLimited / UpstoxBadIdentifier /
    RuntimeError(transport/parse). Bodies with status=error are mapped
    via their UDAPI codes. Nothing credential-bearing ever escapes.
    """
    url = API_BASE + path
    req = urllib.request.Request(url, headers=_auth_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            body = ""
        body = _scrub(body)
        if exc.code in (401, 403):
            raise UpstoxAuthError(
                f"Upstox rejected the analytics token (HTTP {exc.code}). "
                "Regenerate UPSTOX_ANALYTICS_TOKEN in Developer Apps > Analytics."
            )
        if exc.code == 429:
            raise UpstoxRateLimited("Upstox rate limit hit (HTTP 429); backing off.")
        if exc.code in (400, 404):
            raise UpstoxBadIdentifier(f"Upstox HTTP {exc.code}: {body[:160]}")
        raise RuntimeError(f"Upstox HTTP {exc.code}: {body[:160]}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Upstox transport failed: {_scrub(str(exc))[:160]}")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"Upstox malformed JSON: {exc}")
    if isinstance(payload, dict) and payload.get("status") == "error":
        codes = " ".join(
            str(e.get("errorCode") or e.get("code") or "")
            for e in (payload.get("errors") or [])
            if isinstance(e, dict)
        )
        msg = _scrub(str(payload.get("message") or codes or "Upstox error")[:200])
        if any(c in codes for c in _INVALID_CODES):
            raise UpstoxBadIdentifier(
                f"Upstox invalid identifier ({codes.strip()}): {msg}"
            )
        raise RuntimeError(f"Upstox error ({codes.strip() or 'no-code'}): {msg}")
    return payload


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
    elif s.startswith("^") or "=" in s or "-" in s or "." in s:
        return None
    isin = EQUITY_ISIN.get(base)
    if not isin or not _ISIN_RE.match(isin):
        return None
    return f"{exch}|{isin}"


def isin_for(symbol: str) -> str | None:
    """Verified ISIN for a terminal symbol, or None (pass-through)."""
    s = (symbol or "").strip().upper()
    base = s[:-3] if s.endswith((".NS", ".BO")) else s
    isin = EQUITY_ISIN.get(base)
    if not isin or not _ISIN_RE.match(isin):
        return None
    return isin


def _pass(symbol: str, reason: str) -> dict:
    return unavailable(SOURCE, f"Upstox pass-through for {symbol}: {reason}.")


def _num(v: Any) -> float | None:
    if v in (None, "", "-", "None", "N/A", "NA", "null"):
        return None
    if isinstance(v, str):
        v = v.strip().rstrip("%").replace(",", "")
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _stamp(env: dict, source_ts: Any = None) -> dict:
    """Freshness pair: retrieved_at (server) + source_timestamp (venue)."""
    env["retrieved_at"] = _now_iso()
    if source_ts:
        env["source_timestamp"] = source_ts
    return env


def _find_quote_node(data: dict, key: str) -> dict:
    """V3 data is keyed by EXCHANGE:SYMBOL — locate via instrument_token."""
    if not isinstance(data, dict):
        return {}
    for node in data.values():
        if isinstance(node, dict) and node.get("instrument_token") == key:
            return node
    # Fallback: pipe→colon form used for index instruments.
    return (
        data.get(key.replace("|", ":"), {})
        if isinstance(data.get(key.replace("|", ":")), dict)
        else {}
    )


_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def period_label_to_date(label: Any) -> str | None:
    """'Mar 2025' -> '2025-03-31' (month-end). Returns None if unparseable."""
    m = re.match(r"^\s*([A-Za-z]{3,})\s+(\d{4})\s*$", str(label or ""))
    if not m:
        return None
    mon = _MONTHS.get(m.group(1)[:3].upper())
    if not mon:
        return None
    year = int(m.group(2))
    return f"{year:04d}-{mon:02d}-{calendar.monthrange(year, mon)[1]:02d}"


class UpstoxProvider:
    """Analytics leg: quote, history, fundamentals, actions, holdings, news."""

    name = "upstox"
    capabilities = {
        "quote": True,
        "history": True,
        "search": False,
        "fundamentals": True,
        "statements": True,
        "earnings": False,
        "estimates": False,
        "news": True,  # 7-day window, instrument_keys only
        "ipo": False,  # lifecycle read endpoints unverified for this use
        "actions": True,
        "holdings": True,
        "macro": False,
        "technical": False,
        "chart": False,
    }

    # -- quote ------------------------------------------------------
    def _parse_quote_node(self, symbol: str, key: str, node: dict) -> dict | None:
        ltp = _num(node.get("last_price"))
        if ltp is None:
            return None
        # Authoritative provider fields first; derived only as fallback.
        prev = _num(node.get("prev_close_price"))
        chg = _num(node.get("net_change"))
        if chg is None and prev:
            chg = ltp - prev
        chg_pct = (chg / prev * 100.0) if (chg is not None and prev) else None
        ohlc = node.get("ohlc") or {}
        return {
            "symbol": symbol,
            "name": node.get("symbol") or symbol,
            "price": ltp,
            "change": chg,
            "change_pct": chg_pct,
            "volume": node.get("volume"),
            "average_price": _num(node.get("average_price")),
            "day_high": _num(ohlc.get("high")),
            "day_low": _num(ohlc.get("low")),
            "day_open": _num(ohlc.get("open")),
            "previous_close": prev,
            "fifty_two_week_high": _num(node.get("year_high")),
            "fifty_two_week_low": _num(node.get("year_low")),
            "currency": "INR" if is_indian(symbol) else None,
            "exchange": "NSE"
            if symbol.endswith(".NS")
            else ("BSE" if symbol.endswith(".BO") else None),
        }

    def _quote_envelope(self, symbol: str, key: str, node: dict) -> dict:
        q = self._parse_quote_node(symbol, key, node)
        if q is None:
            return unavailable(SOURCE, f"No quote for {symbol} in Upstox response.")
        env = live_envelope(SOURCE, q, delayed=True)
        env["timeliness"] = "DELAYED"
        return _stamp(env, node.get("timestamp") or node.get("last_trade_time"))

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
        except UpstoxBadIdentifier as exc:
            return unavailable(SOURCE, f"Upstox has no quote for {s}: {exc}")
        except UpstoxRateLimited as exc:
            return {
                "status": "rate_limited",
                "source": SOURCE,
                "as_of": None,
                "data": None,
                "code": "RATE_LIMIT",
                "message": str(exc),
            }
        except UpstoxAuthError as exc:
            return error_envelope(SOURCE, str(exc), code="AUTH")
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox quote failed: {exc}")
        node = _find_quote_node(payload.get("data") or {}, key)
        if not node:
            return unavailable(SOURCE, f"No quote for {s} in Upstox response.")
        env = self._quote_envelope(s, key, node)
        if env.get("status") in ("live", "delayed"):
            _cache_set(ck, env)
        return env

    def get_quotes_batch(self, symbols: list[str]) -> dict[str, dict]:
        """One upstream call for up to 500 keys; parsed per instrument_token."""
        out: dict[str, dict] = {}
        if not token_configured():
            return {
                s: unavailable(SOURCE, "UPSTOX_ANALYTICS_TOKEN not configured.")
                for s in symbols
            }
        pairs = [(s, instrument_key(s)) for s in symbols]
        mapped = [(s, k) for s, k in pairs if k]
        for s, _k in pairs:
            if not _k:
                out[s] = _pass(s, "no resolved instrument key")
        if not mapped:
            return out
        keys = ",".join(k for _, k in mapped[:500])
        try:
            payload = _get(
                "/v3/market-quote/quotes?instrument_key="
                + urllib.parse.quote(keys, safe=",")
            )
        except UpstoxBadIdentifier as exc:
            for s, _k in mapped:
                out[s] = unavailable(SOURCE, f"Upstox batch quote: {exc}")
            return out
        except Exception as exc:
            for s, _k in mapped:
                out[s] = error_envelope(SOURCE, f"Upstox batch quote failed: {exc}")
            return out
        data = payload.get("data") or {}
        for s, k in mapped:
            node = _find_quote_node(data, k)
            if not node:
                out[s] = unavailable(SOURCE, f"No quote for {s} in Upstox response.")
                continue
            out[s] = self._quote_envelope(s, k, node)
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
        # Days unit serves up to a decade; clamp so the API never 4XXs.
        days = {
            "1M": 31,
            "3M": 93,
            "6M": 186,
            "1Y": 366,
            "2Y": 732,
            "5Y": 1827,
            "MAX": 3650,
        }.get((range_ or "1M").upper(), 31)
        days = min(days, 3650)
        now = datetime.now(timezone.utc)
        to_d = now.date().isoformat()
        from_d = (
            datetime.fromtimestamp(now.timestamp() - days * 86400, tz=timezone.utc)
            .date()
            .isoformat()
        )
        ck = f"upstox:h:{key}:{unit}:{range_}:{interval}"
        hit = _cache_get(ck, HIST_TTL)
        if hit is not None:
            return hit
        try:
            payload = _get(
                f"/v3/historical-candle/{urllib.parse.quote(key, safe='')}"
                f"/{unit}/1/{to_d}/{from_d}"
            )
        except UpstoxBadIdentifier as exc:
            return unavailable(SOURCE, f"Upstox has no history for {s}: {exc}")
        except UpstoxRateLimited as exc:
            return {
                "status": "rate_limited",
                "source": SOURCE,
                "as_of": None,
                "data": None,
                "code": "RATE_LIMIT",
                "message": str(exc),
            }
        except UpstoxAuthError as exc:
            return error_envelope(SOURCE, str(exc), code="AUTH")
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox history failed: {exc}")
        try:
            candles = (payload.get("data") or {}).get("candles") or []
            bars: list[dict[str, Any]] = []
            for c in candles:
                # [timestamp, open, high, low, close, volume, oi]
                if not isinstance(c, (list, tuple)) or len(c) < 5:
                    continue
                ts = c[0]
                if isinstance(ts, str):
                    try:
                        ts = int(
                            datetime.fromisoformat(
                                ts.replace("Z", "+00:00")
                            ).timestamp()
                        )
                    except ValueError:
                        continue
                elif isinstance(ts, (int, float)):
                    ts = int(ts / 1000) if ts > 1e12 else int(ts)
                else:
                    continue
                o, hi, lo, cl = (_num(c[1]), _num(c[2]), _num(c[3]), _num(c[4]))
                if None in (o, hi, lo, cl):
                    continue
                bars.append(
                    {
                        "t": ts,
                        "o": o,
                        "h": hi,
                        "l": lo,
                        "c": cl,
                        "v": c[5] if len(c) > 5 else None,
                    }
                )
            bars.sort(key=lambda b: int(b["t"]))
            if not bars:
                return unavailable(SOURCE, f"No usable candles for {s} from Upstox.")
            env = live_envelope(
                SOURCE,
                {
                    "symbol": s,
                    "range": range_,
                    "interval": interval,
                    "bars": bars,
                    "adjustment_note": "OHLC as provided by Upstox; "
                    "adjustment policy unverified — cross-checked via "
                    "reconciliation, never averaged.",
                },
                delayed=True,
            )
            env["timeliness"] = "DELAYED"
            env = _stamp(env)
            _cache_set(ck, env)
            return env
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox history parse failed: {exc}")

    def search(self, query: str, limit: int = 10) -> dict:
        return unavailable(
            SOURCE, "Upstox search rides the terminal symbol map; use /api/search."
        )

    # -- fundamentals (verified /v2/fundamentals/:isin/... suite) ---
    def _fund_path(self, kind: str, isin: str, period: str) -> str | None:
        base = f"/v2/fundamentals/{isin}"
        annual = (period or "annual").lower() == "annual"
        tp = "yearly" if annual else "quarterly"
        if kind == "profile":
            return f"{base}/profile"
        if kind == "ratios":
            return f"{base}/key-ratios"
        if kind == "holdings":
            return f"{base}/share-holdings"
        if kind == "actions":
            return f"{base}/corporate-actions"
        if kind == "income":
            return f"{base}/income-statement?type=consolidated&time_period={tp}&fs=true"
        if kind == "balance":
            # Balance sheet documents type+fs only; always annual detail.
            return f"{base}/balance-sheet?type=consolidated&fs=true"
        if kind == "cashflow":
            return f"{base}/cash-flow?type=consolidated&time_period={tp}&fs=true"
        return None

    def _fund_raw(self, kind: str, symbol: str, period: str = "annual") -> dict:
        """Raw verified-suite fetch. Returns envelope (cached on success)."""
        s = (symbol or "").strip().upper()
        if not token_configured():
            return unavailable(SOURCE, "UPSTOX_ANALYTICS_TOKEN not configured.")
        isin = isin_for(s)
        if not isin:
            return _pass(s, "ISIN unmapped for fundamentals")
        path = self._fund_path(kind, isin, period)
        if not path:
            return error_envelope(SOURCE, f"Unknown fundamentals kind: {kind}")
        ck = f"upstox:f:{kind}:{isin}:{period}"
        hit = _cache_get(ck, DOMAIN_TTL)
        if hit is not None:
            return hit
        try:
            payload = _get(path)
        except UpstoxBadIdentifier as exc:
            return unavailable(SOURCE, f"Upstox has no {kind} for {s}: {exc}")
        except UpstoxRateLimited as exc:
            return {
                "status": "rate_limited",
                "source": SOURCE,
                "as_of": None,
                "data": None,
                "code": "RATE_LIMIT",
                "message": str(exc),
            }
        except UpstoxAuthError as exc:
            return error_envelope(SOURCE, str(exc), code="AUTH")
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox {kind} failed: {exc}")
        env = live_envelope(SOURCE, payload.get("data"), delayed=True)
        env["timeliness"] = "DELAYED"
        env = _stamp(env)
        if env.get("status") in ("live", "delayed") and env.get("data") is not None:
            _cache_set(ck, env)
        return env

    def get_company_profile(self, symbol: str) -> dict:
        """{Name?, Sector, Description} — Upstox profile has no company name;
        identity stays with the quote chain; sector/description merge in."""
        s = (symbol or "").strip().upper()
        env = self._fund_raw("profile", s)
        if env.get("status") not in ("live", "delayed") or not env.get("data"):
            return env
        d = env["data"] or {}
        out = dict(env)
        out["data"] = {
            "symbol": s,
            "name": None,  # profile carries no company name — never invented
            "exchange": "NSE"
            if s.endswith(".NS")
            else ("BSE" if s.endswith(".BO") else None),
            "currency": "INR",
            "Sector": d.get("sector"),
            "sector": d.get("sector"),
            "Description": d.get("company_profile"),
            "description": d.get("company_profile"),
            "sector_market_cap": d.get("sector_market_cap_inr"),
        }
        return out

    def get_ratios(self, symbol: str) -> dict:
        """Key ratios -> flat AV-style overview dict + benchmarks/definitions.

        Definitions (Upstox-documented): P/E = price/EPS; P/B = price/book;
        ROA = NI/assets %; ROE = NI/equity %; ROCE = EBIT/capital-employed %;
        EV/EBITDA. Compatible with the terminal valuation merge.
        """
        s = (symbol or "").strip().upper()
        env = self._fund_raw("ratios", s)
        if env.get("status") not in ("live", "delayed") or not env.get("data"):
            return env
        rows = env["data"] if isinstance(env["data"], list) else []
        vals: dict[str, float] = {}
        bench: dict[str, float] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = str(r.get("name") or "").strip().upper().replace(" ", "")
            v, b = _num(r.get("company_value")), _num(r.get("sector_value"))
            if v is not None:
                vals[name] = v
            if b is not None:
                bench[name] = b
        if not vals:
            return unavailable(SOURCE, f"No key ratios for {s} from Upstox.")
        out = dict(env)
        out["data"] = {
            "Symbol": s,
            "Currency": "INR",
            "PERatio": vals.get("P/E"),
            "PriceToBookRatio": vals.get("P/B"),
            "ReturnOnAssetsTTM": vals.get("ROA"),
            "ROE": vals.get("ROE"),
            "ROCE": vals.get("ROCE"),
            "EVEBITDA": vals.get("EV/EBITDA"),
            "sector_benchmarks": bench or None,
            "definitions": {
                "PERatio": "Market price per share / earnings per share (Upstox).",
                "PriceToBookRatio": "Market price per share / book value per share (Upstox).",
                "ReturnOnAssetsTTM": "Net income as % of total assets (Upstox).",
                "ROE": "Net income as % of shareholders' equity (Upstox).",
                "ROCE": "EBIT as % of capital employed (Upstox).",
                "EVEBITDA": "Enterprise value / EBITDA (Upstox).",
            },
        }
        return out

    # -- statements: Upstox crore figures -> canonical AV-style reports --
    # Per-share lines are quoted in INR (never scaled); monetary lines
    # arrive in INR crore and convert to absolute INR (x 1e7).
    _PER_SHARE_KEYS = frozenset({"basicEPS", "dilutedEPS"})

    @staticmethod
    def _harvest_full_statement(
        full: Any, wanted: dict[str, list[str]]
    ) -> dict[str, dict[str, float]]:
        """full_statement particulars -> {line_key: {fiscalDateEnding: abs_value}}.

        Exact normalized matching only: a bare "Tax" needle must never
        match "Profit After Tax", and "Current Liabilities" must never
        match "Non-Current Liabilities" (both regression-tested).
        Unknown labels are skipped — never force-mapped.
        """

        def _norm(t: Any) -> str:
            return re.sub(r"\s+", " ", str(t or "").strip().lower())

        got: dict[str, dict[str, float]] = {}
        if not isinstance(full, list):
            return got
        for item in full:
            if not isinstance(item, dict):
                continue
            part = _norm(item.get("particular"))
            key = None
            for line_key, needles in wanted.items():
                if any(_norm(n) == part for n in needles):
                    key = line_key
                    break
            if key is None:
                continue
            scale = 1.0 if key in UpstoxProvider._PER_SHARE_KEYS else 1e7
            for h in item.get("history") or []:
                if not isinstance(h, dict):
                    continue
                fed = period_label_to_date(h.get("period"))
                v = _num(h.get("value"))
                if fed and v is not None:
                    got.setdefault(key, {})[fed] = v * scale
        return got

    def get_financial_statements(
        self, symbol: str, statement: str = "income", period: str = "annual"
    ) -> dict:
        s = (symbol or "").strip().upper()
        statement = (statement or "income").lower()
        period = (period or "annual").lower()
        if statement not in ("income", "balance", "cashflow"):
            return error_envelope(SOURCE, f"Unknown statement '{statement}'.")
        if period not in ("annual", "quarterly"):
            return error_envelope(SOURCE, f"Unknown period '{period}'.")
        env = self._fund_raw(statement, s, period)
        if env.get("status") not in ("live", "delayed") or not env.get("data"):
            return env
        d = env["data"] or {}
        if not isinstance(d, dict):
            return unavailable(
                SOURCE, f"Unexpected {statement} shape for {s} from Upstox."
            )
        scope = str(d.get("type") or "consolidated")
        tper = str(
            d.get("time_period") or ("yearly" if period == "annual" else "quarterly")
        )
        ptype = "annual" if tper == "yearly" else "quarterly"
        if statement == "income":
            lines = self._harvest_full_statement(
                d.get("full_statement"),
                {
                    "totalRevenue": ["Total Revenue"],
                    "operatingIncome": ["Profit Before Tax"],
                    "incomeTaxExpense": ["Tax"],
                    "netIncome": ["Profit After Tax"],
                    "basicEPS": ["EPS - Basic"],
                    "dilutedEPS": ["EPS - Diluted"],
                },
            )
            # Category cross-check (revenue/operating_profit/net_profit).
            cats = {
                str(c.get("category")): c.get("history") or []
                for c in (d.get("income_statement") or [])
                if isinstance(c, dict)
            }
        elif statement == "balance":
            lines = self._harvest_full_statement(
                d.get("full_statement"),
                {
                    "totalAssets": ["Total Assets"],
                    "totalCurrentAssets": ["Current Assets"],
                    "totalCurrentLiabilities": ["Current Liabilities"],
                    "totalShareholderEquity": ["Equity Capital"],
                    "totalEquityLiabilities": ["Total Equity & Liabilities"],
                },
            )
            # Summary history carries total_asset/total_liability per period.
            for h in d.get("history") or []:
                if not isinstance(h, dict):
                    continue
                fed = period_label_to_date(h.get("period"))
                if not fed:
                    continue
                ta, tl = _num(h.get("total_asset")), _num(h.get("total_liability"))
                if ta is not None:
                    lines.setdefault("totalAssets", {}).setdefault(fed, ta * 1e7)
                if tl is not None:
                    lines.setdefault("totalLiabilities", {}).setdefault(fed, tl * 1e7)
            cats = {}
        else:  # cashflow — exact documented-style labels only; anything
            # else is honestly unavailable (never force-mapped).
            lines = self._harvest_full_statement(
                d.get("full_statement"),
                {
                    "operatingCashflow": [
                        "Operating Cash Flow",
                        "Cash from Operations",
                        "Net Cash from Operating Activities",
                    ],
                    "capitalExpenditures": [
                        "Capital Expenditure",
                        "Purchase of Fixed Assets",
                    ],
                    "dividendPayout": ["Dividends Paid", "Dividend Paid"],
                    "netIncome": ["Profit After Tax", "Net Income"],
                },
            )
            cats = {}
        dates = sorted({dt for per in lines.values() for dt in per}, reverse=True)[:12]
        reports = []
        for dt in dates:
            row: dict[str, Any] = {"fiscalDateEnding": dt}
            for lk, per in lines.items():
                if dt in per:
                    row[lk] = per[dt]
            reports.append(row)
        if not reports:
            # Fall back to category histories (income) before giving up.
            if statement == "income" and cats:
                by_date: dict[str, dict] = {}
                cmap = {
                    "revenue": "totalRevenue",
                    "operating_profit": "operatingIncome",
                    "net_profit": "netIncome",
                }
                for cat, hist in cats.items():
                    line_key: str | None = cmap.get(cat)
                    if not line_key:
                        continue
                    lk = line_key
                    for h in hist:
                        fed = period_label_to_date((h or {}).get("period"))
                        v = _num((h or {}).get("value"))
                        if fed and v is not None:
                            by_date.setdefault(fed, {})[lk] = v * 1e7
                reports = [
                    {"fiscalDateEnding": dt, **vals}
                    for dt, vals in sorted(by_date.items(), reverse=True)[:12]
                ]
            if not reports:
                return unavailable(
                    SOURCE, f"No {period} {statement} data for '{s}' from Upstox."
                )
        # Balance identity validation: Assets ≈ Equity+Liabilities.
        identity = None
        if statement == "balance":
            checks = []
            for r in reports:
                ta = r.get("totalAssets")
                te = r.get("totalEquityLiabilities")
                if ta is not None and te is not None and ta:
                    diff = abs(ta - te) / abs(ta) * 100.0
                    checks.append(
                        {
                            "period": r["fiscalDateEnding"],
                            "diff_pct": round(diff, 3),
                            "ok": diff <= 1.0,
                        }
                    )
            identity = {
                "rule": "Total Assets ≈ Total Equity & Liabilities (tol 1%)",
                "checks": checks,
            } or None
        out = dict(env)
        out["data"] = {
            "symbol": s,
            "statement": statement,
            "period": ptype,
            "scope": scope,
            "currency": "INR",
            "units": "absolute INR (converted from Upstox INR-crore x 1e7)",
            "reports": reports,
            "identity_check": identity,
        }
        return out

    def get_shareholding(self, symbol: str) -> dict:
        """Quarterly % by category -> canonical {ownership:[...]} + trends."""
        s = (symbol or "").strip().upper()
        env = self._fund_raw("holdings", s)
        if env.get("status") not in ("live", "delayed") or not env.get("data"):
            return env
        rows = env["data"] if isinstance(env["data"], list) else []
        labels = {
            "promoters": "Promoters",
            "fii": "FII",
            "other_dii": "DII",
            "mutual_funds": "Mutual Funds",
            "retail_and_other": "Public",
        }
        ownership = []
        for cat in rows:
            if not isinstance(cat, dict):
                continue
            key = str(cat.get("category") or "")
            hist = [h for h in (cat.get("history") or []) if isinstance(h, dict)]
            if not hist:
                continue
            latest = hist[0]
            pct = _num(latest.get("value"))
            if pct is None:
                continue
            ownership.append(
                {
                    "category": labels.get(key, key or "Other"),
                    "holding_date": latest.get("period"),
                    "percentage": pct,
                    "trend": [
                        {"period": h.get("period"), "percentage": _num(h.get("value"))}
                        for h in hist[:8]
                    ],
                }
            )
        if not ownership:
            return unavailable(SOURCE, f"No ownership split for '{s}' from Upstox.")
        out = dict(env)
        out["data"] = {
            "symbol": s,
            "ownership": ownership,
            "note": "Provider-reported quarterly filing percentages (Upstox); not inferred.",
        }
        return out

    def get_corporate_actions(self, symbol: str) -> dict:
        """Events -> canonical {dividends:[{date,amount}], splits:[{date,...}]}."""
        s = (symbol or "").strip().upper()
        env = self._fund_raw("actions", s)
        if env.get("status") not in ("live", "delayed") or not env.get("data"):
            return env
        events = env["data"] if isinstance(env["data"], list) else []
        dividends, splits, other = [], [], []
        for e in events:
            if not isinstance(e, dict):
                continue
            name = str(e.get("name") or "")
            date = e.get("expiry_date")
            details = {
                str(x.get("name")): str(x.get("value"))
                for x in (e.get("event_details") or [])
                if isinstance(x, dict)
            }
            if name.lower() == "dividend":
                amt = _num(e.get("amount"))
                if date and amt is not None:
                    dividends.append(
                        {
                            "date": date,
                            "amount": amt,
                            "currency": "INR",
                            "kind": details.get("Dividend type"),
                            "source": SOURCE,
                        }
                    )
            elif name.lower() in ("split", "bonus"):
                ratio = str(e.get("ratio") or "")
                m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$", ratio)
                if date and m:
                    splits.append(
                        {
                            "date": date,
                            "numerator": float(m.group(1)),
                            "denominator": float(m.group(2)),
                            "kind": name,
                            "source": SOURCE,
                        }
                    )
                else:
                    other.append({"date": date, "kind": name, "detail": details})
            else:
                other.append({"date": date, "kind": name or "Other", "detail": details})
        if not dividends and not splits and not other:
            return unavailable(SOURCE, f"No corporate actions for '{s}' from Upstox.")
        out = dict(env)
        out["data"] = {
            "symbol": s,
            "dividends": dividends[:40],
            "splits": splits[:40],
            "other": other[:20],
            "note": "ISIN-linked exchange events (Upstox); announcement/ex/record "
            "dates preserved per row detail where provided.",
        }
        return out

    def get_news(
        self, symbol: str | None = None, topic: Any = None, limit: int = 20
    ) -> dict:
        """Past-7-day instrument news -> canonical {items:[...]} for the
        existing dedup pipeline (URL + headline-similarity, entity-ranked)."""
        s: str | None = (symbol or "").strip().upper() or None
        if not token_configured():
            return unavailable(SOURCE, "UPSTOX_ANALYTICS_TOKEN not configured.")
        if not s:
            return unavailable(SOURCE, "Upstox news needs a symbol (7-day window).")
        key = instrument_key(s)
        if not key:
            return _pass(s, "no resolved instrument key (ISIN unmapped)")
        try:
            limit = max(1, min(int(limit or 20), 100))
        except (TypeError, ValueError):
            limit = 20
        ck = f"upstox:n:{key}:{limit}"
        hit = _cache_get(ck, NEWS_TTL)
        if hit is not None:
            return hit
        try:
            payload = _get(
                "/v2/news?category=instrument_keys&instrument_keys="
                + urllib.parse.quote(key, safe="")
                + f"&page_number=1&page_size={limit}"
            )
        except UpstoxBadIdentifier as exc:
            return unavailable(SOURCE, f"Upstox has no news for {s}: {exc}")
        except UpstoxRateLimited as exc:
            return {
                "status": "rate_limited",
                "source": SOURCE,
                "as_of": None,
                "data": None,
                "code": "RATE_LIMIT",
                "message": str(exc),
            }
        except UpstoxAuthError as exc:
            return error_envelope(SOURCE, str(exc), code="AUTH")
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox news failed: {exc}")
        try:
            data = payload.get("data") or {}
            raw_items = data.get(key, data.get(key.replace("|", ":"), [])) or []
            items = []
            for n in raw_items:
                if not isinstance(n, dict):
                    continue
                url = n.get("article_link")
                title = n.get("heading")
                if not url or not title:
                    continue
                ts = n.get("published_time")
                pub = None
                if isinstance(ts, (int, float)):
                    pub = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
                items.append(
                    {
                        "title": title,
                        "summary": n.get("summary"),
                        "url": url,
                        "published_at": pub,
                        "source": "Upstox News",
                        "thumbnail": n.get("thumbnail"),
                    }
                )
            if not items:
                return unavailable(
                    SOURCE,
                    f"No Upstox news in the past 7 days for {s}.",
                    code="EMPTY_WINDOW",
                )
            env = live_envelope(SOURCE, {"items": items[:limit]}, delayed=True)
            env["timeliness"] = "DELAYED"
            env["window"] = "past 7 days (Upstox-documented)"
            env = _stamp(env)
            _cache_set(ck, env)
            return env
        except Exception as exc:
            return error_envelope(SOURCE, f"Upstox news parse failed: {exc}")

    def status(self) -> dict:
        # key_configured is a boolean only — the value never leaves here.
        return {
            "provider": SOURCE_LABEL,
            "state": "live" if token_configured() else "key_missing",
            "detail": "Verified Upstox Developer APIs: market-quote V3, "
            "historical-candle V3, /v2/fundamentals/:isin suite, "
            "/v2/news (7-day, instrument_keys). Analytics only; no trading.",
            "key_configured": token_configured(),
        }
