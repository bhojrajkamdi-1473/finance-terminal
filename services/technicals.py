"""Local technical indicators, calculated ONLY from verified history.

CALCULATED FROM: backend OHLC history (Yahoo/Stooq/TwelveData/AlphaVantage)
Results are labelled CALCULATED with period + timestamp by callers.
Pure functions, unit-tested against published reference vectors.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone


def _floats(values: Sequence[float | None]) -> list[float | None]:
    out: list[float | None] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(None)
    return out


def ema(values: Sequence[float | None], window: int) -> list[float | None]:
    """Exponential moving average (Wilder-style seed = SMA of first window)."""
    vals = _floats(values)
    out: list[float | None] = [None] * len(vals)
    if window <= 0 or len(vals) < window:
        return out
    if any(v is None for v in vals[:window]):
        return out
    k = 2.0 / (window + 1)
    seed = sum(float(v) for v in vals[:window] if v is not None) / window
    out[window - 1] = seed
    prev = seed
    for i in range(window, len(vals)):
        v = vals[i]
        if v is None:
            out[i] = None
            continue
        prev = v * k + prev * (1 - k)
        out[i] = prev
    return out


def sma_last(values: Sequence[float | None], window: int) -> float | None:
    vals = [v for v in _floats(values[-window:]) if v is not None]
    if len(vals) < window or window <= 0:
        return None
    return sum(vals) / window


def rsi(closes: Sequence[float | None], window: int = 14) -> list[float | None]:
    """Wilder's RSI. Reference: Investopedia 14-period example -> 70.46."""
    vals = _floats(closes)
    out: list[float | None] = [None] * len(vals)
    if window <= 0 or len(vals) < window + 1:
        return out
    gains, losses = [], []
    for i in range(1, window + 1):
        cur, prev = vals[i], vals[i - 1]
        if cur is None or prev is None:
            return out
        delta = cur - prev
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    out[window] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(window + 1, len(vals)):
        cur, prev = vals[i], vals[i - 1]
        if cur is None or prev is None:
            out[i] = None
            continue
        delta = cur - prev
        avg_gain = (avg_gain * (window - 1) + max(delta, 0.0)) / window
        avg_loss = (avg_loss * (window - 1) + max(-delta, 0.0)) / window
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def macd(
    closes: Sequence[float | None],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, list[float | None]]:
    """MACD line, signal line, histogram (series aligned to input)."""
    fast_e = ema(closes, fast)
    slow_e = ema(closes, slow)
    line: list[float | None] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_e, slow_e)
    ]
    # signal = EMA of the macd line over valid values only
    compact = [v for v in line if v is not None]
    sig_compact = ema(compact, signal)
    sig_iter = iter(sig_compact)
    sig: list[float | None] = [next(sig_iter) if v is not None else None for v in line]
    hist = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(line, sig)
    ]
    return {"macd": line, "signal": sig, "histogram": hist}


def atr(
    highs: Sequence[float | None],
    lows: Sequence[float | None],
    closes: Sequence[float | None],
    window: int = 14,
) -> list[float | None]:
    """Wilder's Average True Range."""
    h, low, c = _floats(highs), _floats(lows), _floats(closes)
    n = min(len(h), len(low), len(c))
    out: list[float | None] = [None] * len(c)
    if window <= 0 or n < window + 1:
        return out
    trs: list[float | None] = [None] * n
    for i in range(1, n):
        hi, lo, ci, cim1 = h[i], low[i], c[i], c[i - 1]
        if hi is None or lo is None or ci is None or cim1 is None:
            trs[i] = None
            continue
        trs[i] = max(hi - lo, abs(hi - cim1), abs(lo - cim1))
    seed_vals = trs[1 : window + 1]
    if any(v is None for v in seed_vals):
        return out
    prev = sum(v for v in seed_vals if v is not None) / window
    out[window] = prev
    for i in range(window + 1, n):
        tr = trs[i]
        if tr is None:
            out[i] = None
            continue
        prev = (prev * (window - 1) + tr) / window
        out[i] = prev
    return out


def log_returns(closes: Sequence[float | None]) -> list[float]:
    vals = [v for v in _floats(closes) if v is not None and v > 0]
    return [math.log(vals[i] / vals[i - 1]) for i in range(1, len(vals))]


def volatility_ann(closes: Sequence[float | None], window: int = 20) -> float | None:
    rets = log_returns(closes[-window - 1 :])
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100.0


def period_return(closes: Sequence[float | None], periods: int) -> float | None:
    vals = [v for v in _floats(closes) if v is not None]
    if len(vals) <= periods or periods <= 0 or vals[-1 - periods] == 0:
        return None
    return (vals[-1] - vals[-1 - periods]) / abs(vals[-1 - periods]) * 100.0


def max_drawdown(closes: Sequence[float | None]) -> float | None:
    vals = [v for v in _floats(closes) if v is not None]
    if not vals:
        return None
    peak, worst = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak * 100.0)
    return worst


def beta(asset: Sequence[float | None], bench: Sequence[float | None]) -> float | None:
    """Beta of asset closes vs benchmark closes (overlapping tail)."""
    a = [v for v in _floats(asset) if v is not None]
    b = [v for v in _floats(bench) if v is not None]
    n = min(len(a), len(b))
    if n < 30:
        return None
    a, b = a[-n:], b[-n:]
    ra = [math.log(a[i] / a[i - 1]) for i in range(1, n) if a[i - 1] > 0 and a[i] > 0]
    rb = [math.log(b[i] / b[i - 1]) for i in range(1, n) if b[i - 1] > 0 and b[i] > 0]
    m = min(len(ra), len(rb))
    if m < 29:
        return None
    ra, rb = ra[-m:], rb[-m:]
    ma, mb = sum(ra) / m, sum(rb) / m
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (m - 1)
    var = sum((y - mb) ** 2 for y in rb) / (m - 1)
    if var == 0:
        return None
    return cov / var


def compute_all(
    closes: Sequence[float | None],
    highs: Sequence[float | None] | None = None,
    lows: Sequence[float | None] | None = None,
    bench: Sequence[float | None] | None = None,
    source: str = "backend-history",
) -> dict:
    """Last-value technical snapshot with provenance."""
    r = rsi(closes)
    m = macd(closes)
    out: dict = {
        "sma20": sma_last(closes, 20),
        "sma50": sma_last(closes, 50),
        "sma200": sma_last(closes, 200),
        "rsi14": r[-1] if r else None,
        "macd": m["macd"][-1] if m["macd"] else None,
        "macd_signal": m["signal"][-1] if m["signal"] else None,
        "macd_histogram": m["histogram"][-1] if m["histogram"] else None,
        "atr14": None,
        "volatility_20d_ann_pct": volatility_ann(closes, 20),
        "return_1m_pct": period_return(closes, 21),
        "return_3m_pct": period_return(closes, 63),
        "return_1y_pct": period_return(closes, 252),
        "max_drawdown_pct": max_drawdown(closes),
        "beta_vs_benchmark": beta(closes, bench) if bench else None,
        "periods": len([v for v in closes if v is not None]),
        "calculated_from": source,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }
    if highs is not None and lows is not None:
        a = atr(highs, lows, closes)
        out["atr14"] = a[-1] if a else None
    return out
