"""Yahoo Finance fundamentals leg — free, no API key.

Two public endpoints (same standing as the quote/chart legs already
used; documented by gadicc/yahoo-finance2, MIT):
- ws/fundamentals-timeseries (no crumb): annual/quarterly income,
  balance-sheet and cash-flow line items. Replaces the deprecated
  quoteSummary *History modules (empty since Nov 2024).
- v10/finance/quoteSummary (crumb): trailing ratios, earnings chart,
  company profile (sector/industry/description).

Shapes mirror AlphaVantageFundamentalsProvider outputs so the
orchestrator can treat this leg as a drop-in free first resort.
Values are reported raw floats; AV-style key names are used for
statement rows. DividendYield is converted to AV percent convention.
Nothing is synthesised; gaps stay missing.
"""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base import error_envelope, live_envelope, unavailable
from .yahoo import RateLimitedError, rate_limited

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}
SOURCE = "yahoo-fundamentals"

_TS_BASE = "https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/"
_QS_BASE = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"

_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 6 * 3600.0

_crumb: tuple[str, http.cookiejar.CookieJar] | None = None
_crumb_at: float = 0.0
_crumb_fail_at: float = 0.0


def _get_crumb() -> tuple[str, http.cookiejar.CookieJar] | None:
    """Yahoo crumb + cookies, refreshed hourly. None if unreachable.

    Negative results are cached 10 minutes so a consent-walled or
    crumb-less network never slows every fundamentals call. Timeseries
    statements do not need a crumb and are unaffected.
    """
    global _crumb, _crumb_at, _crumb_fail_at
    if _crumb is not None and time.time() - _crumb_at < 3600:
        return _crumb
    if time.time() - _crumb_fail_at < 600:
        return None
    try:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        seed = opener.open(
            urllib.request.Request("https://query1.finance.yahoo.com/", headers=UA),
            timeout=15,
        )
        seed.read()
        resp = opener.open(
            urllib.request.Request(_CRUMB_URL, headers=UA), timeout=15
        )
        crumb = resp.read().decode("utf-8", "replace").strip()
        if not crumb or "{" in crumb:
            _crumb_fail_at = time.time()
            return None
        _crumb = (crumb, jar)
        _crumb_at = time.time()
        return _crumb
    except Exception:
        _crumb_fail_at = time.time()
        return None


def _http_json(url: str, jar: http.cookiejar.CookieJar | None = None,
               timeout: float = 20.0) -> Any:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            if jar is not None:
                opener = urllib.request.build_opener(
                    urllib.request.HTTPCookieProcessor(jar)
                )
                with opener.open(
                    urllib.request.Request(url, headers=UA), timeout=timeout
                ) as resp:
                    return json.loads(resp.read().decode("utf-8", "replace"))
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            if exc.code == 429:
                raise RateLimitedError(f"HTTP 429 from Yahoo for {url}")
            if exc.code in (401, 403):
                raise PermissionError(f"HTTP {exc.code} from Yahoo for {url}")
            raise
    assert last_exc is not None
    raise last_exc


def _cache_get(key: str):
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < CACHE_TTL:
        return hit[1]
    return None


def _cache_set(key: str, value: dict) -> None:
    _cache[key] = (time.time(), value)


def _raw(node: Any) -> float | None:
    if isinstance(node, dict):
        node = node.get("raw", node.get("value"))
    if node in (None, "", "-", "None", "N/A"):
        return None
    try:
        return float(node)
    except (TypeError, ValueError):
        return None


