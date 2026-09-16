"""Stooq historical-data leg (no key).

Uses the public daily CSV endpoint for suffix-less (US) symbols only,
e.g. AAPL -> aapl.us. Verified live (Sep 2026):
- stooq.com is behind a bot-wall for browser-style quote pages, but the
  /q/d/l/ CSV endpoint shape is validated on every response.
- Symbols outside the verified mapping (.NS/.BO/indices) are NOT
  attempted: Stooq's non-US conventions are unverifiable from here,
  and a wrong mapping could misattribute another company's history.

Any block (bot-wall HTML, 401, limit text, bad shape) becomes an
honest "unavailable" envelope so the history chain continues.
Timeliness is always HISTORICAL — never real-time.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .base import MarketDataProvider, error_envelope, live_envelope, unavailable

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}


def to_stooq_symbol(symbol: str) -> str | None:
    s = (symbol or "").strip().upper()
    if not s or s.startswith("^") or "." in s or "/" in s or " " in s:
        return None
    return s.lower() + ".us"


def _fetch_csv(symbol: str, timeout: float = 20.0) -> str:
    stooq = to_stooq_symbol(symbol)
    assert stooq is not None
    url = "https://stooq.com/q/d/l/?s=" + urllib.parse.quote(stooq) + "&i=d"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_daily_csv(text: str) -> list[dict] | None:
    """Parse Stooq daily CSV. Returns bars or None when the response is
    not a valid history CSV (bot-wall HTML, limit notice, unknown symbol)."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    header = [h.strip().lower() for h in lines[0].split(",")]
    if not ("date" in header and "close" in header):
        return None
    idx = {h: i for i, h in enumerate(header)}
    bars = []
    for ln in lines[1:]:
        cells = [c.strip() for c in ln.split(",")]
        try:
            dt = datetime.strptime(cells[idx["date"]], "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            c = float(cells[idx["close"]])
        except (ValueError, IndexError, KeyError):
            continue

        def num(key: str) -> float | None:
            try:
                return float(cells[idx[key]])
            except (ValueError, IndexError, KeyError):
                return None

        bars.append(
            {
                "t": int(dt.timestamp()),
                "o": num("open"),
                "h": num("high"),
                "l": num("low"),
                "c": c,
                "adj": c,
                "v": num("volume"),
            }
        )
    return bars or None


class StooqProvider(MarketDataProvider):
    name = "stooq"
    capabilities: dict[str, bool] = {"history": True}

    def search(self, query: str, limit: int = 10) -> dict:
        return unavailable("stooq", "No search on the Stooq leg.")

    def get_quote(self, symbol: str) -> dict:
        return unavailable(
            "stooq", "Stooq is a historical leg, not a live quote provider."
        )

    def get_historical_prices(
        self, symbol: str, range_: str = "1M", interval: str = "1d"
    ) -> dict:
        symbol = (symbol or "").strip().upper()
        if to_stooq_symbol(symbol) is None:
            return unavailable(
                "stooq",
                f"Stooq symbol mapping unverified for '{symbol}' "
                "(US suffix-less symbols only); passing through.",
            )
        if (interval or "1d").lower() != "1d":
            return error_envelope("stooq", "Stooq leg serves daily history only.")
        try:
            text = _fetch_csv(symbol)
        except Exception as exc:
            return error_envelope("stooq", f"History fetch failed: {exc}")
        bars = parse_daily_csv(text)
        if not bars:
            return unavailable(
                "stooq",
                "No valid history CSV returned (blocked, capped or unknown "
                "symbol). Passing through.",
            )
        want = {
            "1D": 5,
            "5D": 10,
            "1M": 30,
            "3M": 90,
            "6M": 180,
            "1Y": 260,
            "2Y": 520,
            "5Y": 1300,
            "MAX": len(bars),
        }.get((range_ or "1M").upper(), 30)
        env = live_envelope(
            "stooq",
            {
                "symbol": symbol,
                "range": range_,
                "interval": "1d",
                "currency": "USD",
                "bars": bars[-want:],
            },
            delayed=True,
        )
        env["timeliness"] = "HISTORICAL"
        env["timeliness_note"] = (
            "Stooq daily CSV: historical end-of-day data, not live."
        )
        return env
