"""Citations + provenance attachment (stdlib only).

Every report section carries the sources it was built from: provider id,
retrieval/calculation timestamp, and kind (REPORTED/CALCULATED). URLs
come only from application news payloads — never invented.
"""

from __future__ import annotations


def section_citations(section: str, legs: dict) -> list[dict]:
    mapping = {
        "market": ["quote", "technicals"],
        "fundamental": ["valuation", "income_annual", "balance_annual", "cashflow_annual", "earnings", "estimates"],
        "news": ["news"],
        "bull": ["quote", "valuation", "income_annual", "news", "technicals"],
        "bear": ["quote", "valuation", "income_annual", "news", "technicals"],
        "risk": ["valuation", "balance_annual", "ownership", "actions", "news"],
        "manager": ["quote", "profile", "valuation", "technicals", "news"],
    }
    out: list[dict] = []
    for leg_name in mapping.get(section, ["quote"]):
        leg = legs.get(leg_name) or {}
        if leg.get("reason") == "NOT_REQUESTED":
            continue
        out.append(
            {
                "domain": leg_name,
                "source": leg.get("source") or "terminal",
                "retrieved_at": leg.get("as_of"),
                "kind": "CALCULATED" if leg.get("source") == "terminal-calc" else "REPORTED",
                "status": "ok" if leg.get("ok") else (leg.get("reason") or "unavailable"),
            }
        )
    return out


def news_sources(legs: dict) -> list[dict]:
    leg = legs.get("news") or {}
    items = ((leg.get("data") or {}).get("items") or []) if leg.get("ok") else []
    return [
        {"title": n.get("title"), "source": n.get("source"), "published_at": n.get("published_at"), "url": n.get("url")}
        for n in items[:8]
    ]


def sources_panel(legs: dict, model: str, provider: str) -> list[dict]:
    panel: list[dict] = []
    for leg_name, leg in legs.items():
        if not isinstance(leg, dict) or leg.get("reason") == "NOT_REQUESTED":
            continue
        panel.append(
            {
                "category": "Analytics" if leg.get("source") == "terminal-calc" else ("News" if leg_name == "news" else "Market Data"),
                "domain": leg_name,
                "provider": leg.get("source") or "terminal",
                "as_of": leg.get("as_of"),
                "status": "ok" if leg.get("ok") else (leg.get("reason") or "unavailable"),
            }
        )
    panel.append({"category": "AI", "domain": "synthesis", "provider": f"{provider}:{model}", "as_of": None, "status": "ok"})
    return panel
