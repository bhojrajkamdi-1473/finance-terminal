"""Provider interfaces for the finance terminal.

Every provider returns an envelope dict so the UI can always
distinguish live / historical / calculated / unavailable data:

    {"status": "live"|"delayed"|"unavailable"|"error",
     "source": "provider name",
     "as_of": ISO timestamp or None,
     "data": ... or None,
     "message": human-readable note when not live}

No provider may fabricate market data. When upstream data is missing,
return status="unavailable" with an explanatory message.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def unavailable(source: str, message: str, code: str | None = None) -> dict:
    env = {
        "status": "unavailable",
        "source": source,
        "as_of": None,
        "data": None,
        "message": message,
    }
    if code:
        env["code"] = code
    return env


def error_envelope(source: str, message: str, code: str | None = None) -> dict:
    env = {
        "status": "error",
        "source": source,
        "as_of": None,
        "data": None,
        "message": message,
    }
    if code:
        env["code"] = code
    return env


def live_envelope(source: str, data: Any, delayed: bool = False) -> dict:
    return {
        "status": "delayed" if delayed else "live",
        "source": source,
        "as_of": utcnow_iso(),
        "data": data,
        "message": None,
    }


class MarketDataProvider(ABC):
    """Live/historical price data."""

    name: str = "base"
    # Declared capabilities; the registry routes each domain only to
    # legs that claim it. Keys: quote, history, search.
    capabilities: dict[str, bool] = {}

    @abstractmethod
    def get_quote(self, symbol: str) -> dict:
        """Current quote for a symbol. Returns envelope."""

    @abstractmethod
    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        """OHLCV history. Returns envelope with {"bars": [...]}."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> dict:
        """Search instruments by name/ticker. Returns envelope."""


class CompanyProvider(ABC):
    name: str = "base"
    capabilities: dict[str, bool] = {}

    @abstractmethod
    def get_company_profile(self, symbol: str) -> dict:
        """Name, exchange, sector, industry, currency. Envelope."""


class FundamentalsProvider(ABC):
    name: str = "base"
    # Keys: fundamentals, statements, earnings, estimates.
    capabilities: dict[str, bool] = {}

    @abstractmethod
    def get_financial_statements(
        self, symbol: str, statement: str = "income", period: str = "annual"
    ) -> dict:
        """Income / balance / cashflow statements. Envelope."""

    @abstractmethod
    def get_ratios(self, symbol: str) -> dict:
        """Valuation & quality ratios. Envelope."""


class NewsProvider(ABC):
    name: str = "base"
    capabilities: dict[str, bool] = {"news": True}

    @abstractmethod
    def get_news(
        self,
        symbol: str | None = None,
        topic: str | None = None,
        limit: int = 20,
    ) -> dict:
        """News headlines. Envelope."""


class CorporateActionsProvider(ABC):
    name: str = "base"
    capabilities: dict[str, bool] = {"actions": True}

    @abstractmethod
    def get_corporate_actions(self, symbol: str) -> dict:
        """Dividends / splits / earnings dates. Envelope."""


class EstimatesProvider(ABC):
    name: str = "base"
    capabilities: dict[str, bool] = {"estimates": False}

    @abstractmethod
    def get_estimates(self, symbol: str) -> dict:
        """Analyst estimates. Envelope."""


# Canonical capability keys used by the registry + /api/providers.
CAPABILITIES = (
    "quote",
    "history",
    "search",
    "fundamentals",
    "statements",
    "earnings",
    "estimates",
    "news",
    "ipo",
    "actions",
    "holdings",
    "macro",
    "technical",
    "chart",
)


def describe(provider) -> dict[str, bool]:
    """Capability map for a provider instance (missing = unsupported)."""
    declared = getattr(provider, "capabilities", {}) or {}
    return {k: bool(declared.get(k, False)) for k in CAPABILITIES}
