"""Canonical ratio engine: the single calculation authority.

Every surface (Overview, Valuation, AI Research) consumes this output —
no divergent formulas. Pure functions, stdlib only.

Input: statement report rows (Alpha Vantage camelCase AND plain-English
/ Indian-API tabular labels both accepted via alias matching) plus
optional market inputs (price, market cap, shares outstanding).

Output per ratio (or absent when required inputs are missing — never
fabricated):
    {"key","label","value","unit","kind":"CALCULATED","formula",
     "inputs":[{"label","value","period","source"}],
     "variant": None | "ending equity approximation" | ...,
     "calculated_at": ISO}

Conventions: margins as %; multiples as x; ratios unitless.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

CALCULATED = "CALCULATED"


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key or "").lower())


# Canonical line item -> alias match list (normalized form matched by
# exact equality OR substring containment, longest-alias-first).
_ALIASES: dict[str, list[str]] = {
    "revenue": ["totalrevenue", "revenue", "revenues", "sales", "totalsales",
                "netrevenue", "netsales", "totalincome", "incomefromoperations",
                "grosssales"],
    "cogs": ["costofrevenue", "cogs", "costofgoodsold", "costofsales",
             "costofgoodssold", "directcosts"],
    "gross_profit": ["grossprofit", "grossincome", "grossmarginamount"],
    "opex": ["operatingexpenses", "totaloperatingexpenses"],
    "rd": ["researchanddevelopment", "rdexpense"],
    "sga": ["sellinggeneralandadministrative", "sgaexpense", "sganda"],
    "ebitda": ["ebitda", "ebitdaannual", "operatingebitda"],
    "ebit": ["ebit", "operatingincome", "operatingprofit", "operatingprofitloss",
             "profitbeforetaxandinterest", "pbit", "operatingearning"],
    "interest_expense": ["interestexpense", "financecosts", "financecost",
                         "interestpaid", "interestandfinancecharges"],
    "pbt": ["incomebeforetax", "profitbeforetax", "pbt", "earningbeforetax",
            "profitbeforetaxandextraordinary", "totalprofitbeforetax"],
    "tax": ["incometaxexpense", "taxexpense", "provisionfortax", "tax",
            "currenttax", "deferredtax"],
    "net_income": ["netincome", "netincomefromcontinuingoperations",
                   "netearnings", "pat", "profitaftertax",
                   "netprofit", "netprofitloss", "profitfortheperiod",
                   "netincometocommonshareholders"],
    "eps": ["dilutedEPS".lower(), "eps", "dilutedearnings", "basiceps",
            "earningpershare", "dilutednormaleps"],
    "total_assets": ["totalassets", "totalasset"],
    "current_assets": ["totalcurrentassets", "currentassets"],
    "cash": ["cashandcashequivalentsatcarryingvalue", "cashandcashequivalents",
             "cashandbankbalances", "cash", "cashonhand"],
    "inventory": ["inventory", "inventories", "stockintrade", "stock"],
    "receivables": ["currentnetreceivables", "receivables", "tradereceivables",
                    "sundrydebtors", "accountsreceivable"],
    "current_liabilities": ["totalcurrentliabilities", "currentliabilities"],
    "payables": ["accountspayable", "tradepayables", "sundrycreditors",
                 "currentaccountspayable"],
    "total_liabilities": ["totalliabilities", "totalliab", "totallib",
                          "totalliability"],
    "total_debt": ["totaldebt", "totalborrowings", "borrowings",
                   "shorttermdebtandcurrentlongtermdebt", "grossdebt"],
    "short_debt": ["shorttermdebt", "shorttermborrowings",
                   "currentdebt", "currentmaturities"],
    "long_debt": ["longtermdebt", "longtermborrowings", "noncurrentdebt"],
    "equity": ["totalshareholderequity", "shareholderequity", "totalequity",
               "equity", "networth", "shareholdersfunds",
               "totalnetworth", "ownerscapital"],
    "retained": ["retainedearnings", "retainedearning"],
    "shares_out": ["commonstocksharesoutstanding", "sharesoutstanding",
                   "weightedaverageshares", "dilutedweightedaverageshares",
                   "noofshares", "outstandingshares", "equityshares"],
    "cfo": ["operatingcashflow", "cashflowfromoperations",
            "cashgeneratedfromoperations", "netcashfromoperatingactivities",
            "cashfromoperations", "cfo"],
    "capex": ["capitalexpenditures", "capex", "purchaseofpropertyplantandequipment",
              "purchaseoffixedassets", "fixedassetspurchased"],
    "dividends_paid": ["dividendpayout", "dividendspaid", "dividend",
                       "dividendpayment", "equitydividend"],
    "dps": ["dividendpershare", "dps", "dividendratepershare"],
    "minority": ["minorityinterest", "noncontrollinginterest"],
}


def _num(value: Any) -> float | None:
    if value in (None, "", "-", "None", "N/A", "NA", "null", "NM"):
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        out = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return out


def _pick(report: dict, item: str) -> tuple[float | None, str | None, str | None]:
    """Best-matching line value + actual report key + period."""
    if not isinstance(report, dict):
        return None, None, None
    period = _period(report)
    normed = {_norm_key(k): k for k in report}
    for alias in _ALIASES.get(item, []):
        if alias in normed:
            return _num(report[normed[alias]]), normed[alias], period
    for alias in sorted(_ALIASES.get(item, []), key=len, reverse=True):
        for nk, orig in normed.items():
            if alias and alias in nk:
                return _num(report[orig]), orig, period
    return None, None, period


def _period(report: dict) -> str | None:
    for k in ("fiscalDateEnding", "date", "period", "fiscalDate", "year", "quarter"):
        v = report.get(k)
        if v:
            return str(v)
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result(key: str, label: str, value: float | None, unit: str,
            formula: str, inputs: list[dict], variant: str | None = None) -> dict | None:
    if value is None:
        return None
    return {
        "key": key, "label": label, "value": round(value, 4), "unit": unit,
        "kind": CALCULATED, "formula": formula, "inputs": inputs,
        "variant": variant, "calculated_at": _now(),
    }


def _inp(label: str, value: float | None, period: str | None, source: str) -> dict:
    return {"label": label, "value": value, "period": period, "source": source}


def compute_all(
    income: list[dict] | None = None,
    balance: list[dict] | None = None,
    cashflow: list[dict] | None = None,
    *,
    price: float | None = None,
    market_cap: float | None = None,
    source: str = "statements",
    currency: str | None = None,
) -> dict[str, dict]:
    """Compute every ratio whose inputs exist. Missing inputs -> absent key."""
    income = [r for r in (income or []) if isinstance(r, dict)]
    balance = [r for r in (balance or []) if isinstance(r, dict)]
    cashflow = [r for r in (cashflow or []) if isinstance(r, dict)]
    out: dict[str, dict] = {}
    cur = income[0] if income else {}
    bal0 = balance[0] if balance else {}
    bal1 = balance[1] if len(balance) > 1 else {}
    cf0 = cashflow[0] if cashflow else {}

    rev, _, rev_p = _pick(cur, "revenue")
    ni, _, ni_p = _pick(cur, "net_income")
    gp, _, _ = _pick(cur, "gross_profit")
    cogs, _, _ = _pick(cur, "cogs")
    if gp is None and rev is not None and cogs is not None:
        gp = rev - cogs
    ebitda, _, eb_p = _pick(cur, "ebitda")
    ebit, _, _ = _pick(cur, "ebit")
    if ebit is None and ebitda is not None:
        ebit = ebitda  # depreciation split unavailable; flagged in variant
        _ebit_approx = True
    else:
        _ebit_approx = False
    interest, _, _ = _pick(cur, "interest_expense")
    eps, _, eps_p = _pick(cur, "eps")
    eq0, _, eq0_p = _pick(bal0, "equity")
    eq1, _, eq1_p = _pick(bal1, "equity")
    ta0, _, _ = _pick(bal0, "total_assets")
    ta1, _, _ = _pick(bal1, "total_assets")
    ca, _, _ = _pick(bal0, "current_assets")
    cash, _, _ = _pick(bal0, "cash")
    inv, _, _ = _pick(bal0, "inventory")
    recv, _, _ = _pick(bal0, "receivables")
    cl, _, _ = _pick(bal0, "current_liabilities")
    debt, _, _ = _pick(bal0, "total_debt")
    if debt is None:
        sd, _, _ = _pick(bal0, "short_debt")
        ld, _, _ = _pick(bal0, "long_debt")
        if sd is not None or ld is not None:
            debt = (sd or 0.0) + (ld or 0.0)
    cfo, _, cfo_p = _pick(cf0, "cfo")
    capex, _, _ = _pick(cf0, "capex")
    dps, _, _ = _pick(cur, "dps")
    divp, _, _ = _pick(cf0, "dividends_paid")
    if divp is not None:
        divp = abs(divp)  # Yahoo signs cash outflows negative; payout uses magnitude
    _ccy = f" ({currency})" if currency else ""

    def put(res: dict | None) -> None:
        if res is not None:
            out[res["key"]] = res

    # -- profitability --
    if ni is not None and (eq0 is not None or eq1 is not None):
        if eq0 is not None and eq1 is not None and (eq0 + eq1) != 0:
            avg, variant = (eq0 + eq1) / 2, None
            formula = "Net Income / Average Equity x 100"
            extra = [_inp(f"Equity {eq1_p or ''}".strip(), eq1, eq1_p, source)]
        elif eq0 is not None and eq0 != 0:
            avg, variant = eq0, "ending equity approximation"
            formula = "Net Income / Ending Equity x 100 (average unavailable)"
            extra = []
        else:
            avg, variant, formula, extra = None, None, "", []
        if avg:
            put(_result("roe", "ROE", ni / avg * 100, "%", formula,
                        [_inp(f"Net Income {ni_p or ''}".strip(), ni, ni_p, source),
                         _inp(f"Equity {eq0_p or ''}".strip(), eq0, eq0_p, source)] + extra,
                        variant))
    if ni is not None and (ta0 is not None or ta1 is not None):
        base = (ta0 + ta1) / 2 if (ta0 is not None and ta1 is not None and (ta0 + ta1) != 0) else ta0
        if base:
            put(_result("roa", "ROA", ni / base * 100, "%", "Net Income / Average Assets x 100",
                        [_inp("Net Income", ni, ni_p, source), _inp("Assets", base, _period(bal0), source)],
                        None if ta1 is not None else "ending assets approximation"))
    if ebit is not None and eq0 is not None and debt is not None and (eq0 + debt) != 0:
        put(_result("roce", "ROCE", ebit / (eq0 + debt) * 100, "%", "EBIT / Capital Employed x 100",
                    [_inp("EBIT", ebit, eb_p, source), _inp("Equity", eq0, eq0_p, source),
                     _inp("Debt", debt, eq0_p, source)],
                    "EBIT approximated from EBITDA" if _ebit_approx else None))
    if gp is not None and rev:
        put(_result("gross_margin", "Gross Margin", gp / rev * 100, "%", "(Revenue - COGS) / Revenue x 100",
                    [_inp("Revenue", rev, rev_p, source), _inp("Gross Profit", gp, rev_p, source)]))
    if ebitda is not None and rev:
        put(_result("ebitda_margin", "EBITDA Margin", ebitda / rev * 100, "%", "EBITDA / Revenue x 100",
                    [_inp("EBITDA", ebitda, eb_p, source), _inp("Revenue", rev, rev_p, source)]))
    if ebit is not None and rev:
        put(_result("op_margin", "Operating Margin", ebit / rev * 100, "%", "EBIT / Revenue x 100",
                    [_inp("EBIT", ebit, eb_p, source), _inp("Revenue", rev, rev_p, source)],
                    "EBIT approximated from EBITDA" if _ebit_approx else None))
    if ni is not None and rev:
        put(_result("net_margin", "Net Margin", ni / rev * 100, "%", "Net Income / Revenue x 100",
                    [_inp("Net Income", ni, ni_p, source), _inp("Revenue", rev, rev_p, source)]))
    # -- liquidity --
    if ca is not None and cl:
        put(_result("current_ratio", "Current Ratio", ca / cl, "x", "Current Assets / Current Liabilities",
                    [_inp("Current Assets", ca, eq0_p, source), _inp("Current Liabilities", cl, eq0_p, source)]))
        quick_base = ca - (inv or 0.0)
        put(_result("quick_ratio", "Quick Ratio", quick_base / cl, "x", "(Current Assets - Inventory) / Current Liabilities",
                    [_inp("Current Assets", ca, eq0_p, source), _inp("Inventory", inv, eq0_p, source),
                     _inp("Current Liabilities", cl, eq0_p, source)],
                    None if inv is not None else "inventory unavailable; quick = current"))
    # -- leverage --
    if debt is not None and eq0:
        put(_result("debt_equity", "Debt / Equity", debt / eq0, "x", "Total Debt / Equity",
                    [_inp("Total Debt", debt, eq0_p, source), _inp("Equity", eq0, eq0_p, source)]))
    if debt is not None and cash is not None and ebitda:
        put(_result("net_debt_ebitda", "Net Debt / EBITDA", (debt - cash) / ebitda, "x", "(Debt - Cash) / EBITDA",
                    [_inp("Debt", debt, eq0_p, source), _inp("Cash", cash, eq0_p, source),
                     _inp("EBITDA", ebitda, eb_p, source)]))
    if ebit is not None and interest:
        put(_result("interest_coverage", "Interest Coverage", ebit / interest, "x", "EBIT / Interest Expense",
                    [_inp("EBIT", ebit, eb_p, source), _inp("Interest Expense", interest, eb_p, source)],
                    "EBIT approximated from EBITDA" if _ebit_approx else None))
    # -- efficiency --
    if rev is not None and (ta0 is not None or ta1 is not None):
        base = (ta0 + ta1) / 2 if (ta0 is not None and ta1 is not None and (ta0 + ta1) != 0) else ta0
        if base:
            put(_result("asset_turnover", "Asset Turnover", rev / base, "x", "Revenue / Average Assets",
                        [_inp("Revenue", rev, rev_p, source), _inp("Assets", base, _period(bal0), source)]))
    if cogs is not None and inv:
        put(_result("inventory_turnover", "Inventory Turnover", cogs / inv, "x", "COGS / Inventory",
                    [_inp("COGS", cogs, rev_p, source), _inp("Inventory", inv, eq0_p, source)]))
    if rev is not None and recv:
        put(_result("receivables_turnover", "Receivables Turnover", rev / recv, "x", "Revenue / Receivables",
                    [_inp("Revenue", rev, rev_p, source), _inp("Receivables", recv, eq0_p, source)]))
    # -- growth (CAGR over available annual reports) --
    def cagr(key: str, label: str, item: str) -> None:
        pts = [(_pick(r, item)[0], _period(r)) for r in income[:5]]
        pts = [(v, p) for v, p in pts if v is not None]
        if len(pts) < 2:
            return
        end, end_p = pts[0]
        start, start_p = pts[-1]
        n = len(pts) - 1
        if start is None or end is None or start <= 0 or end <= 0 or n <= 0:
            return
        val = (end / start) ** (1 / n) - 1
        put(_result(key, label, val * 100, "%", f"({end}/{start})^(1/{n}) - 1 over {n}y",
                    [_inp(f"{label} {end_p or ''}".strip(), end, end_p, source),
                     _inp(f"{label} {start_p or ''}".strip(), start, start_p, source)]))
    cagr("revenue_cagr", "Revenue CAGR", "revenue")
    cagr("ebitda_cagr", "EBITDA CAGR", "ebitda")
    cagr("pat_cagr", "PAT CAGR", "net_income")
    cagr("eps_cagr", "EPS CAGR", "eps")
    # -- cash flow --
    fcf = None
    if cfo is not None and capex is not None:
        fcf = cfo - capex
        put(_result("fcf", "Free Cash Flow", fcf, _ccy.strip() or "value", "CFO - CapEx",
                    [_inp("CFO", cfo, cfo_p, source), _inp("CapEx", capex, cfo_p, source)]))
        if rev:
            put(_result("fcf_margin", "FCF Margin", fcf / rev * 100, "%", "FCF / Revenue x 100",
                        [_inp("FCF", fcf, cfo_p, source), _inp("Revenue", rev, rev_p, source)]))
    if cfo is not None and ni:
        put(_result("cfo_pat", "CFO / PAT", cfo / ni, "x", "Operating Cash Flow / Net Income",
                    [_inp("CFO", cfo, cfo_p, source), _inp("Net Income", ni, ni_p, source)]))
    # -- dividend --
    if dps is not None and price:
        put(_result("div_yield_calc", "Dividend Yield", dps / price * 100, "%", "DPS / Price x 100",
                    [_inp("DPS", dps, eps_p, source), _inp("Price", price, "quote", "quote")]))
    if divp is not None and ni:
        put(_result("payout_ratio", "Payout Ratio", divp / ni * 100, "%", "Dividends Paid / Net Income x 100",
                    [_inp("Dividends Paid", divp, cfo_p, source), _inp("Net Income", ni, ni_p, source)]))
    elif dps is not None and eps:
        put(_result("payout_ratio", "Payout Ratio", dps / eps * 100, "%", "DPS / EPS x 100",
                    [_inp("DPS", dps, eps_p, source), _inp("EPS", eps, eps_p, source)]))
    # -- valuation multiples from market inputs --
    if price and eps:
        put(_result("pe_calc", "P/E", price / eps, "x", "Price / EPS",
                    [_inp("Price", price, "quote", "quote"), _inp("EPS", eps, eps_p, source)]))
    if market_cap and ni:
        put(_result("pe_from_mcap", "P/E (mcap)", market_cap / ni, "x", "Market Cap / Net Income",
                    [_inp("Market Cap", market_cap, "quote", "quote"), _inp("Net Income", ni, ni_p, source)]))
    if market_cap and eq0:
        put(_result("pb_calc", "P/B", market_cap / eq0, "x", "Market Cap / Equity",
                    [_inp("Market Cap", market_cap, "quote", "quote"), _inp("Equity", eq0, eq0_p, source)]))
    if fcf is not None and market_cap:
        put(_result("fcf_yield", "FCF Yield", fcf / market_cap * 100, "%", "Free Cash Flow / Market Cap x 100",
                    [_inp("FCF", fcf, cfo_p, source), _inp("Market Cap", market_cap, "quote", "quote")]))
    return out


def core_keys() -> list[str]:
    """Ratio keys the sheet treats as core coverage."""
    return ["roe", "roa", "roce", "debt_equity", "current_ratio", "net_margin"]
