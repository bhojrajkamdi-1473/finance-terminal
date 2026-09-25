"""ProviderManager: multi-provider orchestration with reconciliation.

Cheap paths (quote/history/search endpoints) keep first-healthy chain
semantics. IMPORTANT company domains fan OUT here — Yahoo, Indian API,
Alpha Vantage and Twelve Data are queried in parallel where applicable,
normalized into ONE internal schema, reconciled field-by-field, and
returned with full provenance:

    PRIMARY value (provider-selected) + CROSS_CHECK (every source shown)
    + status CROSS_CHECK_OK | PROVIDER_DISCREPANCY | SINGLE_SOURCE

Conflicting values are NEVER averaged and NEVER hidden.

Quota discipline (free tiers, no paid subscriptions):
- Twelve Data: dispatched only when budget_snapshot() shows room.
- Alpha Vantage (25/day): long server TTLs + in-flight coalescing.
- Identical concurrent requests share one upstream execution.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

from providers.indian import is_indian
from services import reconcile as _rec
from services.refresh import TTLCache

QUOTE_TTL = 30.0
PROFILE_TTL = 24 * 3600.0
STATEMENTS_TTL = 7 * 24 * 3600.0
VALUATION_TTL = 24 * 3600.0
EARNINGS_TTL = 24 * 3600.0
ESTIMATES_TTL = 24 * 3600.0
NEWS_TTL = 10 * 60.0
ACTIONS_TTL = 24 * 3600.0
IPO_TTL = 3600.0

# Bump when merge/fallback semantics change so stale envelopes from an
# older build are never served for the rest of a long TTL window.
CACHE_VERSION = "v3"

# Machine-readable capability registry: which provider legs actually
# implement each company domain. Mirrors the real provider classes —
# never assume capability merely because a provider file exists.
# Yahoo covers market data; fundamentals-family domains need the
# key-gated legs (Alpha Vantage / Twelve Data / Indian API).
CAPABILITIES: dict[str, dict[str, bool]] = {
    "yahoo": {
        "quote": True,
        "history": True,
        "search": True,
        "profile": True,  # thin: identity from quote chain
        "actions": True,  # chart events (dividends/splits)
        "news": True,  # RSS leg
        "statements": False,
        "valuation": False,
        "estimates": False,
        "earnings": False,
        "holdings": False,
    },
    "alphavantage": {
        "quote": True,  # last-resort GLOBAL_QUOTE
        "history": True,  # daily only, scarce
        "search": True,
        "profile": True,  # OVERVIEW identity fields
        "statements": True,
        "valuation": True,  # OVERVIEW flat dict
        "estimates": True,
        "earnings": True,
        "actions": True,  # DIVIDENDS + SPLITS
        "news": True,  # NEWS_SENTIMENT
        "holdings": False,
    },
    "twelvedata": {
        "quote": True,
        "history": True,
        "search": True,
        "profile": False,
        "statements": True,  # expensive (cost ~100), budget-guarded
        "valuation": True,  # statistics
        "estimates": False,
        "earnings": True,
        "actions": True,
        "news": False,
        "holdings": False,
    },
    "indian-api": {
        "quote": True,  # NSE/BSE only (keyed snapshot, else no-auth leg)
        "history": False,  # historical datasets via get_indian_history
        "search": False,
        "profile": True,  # NSE/BSE only (keyed rich, else sector/industry)
        "statements": True,  # keyed only (/stock, /statement, stats)
        "valuation": True,  # keyed rich ratios, else market fundamentals
        "estimates": True,  # keyed only (ratings + forecasts + targets)
        "earnings": True,  # keyed only (fiscal-year reported EPS)
        "actions": True,  # keyed only; no-auth covered by yahoo-events
        "news": True,  # keyed only; no-auth covered by yahoo-rss
        "holdings": True,  # keyed only (shareholding)
    },
    "stooq": {
        "quote": False,
        "history": True,  # US suffix-less only, 1d only
        "search": False,
        "profile": False,
        "statements": False,
        "valuation": False,
        "estimates": False,
        "earnings": False,
        "actions": False,
        "news": False,
        "holdings": False,
    },
    "tradingview": {
        "quote": False,
        "history": False,
        "search": False,
        "profile": False,
        "statements": False,
        "valuation": False,
        "estimates": False,
        "earnings": False,
        "actions": False,
        "news": False,
        "holdings": False,
    },
}


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class ProviderManager:
    def __init__(
        self,
        *,
        yahoo=None,
        indian=None,
        indianapi=None,
        twelvedata=None,
        alphavantage=None,
        news_rss=None,
        actions_yahoo=None,
        yahoo_fund=None,
        max_workers: int = 6,
    ):
        self.yahoo = yahoo
        self.indian = indian
        self.indianapi = indianapi
        self.twelvedata = twelvedata
        self.alphavantage = alphavantage
        self.news_rss = news_rss
        self.actions_yahoo = actions_yahoo
        self.yahoo_fund = yahoo_fund
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._cache = TTLCache()
        self._inflight: dict[str, Any] = {}
        import threading

        self._lock = threading.Lock()

    def _indian_leg(self):
        """Resolved Indian leg: the new keyed provider wins; callers keep
        passing `indian=` for backward-compatible tests."""
        return self.indianapi or self.indian

    # -- guards ---------------------------------------------------------
    def _td_room(self, cost: int = 2) -> tuple[bool, str]:
        if self.twelvedata is None:
            return False, "Twelve Data leg not wired."
        try:
            from providers.twelvedata import _api_key, budget_probe
        except Exception:
            return False, "Twelve Data unavailable."
        if not _api_key():
            return False, "TWELVE_DATA_API_KEY not configured."
        blocked = budget_probe(cost)
        if blocked:
            return False, f"Twelve Data {blocked[0].lower() + blocked[1:]}."
        return True, ""

    def _av_ready(self) -> tuple[bool, str]:
        if self.alphavantage is None:
            return False, "Alpha Vantage leg not wired."
        try:
            from providers.fundamentals import _api_key
        except Exception:
            return False, "Alpha Vantage unavailable."
        if not _api_key():
            return False, "ALPHA_VANTAGE_API_KEY not configured."
        return True, ""

    def _indian_ready(self, symbol: str) -> tuple[bool, str]:
        """Indian leg FULL readiness: wired + Indian symbol + API key.

        Keyed domains (statements, earnings, estimates, actions, news,
        holdings, historical datasets) need INDIAN_STOCK_MARKET_API_KEY.
        Quote/profile/valuation additionally work keyless via
        _indian_basic() (free no-auth leg).
        """
        leg = self._indian_leg()
        if leg is None:
            return False, "Indian Stock Market API leg not wired."
        if not is_indian(symbol):
            return False, "Non-Indian symbol."
        try:
            from providers.indianapi import _api_key as _indian_key
        except Exception:
            return False, "Indian Stock Market API unavailable."
        if not _indian_key():
            return False, "INDIAN_STOCK_MARKET_API_KEY not configured."
        return True, ""

    def _indian_basic(self, symbol: str) -> tuple[bool, str]:
        """Indian leg BASIC readiness: wired + Indian symbol, no key.

        Covers quote, company identity and market fundamentals through
        the free no-auth leg. Never KEY_REQUIRED for these domains.
        """
        leg = self._indian_leg()
        if leg is None:
            return False, "Indian Stock Market API leg not wired."
        if not is_indian(symbol):
            return False, "Non-Indian symbol."
        return True, ""

    # -- parallel fan-out with coalescing ---------------------------------
    def _fanout(
        self,
        key: str,
        ttl: float,
        calls: list[tuple[str, Callable[[], dict]]],
        timeout_each: float = 25.0,
    ) -> dict[str, dict]:
        """Run independent provider calls concurrently. Identical in-flight
        requests share one execution (deduplication)."""
        with self._lock:
            fut = self._inflight.get(key)
            if fut is None:
                fut = self._pool.submit(self._run_calls, calls, timeout_each)
                self._inflight[key] = fut
                owner = True
            else:
                owner = False
        try:
            results = fut.result(timeout=timeout_each + 10)
            if owner:
                with self._lock:
                    self._inflight.pop(key, None)
            return results
        except Exception as exc:
            if owner:
                with self._lock:
                    self._inflight.pop(key, None)
            return {
                "_manager": {
                    "status": "error",
                    "source": "orchestrator",
                    "message": f"Fan-out failed: {exc}",
                }
            }

    def _run_calls(self, calls, timeout_each: float) -> dict[str, dict]:
        futures = {name: self._pool.submit(fn) for name, fn in calls}
        out: dict[str, dict] = {}
        for name, fut in futures.items():
            try:
                out[name] = fut.result(timeout=timeout_each)
            except FuturesTimeout:
                out[name] = {
                    "status": "error",
                    "source": name,
                    "message": "Provider timeout.",
                    "code": "TIMEOUT",
                }
            except Exception as exc:
                out[name] = {
                    "status": "error",
                    "source": name,
                    "message": f"Leg crashed: {exc}",
                }
        return out

    def _cached_or(self, key: str, ttl: float, compute: Callable[[], dict]) -> dict:
        # Cache hygiene: version the namespace so a deploy that changes
        # merge/fallback logic never serves envelopes computed by older
        # code for the rest of a long TTL window.
        key = f"{CACHE_VERSION}:{key}"
        hit = self._cache.get(key)
        if hit is not None:
            env = dict(hit)
            env["served_from"] = "cache"
            return env
        env = compute()
        if env.get("status") in ("live", "delayed"):
            self._cache.set(key, env, ttl)
            env = dict(env)
        env["served_from"] = env.get("served_from", "provider")
        return env

    # -- normalization ------------------------------------------------------
    @staticmethod
    def _quote_fields(symbol: str, env: dict) -> dict[str, dict]:
        """Envelope quote dict -> normalized field dict."""
        from providers.schema import field as _f

        q = (env.get("data") or {}) if env.get("data") else {}
        src = env.get("source", "?")
        as_of = env.get("as_of")
        ccy = q.get("currency")
        return {
            "price": _f(q.get("price"), src, as_of, None, ccy),
            "change_pct": _f(q.get("change_pct"), src, as_of, None, None),
            "change": _f(q.get("change"), src, as_of, None, ccy),
            "volume": _f(q.get("volume"), src, as_of, None, None),
            "day_high": _f(q.get("day_high"), src, as_of, None, ccy),
            "day_low": _f(q.get("day_low"), src, as_of, None, ccy),
            "previous_close": _f(q.get("previous_close"), src, as_of, None, ccy),
            "fifty_two_week_high": _f(
                q.get("fifty_two_week_high"), src, as_of, None, ccy
            ),
            "fifty_two_week_low": _f(
                q.get("fifty_two_week_low"), src, as_of, None, ccy
            ),
        }

    # -- domains --------------------------------------------------------------
    def get_quote(self, symbol: str) -> dict:
        """Multi-source quote: Yahoo + Indian (Indian symbols) + Twelve
        Data (key + budget). Primary by Yahoo > indian > twelvedata."""
        from providers.indian import is_indian

        symbol = (symbol or "").strip().upper()
        key = f"oq:{symbol}"

        def compute() -> dict:
            calls: list[tuple[str, Callable[[], dict]]] = []
            skipped: list[dict] = []
            if self.yahoo is not None:
                calls.append(("yahoo", lambda: self.yahoo.get_quote(symbol)))
            else:
                skipped.append({"provider": "yahoo", "reason": "Leg not wired."})
            leg = self._indian_leg()
            if leg is not None and is_indian(symbol):
                calls.append(("indian-api", lambda: leg.get_quote(symbol)))
            else:
                skipped.append(
                    {
                        "provider": "indian-api",
                        "reason": "Leg not wired."
                        if leg is None
                        else "Non-Indian symbol.",
                    }
                )
            ok, reason = self._td_room(1)
            if ok and self.twelvedata is not None:
                calls.append(("twelvedata", lambda: self.twelvedata.get_quote(symbol)))
            else:
                skipped.append(
                    {"provider": "twelvedata", "reason": reason or "Leg not wired."}
                )
            results = self._fanout(key + ":fan", QUOTE_TTL, calls)
            order = ["yahoo", "indian-api", "twelvedata", "alphavantage"]
            live = [
                (n, e)
                for n in order
                for (nn, e) in [(n, results.get(n))]
                if e is not None
                and isinstance(e, dict)
                and e.get("status") in ("live", "delayed")
                and (e.get("data") or {}).get("price") is not None
            ]
            if not live:
                first = next((results.get(n) for n in order if results.get(n)), None)
                env = dict(
                    first
                    or {
                        "status": "unavailable",
                        "source": "orchestrator",
                        "message": "No quote provider answered.",
                    }
                )
                env["providers_queried"] = _queried(results)
                return env
            primary_name, primary_env = live[0]
            fields = {n: self._quote_fields(symbol, e) for n, e in live}
            comparisons = []
            for fname in ("price", "change_pct", "volume"):
                comparisons.append(
                    _rec.compare(
                        fname,
                        fields[primary_name][fname],
                        [fields[n][fname] for n, _ in live[1:]],
                    )
                )
            summary = _rec.summarize(comparisons)
            env = dict(primary_env)
            env["source"] = primary_env.get("source")
            env["providers_queried"] = _queried(results)
            env["market"] = _classify_market(
                symbol, (primary_env.get("data") or {})
            )
            env["reconciliation"] = {
                "comparisons": comparisons,
                "summary": summary,
                "primary": primary_name,
                "skipped": skipped,
            }
            failed = {
                name: str(e.get("message") or e.get("status"))[:200]
                for name, e in results.items()
                if isinstance(e, dict) and e.get("status") not in ("live", "delayed")
            }
            if failed:
                env["leg_errors"] = failed
            return env

        return self._cached_or(key, QUOTE_TTL, compute)

    def get_profile(self, symbol: str, quote_env: dict | None = None) -> dict:
        """Company overview: AV overview + TD statistics + quote identity."""
        symbol = (symbol or "").strip().upper()
        key = f"opro:{symbol}"

        def compute() -> dict:
            calls: list[tuple[str, Callable[[], dict]]] = []
            skipped: list[dict] = []
            av_ok, av_reason = self._av_ready()
            if av_ok and self.alphavantage is not None:
                calls.append(
                    ("alphavantage", lambda: self.alphavantage.get_ratios(symbol))
                )
            else:
                skipped.append(
                    {
                        "provider": "alphavantage",
                        "reason": av_reason or "Leg not wired.",
                    }
                )
            td_ok, td_reason = self._td_room(2)
            if td_ok and self.twelvedata is not None:
                calls.append(
                    ("twelvedata", lambda: self.twelvedata.get_statistics(symbol))
                )
            else:
                skipped.append(
                    {"provider": "twelvedata", "reason": td_reason or "Leg not wired."}
                )
            leg = self._indian_leg()
            if leg is not None and is_indian(symbol):
                calls.append(("indian-api", lambda: leg.get_company_profile(symbol)))
            else:
                skipped.append(
                    {
                        "provider": "indian-api",
                        "reason": "Leg not wired."
                        if leg is None
                        else "Non-Indian symbol.",
                    }
                )
            if self.yahoo_fund is not None:
                calls.append(
                    ("yahoo-fundamentals", lambda: self.yahoo_fund.get_company_profile(symbol))
                )
            else:
                skipped.append(
                    {"provider": "yahoo-fundamentals", "reason": "Leg not wired."}
                )
            results = self._fanout(key + ":fan", PROFILE_TTL, calls)
            av = results.get("alphavantage", {})
            td = results.get("twelvedata", {})
            inapi = results.get("indian-api", {})
            yf = results.get("yahoo-fundamentals", {})
            av_d = av.get("data") if _ok(av) else {}
            td_d = td.get("data") if _ok(td) else {}
            in_d = inapi.get("data") if _ok(inapi) else {}
            y_d = yf.get("data") if _ok(yf) else {}
            q = (
                (quote_env.get("data") or {})
                if quote_env and quote_env.get("data")
                else {}
            )
            as_of = (
                av.get("as_of")
                if _ok(av)
                else (
                    inapi.get("as_of")
                    if _ok(inapi)
                    else (
                        yf.get("as_of")
                        if _ok(yf)
                        else (
                            td.get("as_of") if _ok(td) else (quote_env or {}).get("as_of")
                        )
                    )
                )
            )
            from providers.schema import field as _f

            pri_d = av_d or in_d or y_d or {}
            if pri_d is in_d:
                prim_src, prim_asof = "indian-api", inapi.get("as_of")
            elif pri_d is y_d:
                prim_src, prim_asof = "yahoo-fundamentals", yf.get("as_of")
            else:
                prim_src, prim_asof = "alphavantage", av.get("as_of")

            def ovf(k, alias=None, period=None, ccy=None):
                v = (pri_d or {}).get(k)
                if v is None and alias:
                    v = (pri_d or {}).get(alias)
                return _f(
                    v,
                    prim_src,
                    prim_asof,
                    period,
                    ccy
                    or (pri_d or {}).get("Currency")
                    or (pri_d or {}).get("currency"),
                )

            merged = {
                "symbol": symbol,
                "name": (pri_d or {}).get("Name")
                or (pri_d or {}).get("name")
                or q.get("name"),
                "exchange": (pri_d or {}).get("Exchange")
                or (pri_d or {}).get("exchange")
                or q.get("exchange"),
                "currency": (pri_d or {}).get("Currency")
                or (pri_d or {}).get("currency")
                or q.get("currency"),
                "instrument_type": q.get("instrument_type"),
                "timezone": q.get("timezone"),
                "sector": (pri_d or {}).get("Sector") or (pri_d or {}).get("sector") or (y_d or {}).get("sector"),
                "industry": (pri_d or {}).get("Industry")
                or (pri_d or {}).get("industry")
                or (y_d or {}).get("industry"),
                "description": (pri_d or {}).get("Description")
                or (pri_d or {}).get("description")
                or (y_d or {}).get("description"),
                "profile_note": (
                    "Identity from quote chain; sector/industry/description "
                    "from the configured fundamental feeds (Alpha Vantage, "
                    "Yahoo fundamentals and/or Indian Stock Market API)."
                ),
            }
            comparisons = []
            pairs = [
                (
                    "market_cap",
                    ovf("MarketCapitalization"),
                    (td_d or {}).get("market_cap"),
                ),
                ("pe", ovf("PERatio"), (td_d or {}).get("pe")),
                ("pb", ovf("PriceToBookRatio"), (td_d or {}).get("pb")),
                ("eps", ovf("EPS"), (td_d or {}).get("eps")),
                (
                    "dividend_yield",
                    ovf("DividendYield"),
                    (td_d or {}).get("dividend_yield"),
                ),
                ("beta", ovf("Beta"), (td_d or {}).get("beta")),
            ]
            for fname, a, t in pairs:
                others = (
                    [t] if isinstance(t, dict) and t.get("value") is not None else []
                )
                comparisons.append(_rec.compare(fname, a, others))
            summary = _rec.summarize(comparisons)
            has_any = bool(av_d or td_d or in_d or y_d or q)
            status = "live" if has_any else "unavailable"
            return {
                "status": status,
                "source": "orchestrator",
                "as_of": as_of,
                "timeliness": "DELAYED",
                "data": merged if has_any else None,
                "message": None
                if has_any
                else ("No profile provider answered: " + "; ".join(_queried(results))),
                "providers_queried": _queried(results),
                "reconciliation": {
                    "comparisons": comparisons,
                    "summary": summary,
                    "primary": prim_src,
                    "skipped": skipped,
                },
            }

        return self._cached_or(key, PROFILE_TTL, compute)

    def get_statements(
        self, symbol: str, statement: str = "income", period: str = "annual"
    ) -> dict:
        """Statements from AV + TD in parallel; common lines reconciled."""
        symbol = (symbol or "").strip().upper()
        key = f"ost:{symbol}:{statement}:{period}"

        def compute() -> dict:
            calls: list[tuple[str, Callable[[], dict]]] = []
            skipped: list[dict] = []
            av_ok, av_reason = self._av_ready()
            if av_ok and self.alphavantage is not None:
                calls.append(
                    (
                        "alphavantage",
                        lambda: self.alphavantage.get_financial_statements(
                            symbol, statement, period
                        ),
                    )
                )
            else:
                skipped.append(
                    {
                        "provider": "alphavantage",
                        "reason": av_reason or "Leg not wired.",
                    }
                )
            td_ok, td_reason = self._td_room(100)
            if td_ok and self.twelvedata is not None:
                calls.append(
                    (
                        "twelvedata",
                        lambda: self.twelvedata.get_statement_td(
                            symbol, statement, period
                        ),
                    )
                )
            else:
                skipped.append(
                    {"provider": "twelvedata", "reason": td_reason or "Leg not wired."}
                )
            # Free Yahoo fundamentals leg (timeseries statements, no key):
            # always attempted so keyless users get real financials.
            if self.yahoo_fund is not None:
                calls.append(
                    (
                        "yahoo-fundamentals",
                        lambda: self.yahoo_fund.get_financial_statements(
                            symbol, statement, period
                        ),
                    )
                )
            else:
                skipped.append(
                    {"provider": "yahoo-fundamentals", "reason": "Leg not wired."}
                )
            # Capability routing: keyed Indian leg (/stock, /statement,
            # /historical_stats) joins AV/TD; keyless it stays out.
            leg = self._indian_leg()
            in_ok, in_reason = self._indian_ready(symbol)
            if in_ok and leg is not None and is_indian(symbol):
                calls.append(
                    (
                        "indian-api",
                        lambda: leg.get_financial_statements(
                            symbol, statement, period
                        ),
                    )
                )
            else:
                skipped.append(
                    {
                        "provider": "indian-api",
                        "reason": in_reason or "Leg not wired.",
                    }
                )
            results = self._fanout(key + ":fan", STATEMENTS_TTL, calls)
            av = results.get("alphavantage", {})
            td = results.get("twelvedata", {})
            inapi = results.get("indian-api", {})
            yf = results.get("yahoo-fundamentals", {})
            av_live = _ok(av) and av.get("data")
            td_live = _ok(td) and td.get("data")
            in_live = _ok(inapi) and inapi.get("data")
            y_live = _ok(yf) and yf.get("data")
            if not av_live and not td_live and not in_live and not y_live:
                return _honest_unavailable("financial statement", results, skipped)
            if av_live:
                primary = av
            elif y_live:
                primary = yf
            elif in_live:
                primary = inapi
            else:
                primary = td
            in_data = (inapi.get("data") or {}) if in_live else None
            data = dict(primary.get("data") or {})
            comparisons = _reconcile_statements(
                statement,
                (av.get("data") or {}) if av_live else None,
                (td.get("data") or {}) if td_live else None,
            )
            env = {
                "status": "live",
                "source": primary.get("source"),
                "as_of": primary.get("as_of"),
                "timeliness": "END-OF-DAY",
                "data": data,
                "providers_queried": _queried(results),
                "reconciliation": {
                    "comparisons": comparisons,
                    "summary": _rec.summarize(comparisons),
                    "primary": primary.get("source"),
                    "skipped": skipped,
                },
                "message": None,
            }
            if td_live and av_live:
                env["td_reports"] = (td.get("data") or {}).get("reports")
            elif y_live and not av_live:
                yf_data = yf.get("data") or {}
                data.update(
                    {
                        "symbol": symbol,
                        "statement": statement,
                        "period": period,
                        "currency": yf_data.get("currency"),
                        "reports": yf_data.get("reports"),
                    }
                )
            elif in_live and not av_live:
                data.update(
                    {
                        "symbol": symbol,
                        "statement": statement,
                        "period": period,
                        "currency": (in_data or {}).get("currency") or "INR",
                        "reports": (in_data or {}).get("reports"),
                    }
                )
            elif td_live:
                data.update(
                    {
                        "symbol": symbol,
                        "statement": statement,
                        "period": period,
                        "currency": (td.get("data") or {}).get("currency"),
                        "reports": (td.get("data") or {}).get("reports"),
                    }
                )
            return env

        return self._cached_or(key, STATEMENTS_TTL, compute)

    def get_valuation(self, symbol: str, quote_env: dict | None = None) -> dict:
        """Valuation metrics: AV overview + TD statistics, reconciled."""
        symbol = (symbol or "").strip().upper()
        key = f"oval:{symbol}"

        def compute() -> dict:
            calls: list[tuple[str, Callable[[], dict]]] = []
            skipped: list[dict] = []
            av_ok, av_reason = self._av_ready()
            if av_ok and self.alphavantage is not None:
                calls.append(
                    ("alphavantage", lambda: self.alphavantage.get_ratios(symbol))
                )
            else:
                skipped.append(
                    {
                        "provider": "alphavantage",
                        "reason": av_reason or "Leg not wired.",
                    }
                )
            td_ok, td_reason = self._td_room(2)
            if td_ok and self.twelvedata is not None:
                calls.append(
                    ("twelvedata", lambda: self.twelvedata.get_statistics(symbol))
                )
            else:
                skipped.append(
                    {"provider": "twelvedata", "reason": td_reason or "Leg not wired."}
                )
            if self.yahoo_fund is not None:
                calls.append(
                    ("yahoo-fundamentals", lambda: self.yahoo_fund.get_ratios(symbol))
                )
            else:
                skipped.append(
                    {"provider": "yahoo-fundamentals", "reason": "Leg not wired."}
                )
            leg = self._indian_leg()
            in_ok, in_reason = self._indian_basic(symbol)
            if in_ok and leg is not None and is_indian(symbol):
                calls.append(("indian-api", lambda: leg.get_ratios(symbol)))
            else:
                skipped.append(
                    {
                        "provider": "indian-api",
                        "reason": in_reason or "Leg not wired.",
                    }
                )
            results = self._fanout(key + ":fan", VALUATION_TTL, calls)
            av = results.get("alphavantage", {})
            td = results.get("twelvedata", {})
            inapi = results.get("indian-api", {})
            yf = results.get("yahoo-fundamentals", {})
            av_d = av.get("data") if _ok(av) else {}
            td_d = td.get("data") if _ok(td) else {}
            in_d = inapi.get("data") if _ok(inapi) else {}
            y_d = yf.get("data") if _ok(yf) else {}
            if not av_d and not td_d and not in_d and not y_d:
                miss = _honest_unavailable("valuation", results, skipped)
                miss["message"] = (
                    "Valuation could not be answered by any provider "
                    "right now: "
                    + "; ".join(_queried(results))
                    + ". "
                    + "; ".join(_leg_detail(results))
                    + " Set "
                    "ALPHA_VANTAGE_API_KEY and/or TWELVE_DATA_API_KEY to "
                    "enable further coverage. The free Yahoo fundamentals "
                    "and no-auth Indian legs "
                    "were checked automatically for applicable symbols. "
                    "(Common causes: Alpha Vantage free quota spent "
                    "(25/day), Twelve Data budget/coverage limits.)"
                )
                return miss
            from providers.schema import field as _f

            pri_d = av_d or y_d or in_d or {}
            if pri_d is in_d:
                prim_src, prim_asof = "indian-api", inapi.get("as_of")
            elif pri_d is y_d:
                prim_src, prim_asof = "yahoo-fundamentals", yf.get("as_of")
            else:
                prim_src, prim_asof = "alphavantage", av.get("as_of")
            metrics: dict[str, dict] = {}
            comparisons = []
            amap = [
                ("pe", "PERatio"),
                ("pb", "PriceToBookRatio"),
                ("eps", "EPS"),
                ("dividend_yield", "DividendYield"),
                ("market_cap", "MarketCapitalization"),
                ("beta", "Beta"),
                ("week_52_high", "52WeekHigh"),
                ("week_52_low", "52WeekLow"),
            ]
            for fname, akey in amap:
                a = _f(
                    (pri_d or {}).get(akey),
                    prim_src,
                    prim_asof,
                    "TTM",
                    (pri_d or {}).get("Currency") or (pri_d or {}).get("currency"),
                )
                t = (td_d or {}).get(fname)
                others = (
                    [t] if isinstance(t, dict) and t.get("value") is not None else []
                )
                c = _rec.compare(fname, a, others)
                comparisons.append(c)
                kind = "REPORTED"
                if fname == "market_cap":
                    kind = (pri_d or {}).get("MarketCapKind") or "REPORTED"
                metrics[fname] = {
                    "value": a.get("value"),
                    "kind": kind,
                    "primary_source": prim_src,
                    "cross_check": c["cross_check"],
                    "status": c["status"],
                }
            q = (
                (quote_env.get("data") or {})
                if quote_env and quote_env.get("data")
                else {}
            )
            from providers.schema import num as _snum

            eps_v = _snum((pri_d or {}).get("EPS"))
            px = _snum(q.get("price"))
            if eps_v and eps_v > 0 and px:
                metrics["pe_calc"] = {
                    "value": round(px / eps_v, 2),
                    "kind": "CALCULATED",
                    "formula": f"price ÷ reported EPS ({q.get('price')} ÷ "
                    f"{(pri_d or {}).get('EPS')})",
                    "inputs": {
                        "price": {
                            "value": q.get("price"),
                            "source": q.get("source", "quote"),
                        },
                        "eps": {
                            "value": (pri_d or {}).get("EPS"),
                            "source": prim_src,
                        },
                    },
                    "status": "CALCULATED",
                }
            overview = av_d or y_d or in_d or {}
            return {
                "status": "live",
                "source": "orchestrator",
                "as_of": av.get("as_of") or yf.get("as_of") or inapi.get("as_of") or td.get("as_of"),
                "timeliness": "DELAYED",
                "data": {
                    "symbol": symbol,
                    "metrics": metrics,
                    "overview": overview or None,
                },
                "providers_queried": _queried(results),
                "reconciliation": {
                    "comparisons": comparisons,
                    "summary": _rec.summarize(comparisons),
                    "primary": prim_src,
                    "skipped": skipped,
                },
                "message": None,
            }

        return self._cached_or(key, VALUATION_TTL, compute)

    def get_ratio_sheet(self, symbol: str) -> dict:
        """ROE hierarchy + canonical ratio sheet.

        Priority per metric: provider-REPORTED overview value first,
        ratio-engine CALCULATED fill second, UNAVAILABLE only when all
        paths are exhausted. Statement legs ride the 7-day cached
        get_statements paths, so no extra quota beyond what the
        Financials tab already spends.
        """
        symbol = (symbol or "").strip().upper()
        key = f"oratio:{symbol}"

        def compute() -> dict:
            from providers.schema import num as _snum
            from services.analytics import ratios as _ratios

            val_env = self.get_valuation(symbol)
            val_data = (val_env.get("data") or {}) if val_env.get("status") == "live" else {}
            overview = val_data.get("overview") or {}
            currency = overview.get("Currency") or overview.get("currency")
            price = None
            try:
                q = self.get_quote(symbol)
                price = _snum((q.get("data") or {}).get("price"))
                currency = currency or (q.get("data") or {}).get("currency")
            except Exception:
                price = None
            reps: dict[str, list] = {}
            rep_source = "statements"
            for stmt in ("income", "balance", "cashflow"):
                try:
                    env = self.get_statements(symbol, stmt, "annual")
                except Exception:
                    continue
                if env.get("status") == "live" and (env.get("data") or {}).get("reports"):
                    reps[stmt] = env["data"]["reports"]
                    rep_source = env.get("source") or rep_source
            market_cap = _snum(overview.get("MarketCapitalization"))
            computed = _ratios.compute_all(
                reps.get("income"), reps.get("balance"), reps.get("cashflow"),
                price=price, market_cap=market_cap,
                source=rep_source, currency=currency,
            )
            reported_roe = _snum(overview.get("ROE") or overview.get("ReturnOnEquityTTM"))
            reported_roa = _snum(overview.get("ROA") or overview.get("ReturnOnAssetsTTM"))
            display: dict[str, dict] = {}
            if reported_roe is not None:
                display["roe"] = {"value": reported_roe, "unit": "%", "kind": "REPORTED",
                                  "source": val_env.get("source"), "label": "ROE"}
            elif "roe" in computed:
                display["roe"] = computed["roe"]
            if reported_roa is not None:
                display["roa"] = {"value": reported_roa, "unit": "%", "kind": "REPORTED",
                                  "source": val_env.get("source"), "label": "ROA"}
            elif "roa" in computed:
                display["roa"] = computed["roa"]
            for k in ("roce", "gross_margin", "op_margin", "net_margin", "current_ratio",
                      "quick_ratio", "debt_equity", "net_debt_ebitda", "interest_coverage",
                      "asset_turnover", "revenue_cagr", "ebitda_cagr", "pat_cagr", "eps_cagr",
                      "fcf", "fcf_margin", "cfo_pat", "div_yield_calc", "payout_ratio",
                      "pe_calc", "pe_from_mcap"):
                if k in computed:
                    display[k] = computed[k]
            gaps = [k for k in _ratios.core_keys() if k not in display]
            live = bool(display) or val_env.get("status") == "live"
            return {
                "status": "live" if live else "unavailable",
                "source": "orchestrator+ratio-engine",
                "as_of": val_env.get("as_of"),
                "timeliness": val_env.get("timeliness") or "DELAYED",
                "data": {
                    "symbol": symbol,
                    "currency": currency,
                    "display": display,
                    "computed": computed,
                    "gaps": gaps,
                    "statements_used": sorted(reps),
                } if live else None,
                "message": None if live else "No reported overview and no computable statements.",
                "providers_queried": val_env.get("providers_queried"),
            }

        return self._cached_or(key, VALUATION_TTL, compute)

    def get_ipo_dashboard(self) -> dict:
        """IPO dashboard: IPO Guru (keyed, Indian) + AV calendar merged.

        Rows stay source-tagged; GMP/subscription surface only with
        source + timestamp. Disagreeing GMP sources are shown side by
        side (GMP DISCREPANCY), never averaged.
        """
        key = "oipo:dashboard"

        def compute() -> dict:
            from providers import ipo as _ipo
            from providers import ipoguru as _guru

            calls: list[tuple[str, Callable[[], dict]]] = []
            skipped: list[dict] = []
            if _guru.key_configured():
                calls.append(("ipo-guru", lambda: _guru.get_ipos()))
            else:
                skipped.append({"provider": "ipo-guru",
                                "reason": "IPOGURU_API_KEY not configured."})
            av_ok, av_reason = self._av_ready()
            if av_ok and self.alphavantage is not None:
                calls.append(("alphavantage",
                              lambda: self.alphavantage.get_ipo_calendar()))
            else:
                skipped.append({"provider": "alphavantage",
                                "reason": av_reason or "Leg not wired."})
            results = self._fanout(key + ":fan", IPO_TTL, calls)
            rows: list[dict] = []
            for name in ("ipo-guru", "alphavantage"):
                env = results.get(name, {})
                if env.get("status") not in ("live", "delayed"):
                    continue
                for row in (env.get("data") or {}).get("rows") or []:
                    if isinstance(row, dict):
                        tagged = dict(row)
                        tagged["_feed"] = name
                        rows.append(tagged)
            if not rows:
                out = _honest_unavailable("IPO calendar", results, skipped)
                out["buckets"] = {"upcoming": [], "open": [], "closed": [],
                                  "listed": [], "unclassified": []}
                out["gmp"] = _ipo.gmp_unavailable()
                out["subscription"] = _ipo.subscription_unavailable()
                return out
            buckets = _ipo.classify(rows)
            gmp_sources = [
                {"source": "IPO Guru", "value": r.get("gmp_value"),
                 "percent": r.get("gmp_percent"),
                 "updated_at": r.get("gmp_updated_at"),
                 "company": r.get("company_name")}
                for r in rows
                if r.get("gmp_value") is not None
            ]
            if gmp_sources:
                gmp = {"status": "live", "source": "ipo-guru",
                       "label": _ipo.GMP_LABEL, "data": gmp_sources,
                       "discrepancy_note": _ipo.DISCREPANCY_LABEL + ": values shown "
                       "per source, never averaged." if len({g["value"] for g in gmp_sources}) > 1 else None,
                       "message": None}
            else:
                gmp = _ipo.gmp_unavailable()
            subs = [r for r in rows if r.get("subscription_total") is not None]
            subscription = (
                {"status": "live", "source": "ipo-guru",
                 "data": [{"company": r.get("company_name"),
                           "qib": r.get("subscription_qib"),
                           "nii": r.get("subscription_nii"),
                           "retail": r.get("subscription_retail"),
                           "total": r.get("subscription_total"),
                           "updated_at": r.get("subscription_updated_at")}
                          for r in subs],
                 "message": None}
                if subs else _ipo.subscription_unavailable()
            )
            return {
                "status": "live",
                "source": "orchestrator",
                "as_of": _now_iso(),
                "timeliness": "DELAYED",
                "data": {"rows": rows},
                "buckets": buckets,
                "gmp": gmp,
                "subscription": subscription,
                "providers_queried": _queried(results),
                "reconciliation": {"skipped": skipped},
                "message": None,
            }

        return self._cached_or(key, IPO_TTL, compute)

    def get_earnings(self, symbol: str) -> dict:
        """AV earnings + TD earnings rows, reported-EPS cross-check."""
        symbol = (symbol or "").strip().upper()
        key = f"oearn:{symbol}"

        def compute() -> dict:
            calls: list[tuple[str, Callable[[], dict]]] = []
            skipped: list[dict] = []
            av_ok, av_reason = self._av_ready()
            if av_ok and self.alphavantage is not None:
                calls.append(
                    ("alphavantage", lambda: self.alphavantage.get_earnings(symbol))
                )
            else:
                skipped.append(
                    {
                        "provider": "alphavantage",
                        "reason": av_reason or "Leg not wired.",
                    }
                )
            td_ok, td_reason = self._td_room(2)
            if td_ok and self.twelvedata is not None:
                calls.append(
                    ("twelvedata", lambda: self.twelvedata.get_earnings_td(symbol))
                )
            else:
                skipped.append(
                    {"provider": "twelvedata", "reason": td_reason or "Leg not wired."}
                )
            # Capability routing: keyed Indian leg contributes fiscal-year
            # reported EPS; keyless it stays out.
            leg = self._indian_leg()
            in_ok, in_reason = self._indian_ready(symbol)
            if in_ok and leg is not None and is_indian(symbol):
                calls.append(("indian-api", lambda: leg.get_earnings(symbol)))
            else:
                skipped.append(
                    {
                        "provider": "indian-api",
                        "reason": in_reason or "Leg not wired.",
                    }
                )
            if self.yahoo_fund is not None:
                calls.append(
                    ("yahoo-fundamentals", lambda: self.yahoo_fund.get_earnings(symbol))
                )
            else:
                skipped.append(
                    {"provider": "yahoo-fundamentals", "reason": "Leg not wired."}
                )
            results = self._fanout(key + ":fan", EARNINGS_TTL, calls)
            av = results.get("alphavantage", {})
            td = results.get("twelvedata", {})
            inapi = results.get("indian-api", {})
            yf = results.get("yahoo-fundamentals", {})
            av_d = av.get("data") if _ok(av) else {}
            td_rows = ((td.get("data") or {}).get("rows") if _ok(td) else []) or []
            in_d = inapi.get("data") if _ok(inapi) else {}
            y_d = yf.get("data") if _ok(yf) else {}
            if not av_d and not td_rows and not in_d and not y_d:
                return _honest_unavailable("earnings data", results, skipped)
            from providers.schema import field as _f

            comparisons = []
            if av_d:
                by_date = {}
                for r in td_rows:
                    by_date[str(r.get("date") or "")] = r
                for row in (av_d.get("quarterly") or [])[:8]:
                    d = str(row.get("fiscalDateEnding") or "")
                    match = by_date.get(d)
                    if match is None:
                        continue
                    comparisons.append(
                        _rec.compare(
                            f"reported EPS {d}",
                            _f(
                                row.get("reportedEPS"),
                                "alphavantage",
                                av.get("as_of"),
                                d,
                            ),
                            [
                                _f(
                                    match.get("reported_eps"),
                                    "twelvedata",
                                    td.get("as_of"),
                                    d,
                                )
                            ],
                        )
                    )
            if av_d:
                data = dict(av_d)
                prim_src = "alphavantage"
            elif y_d:
                data = {
                    "symbol": symbol,
                    "annual": [],
                    "quarterly": y_d.get("quarterly") or [],
                    "note": "Quarterly reported vs estimated EPS (Yahoo Finance).",
                }
                prim_src = "yahoo-fundamentals"
            elif in_d:
                data = {
                    "symbol": symbol,
                    "annual": in_d.get("annual") or [],
                    "quarterly": in_d.get("quarterly") or [],
                    "note": in_d.get("note")
                    or "Reported fiscal-year EPS (Indian Stock Market API).",
                }
                prim_src = "indian-api"
            else:
                data = {
                    "symbol": symbol,
                    "annual": [],
                    "quarterly": [],
                    "note": "Alpha Vantage unavailable; Twelve Data rows below.",
                }
                prim_src = "twelvedata"
            if td_rows:
                data["twelvedata_rows"] = td_rows
            return {
                "status": "live",
                "source": prim_src,
                "as_of": av.get("as_of") or yf.get("as_of") or inapi.get("as_of") or td.get("as_of"),
                "timeliness": "END-OF-DAY",
                "data": data,
                "providers_queried": _queried(results),
                "reconciliation": {
                    "comparisons": comparisons,
                    "summary": _rec.summarize(comparisons),
                    "primary": prim_src,
                    "skipped": skipped,
                },
                "message": None,
            }

        return self._cached_or(key, EARNINGS_TTL, compute)

    def get_news(
        self,
        symbol: str | None = None,
        topic: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Yahoo RSS + AV sentiment merged, deduplicated by URL."""
        key = f"onews:{symbol or ''}:{topic or ''}:{limit}"
        symbol = (symbol or "").strip().upper() or None

        def compute() -> dict:
            calls: list[tuple[str, Callable[[], dict]]] = []
            skipped: list[dict] = []
            if self.news_rss is not None:
                calls.append(
                    ("yahoo-rss", lambda: self.news_rss.get_news(symbol, topic, limit))
                )
            else:
                skipped.append({"provider": "yahoo-rss", "reason": "Leg not wired."})
            av_ok, av_reason = self._av_ready()
            if av_ok and self.alphavantage is not None:
                calls.append(
                    (
                        "alphavantage",
                        lambda: self.alphavantage.get_av_news(
                            symbol or "", topic or "", limit
                        ),
                    )
                )
            else:
                skipped.append(
                    {
                        "provider": "alphavantage",
                        "reason": av_reason or "Leg not wired.",
                    }
                )
            # Capability routing: keyed Indian leg (/stock recentNews +
            # /news) joins yahoo-rss + AV; keyless it stays out.
            # symbol may be None here (market headlines): guard the check.
            leg = self._indian_leg()
            in_ok, in_reason = self._indian_ready(symbol or "")
            if (
                in_ok
                and leg is not None
                and symbol is not None
                and is_indian(symbol)
            ):
                calls.append(("indian-api", lambda: leg.get_news(symbol, topic, limit)))
            else:
                skipped.append(
                    {
                        "provider": "indian-api",
                        "reason": "Missing symbol."
                        if not (symbol or "").strip()
                        else (in_reason or "Leg not wired."),
                    }
                )
            results = self._fanout(key + ":fan", NEWS_TTL, calls)
            aliases = _entity_aliases(symbol)
            seen_urls: set[str] = set()
            seen_heads: list[set[str]] = []
            items: list[dict] = []
            for name in ("yahoo-rss", "alphavantage", "indian-api"):
                env = results.get(name, {})
                if env.get("status") != "live":
                    continue
                for it in (env.get("data") or {}).get("items") or []:
                    url = str(it.get("url") or "")
                    if not url or url in seen_urls:
                        continue
                    head = _headline_tokens(str(it.get("title") or ""))
                    if head and any(_same_story(head, prev) for prev in seen_heads):
                        continue  # same story, different publisher
                    seen_urls.add(url)
                    if head:
                        seen_heads.append(head)
                    items.append({**it, "via": name,
                                  "relevance": _relevance(str(it.get("title") or ""),
                                                          str(it.get("summary") or ""),
                                                          aliases)})
            # Company-linked ranking: entity-matching items first. Items
            # that match no alias are kept (market context) but demoted.
            items.sort(key=lambda i: (i.get("relevance") or 0), reverse=True)
            if not items:
                first = next(
                    (
                        results.get(n)
                        for n in ("yahoo-rss", "alphavantage")
                        if results.get(n)
                    ),
                    None,
                )
                env = dict(first or {"status": "unavailable", "source": "orchestrator"})
                env["providers_queried"] = _queried(results)
                env["reconciliation"] = {"skipped": skipped}
                env["provider_status"] = _provider_status_list(skipped)
                return env
            return {
                "status": "live",
                "source": "orchestrator",
                "as_of": _now_iso(),
                "timeliness": "DELAYED",
                "data": {"items": items[:limit]},
                "providers_queried": _queried(results),
                "reconciliation": {"skipped": skipped},
                "message": None,
                "dedup": "URL + headline-similarity (same-story); entity-ranked.",
                "filings_note": "Press/news only. Official NSE/BSE filings and "
                "exchange-reported dividends/splits live under Corporate "
                "Actions, never mixed into news.",
            }

        return self._cached_or(key, NEWS_TTL, compute)

    def get_actions(self, symbol: str) -> dict:
        """Yahoo events + AV + TD actions, every row source-tagged."""
        symbol = (symbol or "").strip().upper()
        key = f"oact:{symbol}"

        def compute() -> dict:
            calls: list[tuple[str, Callable[[], dict]]] = []
            skipped: list[dict] = []
            if self.actions_yahoo is not None:
                calls.append(
                    (
                        "yahoo-events",
                        lambda: self.actions_yahoo.get_corporate_actions(symbol),
                    )
                )
            else:
                skipped.append({"provider": "yahoo-events", "reason": "Leg not wired."})
            av_ok, av_reason = self._av_ready()
            if av_ok and self.alphavantage is not None:
                calls.append(
                    (
                        "alphavantage-div",
                        lambda: self.alphavantage.get_dividends(symbol),
                    )
                )
                calls.append(
                    ("alphavantage-split", lambda: self.alphavantage.get_splits(symbol))
                )
            else:
                skipped.append(
                    {
                        "provider": "alphavantage",
                        "reason": av_reason or "Leg not wired.",
                    }
                )
            td_ok, td_reason = self._td_room(4)
            if td_ok and self.twelvedata is not None:
                calls.append(
                    ("twelvedata", lambda: self.twelvedata.get_actions_td(symbol))
                )
            else:
                skipped.append(
                    {"provider": "twelvedata", "reason": td_reason or "Leg not wired."}
                )
            # Capability routing: keyed Indian leg (dividends/splits +
            # extras) joins yahoo-events + AV + TD; keyless it stays out.
            # (The merge below already dedupes indian-api rows when present.)
            leg = self._indian_leg()
            in_ok, in_reason = self._indian_ready(symbol)
            if in_ok and leg is not None and is_indian(symbol):
                calls.append(("indian-api", lambda: leg.get_actions(symbol)))
            else:
                skipped.append(
                    {
                        "provider": "indian-api",
                        "reason": in_reason or "Leg not wired.",
                    }
                )
            results = self._fanout(key + ":fan", ACTIONS_TTL, calls)
            dividends: list[dict] = []
            splits: list[dict] = []
            ye = results.get("yahoo-events", {})
            if _ok(ye):
                dividends += [
                    {**d, "source": "yahoo-events"}
                    for d in (ye["data"].get("dividends") or [])
                ]
                splits += [
                    {**s, "source": "yahoo-events"}
                    for s in (ye["data"].get("splits") or [])
                ]
            for name in ("alphavantage-div", "alphavantage-split"):
                env = results.get(name, {})
                if _ok(env):
                    rows = (
                        env["data"].get("dividends") or env["data"].get("splits") or []
                    )
                    for row in rows:
                        tagged = {**row, "source": "alphavantage"}
                        (dividends if "div" in name else splits).append(tagged)
            tde = results.get("twelvedata", {})
            if _ok(tde):
                dividends += tde["data"].get("dividends", [])
                splits += tde["data"].get("splits", [])
            iae = results.get("indian-api", {})
            if _ok(iae):
                dividends += [
                    {**d, "source": "indian-api"}
                    for d in iae["data"].get("dividends", [])
                ]
                splits += [
                    {**s, "source": "indian-api"} for s in iae["data"].get("splits", [])
                ]
            if not dividends and not splits:
                return {
                    "status": "unavailable",
                    "source": "orchestrator",
                    "as_of": None,
                    "data": None,
                    "message": "No corporate actions from any provider: "
                    + "; ".join(_queried(results)),
                    "providers_queried": _queried(results),
                    "reconciliation": {"skipped": skipped},
                    "provider_status": _provider_status_list(skipped),
                }
            # Cross-provider dedupe: same date+amount (dividends) or
            # date+ratio (splits) from two feeds is one event. Sources
            # are preserved on the surviving row.
            seen_divs: set[str] = set()
            uniq_divs = []
            for d in dividends:
                dkey = f"{d.get('date')}|{d.get('amount')}"
                if dkey not in seen_divs:
                    seen_divs.add(dkey)
                    uniq_divs.append(d)
            seen_splits: set[str] = set()
            uniq_splits = []
            for s in splits:
                skey = f"{s.get('date')}|{s.get('numerator')}:{s.get('denominator')}"
                if skey not in seen_splits:
                    seen_splits.add(skey)
                    uniq_splits.append(s)
            dividends, splits = uniq_divs, uniq_splits
            dividends.sort(key=lambda d: str(d.get("date") or ""), reverse=True)
            splits.sort(key=lambda s: str(s.get("date") or ""), reverse=True)
            return {
                "status": "live",
                "source": "orchestrator",
                "as_of": _now_iso(),
                "timeliness": "END-OF-DAY",
                "data": {
                    "symbol": symbol,
                    "dividends": dividends[:40],
                    "splits": splits[:40],
                    "note": "Every row carries its source. Nothing "
                    "inferred from price moves.",
                },
                "providers_queried": _queried(results),
                "reconciliation": {"skipped": skipped},
                "message": None,
            }

        return self._cached_or(key, ACTIONS_TTL, compute)

    def get_estimates(self, symbol: str) -> dict:
        """Analyst estimates: Alpha Vantage EPS/revenue forecasts plus the
        keyed Indian leg's reported ratings, forecasts and target prices.
        Estimates are never synthesised."""
        symbol = (symbol or "").strip().upper()
        key = f"oest:{symbol}"

        def compute() -> dict:
            calls: list[tuple[str, Callable[[], dict]]] = []
            skipped: list[dict] = []
            av_ok, av_reason = self._av_ready()
            if av_ok and self.alphavantage is not None:
                calls.append(
                    ("alphavantage", lambda: self.alphavantage.get_estimates(symbol))
                )
            else:
                skipped.append(
                    {
                        "provider": "alphavantage",
                        "reason": av_reason or "Leg not wired.",
                    }
                )
            # Capability routing: keyed Indian leg (ratings + forecasts +
            # targets) joins AV; keyless it stays out.
            leg = self._indian_leg()
            in_ok, in_reason = self._indian_ready(symbol)
            if in_ok and leg is not None and is_indian(symbol):
                calls.append(("indian-api", lambda: leg.get_estimates(symbol)))
            else:
                skipped.append(
                    {
                        "provider": "indian-api",
                        "reason": in_reason or "Leg not wired.",
                    }
                )
            results = self._fanout(key + ":fan", ESTIMATES_TTL, calls)
            av = results.get("alphavantage", {})
            inapi = results.get("indian-api", {})
            av_d = av.get("data") if _ok(av) else {}
            in_d = inapi.get("data") if _ok(inapi) else {}
            if not av_d and not in_d:
                return _honest_unavailable("analyst estimates", results, skipped)
            if av_d:
                data = dict(av_d)
                as_of = av.get("as_of")
                prim_src = av.get("source", "alphavantage")
            else:
                data = dict(in_d or {})
                as_of = inapi.get("as_of")
                prim_src = inapi.get("source", "indian-api")
            if (in_d or {}).get("analyst_ratings"):
                data["analyst_ratings"] = (in_d or {}).get("analyst_ratings")
            if (in_d or {}).get("forecasts"):
                data["indian_forecasts"] = (in_d or {}).get("forecasts")
            if (in_d or {}).get("target_price") is not None:
                data["indian_target_price"] = (in_d or {}).get("target_price")
            return {
                "status": "live",
                "source": prim_src,
                "as_of": as_of,
                "timeliness": "END-OF-DAY",
                "data": data,
                "providers_queried": _queried(results),
                "reconciliation": {"skipped": skipped, "primary": prim_src},
                "message": None,
            }

        return self._cached_or(key, ESTIMATES_TTL, compute)

    def get_shareholding(self, symbol: str) -> dict:
        """Ownership split for NSE/BSE symbols (keyed Indian API).
        Provider-reported filing figures only — never calculated."""
        symbol = (symbol or "").strip().upper()
        key = f"ohold:{symbol}"

        def compute() -> dict:
            leg = self._indian_leg()
            in_ok, in_reason = self._indian_ready(symbol)
            if not in_ok or leg is None:
                skipped = [
                    {
                        "provider": "indian-api",
                        "reason": in_reason or "Leg not wired.",
                    }
                ]
                return {
                    "status": "unavailable",
                    "source": "orchestrator",
                    "as_of": None,
                    "data": None,
                    "message": "No configured provider currently supplies "
                    "ownership splits. Providers checked: indian-api — "
                    + (in_reason or "Leg not wired.")
                    + ".",
                    "providers_queried": ["indian-api:skipped"],
                    "reconciliation": {"skipped": skipped},
                    "provider_status": _provider_status_list(skipped),
                }
            if not is_indian(symbol):
                return {
                    "status": "unavailable",
                    "source": "orchestrator",
                    "as_of": None,
                    "data": None,
                    "message": "Ownership splits are only offered for NSE/BSE "
                    f"symbols; '{symbol}' was skipped (never guessed).",
                    "providers_queried": ["indian-api:skipped"],
                }
            return leg.get_shareholding(symbol)

        return self._cached_or(key, ACTIONS_TTL, compute)


