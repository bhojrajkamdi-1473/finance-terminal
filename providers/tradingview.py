"""TradingView adapter: visualization ENABLED, data paths GATED.

Capability boundary (no source repository present; scope derived from
the project's stated authorization, never assumed):

- Chart widgets / embeds: ENABLED. The terminal already embeds the
  official tv.js widget (frontend). No credentials, no scraping.
- Quote / history / scanner / indicator data feeds: DISABLED by
  default. TradingView's data endpoints are undocumented/internal;
  using them would violate the no-reverse-engineering rule. They stay
  disabled unless TRADINGVIEW_ENABLED=1 is set AND the deployment
  documents an authorized data scope — even then, data is labelled
  source=tradingview with authorization_scope attached, and the
  terminal keeps working if this leg fails.

No username/password/cookies/session/token is ever read or stored.
"""

from __future__ import annotations

import os

from .base import MarketDataProvider, error_envelope, unavailable

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}


def _data_enabled() -> bool:
    return (os.environ.get("TRADINGVIEW_ENABLED") or "").strip() == "1"


def authorization_scope() -> str:
    if _data_enabled():
        return (
            "operator-asserted display+data scope; verify against the "
            "written authorization before relying on values"
        )
    return "visualization-only (official widgets/embeds)"


class TradingViewProvider(MarketDataProvider):
    name = "tradingview"
    capabilities: dict[str, bool] = {
        "quote": False,
        "history": False,
        "search": False,
        "chart": True,
    }

    def _gated(self, what: str) -> dict:
        return unavailable(
            "tradingview",
            f"TradingView {what} is disabled: data feeds require explicit "
            "TRADINGVIEW_ENABLED=1 plus a documented authorized scope. "
            "Charts remain available via the official widget.",
        )

    def search(self, query: str, limit: int = 10) -> dict:
        return self._gated("symbol search")

    def get_quote(self, symbol: str) -> dict:
        if not _data_enabled():
            return self._gated("quotes")
        return error_envelope(
            "tradingview",
            "TRADINGVIEW_ENABLED=1 is set but no authorized data transport "
            "is implemented in this build.",
        )

    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        if not _data_enabled():
            return self._gated("history")
        return error_envelope(
            "tradingview",
            "TRADINGVIEW_ENABLED=1 is set but no authorized data transport "
            "is implemented in this build.",
        )
