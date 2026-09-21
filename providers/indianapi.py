"""Indian Stock Market API — capability-aware NSE/BSE leg.

Dual-mode provider (same id ``indian-api``):

KEYED MODE (INDIAN_STOCK_MARKET_API_KEY present, sent as the
``x-api-key`` header — never in URLs, logs or client payloads):
official https://stock.indianapi.in endpoints —
  GET /stock                  quote, profile, statements, ratios,
                              earnings, ratings, ownership, actions, news
  GET /statement              financial statements (annual/quarterly
                              where returned; never period-substituted)
  GET /historical_data        historical price/indicator datasets
                              (stock_name, period, filter)
  GET /historical_stats       quarter_results, yoy_results, balancesheet,
                              cashflow, ratios, shareholding patterns
  GET /corporate_actions      dividend/bonus/split/rights/merger rows
  GET /stock_forecasts        analyst forecasts where returned
  GET /stock_target_price     analyst target prices where returned
  GET /news                   company news where returned

NO-AUTH MODE (no key configured): free Yahoo quoteSummary-backed leg
for quote, company identity (sector/industry) and market fundamentals
(market cap, P/E, EPS, book value, dividend yield, 52W range). The
Yahoo crumb/cookie handshake stays server-side and is never exposed.

Only .NS/.BO symbols are attempted; global tickers (META, MSFT, AAPL)
pass through untouched so one provider's failure can never fail the
company page. Financial statements, earnings series, estimates,
ownership, forecasts and targets are never synthesised.
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

from .base import (
    MarketDataProvider,
    error_envelope,
    live_envelope,
    unavailable,
)
from .indian import is_indian

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}
# Yahoo only issues session cookies to browser-like requests.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}
SOURCE = "indian-api"
SOURCE_LABEL = "Indian Stock Market API"

DEFAULT_BASE = "https://stock.indianapi.in"
QUOTE_MAX_AGE = 300.0  # quote freshness: refetch after 5 min
DOMAIN_MAX_AGE = 24 * 3600.0  # profile/fundamentals/news/actions
MAX_REPORTS = 12

PER_MINUTE = 30
PER_DAY = 2000

QS_MODULES = "price,summaryDetail,defaultKeyStatistics,assetProfile"
CRUMB_TTL = 50 * 60.0

_budget_lock = threading.Lock()
_minute_window_start = 0.0
_minute_used = 0
_day_key = ""
_day_used = 0

_crumb_lock = threading.Lock()
_crumb_cache: dict[str, Any] = {"crumb": None, "cookie": None, "expires_at": 0.0}

_HIST_PERIODS = ("1m", "6m", "1yr", "3yr", "5yr", "10yr", "max")
_HIST_STATS = (
    "quarter_results",
    "yoy_results",
    "balancesheet",
    "cashflow",
    "ratios",
    "shareholding_pattern_quarterly",
    "shareholding_pattern_yearly",
)


def _api_key() -> str:
    """Server-side key for the official API (x-api-key header).

    Absent locally unless INDIAN_STOCK_MARKET_API_KEY is set; never
    hard-coded, never logged, never sent to clients.
    """
    return (os.environ.get("INDIAN_STOCK_MARKET_API_KEY") or "").strip()


def base_url() -> str:
    return (os.environ.get("INDIAN_API_BASE_URL") or DEFAULT_BASE).rstrip("/")


def budget_snapshot() -> dict:
    with _budget_lock:
        return {
            "per_minute_limit": PER_MINUTE,
            "per_minute_used": _minute_used,
            "daily_limit": PER_DAY,
            "daily_used": _day_used,
            "day": _day_key,
        }


def _budget_take(credits: int = 1) -> str | None:
    global _minute_window_start, _minute_used, _day_key, _day_used
    now = time.time()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _budget_lock:
        if today != _day_key:
            _day_key, _day_used = today, 0
            _minute_window_start, _minute_used = now, 0
        if now - _minute_window_start >= 60:
            _minute_window_start, _minute_used = now, 0
        if _minute_used + credits > PER_MINUTE:
            return "per-minute budget exhausted (self-imposed 30/min guard)"
        if _day_used + credits > PER_DAY:
            return "daily budget exhausted (self-imposed 2000/day guard)"
        _minute_used += credits
        _day_used += credits
        return None


def to_name(symbol: str) -> str:
    """Strip a Yahoo-style suffix to the feed's bare-name lookup."""
    s = (symbol or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def _raw(field: Any) -> Any:
    if isinstance(field, dict):
        return field.get("raw")
    return field


def _num(v: Any) -> float | None:
    if isinstance(v, dict):
        v = v.get("raw", v.get("value", v.get("display")))
    if v in (None, "", "-", "None", "N/A", "NA", "null"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick(rows: list[Any], key: str) -> Any:
    """Find a metric row by key within a keyMetrics-style list."""
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        k = str(r.get("key") or "")
        dn = str(r.get("displayName") or "")
        if k == key or dn.strip() == key:
            return r.get("value")
    return None


def _qsymbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s.endswith((".NS", ".BO")):
        return s
    return s + ".NS" if s else s


def _asof_epoch(epoch: Any) -> str | None:
    try:
        ts = float(epoch)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _asof_ist(date: Any, time_: Any) -> int | None:
    """'16 Sep 2026' + '10:28:24' (IST) -> epoch seconds for the UI clock."""
    if not date or not time_:
        return None
    try:
        dt = datetime.strptime(
            str(date).strip() + " " + str(time_).strip(), "%d %b %Y %H:%M:%S"
        )
        try:
            from zoneinfo import ZoneInfo

            dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        except Exception:
            from datetime import timedelta

            dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


class _UpstreamError(Exception):
    """Raised by the transport with a ready-to-return envelope."""

    def __init__(self, env: dict):
        super().__init__(str(env.get("message") or "upstream error"))
        self.env = env


def _http_text(
    url: str, headers: dict | None = None, cookie: str = "", timeout: float = 15.0
) -> tuple[str, str]:
    head = dict(BROWSER_HEADERS if headers is None else headers)
    if cookie:
        head["Cookie"] = cookie
    req = urllib.request.Request(url, headers=head)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_cookie = resp.headers.get("Set-Cookie") or ""
        return resp.read().decode("utf-8", "replace"), raw_cookie


def _cookies_from(values: list[str]) -> str:
    pairs = []
    for value in values:
        first = (value or "").split(";")[0].strip()
        if first and "=" in first:
            pairs.append(first)
    seen: dict[str, str] = {}
    for pair in pairs:
        seen[pair.split("=", 1)[0]] = pair
    return "; ".join(seen.values())


def _crumb(ticker: str = "TCS.NS", force: bool = False) -> tuple[str, str]:
    """Cookie/crumb pair for Yahoo's authed endpoints (cached ~50 min)."""
    with _crumb_lock:
        hit = _crumb_cache
        if (
            not force
            and hit.get("crumb")
            and time.time() < float(hit.get("expires_at") or 0.0)
        ):
            return str(hit["crumb"]), str(hit.get("cookie") or "")
    try:
        cookie = ""
        for prime in (
            "https://finance.yahoo.com/quote/" + urllib.parse.quote(ticker),
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + urllib.parse.quote(ticker)
            + "?interval=1d&range=5d",
        ):
            try:
                req = urllib.request.Request(prime, headers=dict(BROWSER_HEADERS))
                with urllib.request.urlopen(req, timeout=15) as resp:
                    pairs = resp.headers.get_all("Set-Cookie") or (
                        [resp.headers.get("Set-Cookie")]
                        if resp.headers.get("Set-Cookie")
                        else []
                    )
                    cookie = _cookies_from([str(v) for v in pairs])
                    resp.read(4096)
                if cookie:
                    break
            except Exception:
                continue
        crumb, _ = _http_text(
            "https://query1.finance.yahoo.com/v1/test/getcrumb", None, cookie
        )
        crumb = crumb.strip()
    except Exception as exc:
        raise _UpstreamError(
            unavailable(
                SOURCE,
                "Indian Stock Market API session handshake failed "
                f"(Yahoo crumb unavailable): {exc}",
            )
        )
    if not crumb:
        raise _UpstreamError(
            unavailable(
                SOURCE,
                "Indian Stock Market API session handshake failed "
                "(Yahoo crumb empty).",
            )
        )
    with _crumb_lock:
        _crumb_cache.update(
            {"crumb": crumb, "cookie": cookie, "expires_at": time.time() + CRUMB_TTL}
        )
    return crumb, cookie


def _dedupe_news(items: list[dict]) -> list[dict]:
    """Deduplicate by URL, then headline+publisher similarity."""
    seen_urls: set[str] = set()
    seen_heads: set[str] = set()
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "").strip().lower()
        head = (
            str(it.get("title") or "").strip().lower()
            + "|"
            + str(it.get("source") or "").strip().lower()
        )
        if url and url in seen_urls:
            continue
        if head and head in seen_heads:
            continue
        if url:
            seen_urls.add(url)
        if head.strip("|"):
            seen_heads.add(head)
        out.append(it)
    return out


class IndianApiProvider(MarketDataProvider):
    """Capability-aware NSE/BSE leg: keyed official API, no-auth fallback."""

    name = "indian-api"
    capabilities: dict[str, bool] = {
        "quote": True,
        "fundamentals": True,
        "statements": True,  # keyed only (/stock, /statement, /historical_stats)
        "earnings": True,  # keyed only (fiscal-year reported EPS)
        "estimates": True,  # keyed only (ratings + forecasts/targets)
        "news": True,  # keyed only (/stock recentNews + /news)
        "actions": True,  # keyed only; no-auth covered by yahoo-events
        "holdings": True,  # keyed only (shareholding)
        "search": False,
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}  # name -> {"at", "payload"}
        self._detail_cache: dict[str, dict] = {}  # ticker -> {"at", "detail"}

    def budget_snapshot(self) -> dict:
        return budget_snapshot()

    def key_configured(self) -> bool:
        return bool(_api_key())

    # -- keyed transport -------------------------------------------------
    def _kget(self, path: str, params: dict, timeout: float = 20.0) -> Any:
        """GET base+path with x-api-key. Returns parsed JSON."""
        if not _api_key():
            raise _UpstreamError(
                unavailable(
                    SOURCE,
                    "INDIAN_STOCK_MARKET_API_KEY not configured.",
                    code="NOT_CONFIGURED",
                )
            )
        blocked = _budget_take(1)
        if blocked:
            raise _UpstreamError(
                unavailable(SOURCE, f"Rate budget exhausted: {blocked}.")
            )
        url = base_url() + path + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={**UA, "x-api-key": _api_key()})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise _UpstreamError(
                    {
                        "status": "error",
                        "source": SOURCE,
                        "as_of": None,
                        "data": None,
                        "code": "AUTH_ERROR",
                        "message": "Indian Stock Market API rejected the key "
                        "(HTTP 401). Check INDIAN_STOCK_MARKET_API_KEY.",
                    }
                )
            if exc.code == 429:
                raise _UpstreamError(
                    {
                        "status": "rate_limited",
                        "source": SOURCE,
                        "as_of": None,
                        "data": None,
                        "code": "RATE_LIMIT",
                        "message": "RATE LIMITED by Indian Stock Market API "
                        "(HTTP 429). Cooling down and falling back.",
                    }
                )
            if exc.code == 404:
                raise _UpstreamError(
                    unavailable(
                        SOURCE,
                        f"Symbol not found at {path} (HTTP 404).",
                    )
                )
            raise _UpstreamError(
                error_envelope(
                    SOURCE, f"Indian Stock Market API HTTP {exc.code}: {exc}"
                )
            )
        except _UpstreamError:
            raise
        except Exception as exc:
            raise _UpstreamError(
                error_envelope(
                    SOURCE, f"Indian Stock Market API request failed: {exc}"
                )
            )
        return payload

    def _stock(self, symbol: str, max_age: float) -> tuple[dict | None, dict | None]:
        """Keyed GET /stock payload under a freshness window."""
        name = to_name(symbol)
        now = time.time()
        with self._lock:
            hit = self._cache.get(name)
            if hit is not None and now - hit.get("at", 0.0) < max_age:
                return hit.get("payload"), None
            payload: Any = None
            env: dict | None = None
            try:
                payload = self._kget("/stock", {"name": name})
            except _UpstreamError as exc:
                env = exc.env
            except Exception as exc:
                env = error_envelope(
                    SOURCE, f"Indian Stock Market API request failed: {exc}"
                )
            if payload is not None and not isinstance(payload, dict):
                payload, env = None, unavailable(
                    SOURCE, f"Unexpected response for '{name}'."
                )
            elif isinstance(payload, dict) and (
                payload.get("err") or payload.get("error")
            ):
                payload, env = None, unavailable(
                    SOURCE,
                    str(payload.get("err") or payload.get("error"))
                    + f" (for '{name}').",
                )
            if payload is not None:
                self._cache[name] = {"at": now, "payload": payload}
            return payload, env

    # -- no-auth transport (Yahoo quoteSummary, crumb handshake) ---------
    def _quote_summary(self, ticker: str) -> dict:
        crumb, cookie = _crumb(ticker)
        url = (
            "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
            + urllib.parse.quote(ticker)
            + "?modules="
            + QS_MODULES
            + "&crumb="
            + urllib.parse.quote(crumb)
        )
        try:
            headers = dict(BROWSER_HEADERS, Cookie=cookie)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                try:
                    crumb, cookie = _crumb(ticker, force=True)
                    retry = url.split("&crumb=")[0] + "&crumb=" + urllib.parse.quote(
                        crumb
                    )
                    req = urllib.request.Request(
                        retry, headers=dict(BROWSER_HEADERS, Cookie=cookie)
                    )
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        payload = json.loads(resp.read().decode("utf-8", "replace"))
                except _UpstreamError:
                    raise
                except Exception as exc2:
                    raise _UpstreamError(
                        error_envelope(
                            SOURCE,
                            "Indian Stock Market API request failed "
                            f"(HTTP 401 retry): {exc2}",
                        )
                    )
            elif exc.code == 429:
                raise _UpstreamError(
                    {
                        "status": "rate_limited",
                        "source": SOURCE,
                        "as_of": None,
                        "data": None,
                        "code": "RATE_LIMIT",
                        "message": "RATE LIMITED by the upstream feed "
                        "(HTTP 429). Cooling down and falling back.",
                    }
                )
            else:
                raise _UpstreamError(
                    error_envelope(
                        SOURCE, f"Indian Stock Market API HTTP {exc.code}: {exc}"
                    )
                )
        except _UpstreamError:
            raise
        except Exception as exc:
            raise _UpstreamError(
                error_envelope(
                    SOURCE, f"Indian Stock Market API request failed: {exc}"
                )
            )
        if not isinstance(payload, dict):
            raise _UpstreamError(
                unavailable(SOURCE, f"Unexpected response for '{ticker}'.")
            )
        results = ((payload.get("quoteSummary") or {}).get("result")) or []
        if not results:
            raise _UpstreamError(
                unavailable(SOURCE, f"No data found for symbol '{ticker}'.")
            )
        return results[0]

    def _detail(self, symbol: str) -> dict:
        """Normalized no-auth detail (mirrors /stock res=num schema)."""
        ticker = _qsymbol(symbol)
        now = time.time()
        with self._lock:
            hit = self._detail_cache.get(ticker)
            if hit is not None and now - hit.get("at", 0.0) < QUOTE_MAX_AGE:
                return hit["detail"]
        result = self._quote_summary(ticker)
        price = result.get("price") or {}
        summary = result.get("summaryDetail") or {}
        stats = result.get("defaultKeyStatistics") or {}
        profile = result.get("assetProfile") or {}
        if _num(_raw(price.get("regularMarketPrice"))) is None:
            raise _UpstreamError(
                unavailable(SOURCE, f"No price available for '{ticker}'.")
            )
        pct = _num(_raw(price.get("regularMarketChangePercent")))
        mcap = _num(_raw(price.get("marketCap")))
        mcap_kind = "REPORTED" if mcap is not None else None
        if mcap is None:
            mcap = _num(_raw(summary.get("marketCap")))
            mcap_kind = "REPORTED" if mcap is not None else None
        if mcap is None:
            mcap = _num(_raw(summary.get("nonDilutedMarketCap")))
            mcap_kind = "REPORTED" if mcap is not None else None
        shares = _num(_raw(stats.get("sharesOutstanding")))
        last_px = _num(_raw(price.get("regularMarketPrice")))
        if mcap is None and last_px is not None and shares:
            mcap = round(last_px * shares, 2)
            mcap_kind = "CALCULATED"
        div = _num(_raw(summary.get("dividendYield")))
        detail = {
            "company_name": price.get("longName")
            or price.get("shortName")
            or ticker,
            "currency": price.get("currency") or "INR",
            "exchange": "BSE" if ticker.endswith(".BO") else "NSE",
            "ticker": ticker,
            "last_price": _num(_raw(price.get("regularMarketPrice"))),
            "change": _num(_raw(price.get("regularMarketChange"))),
            "percent_change": (pct * 100.0) if pct is not None else None,
            "previous_close": _num(_raw(price.get("regularMarketPreviousClose"))),
            "open": _num(_raw(price.get("regularMarketOpen"))),
            "day_high": _num(_raw(price.get("regularMarketDayHigh"))),
            "day_low": _num(_raw(price.get("regularMarketDayLow"))),
            "year_high": _num(_raw(summary.get("fiftyTwoWeekHigh"))),
            "year_low": _num(_raw(summary.get("fiftyTwoWeekLow"))),
            "volume": _num(_raw(price.get("regularMarketVolume"))),
            "market_cap": mcap,
            "market_cap_kind": mcap_kind,
            "pe_ratio": _num(_raw(summary.get("trailingPE"))),
            "dividend_yield": (div * 100.0) if div is not None else None,
            "book_value": _num(_raw(stats.get("bookValue"))),
            "eps": _num(_raw(stats.get("trailingEps"))),
            "sector": profile.get("sector") or None,
            "industry": profile.get("industry") or None,
            "market_time": _asof_epoch(_raw(price.get("regularMarketTime"))),
        }
        if detail["open"] is None:
            detail["open"] = _num(_raw(summary.get("open")))
        with self._lock:
            self._detail_cache[ticker] = {"at": now, "detail": detail}
        return detail

    # -- guards / loaders -------------------------------------------------
    def _guard(self, symbol: str) -> dict | None:
        if not is_indian(symbol):
            return unavailable(
                SOURCE,
                f"Symbol '{symbol}' is not an NSE/BSE symbol; "
                "the Indian leg passes it through.",
            )
        return None

    def _free(self, symbol: str) -> tuple[dict | None, dict | None]:
        """No-auth detail loader. Returns (detail, None) or (None, env)."""
        try:
            return self._detail(symbol), None
        except _UpstreamError as exc:
            return None, exc.env
        except Exception as exc:
            return None, error_envelope(
                SOURCE, f"Indian Stock Market API request failed: {exc}"
            )

    # -- quote -------------------------------------------------------------
    def get_quote(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if self.key_configured():
            payload, err = self._stock(symbol, QUOTE_MAX_AGE)
            if err is not None:
                # Invalid/expired key must not kill the page: fall back to
                # the free leg and say so.
                if (err.get("code") in ("AUTH_ERROR", "NOT_CONFIGURED")) or (
                    "rejected the key" in str(err.get("message") or "")
                ):
                    return self._free_quote(symbol, key_note=err.get("message"))
                return err
            assert payload is not None
            return self._keyed_quote(symbol, payload)
        return self._free_quote(symbol)

    def _keyed_quote(self, symbol: str, payload: dict) -> dict:
        cp = payload.get("currentPrice") or {}
        sd = payload.get("stockDetailsReusableData") or {}
        requested_bo = symbol.endswith(".BO")
        nse_px = _num(cp.get("NSE"))
        bse_px = _num(cp.get("BSE"))
        price: float | None = None
        if requested_bo and bse_px is not None:
            price, exchange = bse_px, "BSE"
        elif nse_px is not None:
            price, exchange = nse_px, "NSE"
        elif bse_px is not None:
            price, exchange = bse_px, "BSE"
        else:
            # Fall back to the fused snapshot price fields when the
            # per-exchange map is absent.
            price = _num(sd.get("price")) or _num(payload.get("lastPrice"))
            exchange = "BSE" if requested_bo else "NSE"
            if price is None:
                return unavailable(SOURCE, f"No price for '{symbol}' in the feed.")
        pct: float | None = _num(sd.get("percentChange"))
        if pct is not None and pct != -100.0:
            change = round(price - price / (1.0 + (pct / 100.0)), 2)
        else:
            change = None
        previous_close = round(price - change, 2) if change is not None else None
        quote = {
            "symbol": symbol,
            "name": payload.get("companyName"),
            "exchange": exchange,
            "currency": payload.get("currency") or "INR",
            "instrument_type": payload.get("instrumentType", "Equity"),
            "price": price,
            "previous_close": previous_close,
            "open": _num(sd.get("open")),
            "day_high": _num(sd.get("high")),
            "day_low": _num(sd.get("low")),
            "volume": _num(sd.get("volume")),
            "change": change,
            "change_pct": pct,
            "fifty_two_week_high": _num(sd.get("yhigh"))
            or _num(payload.get("yearHigh")),
            "fifty_two_week_low": _num(sd.get("ylow"))
            or _num(payload.get("yearLow")),
            "market_time": _asof_ist(sd.get("date"), sd.get("time")),
            "timezone": "Asia/Kolkata",
            "sector": payload.get("industry"),
        }
        env = live_envelope(SOURCE, quote, delayed=True)
        env["timeliness"] = "DELAYED"
        env["timeliness_note"] = (
            SOURCE_LABEL + " delayed NSE/BSE snapshot; never presented "
            "as exchange-certified real-time."
        )
        return env

    def _free_quote(self, symbol: str, key_note: str | None = None) -> dict:
        detail, err = self._free(symbol)
        if err:
            return err
        assert detail is not None
        quote = {
            "symbol": symbol,
            "name": detail["company_name"],
            "exchange": detail["exchange"],
            "currency": detail["currency"],
            "instrument_type": "Equity",
            "price": detail["last_price"],
            "previous_close": detail["previous_close"],
            "open": detail["open"],
            "day_high": detail["day_high"],
            "day_low": detail["day_low"],
            "volume": detail["volume"],
            "change": detail["change"],
            "change_pct": detail["percent_change"],
            "fifty_two_week_high": detail["year_high"],
            "fifty_two_week_low": detail["year_low"],
            "market_time": detail["market_time"],
            "timezone": "Asia/Kolkata",
            "market_cap": detail["market_cap"],
            "pe": detail["pe_ratio"],
            "eps": detail["eps"],
            "dividend_yield": detail["dividend_yield"],
            "book_value": detail["book_value"],
            "sector": detail["sector"],
            "industry": detail["industry"],
        }
        env = live_envelope(SOURCE, quote, delayed=True)
        env["timeliness"] = "DELAYED"
        env["timeliness_note"] = (
            SOURCE_LABEL + " delayed NSE/BSE snapshot (no-auth feed)"
            + (f"; key note: {key_note}" if key_note else "")
            + "; never presented as exchange-certified real-time."
        )
        return env

    # -- company identity ---------------------------------------------------
    def get_company_profile(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if self.key_configured():
            payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
            if err is not None:
                if err.get("code") in ("AUTH_ERROR", "NOT_CONFIGURED"):
                    return self._free_profile(symbol)
                return err
            assert payload is not None
            cp = payload.get("companyProfile") or {}
            officers = []
            for o in (cp.get("officers") or {}).get("officer") or []:
                if not isinstance(o, dict):
                    continue
                title = o.get("title")
                name = " ".join(
                    str(o.get(k) or "").strip() for k in ("firstName", "mI", "lastName")
                ).strip()
                officers.append(
                    {
                        "name": name or None,
                        "title": title.get("description")
                        if isinstance(title, dict)
                        else title,
                        "since": o.get("since"),
                    }
                )
            data = {
                "symbol": symbol,
                "name": payload.get("companyName"),
                "exchange": "NSE" if not symbol.endswith(".BO") else "BSE",
                "currency": "INR",
                "instrument_type": "Equity",
                "sector": payload.get("industry"),
                "industry": cp.get("mgIndustry") or payload.get("industry"),
                "description": cp.get("companyDescription"),
                "officers": officers[:10],
                "isin": cp.get("isInId"),
                "bse_code": cp.get("exchangeCodeBse"),
                "nse_code": cp.get("exchangeCodeNse"),
            }
            env = live_envelope(SOURCE, data, delayed=True)
            env["timeliness"] = "DELAYED"
            return env
        return self._free_profile(symbol)

    def _free_profile(self, symbol: str) -> dict:
        detail, err = self._free(symbol)
        if err:
            return err
        assert detail is not None
        return live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "name": detail["company_name"],
                "exchange": detail["exchange"],
                "currency": detail["currency"],
                "sector": detail["sector"],
                "industry": detail["industry"],
                "description": None,
                "profile_note": (
                    "Identity plus sector/industry from the free no-auth "
                    "Indian Stock Market API. Descriptions are not supplied "
                    "by this feed."
                ),
            },
            delayed=True,
        )

    # -- fundamentals: flat AV-style overview shape ------------------------
    def get_ratios(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if self.key_configured():
            payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
            if err is not None:
                if err.get("code") in ("AUTH_ERROR", "NOT_CONFIGURED"):
                    return self._free_ratios(symbol)
                return err
            assert payload is not None
            return self._keyed_ratios(symbol, payload)
        return self._free_ratios(symbol)

    def _keyed_ratios(self, symbol: str, payload: dict) -> dict:
        km = payload.get("keyMetrics") or {}
        cp = payload.get("companyProfile") or {}

        def m(cat: str, key: str) -> float | None:
            return _num(_pick(km.get(cat) or [], key))

        def fy_period() -> str | None:
            fin = payload.get("financials") or []
            end = None
            for rep in fin:
                if isinstance(rep, dict):
                    end = rep.get("EndDate")
                    break
            return f"FY{str(end)[:4]}" if end else None

        data = {
            "Symbol": symbol,
            "Name": payload.get("companyName"),
            "Exchange": "NSE" if not symbol.endswith(".BO") else "BSE",
            "Currency": "INR",
            "Sector": payload.get("industry"),
            "Industry": cp.get("mgIndustry") or payload.get("industry"),
            "Description": cp.get("companyDescription"),
            "MarketCapitalization": m("priceandVolume", "marketCap"),
            "PERatio": m("valuation", "pPerEBasicExcludingExtraordinaryItemsTTM"),
            "ForwardPE": None,
            "PEGRatio": m("valuation", "pegRatio"),
            "PriceToBookRatio": m("valuation", "priceToBookMostRecentFiscalYear"),
            "PriceToSalesRatioTTM": m("valuation", "priceToSalesTrailing12Month"),
            "EVToRevenue": None,
            "EVToEBITDA": None,
            "BookValue": m("persharedata", "bookValuePerShareMostRecentFiscalYear"),
            "EPS": m(
                "persharedata",
                "ePSBasicExcludingExtraordinaryItemsMostRecentFiscalYear",
            ),
            "ROE": m("mgmtEffectiveness", "returnOnAverageEquityMostRecentFiscalYear"),
            "ROA": m("mgmtEffectiveness", "returnOnAverageAssetsMostRecenFiscalYear"),
            "ROIC": m("mgmtEffectiveness", "returnOnInvestmentMostRecentFiscalYear"),
            "ReturnOnEquityTTM": None,
            "ReturnOnAssetsTTM": None,
            "ReturnOnInvestmentTTM": None,
            "ProfitMargin": m("margins", "netProfitMarginPercentTrailing12Month"),
            "OperatingMarginTTM": m("margins", "operatingMarginTrailing12Month"),
            "GrossMarginTTM": m("margins", "grossMarginTrailing12Month"),
            "DebtToEquity": m(
                "financialstrength", "totalDebtPerTotalEquityMostRecentFiscalYear"
            ),
            "CurrentRatio": m("financialstrength", "currentRatioMostRecentFiscalYear"),
            "PayoutRatio": m("financialstrength", "payoutRatioTrailing12Month"),
            "DividendYield": m(
                "valuation", "currentDividendYieldCommonStockPrimaryIssueLTM"
            ),
            "DividendPerShare": m(
                "persharedata", "dividendPerShareMostRecentFiscalYear"
            ),
            "Beta": m("priceandVolume", "beta"),
            "52WeekHigh": m("priceandVolume", "52WeekHigh")
            or _num(payload.get("yearHigh")),
            "52WeekLow": m("priceandVolume", "52WeekLow")
            or _num(payload.get("yearLow")),
            "SharesOutstanding": self._shares_outstanding(payload),
            "_period": fy_period(),
            "_metric_source": "indian-api keyMetrics",
            "MarketCapUnit": "₹ Crore",
            "SharesUnit": "Crore shares",
            "MarketCapKind": "REPORTED",
        }
        env = live_envelope(SOURCE, data, delayed=True)
        env["timeliness"] = "END-OF-DAY"
        env["timeliness_note"] = (
            SOURCE_LABEL + " reported figures; market cap and EPS are "
            "provider values (₹ Crore market cap), not recomputed here."
        )
        return env

    def _free_ratios(self, symbol: str) -> dict:
        """Reported market fundamentals only — no statements, no ROE."""
        detail, err = self._free(symbol)
        if err:
            return err
        assert detail is not None
        data = {
            "Symbol": symbol,
            "Name": detail["company_name"],
            "Currency": detail["currency"],
            "Sector": detail["sector"],
            "Industry": detail["industry"],
            "MarketCapitalization": detail["market_cap"],
            "PERatio": detail["pe_ratio"],
            "EPS": detail["eps"],
            "DividendYield": detail["dividend_yield"],
            "BookValue": detail["book_value"],
            "FiftyTwoWeekHigh": detail["year_high"],
            "FiftyTwoWeekLow": detail["year_low"],
            "_metric_source": "indian-api quoteSummary",
            "_as_of": detail["market_time"],
            "MarketCapKind": detail.get("market_cap_kind") or "REPORTED",
        }
        env = live_envelope(SOURCE, data, delayed=True)
        env["timeliness"] = "END-OF-DAY"
        return env

    @staticmethod
    def _shares_outstanding(payload: dict) -> float | None:
        """Total common shares from the latest balance sheet (crore scale)."""
        for rep in payload.get("financials") or []:
            if not isinstance(rep, dict):
                continue
            bal = (rep.get("stockFinancialMap") or {}).get("BAL") or []
            v = _num(_pick(bal, "Total Common Shares Outstanding"))
            if v is not None:
                return v
        return None

    # -- financial statements ----------------------------------------------
    def get_financial_statements(
        self, symbol: str, statement: str = "income", period: str = "annual"
    ) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        cat = {
            "income": "INC",
            "balance": "BAL",
            "cashflow": "CAS",
        }.get((statement or "income").lower())
        if not cat:
            return {
                "status": "error",
                "source": SOURCE,
                "as_of": None,
                "data": None,
                "message": f"Unknown statement '{statement}'. Use income|balance|cashflow.",
            }
        if not self.key_configured():
            return unavailable(
                SOURCE,
                "Financial statements need the keyed Indian Stock Market "
                "API (no-auth feed offers quote + market fundamentals "
                "only). Set INDIAN_STOCK_MARKET_API_KEY to enable.",
                code="NOT_CONFIGURED",
            )
        want_quarterly = (period or "annual").lower() != "annual"
        # Dedicated /statement endpoint first (annual + quarterly where
        # the API returns them); fall back to the /stock payload.
        stmt = self._statement_api(symbol, statement, period)
        if stmt is not None:
            return stmt
        if want_quarterly:
            # /historical_stats quarter_results is the only quarterly
            # source on this feed — never substitute annual rows.
            quarterly = self._stats_quarterly(symbol, statement)
            if quarterly is not None:
                return quarterly
            return unavailable(
                SOURCE,
                f"No quarterly {statement} rows for '{symbol}' in the feed "
                "(annual data is never substituted for quarterly).",
            )
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
            return err
        assert payload is not None
        rows = []
        for rep in (payload.get("financials") or [])[:MAX_REPORTS]:
            if not isinstance(rep, dict):
                continue
            fmap = rep.get("stockFinancialMap") or {}
            items = fmap.get(cat) or []
            row: dict[str, Any] = {"fiscalDateEnding": rep.get("EndDate")}
            for it in items:
                if not isinstance(it, dict):
                    continue
                key = str(it.get("displayName") or it.get("key") or "").strip()
                if key:
                    row[key] = it.get("value")
            rows.append(row)
        if not rows:
            return unavailable(
                SOURCE, f"No {statement} rows for '{symbol}' in the feed."
            )
        env = live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "statement": statement,
                "period": "annual",
                "currency": "INR",
                "unit": "₹ Crore",
                "reports": rows,
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        env["timeliness_note"] = (
            "Statement figures are provider-reported in ₹ Crore."
        )
        return env

    def _statement_api(
        self, symbol: str, statement: str, period: str
    ) -> dict | None:
        """GET /statement — returns an envelope, or None to fall back."""
        try:
            payload = self._kget(
                "/statement",
                {
                    "stock_name": to_name(symbol),
                    "symbol": symbol,
                    "statement": statement,
                    "period": period,
                },
            )
        except _UpstreamError:
            return None
        rows = _tabular_rows(payload)
        if not rows:
            return None
        env = live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "statement": statement,
                "period": (period or "annual").lower(),
                "currency": "INR",
                "reports": rows[:MAX_REPORTS],
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def _stats_quarterly(self, symbol: str, statement: str) -> dict | None:
        """Quarterly statements via /historical_stats (tolerant parse)."""
        tables = self.get_historical_stats(symbol, "quarter_results")
        data = (tables.get("data") or {}) if tables.get("status") in ("live", "delayed") else {}
        rows = _tabular_rows(data) or _tabular_rows(tables.get("data"))
        if not rows:
            return None
        env = live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "statement": statement,
                "period": "quarterly",
                "currency": "INR",
                "reports": rows[:MAX_REPORTS],
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    # -- earnings ------------------------------------------------------------
    def get_earnings(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if not self.key_configured():
            return unavailable(
                SOURCE,
                "Earnings series are not supplied by the no-auth feed; "
                "set INDIAN_STOCK_MARKET_API_KEY to enable.",
                code="NOT_CONFIGURED",
            )
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
            return err
        assert payload is not None
        annual = []
        for rep in sorted(
            [r for r in (payload.get("financials") or []) if isinstance(r, dict)],
            key=lambda r: str(r.get("FiscalYear") or ""),
            reverse=True,
        )[:8]:
            fmap = rep.get("stockFinancialMap") or {}
            inc = fmap.get("INC") or []
            eps = _num(_pick(inc, "Diluted EPS Excluding Extra Ord Items"))
            if eps is None:
                ni = _num(_pick(inc, "Net Income"))
                sh = _num(_pick(inc, "Diluted Weighted Average Shares"))
                eps = round(ni / sh, 2) if ni is not None and sh else None
            annual.append(
                {
                    "fiscalDateEnding": rep.get("EndDate"),
                    "reportedEPS": eps,
                    "estimatedEPS": None,
                    "surprise": None,
                    "source": SOURCE,
                }
            )
        annual = [
            a
            for a in annual
            if (a.get("reportedEPS") is not None and a.get("reportedEPS") != 0)
            or a.get("fiscalDateEnding")
        ]
        if not annual:
            return unavailable(SOURCE, f"No earnings rows for '{symbol}' in the feed.")
        env = live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "annual": annual,
                "quarterly": [],
                "note": "Reported fiscal-year EPS from provider statements "
                "(Net Income ÷ diluted shares where the feed lacks a direct "
                "per-share line). Quarterly history is not offered by this "
                "feed and is never synthesised.",
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    # -- estimates (ratings + forecasts + targets, all reported) ------------
    def get_estimates(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if not self.key_configured():
            return unavailable(
                SOURCE,
                "Analyst estimates are not supplied by the no-auth feed; "
                "set INDIAN_STOCK_MARKET_API_KEY to enable.",
                code="NOT_CONFIGURED",
            )
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
            return err
        assert payload is not None
        av = payload.get("analystView") or []
        recos = payload.get("recosBar") or {}
        distribution = []
        for row in av:
            if not isinstance(row, dict):
                continue
            analysts = _num(row.get("numberOfAnalystsLatest"))
            if analysts is None:
                continue
            distribution.append(
                {
                    "rating": row.get("ratingName"),
                    "rating_value": row.get("ratingValue"),
                    "analysts": int(analysts),
                }
            )
        stock_analyst = []
        for row in recos.get("stockAnalyst") or []:
            if isinstance(row, dict) and row.get("ratingName"):
                stock_analyst.append(
                    {
                        "rating": row.get("ratingName"),
                        "rating_value": row.get("ratingValue"),
                        "analysts": row.get("numberOfAnalysts"),
                        "band": [row.get("minValue"), row.get("maxValue")],
                    }
                )
        forecasts = self._forecasts(symbol)
        targets = self._targets(symbol)
        ratings = {
            "distribution": distribution,
            "bands": stock_analyst,
            "mean_rating": _num(recos.get("meanValue")),
            "no_of_recommendations": _num(recos.get("noOfRecommendations")),
            "buy_percentage": _num(recos.get("tickerPercentage")),
            "ticker_rating_value": _num(recos.get("tickerRatingValue")),
            "present": bool(recos.get("isDataPresent")),
        }
        if not distribution and not recos and not forecasts and not targets:
            return unavailable(
                SOURCE, f"No analyst coverage data for '{symbol}' in the feed."
            )
        env = live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "annual": [],
                "quarterly": [],
                "analyst_ratings": ratings,
                "forecasts": forecasts,
                "target_price": targets,
                "note": "Reported analyst rating distribution plus "
                "API-supplied forecasts/targets where returned (REPORTED, "
                "never recommendations). EPS/revenue forecasts are NOT "
                "provided by this feed and are never synthesised.",
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def _forecasts(self, symbol: str) -> list[dict]:
        """GET /stock_forecasts — tolerant parse, [] when absent."""
        try:
            payload = self._kget(
                "/stock_forecasts",
                {"stock_name": to_name(symbol), "symbol": symbol},
            )
        except _UpstreamError:
            return []
        return _tabular_rows(payload)

    def _targets(self, symbol: str) -> dict | None:
        """GET /stock_target_price — tolerant parse, None when absent."""
        try:
            payload = self._kget(
                "/stock_target_price",
                {"stock_name": to_name(symbol), "symbol": symbol},
            )
        except _UpstreamError:
            return None
        if isinstance(payload, dict):
            for key in ("target_price", "targetPrice", "target", "data"):
                val = payload.get(key)
                if val is not None:
                    return val if isinstance(val, dict) else {"value": val}
            nums = {k: _num(v) for k, v in payload.items() if _num(v) is not None}
            return nums or None
        return None

    # -- news ----------------------------------------------------------------
    def get_news(
        self, symbol: str | None = None, topic: str | None = None, limit: int = 20
    ) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if not self.key_configured():
            return unavailable(
                SOURCE,
                "News needs the keyed Indian Stock Market API (no-auth "
                "feed offers none; covered by Yahoo RSS). Set "
                "INDIAN_STOCK_MARKET_API_KEY to enable.",
                code="NOT_CONFIGURED",
            )
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
            return err
        assert payload is not None
        limit = max(1, min(int(limit or 20), 50))
        items = []
        for row in (payload.get("recentNews") or [])[: limit * 3]:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or row.get("metadata") or "").strip()
            if url.startswith("/"):
                url = "https://www.livemint.com" + url
            if not url:
                continue
            headline = (row.get("headline") or "").strip()
            if not headline:
                continue
            if (
                topic
                and topic.lower()
                not in (headline + " " + str(row.get("summary") or "")).lower()
            ):
                continue
            items.append(
                {
                    "title": headline,
                    "url": url,
                    "published_at": row.get("date") or row.get("lastPublishedDate"),
                    "source": "LiveMint (via Indian Stock Market API)",
                    "summary": (row.get("summary") or "")[:400],
                    "sentiment": None,
                    "symbol": symbol,
                }
            )
            if len(items) >= limit:
                break
        for row in self._news_api(symbol, topic, limit):
            items.append(row)
            if len(items) >= limit:
                break
        items = _dedupe_news(items)[:limit]
        if not items:
            return unavailable(SOURCE, f"No news items for '{symbol}' in the feed.")
        env = live_envelope(
            SOURCE,
            {
                "items": items,
                "note": "Headlines/links are the feed's; no "
                "sentiment is attached unless the feed reports it.",
            },
            delayed=False,
        )
        return env

    def _news_api(self, symbol: str, topic: str | None, limit: int) -> list[dict]:
        """GET /news — tolerant parse, [] when absent."""
        try:
            payload = self._kget(
                "/news", {"stock_name": to_name(symbol), "symbol": symbol}
            )
        except _UpstreamError:
            return []
        rows = _tabular_rows(payload)
        items = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(
                row.get("url") or row.get("link") or row.get("metadata") or ""
            ).strip()
            title = str(row.get("headline") or row.get("title") or "").strip()
            if not title:
                continue
            if topic and topic.lower() not in (
                title + " " + str(row.get("summary") or "")
            ).lower():
                continue
            items.append(
                {
                    "title": title,
                    "url": url,
                    "published_at": row.get("date")
                    or row.get("published_at")
                    or row.get("publishedAt"),
                    "source": str(
                        row.get("source") or "Indian Stock Market API"
                    ).strip(),
                    "summary": str(row.get("summary") or "")[:400],
                    "sentiment": None,
                    "symbol": symbol,
                }
            )
            if len(items) >= limit:
                break
        return items

    # -- corporate actions -----------------------------------------------------
    def get_actions(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if not self.key_configured():
            return unavailable(
                SOURCE,
                "Corporate actions need the keyed Indian Stock Market "
                "API (no-auth feed offers none; covered by Yahoo chart "
                "events). Set INDIAN_STOCK_MARKET_API_KEY to enable.",
                code="NOT_CONFIGURED",
            )
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
            return err
        assert payload is not None
        ca = payload.get("stockCorporateActionData") or {}
        dividends = []
        for row in ca.get("dividend") or []:
            if not isinstance(row, dict):
                continue
            dividends.append(
                {
                    "date": row.get("xdDate") or row.get("recordDate"),
                    "amount": _num(row.get("value")),
                    "currency": "INR",
                    "source": SOURCE,
                    "remark": row.get("remarks"),
                    "interim_or_final": row.get("interimOrFinal"),
                    "announced": row.get("dateOfAnnouncement"),
                }
            )
        splits = []
        for row in ca.get("splits") or []:
            if not isinstance(row, dict):
                continue
            splits.append(
                {
                    "date": row.get("xsDate") or row.get("recordDate"),
                    "numerator": row.get("oldFaceValue"),
                    "denominator": row.get("newFaceValue"),
                    "source": SOURCE,
                    "remark": row.get("remarks"),
                }
            )
        for row in self._corporate_actions_api(symbol):
            kind = str(row.get("kind") or "").lower()
            if kind.startswith("div"):
                dividends.append({**row, "source": SOURCE})
            elif kind.startswith("spl"):
                splits.append({**row, "source": SOURCE})
        seen: set[str] = set()
        clean_divs = []
        for d in dividends:
            key = f"{d.get('date')}|{d.get('amount')}"
            if key not in seen:
                seen.add(key)
                clean_divs.append(d)
        seen = set()
        clean_splits = []
        for s in splits:
            key = f"{s.get('date')}|{s.get('numerator')}:{s.get('denominator')}"
            if key not in seen:
                seen.add(key)
                clean_splits.append(s)
        extras = {
            "bonus_count": len(ca.get("bonus") or []),
            "rights_count": len(ca.get("rights") or []),
            "agm": [
                {"date": r.get("agmDate"), "purpose": r.get("purpose") or "AGM"}
                for r in (ca.get("annualGeneralMeeting") or [])[:8]
            ],
            "board_meetings": [
                {"date": r.get("boardMeetDate"), "purpose": r.get("purpose")}
                for r in (ca.get("boardMeetings") or [])[:8]
            ],
        }
        if not clean_divs and not clean_splits:
            return unavailable(
                SOURCE,
                "No dividend/split rows for this symbol in the feed "
                "(bonus/rights/AGM counts: "
                f"{extras['bonus_count']}/{extras['rights_count']}).",
            )
        env = live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "dividends": clean_divs[:40],
                "splits": clean_splits[:40],
                "extras": extras,
                "note": "Exchange-reported rows from the feed; every row "
                "carries its source. Nothing inferred from price moves.",
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def _corporate_actions_api(self, symbol: str) -> list[dict]:
        """GET /corporate_actions — tolerant parse, [] when absent."""
        try:
            payload = self._kget(
                "/corporate_actions",
                {"stock_name": to_name(symbol), "symbol": symbol},
            )
        except _UpstreamError:
            return []
        rows = _tabular_rows(payload)
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            action = str(
                row.get("action") or row.get("type") or row.get("kind") or ""
            )
            out.append(
                {
                    "kind": action,
                    "date": row.get("date")
                    or row.get("xdDate")
                    or row.get("recordDate"),
                    "amount": _num(row.get("value") or row.get("amount")),
                    "numerator": row.get("oldFaceValue") or row.get("numerator"),
                    "denominator": row.get("newFaceValue")
                    or row.get("denominator"),
                    "remark": row.get("remarks") or row.get("remark"),
                }
            )
        return out

    # -- ownership --------------------------------------------------------------
    def get_shareholding(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if not self.key_configured():
            return unavailable(
                SOURCE,
                "Ownership splits are not supplied by the no-auth feed; "
                "set INDIAN_STOCK_MARKET_API_KEY to enable.",
                code="NOT_CONFIGURED",
            )
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
            return err
        assert payload is not None
        ownership = []
        for cat in payload.get("shareholding") or []:
            if not isinstance(cat, dict):
                continue

            def latest(entries):
                best = None
                for e in entries or []:
                    if not isinstance(e, dict):
                        continue
                    dt = str(e.get("holdingDate") or "")
                    if dt and (best is None or dt > best[0]):
                        best = (dt, e)
                return best

            hit = latest(cat.get("categories"))
            rows = []
            if hit is not None:
                rows.append(
                    {
                        "holding_date": hit[0],
                        "percentage": _num(hit[1].get("percentage")),
                    }
                )
            ownership.append(
                {
                    "category": cat.get("displayName") or cat.get("categoryName"),
                    "holding_date": rows[0]["holding_date"] if rows else None,
                    "percentage": rows[0]["percentage"] if rows else None,
                }
            )
        ownership = [o for o in ownership if o.get("percentage") is not None]
        if not ownership:
            return unavailable(
                SOURCE,
                "No ownership split for this symbol in the feed "
                "(ownership splits are never guessed).",
            )
        env = live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "ownership": ownership,
                "note": "Ownership split is provider-reported (latest filing "
                "date per category); not inferred.",
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    # -- historical datasets (keyed) -------------------------------------------
    def get_indian_history(
        self, symbol: str, period: str = "1yr", filt: str = "price"
    ) -> dict:
        """GET /historical_data -> normalized {bars} (keyed only)."""
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if not self.key_configured():
            return unavailable(
                SOURCE,
                "Historical datasets need the keyed Indian Stock Market "
                "API; set INDIAN_STOCK_MARKET_API_KEY to enable.",
                code="NOT_CONFIGURED",
            )
        period = (period or "1yr").lower()
        if period not in _HIST_PERIODS:
            return {
                "status": "error",
                "source": SOURCE,
                "as_of": None,
                "data": None,
                "message": f"Unknown period '{period}'. Use "
                + "/".join(_HIST_PERIODS)
                + ".",
            }
        try:
            payload = self._kget(
                "/historical_data",
                {
                    "stock_name": to_name(symbol),
                    "symbol": symbol,
                    "period": period,
                    "filter": filt or "price",
                },
            )
        except _UpstreamError as exc:
            return exc.env
        bars = _history_bars(payload)
        if not bars:
            return unavailable(
                SOURCE, f"No historical rows for '{symbol}' in the feed."
            )
        env = live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "period": period,
                "filter": filt or "price",
                "currency": "INR",
                "bars": bars,
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    def get_historical_stats(self, symbol: str, stat: str = "ratios") -> dict:
        """GET /historical_stats -> {tables} (keyed only)."""
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        if not self.key_configured():
            return unavailable(
                SOURCE,
                "Historical statistics need the keyed Indian Stock "
                "Market API; set INDIAN_STOCK_MARKET_API_KEY to enable.",
                code="NOT_CONFIGURED",
            )
        stat = (stat or "ratios").lower()
        if stat not in _HIST_STATS:
            return {
                "status": "error",
                "source": SOURCE,
                "as_of": None,
                "data": None,
                "message": f"Unknown statistic '{stat}'. Use "
                + "/".join(_HIST_STATS)
                + ".",
            }
        try:
            payload = self._kget(
                "/historical_stats",
                {"stock_name": to_name(symbol), "symbol": symbol, "type": stat},
            )
        except _UpstreamError as exc:
            return exc.env
        if isinstance(payload, dict) and (payload.get("err") or payload.get("error")):
            return unavailable(
                SOURCE,
                str(payload.get("err") or payload.get("error")) + f" (for '{symbol}').",
            )
        env = live_envelope(
            SOURCE,
            {"symbol": symbol, "stat": stat, "tables": payload},
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    # -- pass-through -----------------------------------------------------------
    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        return unavailable(
            SOURCE, "No history endpoint on this feed; use Yahoo/Stooq legs."
        )

    def search(self, query: str, limit: int = 10) -> dict:
        return unavailable(
            SOURCE, "No search endpoint on this feed; use Yahoo/Alpha Vantage."
        )


def _tabular_rows(payload: Any) -> list[dict]:
    """Best-effort list-of-dicts extraction from unknown JSON shapes."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "reports",
        "rows",
        "data",
        "results",
        "items",
        "statements",
        "forecasts",
        "table",
    ):
        val = payload.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return val
        if isinstance(val, dict):
            inner = _tabular_rows(val)
            if inner:
                return inner
    # A bare record dict with scalar fields is one row.
    if payload and all(not isinstance(v, (dict, list)) for v in payload.values()):
        return [payload]
    return []


def _history_bars(payload: Any) -> list[dict]:
    """Normalize historical datasets to {t,o,h,l,c,v} bars (epoch secs)."""
    rows = _tabular_rows(payload)
    bars = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        t = (
            row.get("t")
            or row.get("timestamp")
            or row.get("date")
            or row.get("period")
        )
        epoch: float | None = None
        if isinstance(t, (int, float)):
            epoch = float(t) if t > 1e11 else float(t)
            if epoch < 1e11:
                epoch = epoch  # already seconds
            else:
                epoch = epoch / 1000.0
        elif isinstance(t, str) and t:
            for fmt in ("%Y-%m-%d", "%d %b %Y", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y"):
                try:
                    epoch = datetime.strptime(t[:10], fmt).replace(
                        tzinfo=timezone.utc
                    ).timestamp()
                    break
                except (ValueError, TypeError):
                    continue
        c = _num(
            row.get("c")
            or row.get("close")
            or row.get("price")
            or row.get("value")
        )
        if epoch is None or c is None:
            continue
        bars.append(
            {
                "t": int(epoch),
                "o": _num(row.get("o") or row.get("open")) or c,
                "h": _num(row.get("h") or row.get("high")) or c,
                "l": _num(row.get("l") or row.get("low")) or c,
                "c": c,
                "v": _num(row.get("v") or row.get("volume")),
            }
        )
    bars.sort(key=lambda b: int(b["t"] or 0))
    return bars