def _ok(env: dict) -> bool:
    """A leg answered with usable data (live OR delayed)."""
    return (
        isinstance(env, dict)
        and env.get("status") in ("live", "delayed")
        and env.get("data") is not None
    )


def _classify_market(symbol: str, quote: dict) -> dict:
    """India vs US vs Global bucket from symbol + quote metadata.

    Rules (no guessing): .NS/.BO suffix, NSE/BSE exchange text or INR
    currency -> India. .NS-style Indian indices (^NSEI, ^BSESN, ^NSEBANK,
    ^CNX*) -> India. US exchange text (NASDAQ/NYSE/AMEX/ARCA/BATS) or a
    suffix-less symbol with USD currency -> US. Everything else
    (FX `=X`, crypto `-USD`, futures, other exchanges) -> Global.
    """
    sym = (symbol or "").strip().upper()
    q = quote or {}
    exch = f"{q.get('exchange') or ''} {q.get('timezone') or ''}".upper()
    ccy = str(q.get("currency") or "").upper()
    if "=" in sym or sym.endswith("-USD"):
        # Futures (GC=F), FX (INR=X), crypto (BTC-USD): global bucket.
        return {"id": "GLOBAL", "label": "Global"}
    if (
        sym.endswith((".NS", ".BO"))
        or "NSE" in exch
        or "BSE" in exch
        or "KOLKATA" in exch
        or "MUMBAI" in exch
        or ccy == "INR"
        or sym in ("^NSEI", "^NSEBANK", "^BSESN")
        or sym.startswith("^CNX")
        or sym == "NIFTY_FIN_SERVICE.NS"
    ):
        return {"id": "IN", "label": "India"}
    if (
        any(k in exch for k in ("NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "IEX"))
        or (ccy == "USD" and "." not in sym and not sym.startswith("^"))
    ):
        return {"id": "US", "label": "US"}
    return {"id": "GLOBAL", "label": "Global"}


_STOPWORDS = frozenset(
    "the a an and or of for to in on with stock stocks market markets "
    "ltd limited inc corp corporation company group holdings new".split()
)


def _headline_tokens(title: str) -> set[str]:
    import re as _re

    toks = set(_re.findall(r"[a-z0-9]{3,}", (title or "").lower()))
    return {t for t in toks if t not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _same_story(a: set[str], b: set[str]) -> bool:
    """Duplicate detector for short headlines: Jaccard OR overlap.

    Pure Jaccard punishes short headlines (one extra word tanks the
    score), so near-identical publisher rewrites also match on overlap
    (|intersection| / min length).
    """
    if not a or not b:
        return False
    inter = len(a & b)
    if inter / len(a | b) >= 0.6:
        return True
    return inter / min(len(a), len(b)) >= 0.8


def _entity_aliases(symbol: str | None) -> list[str]:
    """Never search just a ticker: TCS + TCS.NS + NSE:TCS + company tokens."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return []
    out = [sym]
    base = sym.removesuffix(".NS").removesuffix(".BO")
    if base != sym:
        out.append(base)
        out.append("NSE:" + base)
        out.append("BSE:" + base)
    return out


def _relevance(title: str, summary: str, aliases: list[str]) -> int:
    """Entity-match score; company-linked items rank above market noise."""
    text = f"{title} {summary}".upper()
    score = 0
    for alias in aliases:
        if not alias:
            continue
        if alias in text:
            score += 3 if "." in alias or ":" in alias else 2
    return score


def _queried(results: dict[str, dict]) -> list[str]:
    out = []
    for name, env in results.items():
        if not isinstance(env, dict):
            continue
        out.append(f"{name}:{env.get('status', '?')}")
    return out


def _leg_detail(results: dict[str, dict]) -> list[str]:
    """One-line per-leg failure reasons for miss envelopes.

    Safe to expose: server responses pass deep secret redaction, and
    these are upstream status texts, never credentials.
    """
    out = []
    for name, env in results.items():
        if not isinstance(env, dict):
            continue
        if env.get("status") in ("live", "delayed"):
            continue
        msg = str(env.get("message") or "no detail")[:160]
        out.append(f"{name}: {msg}")
    return out


def resolve_providers(ticker: str, capability: str) -> list[dict]:
    """Per-ticker provider resolution: which legs can serve (ticker,
    capability) and why others cannot. Applicability depends on market
    (.NS/.BO vs global), the CAPABILITIES matrix and key configuration
    — never on a single global switch.

    Returns [{provider, applicable, reason}] without network calls.
    """
    from providers import indianapi as _inmod

    sym = (ticker or "").strip().upper()
    cap = (capability or "").strip().lower()
    indian = is_indian(sym)
    av_key = False
    td_key = False
    try:
        from providers.fundamentals import _api_key as _avk

        av_key = bool(_avk())
    except Exception:
        av_key = False
    try:
        from providers.twelvedata import _api_key as _tdk

        td_key = bool(_tdk())
    except Exception:
        td_key = False
    in_key = bool(_inmod._api_key() if hasattr(_inmod, "_api_key") else False)
    out = []
    if cap in ("quote", "history", "search"):
        out.append(
            {"provider": "yahoo", "applicable": True, "reason": "Global free feed."}
        )
    if cap == "quote" and indian:
        out.append(
            {
                "provider": "indian-api",
                "applicable": True,
                "reason": "Keyed snapshot."
                if in_key
                else "No-auth market snapshot.",
            }
        )
    if cap in ("statements", "earnings", "estimates", "actions", "news", "holdings"):
        if indian and CAPABILITIES["indian-api"].get(cap):
            out.append(
                {
                    "provider": "indian-api",
                    "applicable": in_key,
                    "reason": "Keyed endpoint."
                    if in_key
                    else "INDIAN_STOCK_MARKET_API_KEY not configured.",
                }
            )
        else:
            out.append(
                {
                    "provider": "indian-api",
                    "reason": "Non-Indian symbol."
                    if not indian
                    else "Capability not offered.",
                    "applicable": False,
                }
            )
    if cap in ("statements", "earnings", "estimates", "valuation"):
        out.append(
            {
                "provider": "alphavantage",
                "applicable": av_key,
                "reason": "Key configured."
                if av_key
                else "ALPHA_VANTAGE_API_KEY not configured.",
            }
        )
        if cap in ("statements", "earnings", "valuation"):
            out.append(
                {
                    "provider": "twelvedata",
                    "applicable": td_key,
                    "reason": "Key configured; budget-guarded per call."
                    if td_key
                    else "TWELVE_DATA_API_KEY not configured.",
                }
            )
    return out


def _provider_state(reason: str) -> str:
    """Standardize WHY a leg did not contribute: KEY_REQUIRED |
    NOT_CONFIGURED | UPSTREAM_LIMITATION. Never expose credentials."""
    low = (reason or "").lower()
    if "not configured" in low or "api key" in low or "not wired" in low:
        return "KEY_REQUIRED"
    if (
        "non-indian" in low
        or "not covered" in low
        or "unsupported" in low
        or "not supplied" in low
    ):
        return "NOT_CONFIGURED"
    return "UPSTREAM_LIMITATION"


def _provider_status_list(skipped: list[dict] | None) -> list[dict]:
    """Per-provider WHY for miss envelopes (no credentials, reasons only)."""
    return [
        {
            "provider": s.get("provider"),
            "state": _provider_state(str(s.get("reason") or "")),
            "reason": s.get("reason"),
        }
        for s in (skipped or [])
        if isinstance(s, dict)
    ]


def _honest_unavailable(
    domain_label: str,
    results: dict[str, dict],
    skipped: list[dict],
) -> dict:
    """Honest miss envelope: names EVERY provider checked with its reason.

    The terminal must never pretend one provider is the only source, so
    single-leg key messages are never passed through as the domain
    answer. Status stays `unavailable` (never fabricated values); the
    per-provider WHY travels in `provider_status`.
    """
    return {
        "status": "unavailable",
        "source": "orchestrator",
        "as_of": None,
        "data": None,
        "message": f"No configured provider currently supplies this {domain_label}. "
        + "Providers checked: "
        + (
            "; ".join(
                f"{s.get('provider')} — {s.get('reason')}" for s in (skipped or [])
            )
            or "none wired"
        )
        + ".",
        "providers_queried": _queried(results),
        "reconciliation": {"skipped": skipped},
        "provider_status": _provider_status_list(skipped),
    }


def _reconcile_statements(
    statement: str, av_data: dict | None, td_data: dict | None
) -> list[dict]:
    """Reconcile headline lines (revenue, net income) matched by period."""
    from providers.schema import field as _f

    if not av_data or not td_data:
        return []
    aliases = {
        "revenue": (
            ["totalRevenue", "total_revenue", "revenue", "revenues", "sales"],
            ["totalRevenue", "revenue", "revenues", "sales", "total_revenues"],
        ),
        "net_income": (
            ["netIncome", "net_income", "netEarnings"],
            ["netIncome", "net_income", "netEarnings", "net_earnings"],
        ),
    }
    av_reports = av_data.get("reports") or []
    td_reports = td_data.get("reports") or []
    if not av_reports or not td_reports:
        return []
    av0, td0 = av_reports[0], td_reports[0]
    av_end = str(av0.get("fiscalDateEnding") or av0.get("date") or "")
    td_end = str(td0.get("fiscalDateEnding") or td0.get("date") or "")
    av_ccy = av_data.get("currency")
    td_ccy = td_data.get("currency")
    comparisons = []
    for label, (av_keys, td_keys) in aliases.items():
        av_v = next((av0.get(k) for k in av_keys if av0.get(k) is not None), None)
        td_v = next((td0.get(k) for k in td_keys if td0.get(k) is not None), None)
        comparisons.append(
            _rec.compare(
                f"{statement} {label}",
                _f(av_v, "alphavantage", None, av_end, av_ccy),
                [_f(td_v, "twelvedata", None, td_end, td_ccy)],
            )
        )
    return comparisons
