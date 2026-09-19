"""Local technical indicators, calculated ONLY from verified history.

CALCULATED FROM: backend OHLC history (Yahoo/Stooq/TwelveData/AlphaVantage)
Results are labelled CALCULATED with period + timestamp by callers.
Pure functions, unit-tested against published reference vectors.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any


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


def sma_series(values: Sequence[float | None], window: int) -> list[float | None]:
    """Full SMA series (None until window fills or on gaps)."""
    vals = _floats(values)
    out: list[float | None] = []
    for i in range(len(vals)):
        if i + 1 < window:
            out.append(None)
            continue
        window_vals = vals[i + 1 - window : i + 1]
        if any(v is None for v in window_vals):
            out.append(None)
            continue
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
        out.append(total / window if ok else None)
    return out


def sma_slope(
    values: Sequence[float | None], window: int, lookback: int = 20
) -> float | None:
    """Slope of the SMA line over `lookback` bars, in % of its level.

    Positive = rising average (uptrend pressure), negative = falling.
    """
    s = sma_series(values, window)
    valid = [(i, v) for i, v in enumerate(s) if v is not None]
    if len(valid) < lookback + 1 or lookback <= 0:
        return None
    (_, old), (_, new) = valid[-lookback - 1], valid[-1]
    if old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def _hh_ll(closes: list[float], lookback: int) -> tuple[float | None, float | None]:
    if len(closes) < lookback or lookback <= 0:
        return None, None
    window = closes[-lookback:]
    return max(window), min(window)


def phase(
    closes: Sequence[float | None],
    highs: Sequence[float | None] | None = None,
    lows: Sequence[float | None] | None = None,
) -> dict:
    """Stan Weinstein stage classification (documented rules).

    Phase 2 (advancing): price above rising 150-day and 200-day averages,
    50-day above 150-day and 200-day, price within 25% above the 200-day
    average and no closer than 3% below it, 200-day average itself rising.
    Phase 4 (declining): mirror image below falling averages.
    Phase 3/1: transitional/flat. UNKNOWN when fewer than 200 valid
    closes exist. Descriptive only — never a forecast.
    """
    vals = [v for v in _floats(closes) if v is not None]
    method = (
        "Weinstein stage rules on 50/150/200-day SMAs: "
        "Phase 2 = price>SMA150>SMA200 with rising slopes and price "
        "within +25%/-3% of SMA200; Phase 4 = mirror below falling "
        "averages; else transitional."
    )
    if len(vals) < 200:
        return {
            "phase": "UNKNOWN",
            "reason": "INSUFFICIENT_DATA (<200 closes)",
            "method": method,
            "checks": {},
        }
    price = vals[-1]
    s50 = sum(vals[-50:]) / 50
    s150 = sum(vals[-150:]) / 150
    s200 = sum(vals[-200:]) / 200
    slope150 = sma_slope(vals, 150) or 0.0
    slope200 = sma_slope(vals, 200) or 0.0
    above150 = price > s150
    above200 = price > s200
    s50_above = s50 > s150 and s50 > s200
    s150_above200 = s150 > s200
    near200 = (price - s200) / s200 * 100.0 if s200 else None
    checks = {
        "price_above_150_sma": above150,
        "price_above_200_sma": above200,
        "sma50_above_150_and_200": s50_above,
        "sma150_above_sma200": s150_above200,
        "sma150_slope_pct": round(slope150, 2),
        "sma200_slope_pct": round(slope200, 2),
        "distance_to_200_sma_pct": round(near200, 2) if near200 is not None else None,
    }
    rising = slope150 > 0 and slope200 > 0
    falling = slope150 < 0 and slope200 < 0
    if (
        above150
        and above200
        and s50_above
        and s150_above200
        and rising
        and near200 is not None
        and -3.0 <= near200 <= 25.0
    ):
        phase_name = "Phase 2"
    elif (
        not above150
        and not above200
        and not s50_above
        and not s150_above200
        and falling
    ):
        phase_name = "Phase 4"
    elif falling or (not above200 and slope200 <= 0):
        phase_name = "Phase 3"
    else:
        phase_name = "Phase 1"
    return {
        "phase": phase_name,
        "reason": "rules evaluated on latest bar",
        "method": method,
        "checks": checks,
    }


def relative_strength(
    closes: Sequence[float | None],
    bench_closes: Sequence[float | None] | None,
    bench_symbol: str = "",
    lookback: int = 63,
) -> dict:
    """Stock-vs-benchmark relative strength over `lookback` bars.

    RS = stock % return minus benchmark % return (percentage points).
    Also reports the RS trend (slope of cumulative RS line). Benchmark
    is caller-configured (e.g. NIFTY 50 for NSE, S&P 500 for US).
    """
    out: dict = {
        "benchmark": bench_symbol or None,
        "lookback_bars": lookback,
        "stock_return_pct": None,
        "benchmark_return_pct": None,
        "rs_pp": None,
        "rs_trend": None,
        "status": "INSUFFICIENT_DATA",
    }
    if not bench_closes:
        out["status"] = "NO_BENCHMARK"
        return out
    a = [v for v in _floats(closes) if v is not None]
    b = [v for v in _floats(bench_closes) if v is not None]
    n = min(len(a), len(b))
    if n <= lookback or lookback <= 0:
        return out
    a, b = a[-n:], b[-n:]
    if a[-1 - lookback] == 0 or b[-1 - lookback] == 0:
        return out
    ra = (a[-1] - a[-1 - lookback]) / abs(a[-1 - lookback]) * 100.0
    rb = (b[-1] - b[-1 - lookback]) / abs(b[-1 - lookback]) * 100.0
    cum = 0.0
    pts = []
    for i in range(1, n):
        if a[i - 1] > 0 and b[i - 1] > 0 and a[i] > 0 and b[i] > 0:
            cum += math.log(a[i] / a[i - 1]) - math.log(b[i] / b[i - 1])
        pts.append(cum)
    trend = pts[-1] - pts[-1 - lookback] if len(pts) >= lookback + 1 else None
    out.update(
        stock_return_pct=round(ra, 2),
        benchmark_return_pct=round(rb, 2),
        rs_pp=round(ra - rb, 2),
        rs_trend=round(trend, 4) if trend is not None else None,
        status="OK",
    )
    return out


def vcp(
    closes: Sequence[float | None],
    highs: Sequence[float | None] | None = None,
    lows: Sequence[float | None] | None = None,
    volumes: Sequence[float | None] | None = None,
) -> dict:
    """Volatility Contraction Pattern screen (documented Minervini-style
    characteristics): successive pullbacks of shrinking depth over a base
    of up to 150 bars, ideally with declining volume. Returns descriptive
    measurements — detected/not-detected plus quality diagnostics.
    INSUFFICIENT_DATA when fewer than 60 closes exist."""
    vals = [v for v in _floats(closes) if v is not None]
    method = (
        "Swing highs/lows over trailing 150 bars; contractions = "
        "peak-to-trough declines; contraction count, shrinking depth, "
        "base length, volume trend must all be measurable."
    )
    if len(vals) < 60:
        return {"status": "INSUFFICIENT_DATA", "detected": None, "method": method}
    window = vals[-150:]
    swings: list[tuple[int, float]] = []
    for i in range(3, len(window) - 3):
        w = window[i]
        neighbors = [window[j] for j in range(i - 3, i + 4) if j != i]
        if w is not None and all(
            w >= (x if x is not None else -math.inf) for x in neighbors
        ):
            swings.append((i, w))
    contractions = []
    for k in range(1, len(swings)):
        pk = swings[k - 1][1]
        seg = [v for v in window[swings[k - 1][0] : swings[k][0] + 1] if v is not None]
        if not seg or not pk:
            continue
        contractions.append(round((pk - min(seg)) / pk * 100.0, 2))
    shrinking = (
        all(
            contractions[i] <= contractions[i - 1] * 1.05
            for i in range(1, len(contractions))
        )
        if len(contractions) >= 2
        else None
    )
    vol_note = None
    if volumes is not None:
        vv = [v for v in _floats(volumes[-60:]) if v is not None]
        if len(vv) >= 20:
            first = sum(vv[:10]) / 10
            last = sum(vv[-10:]) / 10
            vol_note = round((last - first) / first * 100.0, 1) if first else None
    detected = (
        len(contractions) >= 2 and bool(shrinking) and (contractions[0] or 0) <= 35.0
    )
    return {
        "status": "OK",
        "detected": detected,
        "method": method,
        "contraction_count": len(contractions),
        "contraction_depths_pct": contractions[:6],
        "shrinking": shrinking,
        "base_bars": min(150, len(vals)),
        "volume_change_pct": vol_note,
        "quality": (
            "constructive"
            if detected and (vol_note or 0) < 0
            else ("mixed" if detected else "absent")
        ),
    }


def breakout(
    closes: Sequence[float | None],
    highs: Sequence[float | None] | None = None,
    volumes: Sequence[float | None] | None = None,
    lookback: int = 252,
) -> dict:
    """Breakout state vs the trailing `lookback`-bar high (excl. today).

    Reports reference level, distance, volume confirmation (today vs
    20-day median) and status. Descriptive, never a recommendation.
    """
    vals = [v for v in _floats(closes) if v is not None]
    if len(vals) < 22:
        return {"status": "INSUFFICIENT_DATA"}
    ref = max(vals[-(lookback + 1) : -1]) if len(vals) > lookback else max(vals[:-1])
    price = vals[-1]
    dist = (price - ref) / ref * 100.0 if ref else None
    vol_conf = None
    if volumes is not None:
        vv = [v for v in _floats(volumes) if v is not None]
        if len(vv) >= 21 and vv[-1] is not None:
            med = sorted(vv[-21:-1])[10]
            vol_conf = round(vv[-1] / med, 2) if med else None
    if dist is None:
        status = "INSUFFICIENT_DATA"
    elif dist > 0.5:
        status = "ABOVE_LEVEL"
    elif dist >= -1.0:
        status = "AT_LEVEL"
    else:
        status = "BELOW_LEVEL"
    return {
        "status": status,
        "reference_level": ref,
        "lookback_bars": lookback,
        "price": price,
        "distance_pct": round(dist, 2) if dist is not None else None,
        "volume_vs_median": vol_conf,
        "volume_confirmed": vol_conf is not None and vol_conf >= 1.5,
    }


def trend_template(
    closes: Sequence[float | None],
    bench_closes: Sequence[float | None] | None = None,
    bench_symbol: str = "",
) -> dict:
    """Weinstein/Minervini-style trend checklist. Each condition returns
    pass/fail/unknown independently — failed criteria are never hidden."""
    vals = [v for v in _floats(closes) if v is not None]
    out: dict = {"method": "8-point trend checklist (documented thresholds)"}

    def verdict(ok: bool | None) -> str:
        return "pass" if ok is True else ("fail" if ok is False else "unknown")

    if len(vals) < 200:
        out["status"] = "INSUFFICIENT_DATA"
        out["conditions"] = {}
        return out
    price = vals[-1]
    s50 = sum(vals[-50:]) / 50
    s150 = sum(vals[-150:]) / 150
    s200 = sum(vals[-200:]) / 200
    sl50 = sma_slope(vals, 50) or 0.0
    sl150 = sma_slope(vals, 150) or 0.0
    sl200 = sma_slope(vals, 200) or 0.0
    span = vals[-252:] if len(vals) >= 252 else vals
    hi, lo = max(span), min(span)
    pos = (price - lo) / (hi - lo) * 100.0 if hi != lo else None
    conds: dict[str, bool | None] = {
        "price_above_150_sma": price > s150,
        "price_above_200_sma": price > s200,
        "sma50_above_150_and_200": s50 > s150 and s50 > s200,
        "sma150_above_sma200": s150 > s200,
        "sma200_rising": sl200 > 0,
        "sma50_rising": sl50 > 0,
        "above_52w_low_30pct": pos is not None and pos >= 30.0,
        "within_25pct_of_high": pos is not None and pos >= 75.0,
    }
    rs = relative_strength(vals, bench_closes, bench_symbol)
    conds["rs_positive"] = (
        (rs.get("rs_pp") or 0) > 0 if rs.get("status") == "OK" else None
    )
    out["conditions"] = {k: verdict(v) for k, v in conds.items()}
    out["measurements"] = {
        "price": price,
        "sma50": round(s50, 2),
        "sma150": round(s150, 2),
        "sma200": round(s200, 2),
        "sma50_slope_pct": round(sl50, 2),
        "sma150_slope_pct": round(sl150, 2),
        "sma200_slope_pct": round(sl200, 2),
        "position_in_52w_range_pct": round(pos, 1) if pos is not None else None,
        "relative_strength": rs,
    }
    out["passed"] = sum(1 for v in out["conditions"].values() if v == "pass")
    out["total"] = len(out["conditions"])
    return out


def breadth(universe: dict[str, Sequence[float | None]]) -> dict:
    """Market breadth over an EXPLICIT universe {symbol: closes}.

    Reports share in Phase 2 / Phase 4 plus advancers/decliners on the
    last bar. Universe identity, timestamp and n are always attached —
    never presented as the whole market unless it is.
    """
    from datetime import datetime, timezone

    phase2 = phase4 = adv = dec = unch = scored = 0
    per_symbol: dict[str, str] = {}
    for sym, closes in universe.items():
        vals = [v for v in _floats(closes) if v is not None]
        if len(vals) < 200:
            per_symbol[sym] = "INSUFFICIENT_DATA"
            continue
        scored += 1
        ph = phase(vals)["phase"]
        per_symbol[sym] = ph
        if ph == "Phase 2":
            phase2 += 1
        elif ph == "Phase 4":
            phase4 += 1
        if len(vals) >= 2:
            if vals[-1] > vals[-2]:
                adv += 1
            elif vals[-1] < vals[-2]:
                dec += 1
            else:
                unch += 1
    denom = scored or 1
    return {
        "universe_size": len(universe),
        "scored": scored,
        "phase2_pct": round(phase2 / denom * 100, 1),
        "phase4_pct": round(phase4 / denom * 100, 1),
        "advancers": adv,
        "decliners": dec,
        "unchanged": unch,
        "per_symbol": per_symbol,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def market_regime(
    bench_closes: Sequence[float | None],
    bench_breadth: dict | None = None,
) -> dict:
    """Transparent regime gauge: benchmark vs its 200-day average plus
    optional breadth confirmation. RISK_ON / RISK_OFF / MIXED / UNKNOWN
    with all measurements exposed — no predictive claim."""
    vals = [v for v in _floats(bench_closes) if v is not None]
    if len(vals) < 200:
        return {
            "status": "UNKNOWN",
            "reason": "INSUFFICIENT_DATA (<200 bars)",
            "measurements": {},
        }
    price = vals[-1]
    s200 = sum(vals[-200:]) / 200
    slope = sma_slope(vals, 200) or 0.0
    above = price > s200
    measurements: dict = {
        "price": price,
        "sma200": round(s200, 2),
        "distance_pct": round((price - s200) / s200 * 100, 2),
        "sma200_slope_pct": round(slope, 2),
    }
    breadth_vote: bool | None = None
    if bench_breadth:
        p2 = bench_breadth.get("phase2_pct")
        p4 = bench_breadth.get("phase4_pct")
        if p2 is not None and p4 is not None:
            measurements["phase2_pct"] = p2
            measurements["phase4_pct"] = p4
            breadth_vote = True if p2 >= 50 else (False if p4 >= 50 else None)
    # Base gauge: price vs 200-day average and its slope. Breadth can
    # only downgrade a directional call to MIXED, never invent one.
    if above and slope > 0:
        base = "RISK_ON"
    elif not above and slope < 0:
        base = "RISK_OFF"
    else:
        base = "MIXED"
    if breadth_vote is False and base == "RISK_ON":
        status = "MIXED"
    elif breadth_vote is True and base == "RISK_OFF":
        status = "MIXED"
    else:
        status = base
    return {"status": status, "measurements": measurements}


def risk_reward(
    price: float | None,
    atr_value: float | None,
    resistance: float | None = None,
) -> dict:
    """Technical reference levels (NOT investment advice).

    stop = price - 2xATR, target = resistance. A target requires a real
    level — never an invented one. INSUFFICIENT_DATA unless price, ATR
    and resistance all exist.
    """
    if price is None or atr_value is None or resistance is None:
        return {
            "status": "INSUFFICIENT_DATA",
            "label": "TECHNICAL REFERENCE (not investment advice)",
        }
    stop = price - 2 * atr_value
    risk = (price - stop) / price * 100.0 if price else None
    reward = (resistance - price) / price * 100.0 if price else None
    ratio = None
    if reward is not None and risk:
        ratio = reward / risk
    return {
        "status": "OK",
        "label": "TECHNICAL REFERENCE (not investment advice)",
        "reference_entry": round(price, 2),
        "technical_stop": round(stop, 2),
        "risk_pct": round(risk, 2) if risk is not None else None,
        "reference_target": round(resistance, 2),
        "reward_pct": round(reward, 2) if reward is not None else None,
        "risk_reward_ratio": round(ratio, 2) if ratio is not None else None,
    }


def score_snapshot(bundle: dict) -> dict:
    """Transparent composite scoring. Every component shows value,
    maximum and missing inputs. UNKNOWN when inputs are insufficient.
    Labels are descriptive (structure/quality/momentum), never buy/sell.
    """

    def comp(value: Any, maximum: float, label: str) -> dict:
        if value is None:
            return {
                "label": label,
                "value": None,
                "max": maximum,
                "state": "UNKNOWN",
                "note": "missing input",
            }
        v = max(0.0, min(float(maximum), float(value)))
        pct = v / maximum if maximum else 0
        state = "strong" if pct >= 0.7 else "mixed" if pct >= 0.4 else "weak"
        return {
            "label": label,
            "value": round(v, 2),
            "max": maximum,
            "state": state,
            "note": None,
        }

    parts = bundle.get("components", {}) if isinstance(bundle, dict) else {}
    out = {}
    for k, v in parts.items():
        if isinstance(v, dict):
            out[k] = comp(v.get("value"), v.get("max", 10), k.replace("_", " "))
        else:
            out[k] = comp(v, 10, k.replace("_", " "))
    known = [c for c in out.values() if c["state"] != "UNKNOWN"]
    total = sum(c["value"] for c in known)
    maximum = sum(c["max"] for c in known)
    if not known:
        overall = "UNKNOWN / INSUFFICIENT_DATA"
    else:
        pct = total / maximum if maximum else 0
        overall = (
            "Strong Technical Structure"
            if pct >= 0.7
            else "Mixed Technical Structure"
            if pct >= 0.4
            else "Weak Technical Structure"
        )
    return {
        "components": out,
        "total": round(total, 2),
        "maximum": maximum,
        "overall": overall,
    }


def fundamental_trends(reports: list[dict]) -> dict:
    """Growth/margin trends across fiscal reports (newest first).

    Each report needs aligned period labels in `_period`; mixed annual
    and quarterly rows return NOT_COMPARABLE. Never mixes periods.
    """

    def gval(rep: dict, keys: list[str]) -> float | None:
        for k in keys:
            v = rep.get(k)
            if v in (None, "", "-", "None"):
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    def growth(rows: list[float | None]) -> float | None:
        if len(rows) < 2 or rows[0] is None or rows[1] is None or rows[1] == 0:
            return None
        return (rows[0] - rows[1]) / abs(rows[1]) * 100.0

    if len(reports) < 2:
        return {"status": "INSUFFICIENT_DATA"}
    periods = {r.get("_period") for r in reports[:3]}
    periods.discard(None)
    if len(periods) > 1:
        return {
            "status": "NOT_COMPARABLE",
            "reason": "mixed fiscal periods in input",
        }
    rev = [
        gval(r, ["totalRevenue", "revenue", "revenues", "sales"]) for r in reports[:3]
    ]
    ni = [gval(r, ["netIncome", "net_income", "netEarnings"]) for r in reports[:3]]
    out: dict = {
        "status": "OK",
        "period": reports[0].get("_period") or reports[0].get("fiscalDateEnding"),
    }
    out["revenue_growth_pct"] = growth(rev)
    out["profit_growth_pct"] = growth(ni)
    if rev[0] and ni[0]:
        out["net_margin_pct"] = round(ni[0] / abs(rev[0]) * 100.0, 2)
    else:
        out["net_margin_pct"] = None
    eps = [gval(r, ["eps", "EPS", "dilutedEPS"]) for r in reports[:3]]
    out["eps_growth_pct"] = growth(eps)
    return out
