"""Evidence-context construction (stdlib only).

Builds a compact, provenance-stamped bundle the LLM must ground every
claim in. Missing data stays missing: unavailable legs become explicit
{"_unavailable": reason} markers, never synthesised values.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _num(value: Any) -> float | None:
    if value in (None, "-", "None", "N/A", ""):
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reports(env: dict, limit: int = 3) -> list[dict]:
    data = env.get("data") or {}
    reps = data.get("reports") or []
    return reps[:limit]


def build_context(
    symbol: str,
    adapter: Any,
    sections: list[str],
    portfolio: dict | None = None,
    news_limit: int = 8,
) -> dict:
    symbol = (symbol or "").strip().upper()
    legs: dict[str, dict] = {}
    legs["quote"] = adapter.get_quote(symbol)
    legs["profile"] = adapter.get_fundamentals(symbol)
    legs["valuation"] = adapter.get_valuation(symbol)
    legs["technicals"] = adapter.get_technicals(symbol)
    if any(s in sections for s in ("fundamentals", "valuation", "bull", "bear", "risk", "conclusion")):
        legs["income_annual"] = adapter.get_financials(symbol, "income", "annual")
        legs["balance_annual"] = adapter.get_financials(symbol, "balance", "annual")
        legs["cashflow_annual"] = adapter.get_financials(symbol, "cashflow", "annual")
        legs["earnings"] = adapter.get_earnings(symbol)
        legs["estimates"] = adapter.get_estimates(symbol)
    else:
        legs["income_annual"] = {"ok": False, "reason": "NOT_REQUESTED"}
        legs["balance_annual"] = {"ok": False, "reason": "NOT_REQUESTED"}
        legs["cashflow_annual"] = {"ok": False, "reason": "NOT_REQUESTED"}
        legs["earnings"] = {"ok": False, "reason": "NOT_REQUESTED"}
        legs["estimates"] = {"ok": False, "reason": "NOT_REQUESTED"}
    if any(s in sections for s in ("news", "bull", "bear", "risk", "conclusion", "catalysts")):
        legs["news"] = adapter.get_news(symbol, news_limit)
        legs["actions"] = adapter.get_actions(symbol)
    else:
        legs["news"] = {"ok": False, "reason": "NOT_REQUESTED"}
        legs["actions"] = {"ok": False, "reason": "NOT_REQUESTED"}
    if "risk" in sections or "conclusion" in sections or "unknowns" in sections:
        legs["ownership"] = adapter.get_ownership(symbol)
    else:
        legs["ownership"] = {"ok": False, "reason": "NOT_REQUESTED"}

    facts = _extract_facts(symbol, legs)
    evidence_text = _render_evidence(symbol, legs, facts)
    context_hash = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()[:16]
    sources = _collect_sources(legs)
    return {
        "symbol": symbol,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "date_utc": utc_today(),
        "legs": legs,
        "facts": facts,
        "evidence_text": evidence_text,
        "context_hash": context_hash,
        "sources": sources,
        "provider_count": len({s.get("source") for s in sources if s.get("source")}),
        "portfolio": _min_portfolio(portfolio),
    }


def _min_portfolio(portfolio: dict | None) -> dict | None:
    if not isinstance(portfolio, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("symbol", "weight_pct", "avg_price", "current_value", "pnl_pct"):
        if portfolio.get(key) is not None:
            out[key] = portfolio[key]
    return out or None


def _extract_facts(symbol: str, legs: dict) -> dict:
    facts: dict[str, Any] = {"symbol": symbol}
    q = (legs.get("quote", {}).get("data") or {}) if legs.get("quote", {}).get("ok") else {}
    facts["price"] = _num(q.get("price"))
    facts["change_pct"] = _num(q.get("change_pct"))
    facts["volume"] = _num(q.get("volume"))
    facts["currency"] = q.get("currency")
    facts["quote_source"] = legs.get("quote", {}).get("source")
    facts["quote_as_of"] = legs.get("quote", {}).get("as_of")
    val_data = (legs.get("valuation", {}).get("data") or {}) if legs.get("valuation", {}).get("ok") else {}
    metrics = val_data.get("metrics") or {}
    for key in ("pe", "pb", "eps", "dividend_yield", "market_cap", "beta"):
        node = metrics.get(key) or {}
        facts[key] = _num(node.get("value"))
    overview = val_data.get("overview") or {}
    facts["company_name"] = overview.get("Name") or overview.get("name")
    # Statements: latest two annual income reports for growth math.
    reps = _reports(legs.get("income_annual", {}))
    facts["income_reports"] = []
    for rep in reps[:2]:
        row: dict[str, Any] = {"period": rep.get("fiscalDateEnding") or rep.get("date")}
        for out_key, candidates in (
            ("revenue", ["totalRevenue", "revenue", "revenues", "sales"]),
            ("net_income", ["netIncome", "net_income", "netEarnings"]),
            ("eps", ["eps", "EPS", "dilutedEPS"]),
        ):
            for cand in candidates:
                v = _num(rep.get(cand))
                if v is not None:
                    row[out_key] = v
                    break
        facts["income_reports"].append(row)
    if len(facts["income_reports"]) == 2:
        for key in ("revenue", "net_income", "eps"):
            a = facts["income_reports"][0].get(key)
            b = facts["income_reports"][1].get(key)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b != 0:
                facts[f"{key}_yoy_pct"] = round((a - b) / abs(b) * 100, 2)
    tech = (legs.get("technicals", {}).get("data") or {}) if legs.get("technicals", {}).get("ok") else {}
    for key in ("phase", "relative_strength", "vcp", "breakout", "trend_template"):
        facts[f"tech_{key}"] = _summarize_tech(key, tech.get(key))
    facts["tech_source"] = legs.get("technicals", {}).get("source")
    facts["tech_as_of"] = legs.get("technicals", {}).get("as_of")
    news_items = (((legs.get("news", {}).get("data") or {}).get("items")) or []) if legs.get("news", {}).get("ok") else []
    facts["news"] = [
        {"title": n.get("title"), "source": n.get("source"), "published_at": n.get("published_at"), "url": n.get("url")}
        for n in news_items[:8]
    ]
    return facts


def _summarize_tech(key: str, node: Any) -> Any:
    if not isinstance(node, dict):
        return None
    keep = {
        "phase": ["phase", "above_sma50", "above_sma200"],
        "relative_strength": ["rs", "rs_pp", "verdict", "benchmark"],
        "vcp": ["detected", "quality", "contractions"],
        "breakout": ["status", "reference_level", "volume_confirmed"],
        "trend_template": ["passed", "total", "verdict"],
    }.get(key, [])
    return {k: node.get(k) for k in keep}


def _render_evidence(symbol: str, legs: dict, facts: dict) -> str:
    lines = [f"EVIDENCE PACK — {symbol}. Every claim must come from below. Missing data must stay missing."]
    q = (legs.get("quote", {}).get("data") or {}) if legs.get("quote", {}).get("ok") else None
    if q:
        lines.append(
            f"QUOTE source={legs['quote'].get('source')} as_of={legs['quote'].get('as_of')} "
            f"price={q.get('price')} {q.get('currency') or ''} change_pct={q.get('change_pct')} "
            f"volume={q.get('volume')} prev_close={q.get('previous_close')} "
            f"52w_high={q.get('fifty_two_week_high')} 52w_low={q.get('fifty_two_week_low')}"
        )
    else:
        lines.append(f"QUOTE unavailable reason={legs.get('quote', {}).get('reason')} detail={legs.get('quote', {}).get('detail')}")
    if facts.get("company_name"):
        lines.append(f"COMPANY name={facts['company_name']}")
    for key in ("pe", "pb", "eps", "dividend_yield", "market_cap", "beta"):
        lines.append(f"VALUATION {key}={facts.get(key)} (unavailable means unknown — never estimate)")
    for i, rep in enumerate(facts.get("income_reports") or []):
        lines.append(f"INCOME t-{i} period={rep.get('period')} revenue={rep.get('revenue')} net_income={rep.get('net_income')} eps={rep.get('eps')}")
    for key in ("revenue_yoy_pct", "net_income_yoy_pct", "eps_yoy_pct"):
        if facts.get(key) is not None:
            lines.append(f"GROWTH {key}={facts[key]}%")
    for key in ("phase", "relative_strength", "vcp", "breakout", "trend_template"):
        lines.append(f"TECHNICAL {key}={json.dumps(facts.get('tech_' + key), default=str)} source=terminal-calc as_of={facts.get('tech_as_of')}")
    for n in facts.get("news") or []:
        lines.append(f"NEWS title={n.get('title')} source={n.get('source')} published={n.get('published_at')} url={n.get('url')}")
    if not facts.get("news"):
        lines.append(f"NEWS unavailable reason={(legs.get('news') or {}).get('reason')}")
    for leg_name in ("estimates", "earnings", "actions", "ownership", "profile"):
        leg = legs.get(leg_name) or {}
        if not leg.get("ok"):
            lines.append(f"{leg_name.upper()} unavailable reason={leg.get('reason')} detail={str(leg.get('detail'))[:160]}")
        else:
            payload = json.dumps(leg.get("data"), default=str)
            lines.append(f"{leg_name.upper()} source={leg.get('source')} as_of={leg.get('as_of')} data={payload[:1500]}")
    text = "\n".join(lines)
    # Prompt-budget guard: cap at ~12k chars, keep quote/valuation/tech head.
    if len(text) > 12000:
        text = text[:12000] + "\n[TRUNCATED: evidence capped for prompt budget]"
    return text


def _collect_sources(legs: dict) -> list[dict]:
    out: list[dict] = []
    for leg_name, leg in legs.items():
        if not isinstance(leg, dict) or leg.get("reason") == "NOT_REQUESTED":
            continue
        out.append(
            {
                "domain": leg_name,
                "source": leg.get("source") or "terminal",
                "as_of": leg.get("as_of"),
                "status": "ok" if leg.get("ok") else (leg.get("reason") or "unavailable"),
                "kind": "CALCULATED" if leg.get("source") == "terminal-calc" else "REPORTED",
            }
        )
    return out