# timeseries key -> AV-style report key, per statement family.
_TS_MAP: dict[str, dict[str, str]] = {
    "income": {
        "totalRevenue": "totalRevenue",
        "costOfRevenue": "costOfRevenue",
        "grossProfit": "grossProfit",
        "operatingExpense": "operatingExpenses",
        "researchAndDevelopment": "researchAndDevelopment",
        "sellingGeneralAndAdministration": "sellingGeneralAndAdministrative",
        "ebitda": "ebitda",
        "ebit": "ebit",
        "operatingIncome": "operatingIncome",
        "interestExpense": "interestExpense",
        "incomeBeforeTax": "incomeBeforeTax",
        "incomeTaxExpense": "incomeTaxExpense",
        "netIncome": "netIncome",
        "dilutedEPS": "dilutedEPS",
        "dilutedNIAvailToComStockholders": "dilutedEPS",
        "basicEPS": "basicEPS",
    },
    "balance": {
        "totalAssets": "totalAssets",
        "totalCurrentAssets": "totalCurrentAssets",
        "cashAndCashEquivalents": "cashAndCashEquivalentsAtCarryingValue",
        "inventory": "inventory",
        "netReceivables": "currentNetReceivables",
        "totalCurrentLiabilities": "totalCurrentLiabilities",
        "accountsPayable": "accountspayable",
        "totalLiab": "totalLiabilities",
        "totalLiabilitiesNetMinorityInterest": "totalLiabilities",
        "totalDebt": "totalDebt",
        "longTermDebt": "longTermDebt",
        "shortTermDebt": "shortTermDebt",
        "totalStockholderEquity": "totalShareholderEquity",
        "retainedEarnings": "retainedEarnings",
        "commonStockSharesOutstanding": "commonStockSharesOutstanding",
    },
    "cashflow": {
        "operatingCashflow": "operatingCashflow",
        "capitalExpenditure": "capitalExpenditures",
        "freeCashFlow": "freeCashFlow",
        "dividendsPaid": "dividendPayout",
        "netIncome": "netIncome",
    },
}

_TS_MODULE = {"income": "financials", "balance": "balance-sheet", "cashflow": "cash-flow"}


def _ts_types(prefix: str, keys: list[str]) -> str:
    return ",".join(f"{prefix}{k[0].upper()}{k[1:]}" for k in keys)


