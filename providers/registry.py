"""Provider registry — single place where the server wires providers.

Automatic free-mode chains (no paid subscription required):

QUOTE (Indian first):
    indian-api -> yahoo -> twelvedata -> alphavantage -> UNAVAILABLE
QUOTE (global): yahoo first (indian leg passes non-Indian symbols through)
HISTORY:
    yahoo -> stooq -> twelvedata -> alphavantage -> UNAVAILABLE
FUNDAMENTALS / STATEMENTS:
    indian-api (NSE/BSE) else alphavantage -> twelvedata
EARNINGS:  alphavantage (indian-api annual EPS for NSE/BSE)
ESTIMATES: alphavantage (non-Indian) | indian-api analyst ratings
           (NSE/BSE). Never synthesised EPS forecasts.
NEWS:    yahoo-rss -> alphavantage (indian-api news for NSE/BSE)
IPO:     alphavantage         MACRO: alphavantage indicators
ACTIONS: yahoo-events (indian-api dividends/splits for NSE/BSE)
HOLDINGS: indian-api ownership split (NSE/BSE only)
TECHNICAL: local calc from history   CHART: TradingView widget

Swap implementations here (or via env vars) without touching the UI.
"""

from __future__ import annotations

import os

from . import base as _base
from .fallback import FallbackMarketData
from .fundamentals import AlphaVantageFundamentalsProvider
from .indianapi import IndianApiProvider
from .news import YahooCorporateActionsProvider, YahooRssNewsProvider
from .orchestrator import ProviderManager
from .stooq import StooqProvider
from .twelvedata import TwelveDataProvider, budget_snapshot
from .yahoo import YahooMarketDataProvider

_yahoo = YahooMarketDataProvider()
_indianapi = IndianApiProvider()
_twelvedata = TwelveDataProvider()
_alphavantage = AlphaVantageFundamentalsProvider()
_stooq = StooqProvider()

# QUOTE chain: Indian leg first (passes non-Indian symbols through),
# then Yahoo -> Twelve Data -> Alpha Vantage (scarce, 6 h cache).
market_data = FallbackMarketData(
    legs=[
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


# HISTORY chain: Yahoo -> Stooq -> Twelve Data -> Alpha Vantage.
history = FallbackMarketData(
    legs=[
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
    news_rss=news,
    actions_yahoo=corporate_actions,
)
# Estimates: Alpha Vantage EARNINGS_ESTIMATES (key configured) for
# non-Indian symbols; the indian-api analyst-rating distribution for
# NSE/BSE symbols. Never synthesised EPS forecasts.
estimates = manager
holdings = manager


def _configured(env_name: str) -> bool:
    return bool((os.environ.get(env_name) or "").strip())


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
            "quote": ["indian-api", "yahoo", "twelvedata", "alphavantage"],
            "history": ["yahoo", "stooq", "twelvedata", "alphavantage"],
            "news": ["yahoo-rss", "alphavantage", "indian-api"],
            "fundamentals": ["alphavantage", "twelvedata", "indian-api"],
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
                "id": "indian-api",
                "label": "Indian Stock Market API (stock.indianapi.in)",
                "state": "connected"
                if health.get("indian-api", {}).get("state") == "ok"
                and health.get("indian-api", {}).get("last_ok")
                else "unreachable",
                "detail": "Keyed NSE/BSE feed (X-API-Key). One delayed "
                "snapshot powers quote, fundamentals, statements, "
                "earnings, analyst ratings, ownership, corporate actions "
                "and news for NSE/BSE symbols. Rate budget self-imposed "
                "(30/min, 2000/day); responses cached.",
                "key_required": True,
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
                "visualisation, not a backend data feed). Never scraped, "
                "never presented as our data.",
                "key_required": False,
                "key_configured": True,
                "capabilities": {"chart": True},
            },
        ],
    }
