"""Research orchestrator: validate -> evidence -> agents -> ground -> report."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from . import adapter as _adapter
from . import agents as _agents
from . import cache as _cache
from . import citations as _cite
from . import config as _cfg
from . import context as _ctx
from . import grounding as _ground
from . import llm as _llm
from . import schemas as _schemas

_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,24}$")

RESEARCH_TTL_NOTE = "standard 4h · deep 2h · key: ticker|date|depth|context-hash|model"


def validate_ticker(raw: object) -> str:
    sym = str(raw or "").strip().upper()
    if not sym or not _TICKER.match(sym):
        raise ValueError("Invalid ticker. Examples: TCS.NS, RELIANCE.NS, META, MSFT, AAPL.")
    return sym


def _bullets(text: str, limit: int = 6) -> list[str]:
    lines = [ln.strip("•-* \t") for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if len(ln) > 12][:limit]
    if not lines and text.strip():
        return [text.strip()[:400]]
    return lines


def _section(role_text: str, legs: dict, section: str, grounding: dict) -> dict:
    return {
        "text": role_text,
        "points": _bullets(role_text),
        "citations": _cite.section_citations(section, legs),
        "grounding": grounding.get("verdict", "unverified"),
        "grounding_note": grounding.get("note"),
    }


def run_research(
    ticker: str,
    depth: str = "standard",
    sections: list[str] | None = None,
    *,
    portfolio: dict | None = None,
    force: bool = False,
    progress: Callable[[str, str], None] | None = None,
    adapter: Any | None = None,
) -> dict:
    symbol = validate_ticker(ticker)
    depth = (depth or "standard").strip().lower()
    if depth not in ("standard", "deep"):
        raise ValueError("depth must be 'standard' or 'deep'")
    wanted = _schemas.normalize_sections(sections, depth)

    llm_status = _cfg.status()
    use_llm = bool(llm_status.get("available"))
    model = llm_status.get("model") or _cfg.model()
    provider = llm_status.get("provider") or _cfg.provider()

    adapt = adapter or _adapter.FinanceTerminalDataAdapter()
    bundle = _ctx.build_context(symbol, adapt, wanted, portfolio)
    legs = bundle["legs"]
    evidence_text = bundle["evidence_text"]

    key = _cache.cache_key(symbol, depth, wanted, bundle["context_hash"], model if use_llm else "extractive", bundle["date_utc"])
    if not force:
        hit = _cache.get(key)
        if hit is not None:
            out = dict(hit)
            out["cache"] = {"hit": True, "key_hash": key[:24] + "…", "ttl_note": RESEARCH_TTL_NOTE}
            return out

    if progress:
        try:
            progress("prepare", "done")
        except Exception:
            pass
    agent_results = _agents.run_all(evidence_text, use_llm=use_llm, progress=progress)
    fail_kind = _agents.failed_kind(agent_results)
    if fail_kind == "LLM_NOT_CONFIGURED":
        use_llm = False
    elif fail_kind in ("LLM_TIMEOUT", "RATE_LIMIT", "LLM_API_ERROR") and all(
        not (agent_results.get(r) or {}).get("ok") for r in _agents.AGENT_ORDER
    ):
        raise _llm.LLMError("AI research temporarily unavailable.", kind=fail_kind)

    grounding = _ground.ground_all(agent_results, evidence_text, legs)

    def txt(role: str) -> str:
        res = agent_results.get(role) or {}
        if res.get("ok") and res.get("text"):
            return res["text"]
        return f"{role} analysis unavailable ({res.get('error_kind') or 'no data'}). Evidence pack retained in Sources."

    report = {
        "ticker": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_timestamp": bundle["built_at"],
        "model": model if use_llm else "extractive (no LLM configured)",
        "provider": provider if use_llm else "none",
        "depth": depth,
        "sections": wanted,
        "llm_backed": use_llm,
        "executive_snapshot": {"text": txt("manager"), "citations": _cite.section_citations("manager", legs)},
        "fundamentals": _section(txt("fundamental"), legs, "fundamental", grounding.get("fundamental", {})),
        "valuation": _section(txt("fundamental"), legs, "fundamental", grounding.get("fundamental", {})),
        "technical": _section(txt("market"), legs, "market", grounding.get("market", {})),
        "news_sentiment": {
            "text": txt("news"),
            "items": _cite.news_sources(legs),
            "citations": _cite.section_citations("news", legs),
            "grounding": grounding.get("news", {}).get("verdict", "unverified"),
        },
        "bull_case": _section(txt("bull"), legs, "bull", grounding.get("bull", {})),
        "bear_case": _section(txt("bear"), legs, "bear", grounding.get("bear", {})),
        "risks": _section(txt("risk"), legs, "risk", grounding.get("risk", {})),
        "catalysts": {"points": _bullets(txt("news") + "\n" + txt("bull")), "citations": _cite.section_citations("news", legs)},
        "unknowns": {
            "points": _bullets(txt("manager")),
            "citations": _cite.section_citations("manager", legs),
        },
        "data_gaps": _data_gaps(legs),
        "conclusion": {"text": txt("manager"), "citations": _cite.section_citations("manager", legs)},
        "sources": _cite.sources_panel(legs, model if use_llm else "extractive", provider if use_llm else "none"),
        "context_hash": bundle["context_hash"],
        "provider_count": bundle["provider_count"],
        "grounding": {k: (v or {}).get("verdict") for k, v in grounding.items()},
        "stages": {role: ("done" if (agent_results.get(role) or {}).get("ok") else "failed") for role in _agents.AGENT_ORDER},
    }
    problems = _schemas.validate_report(report)
    if problems:
        # Self-heal banned language rather than fail the whole report.
        for field in ("executive_snapshot", "conclusion"):
            node = report.get(field)
            if isinstance(node, dict) and isinstance(node.get("text"), str):
                node["text"] = _strip_advice(node["text"])
    out = {
        "ok": True,
        "report": report,
        "cache": {"hit": False, "key_hash": key[:24] + "…", "ttl_note": RESEARCH_TTL_NOTE},
    }
    _cache.set(key, out, depth)
    return out


def _data_gaps(legs: dict) -> list[dict]:
    gaps = []
    for name, leg in legs.items():
        if not isinstance(leg, dict) or leg.get("reason") == "NOT_REQUESTED":
            continue
        if not leg.get("ok"):
            gaps.append({"domain": name, "reason": leg.get("reason") or "unavailable", "detail": str(leg.get("detail") or "")[:200]})
    return gaps


_ADVICE = re.compile(r"\b(strong\s+buy|strong\s+sell|you\s+should\s+(buy|sell))\b", re.IGNORECASE)


def _strip_advice(text: str) -> str:
    return _ADVICE.sub("[removed: research-only output]", text)
