"""Clean research synthesis: user-facing report content, never raw internals.

Two paths:
- LLM-backed: role texts are sanitized (no None/null/undefined/NaN tokens,
  no evidence-dump artifacts) and paired with structured observations.
- Fallback (no LLM): NO agent text at all. The report is built from verified
  facts only: analyst-style executive summary template, structured metric
  observations with source + period, bull/bear points derived from facts,
  and explicit data gaps. It must read like a research desk note, never a log.
"""

from __future__ import annotations

import re

_TOKEN_FIX = re.compile(r"\b(None|null|undefined|NaN|nan)\b")
_ARTIFACT_FIX = re.compile(r"\b(source|as_of|via)=\S+", re.IGNORECASE)


def sanitize_text(text: str) -> str:
    """Remove developer-style tokens from user-facing prose."""
    if not text:
        return ""
    out = _ARTIFACT_FIX.sub("", text)
    out = _TOKEN_FIX.sub("not available", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _fmt_money(value, currency: str | None) -> str | None:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    a = abs(n)
    if currency == "INR":
        if a >= 1e12:
            return f"INR {(n / 1e12):.2f} L Cr"
        if a >= 1e7:
            return f"INR {(n / 1e7):.2f} Cr"
        if a >= 1e5:
            return f"INR {(n / 1e5):.2f} L"
    if a >= 1e12:
        return f"{(n / 1e12):.2f}T"
    if a >= 1e9:
        return f"{(n / 1e9):.2f}B"
    if a >= 1e6:
        return f"{(n / 1e6):.2f}M"
    return f"{n:,.2f}"


def _obs(statement: str, source: str | None, period: str | None) -> dict:
    return {"statement": statement, "source": source or "Terminal", "period": period}


def _leg_source(legs: dict, name: str) -> str | None:
    leg = legs.get(name) or {}
    return leg.get("source")


def build_fallback_report(symbol: str, legs: dict, facts: dict, wanted: list[str]) -> dict:
    """Structured, evidence-only report sections (no LLM prose)."""
    ccy = facts.get("currency")
    price = facts.get("price")
    chg = facts.get("change_pct")
    name = facts.get("company_name") or symbol

    # -- executive summary (template, facts only) --
    price_bit = f"trading at {_fmt_money(price, ccy)} ({chg:+.2f}%)" if price is not None and chg is not None else (
        f"trading at {_fmt_money(price, ccy)}" if price is not None else "with no verified quote available")
    fund_bits: list[str] = []
    reps = facts.get("income_reports") or []
    if reps and reps[0].get("revenue") is not None:
        fund_bits.append(f"revenue of {_fmt_money(reps[0]['revenue'], ccy)} in {reps[0].get('period') or 'the latest period'}")
    if facts.get("revenue_yoy_pct") is not None:
        fund_bits.append(f"revenue {'up' if facts['revenue_yoy_pct'] >= 0 else 'down'} {abs(facts['revenue_yoy_pct']):.1f}% year on year")
    if facts.get("pe") is not None:
        fund_bits.append(f"a reported P/E of {facts['pe']:.1f}")
    fund_bit = ("Fundamental data indicates " + ", ".join(fund_bits) + ".") if fund_bits else "Verified fundamental data is limited (see Data gaps)."
    news_items = facts.get("news") or []
    if news_items:
        news_bit = f"Recent company news includes {len(news_items)} item(s), led by {news_items[0].get('source') or 'a wire source'}."
    else:
        news_bit = "No verified recent news items were returned."
    gaps = _data_gap_notes(legs)
    gap_bit = ("Key uncertainties: " + "; ".join(g.lower() for g in gaps[:2]) + ".") if gaps else "Coverage across quote, fundamentals and technicals looks complete."
    snapshot = (
        f"{name} ({symbol}) is currently {price_bit}. {fund_bit} {news_bit} {gap_bit}"
    )

    sections: dict[str, dict] = {}
    # -- fundamentals observations --
    fund_obs: list[dict] = []
    if reps:
        r0 = reps[0]
        per = r0.get("period")
        src = _leg_source(legs, "income_annual") or "Terminal"
        if r0.get("revenue") is not None:
            fund_obs.append(_obs(f"Revenue {_fmt_money(r0['revenue'], ccy)} in {per or 'latest period'}", src, per))
        if r0.get("net_income") is not None:
            fund_obs.append(_obs(f"Net profit {_fmt_money(r0['net_income'], ccy)}", src, per))
        if r0.get("eps") is not None:
            fund_obs.append(_obs(f"EPS {r0['eps']}", src, per))
        for key, label in (("revenue_yoy_pct", "Revenue"), ("net_income_yoy_pct", "Net profit"), ("eps_yoy_pct", "EPS")):
            if facts.get(key) is not None:
                direction = "grew" if facts[key] >= 0 else "declined"
                fund_obs.append(_obs(f"{label} {direction} {abs(facts[key]):.1f}% year on year", src, per))
    sections["fundamentals"] = {"observations": fund_obs[:5], "metrics": _metric_list(facts, ccy, ("revenue", "net_income", "eps"))}

    # -- valuation --
    val_obs: list[dict] = []
    vsrc = _leg_source(legs, "valuation") or "Terminal"
    for key, label, fmt in (("pe", "P/E", "{:.1f}x"), ("pb", "P/B", "{:.1f}x"),
                            ("eps", "EPS", "{}"), ("dividend_yield", "Dividend yield", "{:.2f}%"),
                            ("market_cap", "Market cap", None), ("beta", "Beta", "{:.2f}")):
        if facts.get(key) is not None:
            disp = _fmt_money(facts[key], ccy) if fmt is None else fmt.format(facts[key])
            val_obs.append(_obs(f"{label} {disp} (reported)", vsrc, "TTM"))
    sections["valuation"] = {"observations": val_obs[:5], "metrics": _metric_list(facts, ccy, ("pe", "pb", "eps", "dividend_yield", "market_cap", "beta"))}

    # -- technicals --
    tech_obs: list[dict] = []
    tsrc = "Terminal calculated analytics"
    phase = (facts.get("tech_phase") or {})
    if isinstance(phase, dict) and phase.get("phase"):
        tech_obs.append(_obs(f"Weinstein phase: {phase['phase']}", tsrc, None))
    rs = facts.get("tech_relative_strength") or {}
    if isinstance(rs, dict) and (rs.get("verdict") or rs.get("rs_pp") is not None):
        bit = rs.get("verdict") or f"{rs.get('rs_pp'):+.1f} pp vs {rs.get('benchmark') or 'benchmark'}"
        tech_obs.append(_obs(f"Relative strength: {bit}", tsrc, None))
    vcp = facts.get("tech_vcp") or {}
    if isinstance(vcp, dict) and vcp.get("detected") is not None:
        tech_obs.append(_obs(f"VCP pattern: {'detected' if vcp['detected'] else 'not detected'}", tsrc, None))
    bo = facts.get("tech_breakout") or {}
    if isinstance(bo, dict) and bo.get("status"):
        tech_obs.append(_obs(f"Breakout status: {bo['status']}", tsrc, None))
    tt = facts.get("tech_trend_template") or {}
    if isinstance(tt, dict) and tt.get("passed") is not None:
        tech_obs.append(_obs(f"Trend template {tt['passed']}/{tt.get('total')}", tsrc, None))
    sections["technical"] = {"observations": tech_obs[:5], "metrics": []}

    # -- news --
    news_obs = [_obs(n.get("title") or "Untitled", n.get("source"), n.get("published_at")) for n in news_items[:5]]
    sections["news"] = {"observations": news_obs, "metrics": []}

    # -- bull / bear (evidence-derived, balanced) --
    bull: list[dict] = []
    bear: list[dict] = []
    if facts.get("revenue_yoy_pct") is not None:
        (bull if facts["revenue_yoy_pct"] >= 0 else bear).append(
            _obs(f"Revenue {'growth' if facts['revenue_yoy_pct'] >= 0 else 'decline'} of {abs(facts['revenue_yoy_pct']):.1f}% YoY",
                 _leg_source(legs, "income_annual"), (reps[0].get("period") if reps else None)))
    if facts.get("net_income_yoy_pct") is not None:
        (bull if facts["net_income_yoy_pct"] >= 0 else bear).append(
            _obs(f"Net profit {'growth' if facts['net_income_yoy_pct'] >= 0 else 'decline'} of {abs(facts['net_income_yoy_pct']):.1f}% YoY",
                 _leg_source(legs, "income_annual"), (reps[0].get("period") if reps else None)))
    if chg is not None:
        (bull if chg >= 0 else bear).append(_obs(f"Session move {chg:+.2f}%", _leg_source(legs, "quote"), None))
    if isinstance(rs, dict) and rs.get("rs_pp") is not None:
        (bull if rs["rs_pp"] >= 0 else bear).append(_obs(f"Relative strength {rs['rs_pp']:+.1f} pp vs {rs.get('benchmark') or 'benchmark'}", tsrc, None))
    if news_items:
        bull.append(_obs(f"{len(news_items)} recent news item(s) to review for catalysts", "News feeds", None))
    if facts.get("pe") is not None and facts["pe"] >= 30:
        bear.append(_obs(f"Elevated reported P/E of {facts['pe']:.1f}x leaves little room for disappointment", vsrc, "TTM"))
    if not bull:
        bull.append(_obs("Insufficient verified evidence for a positive case right now", "Terminal", None))
    if not bear:
        bear.append(_obs("Insufficient verified evidence for a negative case right now", "Terminal", None))
    sections["bull"] = {"observations": bull[:4], "metrics": []}
    sections["bear"] = {"observations": bear[:4], "metrics": []}

    # -- risks --
    risks: list[dict] = []
    if facts.get("pe") is not None and facts["pe"] >= 30:
        risks.append(_obs("Valuation risk: elevated earnings multiple", vsrc, "TTM"))
    if facts.get("revenue_yoy_pct") is not None and facts["revenue_yoy_pct"] < 0:
        risks.append(_obs("Business risk: revenue contraction year on year", _leg_source(legs, "income_annual"), None))
    if news_items:
        risks.append(_obs("Event risk: monitor recent headlines for developing items", "News feeds", None))
    risks.append(_obs("Market risk: broad-market moves affect this security", tsrc, None))
    sections["risk"] = {"observations": risks[:5], "metrics": []}

    conclusion = (
        f"Evidence supports a {'constructive' if (facts.get('revenue_yoy_pct') or 0) >= 0 else 'cautious'} read on fundamentals; "
        f"technical structure is {(phase.get('phase') or 'unavailable') if isinstance(phase, dict) else 'unavailable'}. "
        f"Conflicting or missing items: {('; '.join(g.lower() for g in gaps[:2])) if gaps else 'none material'}. "
        "No directional recommendation is made; the observations above cite their sources."
    )
    return {"snapshot": snapshot, "sections": sections, "conclusion": conclusion}


def _metric_list(facts: dict, ccy: str | None, keys: tuple) -> list[dict]:
    labels = {"revenue": "Revenue", "net_income": "Net profit", "eps": "EPS",
              "pe": "P/E", "pb": "P/B", "dividend_yield": "Dividend yield",
              "market_cap": "Market cap", "beta": "Beta"}
    out = []
    for key in keys:
        val = facts.get(key)
        if val is None:
            out.append({"label": labels.get(key, key), "value": None, "display": None})
        elif key in ("revenue", "net_income", "market_cap"):
            out.append({"label": labels.get(key, key), "value": val, "display": _fmt_money(val, ccy)})
        elif key == "dividend_yield":
            out.append({"label": labels[key], "value": val, "display": f"{val:.2f}%"})
        elif key in ("pe", "pb"):
            out.append({"label": labels[key], "value": val, "display": f"{val:.1f}x"})
        else:
            out.append({"label": labels.get(key, key), "value": val, "display": str(val)})
    return out


def _data_gap_notes(legs: dict) -> list[str]:
    notes = []
    labels = {"estimates": "no verified analyst estimates available",
              "ownership": "ownership breakdown unavailable",
              "earnings": "earnings history unavailable",
              "news": "recent news unavailable",
              "income_annual": "annual statements unavailable",
              "valuation": "valuation multiples unavailable",
              "technicals": "technical analytics unavailable",
              "quote": "live quote unavailable"}
    for name, label in labels.items():
        leg = legs.get(name) or {}
        if leg.get("reason") == "NOT_REQUESTED":
            continue
        if not leg.get("ok"):
            notes.append(label[0].upper() + label[1:])
    return notes
