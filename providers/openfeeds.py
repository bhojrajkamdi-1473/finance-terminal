"""Open (no-key) public data feeds — server-side only, no credentials exist.

Verified live against public endpoints (all HTTPS, no registration):

  - Frankfurter (api.frankfurter.app, ECB euro reference rates):
    GET /latest?from=USD&to=INR,EUR and GET /<from>..<to>?from=&to=.
    Weekend/holiday dates snap to the previous publishing day.
  - CoinGecko free (api.coingecko.com/api/v3, ~10-30 req/min shared):
    /simple/price and /coins/markets. Cached aggressively; never hammered.
  - US Treasury Fiscal Data (api.fiscaldata.treasury.gov, no key):
    average interest rates by security type (monthly).
  - SEC EDGAR full-text search (efts.sec.gov/LATEST/search-index):
    filing discovery (form, company, date). Links to official filings.

Out of scope (deliberately): NSE India direct (403s non-browser
clients — fragile scraping avoided; Yahoo/Upstox cover India),
Econdb (datasets endpoint unverified), er-api (Frankfurter covers FX).

All responses are normalized to terminal canonical shapes (bars, quote
fields, macro points, filings) with honest delayed/EOD timeliness.
Failures become unavailable/error envelopes — never synthetic values.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .base import error_envelope, live_envelope, unavailable

SOURCE = "openfeeds"
USER_AGENT = "FINSIGHT-terminal analytics (server)"

_Q_TTL = 300.0
_H_TTL = 4 * 3600.0
_M_TTL = 24 * 3600.0

_CACHE_MAX = 500
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


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


def _fetch(url: str, timeout: float = 15.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("RATE_LIMITED")
        raise RuntimeError(f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"transport failed: {str(exc)[:120]}")
    except ValueError as exc:
        raise RuntimeError(f"malformed JSON: {exc}")


def _stamp(env: dict, source_ts: Any = None) -> dict:
    env["retrieved_at"] = _now_iso()
    if source_ts:
        env["source_timestamp"] = source_ts
    return env


# ---------------------------------------------------------------- FX ---
_FX_ALIASES = {
    "USDINR": ("USD", "INR"), "USDEUR": ("USD", "EUR"), "USDGBP": ("USD", "GBP"),
    "USDJPY": ("USD", "JPY"), "EURUSD": ("EUR", "USD"), "EURINR": ("EUR", "INR"),
    "GBPINR": ("GBP", "INR"), "USDINR=X": ("USD", "INR"), "INR=X": ("USD", "INR"),
    "EUR=X": ("EUR", "USD"), "INR": ("USD", "INR"),
}


def fx_pair_key(symbol: str) -> tuple[str, str] | None:
    """Map a terminal FX symbol to (base, quote), or None (pass-through)."""
    s = (symbol or "").strip().upper().replace("=X", "").replace("-", "").replace("/", "")
    if len(s) == 6 and s[:3].isalpha() and s[3:].isalpha():
        return s[:3], s[3:]
    return _FX_ALIASES.get(s)


def fx_latest(symbol: str) -> dict:
    """ECB reference rate for an FX pair. Delayed/EOD by construction."""
    s = (symbol or "").strip().upper()
    pair = fx_pair_key(s)
    if not pair:
        return unavailable(SOURCE, f"No FX mapping for {s}.")
    base, quote = pair
    ck = f"openfeeds:fx:{base}:{quote}"
    hit = _cache_get(ck, _Q_TTL)
    if hit is not None:
        return hit
    try:
        payload = _fetch(
            f"https://api.frankfurter.app/latest?from={base}&to={quote}"
        )
    except RuntimeError as exc:
        if "RATE_LIMITED" in str(exc):
            return {"status": "rate_limited", "source": SOURCE, "as_of": None,
                    "data": None, "code": "RATE_LIMIT", "message": "Frankfurter rate limit; backing off."}
        return error_envelope(SOURCE, f"FX quote failed: {exc}")
    rates = payload.get("rates") or {}
    rate = rates.get(quote)
    if rate is None:
        return unavailable(SOURCE, f"No {base}/{quote} rate in Frankfurter response.")
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        return unavailable(SOURCE, f"Non-numeric {base}/{quote} rate.")
    env = live_envelope(SOURCE, {
        "symbol": s, "base": base, "quote": quote, "price": rate,
        "currency": quote, "date": payload.get("date"),
        "note": "ECB euro reference rate; weekends/holidays snap to prior publishing day.",
    }, delayed=True)
    env["timeliness"] = "DELAYED"
    env = _stamp(env, payload.get("date"))
    _cache_set(ck, env)
    return env


def fx_history(symbol: str, days: int = 90) -> dict:
    """ECB daily history -> canonical bars (rate carried on close; no OHLC
    exists for reference rates — o/h/l mirror close, volume None)."""
    s = (symbol or "").strip().upper()
    pair = fx_pair_key(s)
    if not pair:
        return unavailable(SOURCE, f"No FX mapping for {s}.")
    base, quote = pair
    days = max(7, min(int(days or 90), 365))
    ck = f"openfeeds:fxh:{base}:{quote}:{days}"
    hit = _cache_get(ck, _H_TTL)
    if hit is not None:
        return hit
    try:
        to_d = datetime.now(timezone.utc).date()
        from datetime import timedelta
        from_d = (to_d - timedelta(days=days + 10)).isoformat()
        payload = _fetch(
            f"https://api.frankfurter.app/{from_d}..{to_d.isoformat()}?from={base}&to={quote}"
        )
    except RuntimeError as exc:
        return error_envelope(SOURCE, f"FX history failed: {exc}")
    # Frankfurter daterange form returns {rates: {date: {CCY: x}}}; clamp
    # to the requested window client-side (weekends already skipped).
    rates = payload.get("rates") or {}
    rows = sorted(rates.items())[-days:]
    bars: list[dict[str, Any]] = []
    for day, row in rows:
        try:
            v = float((row or {}).get(quote))
        except (TypeError, ValueError):
            continue
        try:
            ts = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
        bars.append({"t": ts, "o": v, "h": v, "l": v, "c": v, "v": None})
    if not bars:
        return unavailable(SOURCE, f"No {base}/{quote} history in Frankfurter response.")
    env = live_envelope(SOURCE, {
        "symbol": s, "range": f"{days}D", "interval": "1d", "bars": bars,
        "adjustment_note": "ECB reference rates; o/h/l mirror close (no intraday range published).",
    }, delayed=True)
    env["timeliness"] = "DELAYED"
    env = _stamp(env)
    _cache_set(ck, env)
    return env


# --------------------------------------------------------------- crypto ---
_CG_IDS = {
    "BTC-USD": "bitcoin", "BTC": "bitcoin", "ETH-USD": "ethereum", "ETH": "ethereum",
    "SOL-USD": "solana", "SOL": "solana", "DOGE-USD": "dogecoin",
}


def crypto_quote(symbol: str) -> dict:
    """CoinGecko free markets quote for tracked crypto symbols."""
    s = (symbol or "").strip().upper()
    cid = _CG_IDS.get(s)
    if not cid:
        return unavailable(SOURCE, f"No crypto mapping for {s}.")
    ck = f"openfeeds:cg:{cid}"
    hit = _cache_get(ck, _Q_TTL)
    if hit is not None:
        return hit
    try:
        payload = _fetch(
            "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids="
            + urllib.parse.quote(cid) + "&price_change_percentage=24h"
        )
    except RuntimeError as exc:
        if "RATE_LIMITED" in str(exc):
            return {"status": "rate_limited", "source": SOURCE, "as_of": None,
                    "data": None, "code": "RATE_LIMIT", "message": "CoinGecko rate limit; backing off."}
        return error_envelope(SOURCE, f"Crypto quote failed: {exc}")
    row = (payload or [{}])[0] if isinstance(payload, list) else {}
    price = row.get("current_price")
    if price is None:
        return unavailable(SOURCE, f"No CoinGecko quote for {s}.")
    env = live_envelope(SOURCE, {
        "symbol": s, "name": row.get("name") or cid, "price": price,
        "change_pct": row.get("price_change_percentage_24h_in_currency"),
        "currency": "USD", "market_cap": row.get("market_cap"),
        "updated": row.get("last_updated"),
    }, delayed=True)
    env["timeliness"] = "DELAYED"
    env = _stamp(env, row.get("last_updated"))
    _cache_set(ck, env)
    return env


# -------------------------------------------------------------- treasury ---
def treasury_rates(limit: int = 12) -> dict:
    """US Treasury average interest rates (monthly, by security type)."""
    ck = "openfeeds:ust"
    hit = _cache_get(ck, _M_TTL)
    if hit is not None:
        return hit
    try:
        payload = _fetch(
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
            "v2/accounting/od/avg_interest_rates?sort=-record_date&page[size]=40"
        )
    except RuntimeError as exc:
        return error_envelope(SOURCE, f"Treasury rates failed: {exc}")
    rows = payload.get("data") or []
    points = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            v = float(r.get("avg_interest_rate_amt"))
        except (TypeError, ValueError):
            continue
        points.append({
            "date": r.get("record_date"),
            "label": r.get("security_desc") or r.get("security_type_desc"),
            "value": v, "unit": "%",
        })
        if len(points) >= max(1, min(int(limit or 12), 40)):
            break
    if not points:
        return unavailable(SOURCE, "No Treasury rate rows in response.")
    env = live_envelope(SOURCE, {
        "indicator": "US_TREASURY_AVG_RATES", "unit": "%", "points": points,
    }, delayed=True)
    env["timeliness"] = "END-OF-DAY"
    env = _stamp(env, points[0].get("date"))
    _cache_set(ck, env)
    return env


# ------------------------------------------------------------------ EDGAR ---
def edgar_search(query: str, limit: int = 8) -> dict:
    """SEC EDGAR full-text filing discovery (no key). Returns filing links."""
    q = (query or "").strip()
    if len(q) < 2:
        return unavailable(SOURCE, "EDGAR search needs a query.")
    ck = f"openfeeds:edgar:{q.lower()}:{limit}"
    hit = _cache_get(ck, _M_TTL)
    if hit is not None:
        return hit
    try:
        payload = _fetch(
            "https://efts.sec.gov/LATEST/search-index?q="
            + urllib.parse.quote(f'"{q}"')
            + "&dateRange=custom&startdt=2023-01-01&enddt=2030-12-31"
        )
    except RuntimeError as exc:
        return error_envelope(SOURCE, f"EDGAR search failed: {exc}")
    hits = ((payload.get("hits") or {}).get("hits")) or []
    items = []
    for h in hits[: max(1, min(int(limit or 8), 20))]:
        src = (h or {}).get("_source") or {}
        forms = src.get("root_forms") or src.get("form") or []
        form = forms[0] if isinstance(forms, list) and forms else None
        names = src.get("display_names") or []
        fid = h.get("_id") or ""
        # _id looks like 0001628280-24-002390:file.htm -> archive URL
        url = None
        if ":" in fid:
            acc, fname = fid.split(":", 1)
            digits = acc.replace("-", "")
            if len(digits) >= 10:
                cik = str((src.get("ciks") or [""])[0]).lstrip("0") or "0"
                url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{digits}/{fname}")
        items.append({
            "title": (names[0] if names else q) + (f" — {form}" if form else ""),
            "company": names[0] if names else None,
            "form": form,
            "date": src.get("file_date"),
            "url": url,
            "source": "SEC EDGAR",
        })
    items = [it for it in items if it.get("url")]
    if not items:
        return unavailable(SOURCE, f"No EDGAR filings with links for '{q}'.")
    env = live_envelope(SOURCE, {"query": q, "items": items}, delayed=True)
    env["timeliness"] = "DELAYED"
    env = _stamp(env)
    _cache_set(ck, env)
    return env


class OpenFeedsProvider:
    """No-key public feeds leg: FX, crypto, Treasury macro, EDGAR filings."""

    name = "openfeeds"
    capabilities = {
        "quote": True,  # FX pairs + tracked crypto
        "history": True,  # FX history (ECB daily)
        "search": False,
        "fundamentals": False,
        "statements": False,
        "earnings": False,
        "estimates": False,
        "news": False,
        "ipo": False,
        "actions": False,
        "holdings": False,
        "macro": True,  # US Treasury rates
        "filings": True,  # SEC EDGAR search
        "technical": False,
        "chart": False,
    }

    def get_quote(self, symbol: str) -> dict:
        s = (symbol or "").strip().upper()
        if fx_pair_key(s):
            return fx_latest(s)
        if s in _CG_IDS:
            return crypto_quote(s)
        return unavailable(SOURCE, f"Open feeds cover FX pairs + tracked crypto, not {s}.")

    def get_historical_prices(self, symbol: str, range_: str = "3M", interval: str = "1d") -> dict:
        s = (symbol or "").strip().upper()
        if not fx_pair_key(s):
            return unavailable(SOURCE, f"Open-feeds history covers FX pairs, not {s}.")
        days = {"1M": 31, "3M": 93, "6M": 186, "1Y": 366}.get((range_ or "3M").upper(), 93)
        return fx_history(s, days)

    def status(self) -> dict:
        return {
            "provider": "Open Feeds",
            "state": "live",
            "detail": "No-key public feeds (server-side): Frankfurter ECB FX, "
            "CoinGecko crypto, US Treasury rates, SEC EDGAR search.",
            "key_configured": True,
            "key_required": False,
        }
