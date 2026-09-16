"""Pure financial calculations.

Every function is side-effect free and unit-tested:
- growth (YoY/QoQ %) with zero/None guards
- margins (gross/ebitda/ebit/net)
- ratios (pe, pb, ev_ebitda, dividend yield, debt/equity)
- moving averages (SMA over close series)
- portfolio aggregation (invested/current/pnl/allocation)

Return None where inputs are insufficient — callers render
"Insufficient data" instead of inventing numbers.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def pct_change(new: float | None, old: float | None) -> float | None:
    """Percentage change from old to new. None if not computable."""
    if new is None or old is None:
        return None
    try:
        new_f, old_f = float(new), float(old)
    except (TypeError, ValueError):
        return None
    if old_f == 0:
        return None
    return (new_f - old_f) / abs(old_f) * 100.0


def margin(numerator: float | None, revenue: float | None) -> float | None:
    if numerator is None or revenue is None:
        return None
    try:
        rev = float(revenue)
    except (TypeError, ValueError):
        return None
    if rev == 0:
        return None
    try:
        return float(numerator) / rev * 100.0
    except (TypeError, ValueError):
        return None


def pe_ratio(price: float | None, eps: float | None) -> float | None:
    if price is None or eps is None:
        return None
    try:
        p, e = float(price), float(eps)
    except (TypeError, ValueError):
        return None
    if e <= 0:
        return None  # N/M for non-positive earnings, not negative P/E
    return p / e


def pb_ratio(price: float | None, book_per_share: float | None) -> float | None:
    if price is None or book_per_share is None:
        return None
    try:
        p, b = float(price), float(book_per_share)
    except (TypeError, ValueError):
        return None
    if b <= 0:
        return None
    return p / b


def ev_enterprise_value(
    market_cap: float | None,
    total_debt: float | None,
    cash: float | None,
) -> float | None:
    if market_cap is None:
        return None
    try:
        ev = float(market_cap)
        ev += float(total_debt or 0)
        ev -= float(cash or 0)
        return ev
    except (TypeError, ValueError):
        return None


def ev_multiple(ev: float | None, metric: float | None) -> float | None:
    if ev is None or metric is None:
        return None
    try:
        m = float(metric)
    except (TypeError, ValueError):
        return None
    if m <= 0:
        return None
    try:
        return float(ev) / m
    except (TypeError, ValueError):
        return None


def dividend_yield(dps: float | None, price: float | None) -> float | None:
    if dps is None or price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    try:
        return float(dps) / p * 100.0
    except (TypeError, ValueError):
        return None


def sma(values: Sequence[float | None], window: int) -> list[float | None]:
    """Simple moving average; None for warm-up / missing inputs."""
    out: list[float | None] = []
    if window <= 0:
        return [None] * len(values)
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
            continue
        window_vals = values[i + 1 - window : i + 1]
        total = 0.0
        ok = True
        for v in window_vals:
            if v is None:
                ok = False
                break
            try:
                total += float(v)
            except (TypeError, ValueError):
                ok = False
                break
        if not ok:
            out.append(None)
            continue
        out.append(total / window)
    return out


def portfolio_position(
    quantity: float, avg_price: float, current_price: float | None
) -> dict:
    invested = quantity * avg_price
    current = quantity * current_price if current_price is not None else None
    pnl = (current - invested) if current is not None else None
    pnl_pct = pct_change(current, invested) if current is not None else None
    return {
        "quantity": quantity,
        "avg_price": avg_price,
        "current_price": current_price,
        "invested_value": invested,
        "current_value": current,
        "unrealized_pnl": pnl,
        "pnl_pct": pnl_pct,
    }


def portfolio_summary(positions: Iterable[dict]) -> dict:
    positions = list(positions)
    invested = sum(p.get("invested_value") or 0 for p in positions)
    current = sum(
        p.get("current_value") or 0
        for p in positions
        if p.get("current_value") is not None
    )
    has_current = any(p.get("current_value") is not None for p in positions)
    pnl = (current - invested) if has_current else None
    out = []
    for p in positions:
        alloc = None
        if has_current and current:
            alloc = (p.get("current_value") or 0) / current * 100.0
        out.append({**p, "allocation_pct": alloc})
    return {
        "positions": out,
        "invested_value": invested,
        "current_value": current if has_current else None,
        "unrealized_pnl": pnl,
        "pnl_pct": pct_change(current, invested) if has_current else None,
    }
