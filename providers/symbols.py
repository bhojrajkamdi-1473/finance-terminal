"""Provider-symbol normalization layer.

Internal canonical form: Yahoo-style, uppercased ("TATASTEEL.NS", "AAPL").

Per-provider mapping:
- yahoo / indian-api / tradingview-widget: canonical as-is.
- stooq: US suffix-less only (existing verified rule).
- twelvedata: .NS -> /NSE, .BO -> /BSE (existing rule).
- alphavantage: resolved via SYMBOL_SEARCH (cached), then validated —
  the response Symbol must share the requested alphanumeric core,
  otherwise the data is rejected (never another company's data under
  the wrong symbol). AV's NSE convention is NOT assumed; it is
  discovered per symbol and cached.

Resolution cache lives here (7 d TTL) so discovery costs at most one
free-tier call per symbol per week.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from services.refresh import TTLCache

RESOLUTION_TTL = 7 * 24 * 3600.0

_cache = TTLCache()


def canonical(symbol: str) -> str:
    return (symbol or "").strip().upper()


def core(symbol: str) -> str:
    """Alphanumeric core used for mismatch detection."""
    return re.sub(r"[^A-Z0-9]", "", canonical(symbol))


def symbols_match(requested: str, returned: str | None) -> bool:
    """True when the provider's echoed symbol plausibly denotes the
    requested instrument: shared core of length >= 3."""
    if not returned:
        return False
    a, b = core(requested), core(returned)
    if len(a) < 3 or len(b) < 3:
        return False
    return a in b or b in a or a[:6] == b[:6]


def for_yahoo(symbol: str) -> str:
    return canonical(symbol)


def resolve_alphavantage(symbol: str, search_fn: Callable[[str], list[dict]]) -> dict:
    """Resolve the Alpha Vantage symbol for an internal symbol.

    Returns {"symbol": av_symbol} or {"unresolved": reason}.
    search_fn(query) -> [{symbol, name}] performs SYMBOL_SEARCH.
    Result cached 7 days (free-tier quota protection).
    """
    symbol = canonical(symbol)
    if not symbol:
        return {"unresolved": "Empty symbol."}
    hit = _cache.get(f"avsym:{symbol}")
    if hit is not None:
        return hit  # type: ignore[return-value]
    base = re.sub(r"\.(NS|BO)$", "", symbol)
    is_indian = symbol.endswith((".NS", ".BO"))
    candidates: list[dict] = []
    try:
        candidates = search_fn(base) or []
    except Exception:
        candidates = []
    best: str | None = None
    for c in candidates:
        cand = str(c.get("symbol") or "")
        if not cand:
            continue
        if is_indian:
            # Accept only a candidate whose core matches the requested
            # base (e.g. TATASTEEL...); US-looking bare matches for an
            # Indian request are rejected.
            if core(base) and core(base) in core(cand):
                best = cand.upper()
                break
        elif core(symbol) == core(cand) or core(cand) == core(symbol):
            best = cand.upper()
            break
    if best is None and not is_indian:
        # Non-Indian symbols pass through uppercased (e.g. AAPL, MSFT);
        # the response validator still guards against mismatches.
        best = symbol
    out: dict[str, Any] = (
        {"symbol": best}
        if best
        else {"unresolved": f"No Alpha Vantage symbol found for '{symbol}'."}
    )
    _cache.set(f"avsym:{symbol}", out, RESOLUTION_TTL)
    return out
