"""Fallback chain + server-side refresh governor.

Order: Yahoo -> Twelve Data -> Alpha Vantage -> UNAVAILABLE.
The chain owns a TTL cache so the backend only calls upstream when a
refresh is actually allowed:

- quotes: 30 s (browser may poll every 10 s; ~2 of 3 hits are cached)
- intraday history: 15 min; daily+ history: 4 h
- search: 10 min
- Alpha-Vantage-served quotes: 6 h (free tier is 25 req/day TOTAL)

A leg that hard-fails (transport error) twice in a row cools down for
5 minutes; definitive "unavailable" answers (bad symbol, no key) do not
trigger cooldown but let the next leg try. If every leg fails and a
cached value exists, it is served marked STALE. Otherwise the terminal
shows DATA UNAVAILABLE — it never fabricates.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .base import (
    CompanyProvider,
    MarketDataProvider,
    error_envelope,
    unavailable,
)
from .yahoo import ALLOWED_INTERVALS, ALLOWED_RANGES

QUOTE_TTL = 30.0
INTRADAY_HISTORY_TTL = 15 * 60.0
DAILY_HISTORY_TTL = 4 * 3600.0
SEARCH_TTL = 10 * 60.0
SCARCE_LEG_TTL = 6 * 3600.0  # Alpha Vantage: 25 req/day
ERROR_COOLDOWN = 5 * 60.0
COOLDOWN_AFTER_ERRORS = 2


class _Entry:
    __slots__ = ("env", "fetched_at", "ttl")

    def __init__(self, env: dict, ttl: float):
        self.env = env
        self.fetched_at = time.time()
        self.ttl = ttl


class FallbackMarketData(MarketDataProvider, CompanyProvider):
    """Chained market-data provider with TTL cache and leg health."""

    def __init__(self, legs: list[tuple[str, Any]], scarce_legs: set | None = None):
        self.legs = legs
        self.scarce_legs = scarce_legs or set()
        self._lock = threading.Lock()
        self._cache: dict[str, _Entry] = {}
        self._health: dict[str, dict] = {
            name: {
                "state": "ok",
                "consecutive_errors": 0,
                "last_ok": None,
                "last_error": None,
                "last_latency_ms": None,
                "cooldown_until": 0.0,
            }
            for name, _ in legs
        }

    # -- health ------------------------------------------------------
    def _cooling(self, name: str) -> bool:
        return time.time() < self._health[name]["cooldown_until"]

    def _record(
        self, name: str, ok: bool, err: str | None, latency_ms: float | None
    ) -> None:
        h = self._health[name]
        h["last_latency_ms"] = latency_ms
        if ok:
            h.update(state="ok", consecutive_errors=0, last_ok=time.time())
        else:
            h["consecutive_errors"] += 1
            h["last_error"] = err
            if h["consecutive_errors"] >= COOLDOWN_AFTER_ERRORS:
                h["state"] = "cooling"
                h["cooldown_until"] = time.time() + ERROR_COOLDOWN
            else:
                h["state"] = "degraded"

    def health(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._health.items()}

    # -- core ----------------------------------------------------------
    def _cached(self, key: str) -> _Entry | None:
        return self._cache.get(key)

    def _fetch_through_chain(
        self,
        key: str,
        ttl: float,
        fetchers: list[tuple[str, Any]],
        method: str,
        scarce_ttl: float = SCARCE_LEG_TTL,
    ) -> dict:
        """fetchers: [(leg_name, bound_fetcher)]. `method` is the _Bound
        method to call (quote | get_historical_prices | search).
        Returns envelope with extra keys: served_from (cache|provider),
        fallback_path, stale (bool), cache_age_s."""
        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
        if entry is not None and now - entry.fetched_at < entry.ttl:
            env = dict(entry.env)
            env["served_from"] = "cache"
            env["stale"] = False
            env["cache_age_s"] = round(now - entry.fetched_at, 1)
            return env

        path: list[str] = []
        last_env: dict | None = None
        for name, fetcher in fetchers:
            with self._lock:
                cooling = self._cooling(name)
            if cooling:
                path.append(f"{name}:cooling")
                continue
            t0 = time.time()
            try:
                env = getattr(fetcher, method)()
            except Exception as exc:  # last-resort guard; legs envelope errors
                env = {
                    "status": "error",
                    "source": name,
                    "as_of": None,
                    "data": None,
                    "message": f"Leg crashed: {exc}",
                }
            latency = round((time.time() - t0) * 1000, 1)
            status = env.get("status")
            if status in ("live", "delayed"):
                with self._lock:
                    self._record(name, True, None, latency)
                    use_ttl = scarce_ttl if name in self.scarce_legs else ttl
                    self._cache[key] = _Entry(env, use_ttl)
                env = dict(env)
                env["served_from"] = "provider"
                env["fallback_path"] = path + [name]
                env["stale"] = False
                env["cache_age_s"] = 0.0
                return env
            path.append(f"{name}:{status}")
            last_env = env
            with self._lock:
                if status == "unavailable":
                    # Definitive answer (bad symbol, no key, out of
                    # coverage): not a failure — never triggers cooldown.
                    h = self._health[name]
                    h["last_latency_ms"] = latency
                    h["last_error"] = None
                    if h["state"] != "cooling":
                        h["state"] = "ok"
                else:
                    self._record(name, False, str(env.get("message"))[:200], latency)
        # total failure: serve stale cache if any, else honest miss
        with self._lock:
            entry = self._cache.get(key)
        if entry is not None:
            env = dict(entry.env)
            env["served_from"] = "cache"
            env["stale"] = True
            env["cache_age_s"] = round(now - entry.fetched_at, 1)
            env["fallback_path"] = path
            env["message"] = (
                "STALE DATA: live refresh failed on every provider; "
                f"showing cached value from {env['cache_age_s']}s ago."
            )
            return env
        if last_env is not None:
            env = dict(last_env)
            env["served_from"] = "none"
            env["fallback_path"] = path
            env["stale"] = False
            return env
        return {
            "status": "unavailable",
            "source": "fallback-chain",
            "as_of": None,
            "data": None,
            "message": "DATA UNAVAILABLE: every provider failed.",
            "served_from": "none",
            "fallback_path": path,
            "stale": False,
        }

    # -- MarketDataProvider --------------------------------------------
    def get_quote(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        key = f"q:{symbol}"
        bound = [
            (n, _Bound(leg, "get_quote", symbol))
            for n, leg in self.legs
            if hasattr(leg, "get_quote")
        ]
        return self._fetch_through_chain(key, QUOTE_TTL, bound, "quote")

    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return error_envelope(
                "fallback-chain", "Empty symbol — no history requested."
            )
        range_ = (range_ or "1M").upper()
        interval = (interval or "1d").lower()
        if range_ not in ALLOWED_RANGES:
            return error_envelope("fallback-chain", f"Unsupported range '{range_}'.")
        if interval not in ALLOWED_INTERVALS:
            return error_envelope(
                "fallback-chain", f"Unsupported interval '{interval}'."
            )
        intraday = interval in ("1m", "5m", "15m", "1h")
        ttl = INTRADAY_HISTORY_TTL if intraday else DAILY_HISTORY_TTL
        key = f"h:{symbol}:{range_}:{interval}"
        bound = [
            (n, _Bound(leg, "get_historical_prices", symbol, range_, interval))
            for n, leg in self.legs
            if hasattr(leg, "get_historical_prices")
        ]
        return self._fetch_through_chain(key, ttl, bound, "get_historical_prices")

    def search(self, query: str, limit: int = 10) -> dict:
        query = (query or "").strip()
        if not query:
            return unavailable(
                "fallback-chain", "Empty search query — nothing to look up."
            )
        key = f"s:{query.lower()}:{limit}"
        bound = [
            (n, _Bound(leg, "search", query, limit))
            for n, leg in self.legs
            if hasattr(leg, "search")
        ]
        return self._fetch_through_chain(key, SEARCH_TTL, bound, "search")

    # -- CompanyProvider -------------------------------------------------
    def get_company_profile(self, symbol: str) -> dict:
        # Company identity rides on the quote chain winner.
        quote_env = self.get_quote(symbol)
        if quote_env.get("status") not in ("live", "delayed") or not quote_env.get(
            "data"
        ):
            out = dict(quote_env)
            out["data"] = None
            return out
        q = quote_env["data"]
        return {
            "status": quote_env["status"],
            "source": quote_env.get("source"),
            "as_of": quote_env.get("as_of"),
            "timeliness": quote_env.get("timeliness"),
            "served_from": quote_env.get("served_from"),
            "data": {
                "symbol": q.get("symbol"),
                "name": q.get("name"),
                "exchange": q.get("exchange"),
                "currency": q.get("currency"),
                "instrument_type": q.get("instrument_type"),
                "timezone": q.get("timezone"),
                "sector": None,
                "industry": None,
                "description": None,
                "profile_note": (
                    "Detailed profile (sector, industry, business description) "
                    "requires a fundamentals provider. "
                    "Set ALPHA_VANTAGE_API_KEY to enable."
                ),
            },
            "message": None,
        }


class _Bound:
    """Adapt a leg method + args to the zero-arg fetcher protocol."""

    def __init__(self, leg: Any, method: str, *args: Any):
        self._leg = leg
        self._method = method
        self._args = args

    def quote(self) -> dict:
        return getattr(self._leg, self._method)(*self._args)

    def get_historical_prices(self) -> dict:
        return getattr(self._leg, self._method)(*self._args)

    def search(self) -> dict:
        return getattr(self._leg, self._method)(*self._args)
