"""Indian Stock Market API (stock.indianapi.in) — keyed NSE/BSE leg.

Requires INDIAN_STOCK_MARKET_API_KEY (sent as the X-API-Key header;
the key never appears in URLs, logs or client payloads).

Endpoints (verified live, Sep 2026):
  GET /stock?name=TATASTEEL          one response carrying a delayed
       NSE/BSE snapshot plus company profile, ~19 fiscal-year financial
       statements (INR), real analyst recommendation distribution,
       ownership breakdown, dividends/splits/bonus/AGM/board events and
       recent news.
  Auth failures: 401 -> invalid/expired key (error envelope).
  Coverage: HTTP 200 with "err": "Stock not found" -> honest
       "unavailable" (e.g. non-Indian names). Never treated as data.

Only .NS/.BO symbols are attempted; everything else passes through.
Timeliness: the feed is a delayed NSE/BSE snapshot — always DELAYED,
never upgraded to real-time.

Rate protection: a self-imposed conservative budget guard (30/min,
2000/day) since the provider's published plan quota is unknown.
Aggressive caches make the upstream call rare in practice.
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
SOURCE = "indian-api"
SOURCE_LABEL = "Indian Stock Market API (stock.indianapi.in)"

DEFAULT_BASE = "https://stock.indianapi.in"
QUOTE_MAX_AGE = 300.0  # quote freshness: refetch after 5 min
DOMAIN_MAX_AGE = 24 * 3600.0  # profile/fundamentals/news/actions
MAX_REPORTS = 12

PER_MINUTE = 30
PER_DAY = 2000

_budget_lock = threading.Lock()
_minute_window_start = 0.0
_minute_used = 0
_day_key = ""
_day_used = 0


def _api_key() -> str:
    return (os.environ.get("INDIAN_STOCK_MARKET_API_KEY") or "").strip()


def base_url() -> str:
    return (
        os.environ.get("INDIAN_API_BASE_URL") or DEFAULT_BASE
    ).rstrip("/")


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
    """Strip a Yahoo-style suffix to the feed's bare-name lookup.

    TATASTEEL.NS / TATASTEEL.BO -> TATASTEEL; the response carries both
    exchanges and we pick the requested one (prefer NSE).
    """
    s = (symbol or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def _num(v: Any) -> float | None:
    if v in (None, "", "-", "None", "N/A", "NA", "null"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick(rows: list[Any], key: str) -> Any:
    """Find a metric row by key within a keyMetrics-style list.

    The feed stores display names with a trailing whitespace and a
    space-less camelCase key; match either form."""
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        k = str(r.get("key") or "")
        dn = str(r.get("displayName") or "")
        if k == key or dn.strip() == key:
            return r.get("value")
    return None


class _UpstreamError(Exception):
    """Raised by the transport with a ready-to-return envelope."""

    def __init__(self, env: dict):
        super().__init__(str(env.get("message") or "upstream error"))
        self.env = env


class IndianApiProvider(MarketDataProvider):
    name = "indian-api"
    capabilities: dict[str, bool] = {
        "quote": True,
        "fundamentals": True,
        "statements": True,
        "earnings": True,
        "estimates": True,
        "news": True,
        "actions": True,
        "holdings": True,
        "search": False,
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}  # name -> {"at", "payload"}

    def budget_snapshot(self) -> dict:
        return budget_snapshot()

    # -- transport / cache ------------------------------------------------
    def _guard(self, symbol: str) -> dict | None:
        if not is_indian(symbol):
            return unavailable(
                SOURCE,
                f"Symbol '{symbol}' is not an NSE/BSE symbol; "
                "the Indian leg passes it through.",
            )
        if not _api_key():
            return unavailable(
                SOURCE,
                "API KEY NOT CONFIGURED. Set INDIAN_STOCK_MARKET_API_KEY "
                "to enable this leg.",
                code="NOT_CONFIGURED",
            )
        return None

    def _fetch(self, name: str) -> dict:
        """GET /stock?name=... -> parsed payload (dict). Raises
        _UpstreamError with the envelope to surface on failure."""
        if not _api_key():
            raise _UpstreamError(
                unavailable(
                    SOURCE, "API KEY NOT CONFIGURED. Set "
                    "INDIAN_STOCK_MARKET_API_KEY to enable this leg.",
                    code="NOT_CONFIGURED",
                )
            )
        blocked = _budget_take(1)
        if blocked:
            raise _UpstreamError(unavailable(SOURCE, f"Rate budget exhausted: {blocked}."))
        url = base_url() + "/stock?" + urllib.parse.urlencode({"name": name})
        req = urllib.request.Request(url, headers={**UA, "X-API-Key": _api_key()})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
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
            raise _UpstreamError(
                {
                    "status": "error",
                    "source": SOURCE,
                    "as_of": None,
                    "data": None,
                    "message": f"Indian Stock Market API HTTP {exc.code}: {exc}",
                }
            )
        except Exception as exc:
            raise _UpstreamError(
                {
                    "status": "error",
                    "source": SOURCE,
                    "as_of": None,
                    "data": None,
                    "message": f"Indian Stock Market API request failed: {exc}",
                }
            )
        if not isinstance(payload, dict):
            raise _UpstreamError(
                unavailable(SOURCE, f"Unexpected response for '{name}'.")
            )
        if payload.get("err") or payload.get("error"):
            raise _UpstreamError(
                unavailable(
                    SOURCE,
                    str(payload.get("err") or payload.get("error"))
                    + f" (for '{name}').",
                )
            )
        return payload

    def _stock(self, symbol: str, max_age: float) -> tuple[dict | None, dict | None]:
        """Load the fused /stock payload under a freshness window.

        Returns (payload, None) or (None, envelope_to_return)."""
        name = to_name(symbol)
        now = time.time()
        with self._lock:
            hit = self._cache.get(name)
            if hit is not None and now - hit.get("at", 0.0) < max_age:
                return hit.get("payload"), None
            payload, env = None, None
            try:
                payload = self._fetch(name)
            except _UpstreamError as exc:
                env = exc.env
            except Exception as exc:
                env = error_envelope(
                    SOURCE, f"Indian Stock Market API request failed: {exc}"
                )
            if payload is not None:
                self._cache[name] = {"at": now, "payload": payload}
            return payload, env

    # -- quote -------------------------------------------------------------
    def get_quote(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        payload, err = self._stock(symbol, QUOTE_MAX_AGE)
        if err:
            return err
        assert payload is not None
        cp = payload.get("currentPrice") or {}
        sd = payload.get("stockDetailsReusableData") or {}
        requested_bo = (symbol or "").endswith(".BO")
        nse_px = _num(cp.get("NSE"))
        bse_px = _num(cp.get("BSE"))
        if requested_bo and bse_px is not None:
            price, exchange = bse_px, "BSE"
        elif nse_px is not None:
            price, exchange = nse_px, "NSE"
        elif bse_px is not None:
            price, exchange = bse_px, "BSE"
        else:
            return unavailable(SOURCE, f"No price for '{symbol}' in the feed.")
        pct = _num(sd.get("percentChange"))
        vm = lambda p: p
        change = vm(price) - vm(price) / (1.0 + (vm(pct) / 100.0)) if pct is not None and pct != -100.0 else None
        change = round(change, 2) if change is not None else None
        previous_close = round(price - change, 2) if change is not None else None
        quote = {
            "symbol": symbol,
            "name": payload.get("companyName"),
            "exchange": exchange,
            "currency": "INR",
            "instrument_type": payload.get("instrumentType", "Equity"),
            "price": price,
            "previous_close": previous_close,
            "open": None,
            "day_high": _num(sd.get("high")),
            "day_low": _num(sd.get("low")),
            "volume": None,
            "change": change,
            "change_pct": pct,
            "fifty_two_week_high": _num(sd.get("yhigh")) or _num(payload.get("yearHigh")),
            "fifty_two_week_low": _num(sd.get("ylow")) or _num(payload.get("yearLow")),
            "market_time": _asof_epoch(sd.get("date"), sd.get("time")),
            "timezone": "Asia/Kolkata",
            "market_cap": _num(sd.get("marketCap")),
            "pe": _num(sd.get("pPerEBasicExcludingExtraordinaryItemsTTM")),
            "dividend_yield": _num(sd.get("currentDividendYieldCommonStockPrimaryIssueLTM")),
            "sector": payload.get("industry"),
        }
        env = live_envelope(SOURCE, quote, delayed=True)
        env["timeliness"] = "DELAYED"
        env["timeliness_note"] = (
            SOURCE_LABEL + " delayed NSE/BSE snapshot; never presented "
            "as exchange-certified real-time."
        )
        return env

    # -- company identity (used by the orchestrator profile merge) ----------
    def get_company_profile(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
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
                    "title": title.get("description") if isinstance(title, dict) else title,
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

    # -- financial statements ------------------------------------------------
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
        if (period or "annual").lower() != "annual":
            return unavailable(
                SOURCE,
                "This feed provides fiscal-year statements only; "
                "quarterly statements are not available (never synthesised).",
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
            return unavailable(SOURCE, f"No {statement} rows for '{symbol}' in the feed.")
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
            "Statement figures are provider-reported in ₹ Crore; "
            "quarterly not offered by this feed."
        )
        return env

    # -- fundamentals: flat AV-style overview shape ---------------------------
    def get_ratios(self, symbol: str) -> dict:
        """Overview-flat dict (Alpha Vantage key shape) so every existing
        UI tab works unchanged. All values are provider-reported.
        keyMetrics carries real per-share, ratio and strength figures."""
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
            return err
        assert payload is not None
        km = payload.get("keyMetrics") or {}
        sd = payload.get("stockDetailsReusableData") or {}
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
            "DebtToEquity": m("financialstrength", "totalDebtPerTotalEquityMostRecentFiscalYear"),
            "CurrentRatio": m("financialstrength", "currentRatioMostRecentFiscalYear"),
            "PayoutRatio": m("financialstrength", "payoutRatioTrailing12Month"),
            "DividendYield": m("valuation", "currentDividendYieldCommonStockPrimaryIssueLTM"),
            "DividendPerShare": m("persharedata", "dividendPerShareMostRecentFiscalYear"),
            "Beta": m("priceandVolume", "beta"),
            "52WeekHigh": m("priceandVolume", "52WeekHigh") or _num(payload.get("yearHigh")),
            "52WeekLow": m("priceandVolume", "52WeekLow") or _num(payload.get("yearLow")),
            "SharesOutstanding": _shares_outstanding(payload),
            "_period": fy_period(),
            "_metric_source": "indian-api keyMetrics",
            "MarketCapUnit": "₹ Crore",
            "SharesUnit": "Crore shares",
        }
        env = live_envelope(SOURCE, data, delayed=True)
        env["timeliness"] = "END-OF-DAY"
        env["timeliness_note"] = (
            SOURCE_LABEL + " reported figures; market cap and EPS are "
            "provider values (₹ Crore market cap), not recomputed here."
        )
        return env

    # -- earnings ------------------------------------------------------------
    def get_earnings(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
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
        annual = [a for a in annual if (a.get("reportedEPS") is not None and a.get("reportedEPS") != 0) or a.get("fiscalDateEnding")]
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

    # -- estimates (real analyst recommendation distribution) ----------------
    def get_estimates(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
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
        if not distribution and not recos:
            return unavailable(
                SOURCE, f"No analyst coverage data for '{symbol}' in the feed."
            )
        stock_analyst = []
        for row in (recos.get("stockAnalyst") or []):
            if isinstance(row, dict) and row.get("ratingName"):
                stock_analyst.append(
                    {
                        "rating": row.get("ratingName"),
                        "rating_value": row.get("ratingValue"),
                        "analysts": row.get("numberOfAnalysts"),
                        "band": [row.get("minValue"), row.get("maxValue")],
                    }
                )
        ratings = {
            "distribution": distribution,
            "bands": stock_analyst,
            "mean_rating": _num(recos.get("meanValue")),
            "no_of_recommendations": _num(recos.get("noOfRecommendations")),
            "buy_percentage": _num(recos.get("tickerPercentage")),
            "ticker_rating_value": _num(recos.get("tickerRatingValue")),
            "present": bool(recos.get("isDataPresent")),
        }
        env = live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "annual": [],
                "quarterly": [],
                "analyst_ratings": ratings,
                "note": "Reported analyst rating distribution (REPORTED). "
                "EPS/revenue forecasts are NOT provided by this feed and are "
                "never synthesised in-terminal.",
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    # -- news ----------------------------------------------------------------
    def get_news(
        self,
        symbol: str | None = None,
        topic: str | None = None,
        limit: int = 20,
    ) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
            return err
        assert payload is not None
        limit = max(1, min(int(limit or 20), 50))
        items = []
        for row in (payload.get("recentNews") or [])[:limit * 3]:
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
            if topic and topic.lower() not in (headline + " " + str(row.get("summary") or "")).lower():
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
        if not items:
            return unavailable(SOURCE, f"No news items for '{symbol}' in the feed.")
        env = live_envelope(
            SOURCE,
            {"items": items, "note": "Headlines/links are the feed's; no "
             "sentiment is attached unless the feed reports it."},
            delayed=False,
        )
        return env

    # -- corporate actions -----------------------------------------------------
    def get_actions(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
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
        if not dividends and not splits:
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
                "dividends": dividends[:40],
                "splits": splits[:40],
                "extras": extras,
                "note": "Exchange-reported rows from the feed; every row "
                "carries its source. Nothing inferred from price moves.",
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        return env

    # -- ownership --------------------------------------------------------------
    def get_shareholding(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        blocked = self._guard(symbol)
        if blocked:
            return blocked
        payload, err = self._stock(symbol, DOMAIN_MAX_AGE)
        if err:
            return err
        assert payload is not None
        ownership = []
        for cat in (payload.get("shareholding") or []):
            if not isinstance(cat, dict):
                continue
            rows = []

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
            if hit is not None:
                rows.append({"holding_date": hit[0], "percentage": _num(hit[1].get("percentage"))})
            else:
                rows = []
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
            {"symbol": symbol, "ownership": ownership,
             "note": "Ownership split is provider-reported (latest filing "
                     "date per category); not inferred."},
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


def _shares_outstanding(payload: dict) -> float | None:
    """Total common shares from the latest balance sheet (₹ Cr scale —
    the feed reports them in crore shares)."""
    for rep in (payload.get("financials") or []):
        if not isinstance(rep, dict):
            continue
        bal = (rep.get("stockFinancialMap") or {}).get("BAL") or []
        v = _num(_pick(bal, "Total Common Shares Outstanding"))
        if v is not None:
            return v
    return None


def _asof_epoch(date: Any, time_: Any) -> int | None:
    """'16 Sep 2026' + '10:28:24' (IST) -> epoch seconds for the UI clock."""
    if not date or not time_:
        return None
    try:
        dt = datetime.strptime(str(date).strip() + " " + str(time_).strip(), "%d %b %Y %H:%M:%S")
        try:
            from zoneinfo import ZoneInfo

            dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        except Exception:
            from datetime import timedelta

            dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None