"""Provider registry — single place where the server wires providers.

Automatic free-mode chains (no paid subscription required):

QUOTE (Indian first):
    indian-api -> yahoo -> twelvedata -> alphavantage -> UNAVAILABLE
QUOTE (global): yahoo first (indian leg passes non-Indian symbols through)
HISTORY:
    yahoo -> stooq -> twelvedata -> alphavantage -> UNAVAILABLE
FUNDAMENTALS / STATEMENTS (free first):
    yahoo-fundamentals -> alphavantage -> twelvedata (+ indian-api keyed)
    Yahoo timeseries statements + trailing ratios need no key and cover
    NSE/BSE + global symbols; AV/TD add depth where configured.
EARNINGS:  alphavantage + twelvedata
ESTIMATES: alphavantage only. Never synthesised EPS forecasts.
NEWS:    yahoo-rss -> alphavantage
IPO:     alphavantage         MACRO: alphavantage indicators
ACTIONS: yahoo-events (+alphavantage/twelvedata legs)
HOLDINGS: no configured provider (honest unavailable)
TECHNICAL: local calc from history   CHART: TradingView widget

Swap implementations here (or via env vars) without touching the UI.
"""

from __future__ import annotations

import os

from . import base as _base
from .fallback import FallbackMarketData
from .fundamentals import AlphaVantageFundamentalsProvider
from .indianapi import IndianApiProvider
from .mutualfunds import MutualFundProvider
from .news import YahooCorporateActionsProvider, YahooRssNewsProvider
from .orchestrator import ProviderManager
from .stooq import StooqProvider
from .tradingview import TradingViewProvider
from .tradingview import authorization_scope as _tradingview_scope
from .twelvedata import TwelveDataProvider, budget_snapshot
from .upstox import UpstoxProvider
from .yahoo import YahooMarketDataProvider
from .yahoo_fundamentals import YahooFundamentalsProvider

_yahoo = YahooMarketDataProvider()
_yahoo_fund = YahooFundamentalsProvider()
mutualfunds = MutualFundProvider()
_indianapi = IndianApiProvider()
_twelvedata = TwelveDataProvider()
_alphavantage = AlphaVantageFundamentalsProvider()
_stooq = StooqProvider()
_tradingview = TradingViewProvider()
_upstox = UpstoxProvider()

# QUOTE chain (field-level routing: Upstox first for ISIN-mapped
# Indian names, else pass-through to Yahoo):
#   upstox -> indian-api -> yahoo -> twelvedata -> alphavantage
# Upstox legs return pass-through `unavailable` (never cooldown) when
# the token is missing or the ISIN is unmapped, so chains are unaffected.
market_data = FallbackMarketData(
    legs=[
        ("upstox", _upstox),
        ("indian-api", _indianapi),
        ("yahoo", _yahoo),
        ("twelvedata", _twelvedata),
        ("alphavantage", _alphavantage),
    ],
    scarce_legs={"alphavantage"},
)


class _AvHistoryAdapter:
    """Expose AlphaVantage TIME_SERIES_DAILY under the history protocol."""

    name = "alphavantage"
    capabilities = {"history": True}

    def get_historical_prices(self, symbol, range_="1M", interval="1d"):
        if (interval or "1d").lower() != "1d":
            from .base import error_envelope

            return error_envelope(
                "alphavantage", "AV history leg serves daily bars only."
            )
        return _alphavantage.get_daily_history(symbol)


# HISTORY chain: Upstox (ISIN-mapped depth) -> Yahoo -> Stooq ->
# Twelve Data -> Alpha Vantage.
history = FallbackMarketData(
    legs=[
        ("upstox", _upstox),
        ("yahoo", _yahoo),
        ("stooq", _stooq),
        ("twelvedata", _twelvedata),
        ("alphavantage-history", _AvHistoryAdapter()),
    ],
    scarce_legs={"alphavantage-history"},
)

company = market_data  # identity rides on the quote-chain winner
fundamentals = _alphavantage
news = YahooRssNewsProvider()
corporate_actions = YahooCorporateActionsProvider()

# Multi-provider orchestrator: fan-out + normalization + reconciliation.
# Cheap endpoints (quote/history/search) keep first-healthy chains;
# company domains below go through the manager.
manager = ProviderManager(
    yahoo=_yahoo,
    indianapi=_indianapi,
    twelvedata=_twelvedata,
    alphavantage=_alphavantage,
    upstox=_upstox,
    news_rss=news,
    actions_yahoo=corporate_actions,
    yahoo_fund=_yahoo_fund,
)
# Estimates: Alpha Vantage EARNINGS_ESTIMATES (key configured) for
# non-Indian symbols; the indian-api analyst-rating distribution for
# NSE/BSE symbols. Never synthesised EPS forecasts.
estimates = manager
holdings = manager


def _configured(env_name: str) -> bool:
    return bool((os.environ.get(env_name) or "").strip())


def _upstox_key() -> bool:
    return bool((os.environ.get("UPSTOX_ANALYTICS_TOKEN") or "").strip())


def _upstox_status_ok() -> bool:
    try:
        h = market_data.health().get("upstox", {}) if hasattr(market_data, "health") else {}
    except Exception:
        h = {}
    if h.get("state") == "cooling":
        return False
    return _upstox_key()


