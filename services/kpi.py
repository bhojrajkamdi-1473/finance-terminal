"""Centralized KPI / analytics engine.

ONE normalization layer: the same KPI has the same value everywhere
(stock page, compare, screener, research). Pages must call this —
never recompute ratios locally.

Rules:
- VALUE EXISTS -> SHOW IT (with source/period/currency/timestamp).
- VALUE CAN BE LEGITIMATELY CALCULATED -> CALCULATE IT (formula shown).
- OTHERWISE -> OMIT IT (the key is absent; never None placeholders,
  never "—", "N/A", "?", "Unavailable").

ROE preference: provider-REPORTED first, else Net Income / Average
Equity x 100 (beginning+ending equity / 2), only when valid.
"""

from __future__ import annotations

from typing import Any


def _num(v: Any) -> float | None:
    if v in (None, "", "-", "None", "N/A", "NA", "null", "nan"):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def omit_absent(d: dict) -> dict:
    """Drop keys whose value is None/placeholder. No empty KPI cards."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            val = v.get("value")
            if (
                _num(val) is None
                and val is not None
                and not isinstance(val, (int, float))
            ):
                # keep non-numeric display values only if truthy string
                if isinstance(val, str) and val.strip():
                    out[k] = v
                continue
            if _num(val) is None:
                continue
            out[k] = v
        elif _num(v) is not None:
            out[k] = v
    return out


def roe_reported_or_calc(
    reported: Any, net_income: Any, equity_begin: Any, equity_end: Any
) -> dict | None:
    """ROE hierarchy: reported wins; else NI / avg equity x 100."""
    r = _num(reported)
    if r is not None:
        return {"value": round(r, 2), "unit": "%", "kind": "REPORTED"}
    ni, eb, ee = _num(net_income), _num(equity_begin), _num(equity_end)
    if ni is None:
        return None
    if eb is not None and ee is not None and (eb + ee) != 0:
        avg = (eb + ee) / 2.0
    elif ee is not None and ee != 0:
        avg = ee
    elif eb is not None and eb != 0:
        avg = eb
    else:
        return None
    if avg == 0:
        return None
    return {
        "value": round(ni / avg * 100.0, 2),
        "unit": "%",
        "kind": "CALCULATED",
        "formula": "Net Income / Average Equity x 100",
    }


def build_kpi_bundle(
    *,
    symbol: str,
    quote: dict | None,
    overview: dict | None,
    computed: dict | None,
    currency: str | None = None,
) -> dict:
    """Merge quote + overview + ratio-engine output into ONE KPI dict.

    Keys follow the terminal KPI vocabulary: market_cap, pe, pb, eps,
    book_value, roe, roce, roa, ev_ebitda, div_yield, debt_equity,
    op_margin, net_margin, revenue_growth, profit_growth, fcf, fcf_yield.
    Absent metrics are OMITTED (no key), never None.
    """
    q = quote or {}
    ov = overview or {}
    co = computed or {}
    ccy = currency or ov.get("Currency") or ov.get("currency") or q.get("currency")

    def rep(*keys):
        for k in keys:
            v = _num(ov.get(k))
            if v is not None:
                return v
        return None

    bundle: dict[str, dict] = {}

    def put(name, value, unit=None, kind="REPORTED", source=None, extra=None):
        if _num(value) is None:
            return
        entry: dict[str, Any] = {"value": value, "kind": kind}
        if unit:
            entry["unit"] = unit
        if source:
            entry["source"] = source
        if ccy and name in ("market_cap", "eps", "book_value", "fcf"):
            entry["currency"] = ccy
        if extra:
            entry.update(extra)
        bundle[name] = entry

    put("market_cap", rep("MarketCapitalization", "market_cap"))
    put("pe", rep("PERatio", "pe"))
    put("pb", rep("PriceToBookRatio", "pb"))
    put("eps", rep("EPS", "eps"))
    put("book_value", rep("BookValue", "book_value"))
    # ROE hierarchy
    roe_rep = rep("ROE", "ReturnOnEquityTTM")
    roe_entry = None
    if roe_rep is not None:
        roe_entry = {"value": roe_rep, "unit": "%", "kind": "REPORTED"}
    elif "roe" in co:
        roe_entry = co["roe"]
    if roe_entry and _num(roe_entry.get("value")) is not None:
        bundle["roe"] = roe_entry
    for k in (
        "roce",
        "roa",
        "op_margin",
        "net_margin",
        "debt_equity",
        "div_yield_calc",
        "fcf",
        "revenue_cagr",
        "pe_calc",
    ):
        if k in co and _num(co[k].get("value")) is not None:
            name = {
                "div_yield_calc": "div_yield",
                "revenue_cagr": "revenue_growth",
                "pe_calc": "pe_calc",
            }.get(k, k)
            bundle[name] = co[k]
    dy = rep("DividendYield", "div_yield")
    if dy is not None and "div_yield" not in bundle:
        put("div_yield", dy, unit="%")
    # 52w + price context live in quote, not KPI bundle
    out = omit_absent(bundle)
    return {"symbol": symbol, "currency": ccy, "kpis": out}


# Field-level superior-provider matrix (authoritative routing table).
# Chosen per field on correctness/authority/freshness/coverage —
# never "one provider wins everywhere".
FIELD_PROVIDERS = {
    "indian_quotes": {
        "primary": "upstox",
        "secondary": "indian-api",
        "why": "Exchange-native snapshot + ISIN-mapped identity; Yahoo cross-check.",
        "fallback": "yahoo",
        "status": "upstox key-gated, else indian-api/yahoo",
    },
    "global_quotes": {
        "primary": "yahoo",
        "secondary": "twelvedata",
        "why": "Yahoo covers global symbols free; TD real-time US per plan.",
        "fallback": "alphavantage",
        "status": "live",
    },
    "history_indian": {
        "primary": "upstox",
        "secondary": "yahoo",
        "why": "Upstox historical-candle V3 depth (2000+); Yahoo breadth for cross-check.",
        "fallback": "indian-api historical_data",
        "status": "upstox key-gated",
    },
    "history_global": {
        "primary": "yahoo",
        "secondary": "stooq",
        "why": "Yahoo range/interval breadth; Stooq US EOD fallback.",
        "fallback": "twelvedata/alphavantage",
        "status": "live",
    },
    "indices": {
        "primary": "yahoo",
        "secondary": "upstox",
        "why": "Yahoo verified index symbols; Upstox NSE_INDEX keys cross-check.",
        "fallback": "none",
        "status": "live",
    },
    "fundamentals": {
        "primary": "yahoo-fundamentals",
        "secondary": "alphavantage",
        "why": "Yahoo timeseries needs no key and covers NSE+global; AV depth when keyed.",
        "fallback": "twelvedata",
        "status": "live",
    },
    "ratios": {
        "primary": "alphavantage",
        "secondary": "upstox",
        "why": "AV overview authority; Upstox key-ratios by ISIN for Indian names.",
        "fallback": "yahoo-fundamentals/indian-api",
        "status": "mixed key-gated",
    },
    "statements": {
        "primary": "yahoo-fundamentals",
        "secondary": "alphavantage",
        "why": "Free timeseries annual+quarterly; AV audited depth when keyed.",
        "fallback": "upstox/indian-api (ISIN-keyed)",
        "status": "live",
    },
    "shareholding": {
        "primary": "upstox",
        "secondary": "indian-api",
        "why": "ISIN-linked shareholding patterns; keyed Indian leg fallback.",
        "fallback": "none",
        "status": "key-gated",
    },
    "actions": {
        "primary": "upstox",
        "secondary": "yahoo-events",
        "why": "ISIN-linked corporate actions; Yahoo chart events free fallback.",
        "fallback": "alphavantage/twelvedata",
        "status": "mixed",
    },
    "news": {
        "primary": "yahoo-rss",
        "secondary": "alphavantage",
        "why": "RSS freshness + entity match; AV sentiment depth.",
        "fallback": "indian-api (keyed)",
        "status": "live",
    },
    "ipo": {
        "primary": "ipo-guru",
        "secondary": "alphavantage",
        "why": "IPO Guru lifecycle/subscription; AV calendar cross-check. GMP separate.",
        "fallback": "none",
        "status": "key-gated",
    },
    "gmp": {
        "primary": "ipo-guru",
        "secondary": "none",
        "why": "GMP only from dedicated GMP feed; never synthesised.",
        "fallback": "none",
        "status": "key-gated",
    },
    "technicals": {
        "primary": "terminal-calc",
        "secondary": "none",
        "why": "Calculated locally from verified history; never provider-reported.",
        "fallback": "none",
        "status": "live",
    },
}
