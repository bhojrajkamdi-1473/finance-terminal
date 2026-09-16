"""News + corporate-actions providers.

News: no API key is required to be honest — without a configured news
feed the terminal must show "news unavailable" rather than inventing
headlines. An optional RSS bridge (Yahoo Finance RSS, no key) is
attempted; if it fails the envelope is "unavailable", never synthetic.

Corporate actions: dividends/splits/earnings events come from Yahoo's
chart API events block (factual, source-attributed).
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from .base import (
    CorporateActionsProvider,
    NewsProvider,
    error_envelope,
    live_envelope,
    unavailable,
)
from .yahoo import YahooMarketDataProvider

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}


class YahooRssNewsProvider(NewsProvider):
    name = "yahoo-rss"
    capabilities: dict[str, bool] = {"news": True}

    def get_news(
        self,
        symbol: str | None = None,
        topic: str | None = None,
        limit: int = 20,
    ) -> dict:
        limit = max(1, min(limit, 50))
        # Yahoo's headline RSS requires a symbol; with none given, use a
        # broad-market proxy so "market headlines" still works. The query
        # actually sent is echoed back in the payload for transparency.
        query_symbol = symbol or "SPY"
        url = (
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s="
            + urllib.parse.quote(query_symbol)
            + "&region=US&lang=en-US"
        )
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", "replace")
            root = ET.fromstring(raw)
            items: list[dict[str, Any]] = []
            for item in root.iter("item"):
                if len(items) >= limit:
                    break
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub = (item.findtext("pubDate") or "").strip()
                desc = re.sub(
                    r"<[^>]+>", "", item.findtext("description") or ""
                ).strip()
                items.append(
                    {
                        "title": html.unescape(title),
                        "url": link,
                        "published_at": pub,
                        "source": "Yahoo Finance RSS",
                        "summary": html.unescape(desc)[:400],
                        "symbol": symbol,
                    }
                )
            if topic:
                items = [
                    i
                    for i in items
                    if topic.lower() in (i["title"] + " " + i["summary"]).lower()
                ]
            if not items:
                return unavailable(
                    "yahoo-rss",
                    "No news items returned for this query.",
                )
            return live_envelope(
                "yahoo-rss",
                {
                    "items": items,
                    "query": query_symbol,
                    "note": "Market-wide view uses SPY (S&P 500 ETF) headlines "
                    "as a proxy; per-symbol views query that symbol.",
                },
                delayed=False,
            )
        except Exception as exc:
            return unavailable("yahoo-rss", f"News unavailable: {exc}")


class YahooCorporateActionsProvider(CorporateActionsProvider):
    name = "yahoo-events"
    capabilities: dict[str, bool] = {"actions": True}

    def get_corporate_actions(self, symbol: str) -> dict:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return unavailable("yahoo-events", "Empty symbol.")
        provider = YahooMarketDataProvider()
        try:
            payload = provider._chart(symbol, "2y", "1d")
        except Exception as exc:
            return error_envelope("yahoo-events", f"Request failed: {exc}")
        try:
            result = (payload.get("chart") or {}).get("result") or []
            if not result:
                return unavailable("yahoo-events", f"No data for '{symbol}'.")
            events = result[0].get("events") or {}
            dividends: list[dict[str, Any]] = [
                {
                    "date": int(ts),
                    "amount": (v or {}).get("amount"),
                    "currency": (result[0].get("meta") or {}).get("currency"),
                }
                for ts, v in (events.get("dividends") or {}).items()
            ]
            splits: list[dict[str, Any]] = [
                {
                    "date": int(ts),
                    "numerator": (v or {}).get("numerator"),
                    "denominator": (v or {}).get("denominator"),
                }
                for ts, v in (events.get("splits") or {}).items()
            ]
            dividends.sort(key=lambda d: d["date"] or 0, reverse=True)
            splits.sort(key=lambda d: d["date"] or 0, reverse=True)
            return live_envelope(
                "yahoo-events",
                {
                    "symbol": symbol,
                    "dividends": dividends[:40],
                    "splits": splits[:40],
                    "note": "Earnings dates require an estimates/corporate "
                    "provider; only exchange-reported dividends and "
                    "splits are shown.",
                },
                delayed=True,
            )
        except Exception as exc:
            return error_envelope("yahoo-events", f"Parse failed: {exc}")
