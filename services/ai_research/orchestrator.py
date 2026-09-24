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

RESEARCH_TTL_NOTE = "quick/standard 4h · deep 2h · key: ticker|date|depth|context-hash|model"


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


def _section(
    role_text: str,
    legs: dict,
    section: str,
    grounding: dict,
    *,
    observations: list | None = None,
    metrics: list | None = None,
    include_text: bool = True,
) -> dict:
    node: dict = {
        "points": ([o["statement"] for o in (observations or [])][:6]
                   if not include_text
                   else _bullets(role_text)),
        "citations": _cite.section_citations(section, legs),
        "grounding": grounding.get("verdict", "unverified"),
        "grounding_note": grounding.get("note"),
        "observations": observations or [],
        "metrics": metrics or [],
    }
    if include_text and role_text:
        node["text"] = role_text
    if not include_text and not node["observations"]:
        node["observations"] = [
            {"statement": "Insufficient verified evidence for this section right now",
             "source": "Terminal", "period": None}
        ]
    return node


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
    if depth not in ("quick", "standard", "deep"):
        raise ValueError("depth must be 'quick', 'standard' or 'deep'")
    wanted = _schemas.normalize_sections(sections, depth)

    llm_status = _cfg.status()
    use_llm = bool(llm_status.get("available"))
    model = llm_status.get("model") or _cfg.model()
    provider = llm_status.get("provider") or _cfg.provider()

    adapt = adapter or _adapter.FinanceTerminalDataAdapter()
    bundle = _ctx.build_context(symbol, adapt, wanted, portfolio)
    legs = bundle["legs"]
    evidence_text = bundle["evidence_text"]

    key = _cache.cache_key(symbol, depth, wanted, bundle["context_hash"], model if use_llm else "evidence", bundle["date_utc"])
    if not force:
        hit = _cache.get(key)
        if hit is not None:
            out = dict(hit)
            out["cache"] = {"hit": True, "key_hash": key[:24] + "…", "ttl_note": RESEARCH_TTL_NOTE}
            return out

    # Daily run budget (Paperclip-style hard stop): executed runs only,
    # cache hits are free. Best-effort — a ledger failure never blocks.
    try:
        from services import store as _store

        _conn = _store.connect()
        try:
            from . import ledger as _ledger

            if _ledger.budget_exhausted(_conn):
                raise _llm.LLMError(
                    f"AI run budget exhausted for today ({_ledger.daily_budget()} runs).",
                    kind="RATE_LIMIT",
                )
        finally:
            _conn.close()
    except _llm.LLMError:
        raise
    except Exception:
        pass

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

    from . import synthesis as _syn

    fb: dict = {}
    if not use_llm:
        # No raw agent text leaves this path: structured facts only.
        fb = _syn.build_fallback_report(symbol, legs, bundle["facts"], wanted)

    def txt(role: str) -> str:
        res = agent_results.get(role) or {}
        if res.get("ok") and res.get("text"):
            return _syn.sanitize_text(res["text"])
        return ""

    def _fb(section: str) -> dict:
        return (fb.get("sections") or {}).get(section) or {}

    def _sec(role: str, section: str, gkey: str) -> dict:
        return _section(
            txt(role), legs, section, grounding.get(gkey, {}),
            observations=_fb(section).get("observations"),
            metrics=_fb(section).get("metrics"),
            include_text=use_llm,
        )

    report = {
        "ticker": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_timestamp": bundle["built_at"],
        "model": model if use_llm else "Terminal evidence synthesis",
        "provider": provider if use_llm else "none",
        "depth": depth,
        "sections": wanted,
        "llm_backed": use_llm,
        "executive_snapshot": {
            "citations": _cite.section_citations("manager", legs),
            **({"text": txt("manager")} if use_llm and txt("manager") else {}),
            **({} if use_llm else {"summary": fb.get("snapshot", "")}),
        },
        "fundamentals": _sec("fundamental", "fundamentals", "fundamental"),
        "valuation": _sec("fundamental", "valuation", "fundamental"),
        "technical": _sec("market", "technical", "market"),
        "news_sentiment": {
            **({"text": txt("news")} if use_llm and txt("news") else {}),
            "observations": _fb("news").get("observations", []),
            "items": _cite.news_sources(legs),
            "citations": _cite.section_citations("news", legs),
            "grounding": grounding.get("news", {}).get("verdict", "unverified"),
        },
        "bull_case": _sec("bull", "bull", "bull"),
        "bear_case": _sec("bear", "bear", "bear"),
        "risks": _sec("risk", "risk", "risk"),
        "catalysts": {"points": _bullets(txt("news") + "\n" + txt("bull")) if use_llm else [o["statement"] for o in _fb("news").get("observations", [])[:4]], "citations": _cite.section_citations("news", legs)},
        "unknowns": {
            "points": _bullets(txt("manager")) if use_llm else [],
            "citations": _cite.section_citations("manager", legs),
        },
        "data_gaps": _data_gaps(legs),
        "conclusion": {
            "citations": _cite.section_citations("manager", legs),
            **({"text": txt("manager")} if use_llm and txt("manager") else {}),
            **({} if use_llm else {"summary": fb.get("conclusion", "")}),
        },
        "sources": _cite.sources_panel(legs, model if use_llm else "Terminal evidence synthesis", provider if use_llm else "none"),
        "context_hash": bundle["context_hash"],
        "provider_count": bundle["provider_count"],
        "grounding": {k: (v or {}).get("verdict") for k, v in grounding.items()},
        "stages": {role: ("done" if (agent_results.get(role) or {}).get("ok") else "failed") for role in _agents.AGENT_ORDER},
        "disclaimer": "Research only — not investment advice. Verify figures against primary sources before acting.",
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
    # Audit-trail record (best-effort; never breaks the response).
    try:
        from services import store as _store

        from . import ledger as _ledger

        _conn = _store.connect()
        try:
            _ledger.record_run(
                _conn, ticker=symbol, depth=depth, sections=wanted,
                model=model if use_llm else "Terminal evidence synthesis",
                provider=provider if use_llm else "none",
                context_hash=bundle["context_hash"],
                stages=report.get("stages") or {},
                grounding=report.get("grounding") or {},
                provider_count=bundle["provider_count"],
                llm_backed=use_llm,
            )
        finally:
            _conn.close()
    except Exception:
        pass
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
