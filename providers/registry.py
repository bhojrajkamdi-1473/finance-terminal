"""Provider registry — single place where the server wires providers.

Swap implementations here (or via env vars) without touching the UI.
"""

from __future__ import annotations

from .fundamentals import AlphaVantageFundamentalsProvider, NoEstimatesProvider
from .news import YahooCorporateActionsProvider, YahooRssNewsProvider
from .yahoo import YahooMarketDataProvider

market_data = YahooMarketDataProvider()
company = YahooMarketDataProvider()  # meta from chart API
fundamentals = AlphaVantageFundamentalsProvider()
news = YahooRssNewsProvider()
corporate_actions = YahooCorporateActionsProvider()
estimates = NoEstimatesProvider()