class YahooFundamentalsProvider:
    """Free fundamentals: statements, ratios, earnings, profile."""

    name = "yahoo-fundamentals"
    capabilities: dict[str, bool] = {
        "statements": True,
        "valuation": True,
        "profile": True,
        "earnings": True,
    }

    # -- statements -------------------------------------------------
    def get_financial_statements(
        self, symbol: str, statement: str = "income", period: str = "annual"
    ) -> dict:
        symbol = (symbol or "").strip().upper()
        statement = (statement or "income").lower()
        period = (period or "annual").lower()
        if statement not in _TS_MAP:
            return error_envelope(
                SOURCE, f"Unknown statement '{statement}'. Use income|balance|cashflow."
            )
        if period not in ("annual", "quarterly"):
            return error_envelope(SOURCE, f"Unknown period '{period}'.")
        cached = _cache_get(f"st:{symbol}:{statement}:{period}")
        if cached is not None:
            return cached
        prefix = "annual" if period == "annual" else "quarterly"
        keys = list(_TS_MAP[statement])
        now = int(time.time())
        url = (
            _TS_BASE
            + urllib.parse.quote(symbol)
            + "?type="
            + urllib.parse.quote(_ts_types(prefix, keys))
            + f"&period1={now - 6 * 365 * 24 * 3600}&period2={now}"
        )
        try:
            payload = _http_json(url)
        except RateLimitedError as exc:
            return rate_limited(SOURCE, f"Statements throttled for {symbol}: {exc}")
        except PermissionError as exc:
            return error_envelope(SOURCE, f"Request refused for {symbol}: {exc}")
        except Exception as exc:
            return error_envelope(SOURCE, f"Statements request failed for {symbol}: {exc}")
        try:
            results = ((payload.get("timeseries") or {}).get("result")) or []
            by_date: dict[str, dict] = {}
            amap = _TS_MAP[statement]
            for entry in results:
                stamps = entry.get("timestamp") or []
                data_keys = [k for k in entry.keys() if k not in ("meta", "timestamp")]
                if not data_keys:
                    continue
                data_key = data_keys[0]
                short = data_key[len(prefix):]
                short = short[0].lower() + short[1:] if short else short
                av_key = amap.get(short)
                if not av_key:
                    continue
                for i, ts in enumerate(stamps):
                    try:
                        point = (entry.get(data_key) or [])[i] or {}
                    except IndexError:
                        continue
                    asof = str(point.get("asOfDate") or "")[:10]
                    if not asof:
                        continue
                    val = _raw((point.get("reportedValue") or {}).get("raw", point.get("reportedValue")))
                    if val is None:
                        continue
                    by_date.setdefault(asof, {})[av_key] = val
            reports = [
                {"fiscalDateEnding": d, **vals}
                for d, vals in sorted(by_date.items(), reverse=True)[:12]
            ]
            if not reports:
                return unavailable(SOURCE, f"No {period} {statement} data for '{symbol}'.")
            currency = self._currency(symbol)
            env = live_envelope(
                SOURCE,
                {
                    "symbol": symbol,
                    "statement": statement,
                    "period": period,
                    "currency": currency,
                    "reports": reports,
                },
            )
            env["timeliness"] = "END-OF-DAY"
            _cache_set(f"st:{symbol}:{statement}:{period}", env)
            return env
        except Exception as exc:
            return error_envelope(SOURCE, f"Could not parse statements for {symbol}: {exc}")

    # -- quoteSummary ------------------------------------------------
    _NO_CRUMB = (
        "Yahoo session (crumb) unreachable from here; trailing ratios "
        "via this leg are unavailable, but timeseries statements above "
        "remain available."
    )

    def _quote_summary(self, symbol: str, modules: list[str]) -> dict | None:
        cached = _cache_get(f"qs:{symbol}:{','.join(sorted(modules))}")
        if cached is not None:
            return cached.get("_payload")
        crumb = _get_crumb()
        if crumb is None:
            raise PermissionError(self._NO_CRUMB)
        url = (
            _QS_BASE
            + urllib.parse.quote(symbol)
            + "?modules="
            + urllib.parse.quote(",".join(modules))
            + ("&crumb=" + urllib.parse.quote(crumb[0]) if crumb else "")
        )
        try:
            payload = _http_json(url, jar=crumb[1] if crumb else None)
        except (RateLimitedError, PermissionError):
            raise
        except Exception:
            # One retry path: stale crumb is the usual cause.
            global _crumb
            _crumb = None
            crumb = _get_crumb()
            if crumb is None:
                raise
            url = (
                _QS_BASE
                + urllib.parse.quote(symbol)
                + "?modules="
                + urllib.parse.quote(",".join(modules))
                + "&crumb="
                + urllib.parse.quote(crumb[0])
            )
            payload = _http_json(url, jar=crumb[1])
        try:
            result = (((payload.get("quoteSummary") or {}).get("result")) or [None])[0]
        except Exception:
            return None
        if result:
            _cache_set(
                f"qs:{symbol}:{','.join(sorted(modules))}", {"_payload": result}
            )
        return result

    def _currency(self, symbol: str) -> str | None:
        try:
            qs = self._quote_summary(symbol, ["price"])
            return ((qs or {}).get("price") or {}).get("currency")
        except Exception:
            return None

    def get_ratios(self, symbol: str) -> dict:
        """AV-OVERVIEW-shaped flat dict (trailing fundamentals)."""
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return unavailable(SOURCE, "Empty symbol.")
        try:
            qs = self._quote_summary(
                symbol,
                ["price", "summaryDetail", "defaultKeyStatistics", "financialData"],
            )
        except RateLimitedError as exc:
            return rate_limited(SOURCE, f"Ratios throttled for {symbol}: {exc}")
        except PermissionError as exc:
            return unavailable(SOURCE, f"No data for '{symbol}': {exc}")
        except Exception as exc:
            return error_envelope(SOURCE, f"Ratios request failed for {symbol}: {exc}")
        if not qs:
            return unavailable(SOURCE, f"No fundamentals for '{symbol}'.")
        price = qs.get("price") or {}
        summary = qs.get("summaryDetail") or {}
        stats = qs.get("defaultKeyStatistics") or {}
        fin = qs.get("financialData") or {}
        dy = _raw(summary.get("dividendYield"))
        out = {
            "Symbol": symbol,
            "Name": price.get("longName") or price.get("shortName"),
            "Exchange": price.get("exchangeName"),
            "Currency": price.get("currency"),
            "MarketCapitalization": _raw(price.get("marketCap")),
            "EBITDA": _raw(fin.get("ebitda")),
            "PERatio": _raw(summary.get("trailingPE")),
            "ForwardPE": _raw(summary.get("forwardPE")),
            "PEGRatio": _raw(stats.get("pegRatio")),
            "BookValue": _raw(stats.get("bookValue")),
            "PriceToBookRatio": _raw(stats.get("priceToBook")),
            "PriceToSalesRatioTTM": _raw(summary.get("priceToSalesTrailing12Months")),
            "EVToRevenue": _raw(stats.get("enterpriseToRevenue")),
            "EVToEBITDA": _raw(stats.get("enterpriseToEbitda")),
            "EPS": _raw(stats.get("trailingEps")),
            "ROE": _pct(_raw(fin.get("returnOnEquity"))),
            "ROA": _pct(_raw(fin.get("returnOnAssets"))),
            "ReturnOnEquityTTM": _pct(_raw(fin.get("returnOnEquity"))),
            "ReturnOnAssetsTTM": _pct(_raw(fin.get("returnOnAssets"))),
            "ProfitMargin": _pct(_raw(fin.get("profitMargins"))),
            "OperatingMarginTTM": _pct(_raw(fin.get("operatingMargins"))),
            "DividendYield": (round(dy * 100.0, 4)) if dy is not None else None,
            "DividendPerShare": _raw(summary.get("dividendRate")),
            "Beta": _raw(summary.get("beta") if _raw(summary.get("beta")) is not None else stats.get("beta")),
            "52WeekHigh": _raw(summary.get("fiftyTwoWeekHigh")),
            "52WeekLow": _raw(summary.get("fiftyTwoWeekLow")),
        }
        if all(v is None for k, v in out.items() if k not in ("Symbol", "Name", "Exchange", "Currency")):
            return unavailable(SOURCE, f"No fundamentals for '{symbol}'.")
        return live_envelope(SOURCE, out)

    def get_company_profile(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        try:
            qs = self._quote_summary(
                symbol, ["price", "summaryProfile", "assetProfile", "quoteType"]
            )
        except RateLimitedError as exc:
            return rate_limited(SOURCE, f"Profile throttled for {symbol}: {exc}")
        except PermissionError as exc:
            return unavailable(SOURCE, f"No data for '{symbol}': {exc}")
        except Exception as exc:
            return error_envelope(SOURCE, f"Profile request failed for {symbol}: {exc}")
        if not qs:
            return unavailable(SOURCE, f"No profile for '{symbol}'.")
        price = qs.get("price") or {}
        prof = qs.get("summaryProfile") or qs.get("assetProfile") or {}
        return live_envelope(
            SOURCE,
            {
                "symbol": symbol,
                "name": price.get("longName") or price.get("shortName"),
                "exchange": price.get("exchangeName"),
                "currency": price.get("currency"),
                "instrument_type": (qs.get("quoteType") or {}).get("quoteType"),
                "sector": prof.get("sector"),
                "industry": prof.get("industry"),
                "description": prof.get("longBusinessSummary"),
                "website": prof.get("website"),
            },
        )

    def get_earnings(self, symbol: str) -> dict:
        """Quarterly reported vs estimated EPS from the earnings chart."""
        symbol = (symbol or "").strip().upper()
        try:
            qs = self._quote_summary(symbol, ["earnings"])
        except RateLimitedError as exc:
            return rate_limited(SOURCE, f"Earnings throttled for {symbol}: {exc}")
        except PermissionError as exc:
            return unavailable(SOURCE, f"No data for '{symbol}': {exc}")
        except Exception as exc:
            return error_envelope(SOURCE, f"Earnings request failed for {symbol}: {exc}")
        chart = ((qs or {}).get("earnings") or {}).get("earningsChart") or {}
        quarterly = chart.get("quarterly") or []
        rows = []
        for q in quarterly:
            rows.append(
                {
                    "fiscalDateEnding": str(q.get("date") or "")[:10] or None,
                    "reportedEPS": _raw((q.get("actual") or {}).get("raw", q.get("actual"))),
                    "estimatedEPS": _raw((q.get("estimate") or {}).get("raw", q.get("estimate"))),
                    "surprise": None,
                    "source": SOURCE,
                }
            )
        rows = [r for r in rows if r["reportedEPS"] is not None or r["estimatedEPS"] is not None]
        if not rows:
            return unavailable(SOURCE, f"No earnings data for '{symbol}'.")
        # Yahoo orders oldest-first; terminal convention is newest-first.
        rows.reverse()
        return live_envelope(
            SOURCE, {"symbol": symbol, "annual": [], "quarterly": rows[:8]}
        )


def _pct(frac: float | None) -> float | None:
    if frac is None:
        return None
    return round(frac * 100.0, 4)