def providers_status() -> dict:
    """Settings -> Data Sources payload. Never exposes key values."""
    health = market_data.health() if hasattr(market_data, "health") else {}
    try:
        hist_health = history.health()
    except Exception:
        hist_health = {}
    td_budget = budget_snapshot()
    av_key = _configured("ALPHA_VANTAGE_API_KEY") or _configured("FUNDAMENTALS_API_KEY")
    td_key = _configured("TWELVE_DATA_API_KEY")
    return {
        "chain": {
            "quote": ["upstox", "indian-api", "yahoo", "twelvedata", "alphavantage"],
            "history": ["upstox", "yahoo", "stooq", "twelvedata", "alphavantage"],
            "news": ["yahoo-rss", "alphavantage", "indian-api"],
            "fundamentals": ["yahoo-fundamentals", "alphavantage", "twelvedata", "indian-api", "upstox"],
        },
        "providers": [
            {
                "id": "yahoo",
                "label": "Yahoo Finance",
                "state": "connected"
                if health.get("yahoo", {}).get("state") != "cooling"
                else "cooling",
                "detail": "Free public feed, exchange-delayed. Quotes, "
                "history, search, company identity, RSS news.",
                "key_required": False,
                "key_configured": True,
                "capabilities": _base.describe(_yahoo),
                "health": health.get("yahoo", {}),
            },
            {
                "id": "yahoo-fundamentals",
                "label": "Yahoo Fundamentals",
                "state": "connected"
                if health.get("yahoo", {}).get("state") != "cooling"
                else "cooling",
                "detail": "Free, no key. Timeseries statements (income, "
                "balance, cash flow — annual + quarterly), trailing ratios, "
                "earnings chart, sector/industry profile. Covers NSE/BSE "
                "and global symbols; exchange-delayed.",
                "key_required": False,
                "key_configured": True,
                "capabilities": _base.describe(_yahoo_fund),
                "health": health.get("yahoo", {}),
            },
            {
                "id": "mfapi",
                "label": "MFAPI (AMFI NAV)",
                "state": "connected",
                "detail": "Free, no key. Indian mutual fund scheme search + "
                "date-stamped NAV history (AMFI-published, not live prices).",
                "key_required": False,
                "key_configured": True,
                "capabilities": _base.describe(mutualfunds),
                "health": {},
            },
            {
                "id": "indian-api",
                "label": "Indian Stock Market API",
                "state": "connected"
                if health.get("indian-api", {}).get("state") == "ok"
                and health.get("indian-api", {}).get("last_ok")
                else "unreachable",
                "detail": "NSE/BSE leg (x-api-key when configured, else "
                "free no-auth quote + market fundamentals). Keyed: quote, "
                "statements, history, stats, actions, news, forecasts, "
                "targets, ownership. No-auth: quote, sector/industry, "
                "market cap, P/E, EPS, book value, dividend yield, 52W.",
                "key_required": False,
                "key_configured": bool(
                    (os.environ.get("INDIAN_STOCK_MARKET_API_KEY") or "").strip()
                ),
                "capabilities": _base.describe(_indianapi),
                "health": health.get("indian-api", {}),
                "budget": _indianapi.budget_snapshot(),
            },
            {
                "id": "alphavantage",
                "label": "Alpha Vantage",
                "state": "connected" if av_key else "key_missing",
                "detail": "Free tier: 25 requests/day, delayed. "
                "Fundamentals, statements, earnings, news, IPO, macro, "
                "last-resort quotes/history.",
                "key_required": True,
                "key_configured": av_key,
                "capabilities": _base.describe(_alphavantage),
                "health": health.get("alphavantage", {}),
            },
            {
                "id": "twelvedata",
                "label": "Twelve Data",
                "state": "connected" if td_key else "key_missing",
                "detail": "Free Basic: 8 credits/min, 800/day. Claims "
                "real-time US equities/ETFs, forex, crypto; "
                "other markets delayed or uncovered.",
                "key_required": True,
                "key_configured": td_key,
                "capabilities": _base.describe(_twelvedata),
                "budget": td_budget,
                "health": health.get("twelvedata", {}),
            },
            {
                "id": "stooq",
                "label": "Stooq",
                "state": "connected",
                "detail": "Historical daily CSV, US symbols only "
                "(mapping unverified elsewhere). History fallback; "
                "never live quotes.",
                "key_required": False,
                "key_configured": True,
                "capabilities": _base.describe(_stooq),
                "health": hist_health.get("stooq", {}),
            },
            {
                "id": "upstox",
                "label": "Upstox",
                "state": "connected" if _upstox_status_ok() else "key_missing",
                "detail": "Verified Upstox Developer APIs (server-side "
                "UPSTOX_ANALYTICS_TOKEN): market-quote V3, "
                "historical-candle V3, /v2/fundamentals/:isin suite "
                "(profile, ratios, statements, holdings, actions), "
                "/v2/news (7-day). "
                "Analytics only; no trading. Missing key → pass-through.",
                "key_required": True,
                "key_configured": _upstox_key(),
                "capabilities": _base.describe(_upstox),
                "health": health.get("upstox", {}),
            },
            {
                "id": "nse",
                "label": "NSE",
                "state": "feed_missing",
                "detail": "NSE REAL-TIME NOT AVAILABLE WITHOUT AUTHORIZED "
                "FEED. NSE symbols load delayed via Yahoo "
                "(e.g. RELIANCE.NS).",
                "key_required": True,
                "key_configured": False,
                "capabilities": {k: False for k in _base.CAPABILITIES},
            },
            {
                "id": "tradingview",
                "label": "TradingView",
                "state": "widget_available",
                "detail": "Official chart widget embed only (chart "
                "visualisation, not a backend data feed). Data feeds "
                "stay disabled without TRADINGVIEW_ENABLED=1 plus a "
                "documented authorized scope. Never scraped, never "
                "presented as our data.",
                "key_required": False,
                "key_configured": True,
                "capabilities": _base.describe(_tradingview),
                "authorization_scope": _tradingview_scope(),
            },
        ],
    }
