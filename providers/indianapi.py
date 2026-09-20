"""Indian Stock Market API — free no-auth NSE/BSE leg.

Integrates the behavior of the MIT-licensed ``Indian-Stock-Market-API``
(v3.0, no authentication or API key required): its ``GET
/stock?symbol={SYMBOL}&res=num`` contract is served here by reading
Yahoo Finance's public ``quoteSummary`` modules
(``price,summaryDetail,defaultKeyStatistics,assetProfile``) through the
same cookie/crumb handshake the upstream project uses, then normalizing
to the same field schema:

  company_name, last_price, change, percent_change, previous_close,
  open, day_high, day_low, year_high, year_low, volume, market_cap,
  pe_ratio, dividend_yield, book_value, earnings_per_share, sector,
  industry, currency

Only .NS/.BO symbols are attempted; everything else passes through.
Timeliness: delayed NSE/BSE snapshot — always DELAYED, never upgraded
to real-time.

Explicitly NOT provided (the upstream project documents none of
these): financial statements, quarterly statements, analyst
estimates, earnings series, ownership/holdings, news, IPO/macro. Those
domains stay on their legitimate providers (Alpha Vantage / Twelve
Data) or honest unavailable states — never synthesised here.

Yahoo crumb/cookie material never leaves the server: it travels only
in outbound HTTPS headers, never in logs, envelopes or client
payloads.
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

from .base import (
    MarketDataProvider,
    error_envelope,
    live_envelope,
    unavailable,
)
from .indian import is_indian

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}
# Yahoo only issues session cookies (A1/A3/A1S) to browser-like
# requests; a bare UA gets none and the crumb handshake then fails.
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
SOURCE_LABEL = "Indian Stock Market API (free, no-auth)"

QS_MODULES = "price,summaryDetail,defaultKeyStatistics,assetProfile"
CRUMB_TTL = 50 * 60.0  # upstream rotates crumbs roughly hourly
QUOTE_MAX_AGE = 300.0  # quote freshness: refetch after 5 min
DOMAIN_MAX_AGE = 24 * 3600.0  # profile/fundamentals reuse window

_crumb_lock = threading.Lock()
_crumb_cache: dict[str, Any] = {"crumb": None, "cookie": None, "expires_at": 0.0}


def _http_text(
    url: str, headers: dict | None = None, cookie: str = "", timeout: float = 15.0
) -> tuple[str, str]:
    """GET url -> (body, set-cookie). Raises on HTTP/network failure."""
    head = dict(BROWSER_HEADERS if headers is None else headers)
    if cookie:
        head["Cookie"] = cookie
    req = urllib.request.Request(url, headers=head)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_cookie = resp.headers.get("Set-Cookie") or ""
        return resp.read().decode("utf-8", "replace"), raw_cookie


def _cookies_from(headers_list: list[tuple[str, str]]) -> str:
    """Combine every Set-Cookie pair (A1/A3/A1S) into one Cookie header."""
    pairs = []
    for _, value in headers_list:
        first = (value or "").split(";")[0].strip()
        if first and "=" in first:
            pairs.append(first)
    # de-duplicate by name, keep last
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
        # Prime session cookies from a Yahoo page (quote page first,
        # chart endpoint as fallback) — both set A1/A3/A1S when the
        # request looks like a browser.
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
                    cookie = _cookies_from([("Set-Cookie", v) for v in pairs])
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


def _raw(field: Any) -> Any:
    """Upstream `raw()` helper: {raw: v} objects unwrap to v."""
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


def _qsymbol(symbol: str) -> str:
    """Bare names default to NSE (.NS), mirroring upstream routing."""
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


class _UpstreamError(Exception):
    """Raised by the transport with a ready-to-return envelope."""

    def __init__(self, env: dict):
        super().__init__(str(env.get("message") or "upstream error"))
        self.env = env


class IndianApiProvider(MarketDataProvider):
    """Free no-auth Indian leg (quote + market fundamentals, NSE/BSE)."""

    name = "indian-api"
    capabilities: dict[str, bool] = {
        "quote": True,
        "fundamentals": True,
        "statements": False,
        "earnings": False,
        "estimates": False,
        "news": False,
        "actions": False,
        "holdings": False,
        "search": False,
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}  # ticker -> {"at", "detail"}

    def budget_snapshot(self) -> dict:
        return {"auth": "none", "key_required": False, "note": "No-auth leg."}

    # -- transport ------------------------------------------------------
    def _quote_summary(self, ticker: str) -> dict:
        """Fetch quoteSummary result[0] for a ticker (crumb handshake)."""
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
                # Session expired mid-flight: refresh once and retry.
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
        """Normalized upstream detail (mirrors /stock res=num schema)."""
        ticker = _qsymbol(symbol)
        now = time.time()
        with self._lock:
            hit = self._cache.get(ticker)
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
        shares = _num(_raw(stats.get("sharesOutstanding")))
        last_px = _num(_raw(price.get("regularMarketPrice")))
        if mcap is None and last_px is not None and shares:
            # Upstream omits marketCap intermittently; price × reported
            # shares outstanding is definitional — labeled CALCULATED.
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
        # open falls back to summaryDetail when the price block lacks it
        if detail["open"] is None:
            detail["open"] = _num(_raw(summary.get("open")))
        with self._lock:
            self._cache[ticker] = {"at": now, "detail": detail}
        return detail

    def _guard(self, symbol: str) -> dict | None:
        if not is_indian(symbol):
            return unavailable(
                SOURCE,
                f"Symbol '{symbol}' is not an NSE/BSE symbol; "
                "the Indian leg passes it through.",
            )
        return None

    def _load(self, symbol: str) -> tuple[dict | None, dict | None]:
        """Returns (detail, None) or (None, envelope_to_return)."""
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
        detail, err = self._load(symbol)
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
            SOURCE_LABEL + " delayed NSE/BSE snapshot (no-auth feed); "
            "never presented as exchange-certified real-time."
        )
        return env

    # -- company identity (used by the orchestrator profile merge) ----------
    def get_company_profile(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        detail, err = self._load(symbol)
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
                    "Indian Stock Market API (quoteSummary-backed). "
                    "Descriptions are not supplied by this feed."
                ),
            },
            delayed=True,
        )

    # -- market fundamentals: flat AV-style overview shape ------------------
    def get_ratios(self, symbol: str) -> dict:
        """Reported market fundamentals only — no statements, no ROE.

        The upstream feed documents no return-on-equity field, so ROE is
        never present here (and must stay unavailable downstream unless
        another legitimate provider supplies it).
        """
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        detail, err = self._load(symbol)
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
            "MarketCapKind": detail.get("market_cap_kind") or "REPORTED",
            "PERatio": detail["pe_ratio"],
            "EPS": detail["eps"],
            "DividendYield": detail["dividend_yield"],
            "BookValue": detail["book_value"],
            "FiftyTwoWeekHigh": detail["year_high"],
            "FiftyTwoWeekLow": detail["year_low"],
            "_metric_source": "indian-api quoteSummary",
            "_as_of": detail["market_time"],
        }
        env = live_envelope(SOURCE, data, delayed=True)
        env["timeliness"] = "END-OF-DAY"
        return env

    # -- unsupported domains: honest unavailable, never synthesised ---------
    def get_financial_statements(
        self, symbol: str, statement: str = "income", period: str = "annual"
    ) -> dict:
        return unavailable(
            SOURCE,
            "Financial statements are not supplied by the Indian Stock "
            "Market API (its documentation offers quote + market "
            "fundamentals only).",
        )

    def get_earnings(self, symbol: str) -> dict:
        return unavailable(
            SOURCE,
            "Earnings series are not supplied by the Indian Stock Market API.",
        )

    def get_estimates(self, symbol: str) -> dict:
        return unavailable(
            SOURCE,
            "Analyst estimates are not supplied by the Indian Stock "
            "Market API.",
        )

    def get_news(
        self, symbol: str | None = None, topic: str | None = None, limit: int = 20
    ) -> dict:
        return unavailable(
            SOURCE, "News is not supplied by the Indian Stock Market API."
        )

    def get_actions(self, symbol: str) -> dict:
        return unavailable(
            SOURCE,
            "Corporate actions are not supplied by the Indian Stock "
            "Market API (covered by Yahoo chart events).",
        )

    def get_shareholding(self, symbol: str) -> dict:
        return unavailable(
            SOURCE,
            "Ownership splits are not supplied by the Indian Stock "
            "Market API.",
        )

    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        return unavailable(
            SOURCE, "History is not supplied by this leg; use Yahoo/Stooq."
        )

    def search(self, query: str, limit: int = 10) -> dict:
        return unavailable(
            SOURCE, "Search is not supplied by this leg; use Yahoo/AV."
        )
