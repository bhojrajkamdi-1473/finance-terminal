"""Role agents: sequential, failure-isolated pipeline (stdlib only).

Order mirrors TradingAgents' debate-then-synthesize flow:
market + fundamental + news (parallel-safe, run sequentially for
quota discipline) -> bull + bear -> risk -> manager synthesis.
Each agent failure degrades to an explicit unavailable note; the
pipeline never crashes because one role failed.
"""

from __future__ import annotations

from collections.abc import Callable

from . import llm as _llm
from . import prompts as _prompts

AGENT_ORDER = ("market", "fundamental", "news", "bull", "bear", "risk", "manager")

STAGE_LABELS = {
    "market": "Market analysis",
    "fundamental": "Fundamental analysis",
    "news": "News analysis",
    "bull": "Bull / Bear research",
    "bear": "Bull / Bear research",
    "risk": "Risk analysis",
    "manager": "Final synthesis",
}


def run_agent(role: str, evidence_text: str, extra: str = "") -> dict:
    """Run one role. Always returns a dict; never raises."""
    try:
        messages = _prompts.build_messages(role, evidence_text, extra)
        out = _llm.complete(messages)
        text = (out.get("text") or "").strip()
        if not text:
            raise _llm.LLMError("Empty LLM response.", kind="LLM_API_ERROR")  # noqa: TRY301
        return {"role": role, "ok": True, "text": text, "model": out.get("model"), "provider": out.get("provider")}
    except _llm.LLMError as exc:
        return {"role": role, "ok": False, "text": "", "error": str(exc)[:300], "error_kind": exc.kind}
    except Exception as exc:
        return {"role": role, "ok": False, "text": "", "error": str(exc)[:200], "error_kind": "LLM_API_ERROR"}


def run_all(
    evidence_text: str,
    *,
    use_llm: bool,
    progress: Callable[[str, str], None] | None = None,
) -> dict[str, dict]:
    """Execute the full role pipeline. Returns {role: result}."""

    def emit(role: str, state: str) -> None:
        if progress:
            try:
                progress(role, state)
            except Exception:
                pass

    results: dict[str, dict] = {}
    for role in ("market", "fundamental", "news"):
        emit(role, "running")
        if use_llm:
            results[role] = run_agent(role, evidence_text)
        else:
            results[role] = {
                "role": role,
                "ok": True,
                "text": _llm.deterministic_extract(role, evidence_text),
                "model": "extractive",
                "provider": "none",
                "fallback": True,
            }
        emit(role, "done" if results[role].get("ok") else "failed")
    debate_src = "\n".join(f"[{r}] {(results[r].get('text') or '')[:1200]}" for r in ("market", "fundamental", "news") if results[r].get("text"))
    for role in ("bull", "bear"):
        emit(role, "running")
        if use_llm:
            results[role] = run_agent(role, evidence_text, debate_src[:3000])
        else:
            results[role] = {
                "role": role,
                "ok": True,
                "text": _llm.deterministic_extract(role, evidence_text),
                "model": "extractive",
                "provider": "none",
                "fallback": True,
            }
        emit(role, "done" if results[role].get("ok") else "failed")
    emit("risk", "running")
    if use_llm:
        results["risk"] = run_agent("risk", evidence_text, debate_src[:3000])
    else:
        results["risk"] = {
            "role": "risk",
            "ok": True,
            "text": _llm.deterministic_extract("risk", evidence_text),
            "model": "extractive",
            "provider": "none",
            "fallback": True,
        }
    emit("risk", "done" if results["risk"].get("ok") else "failed")
    emit("manager", "running")
    synthesis_src = "\n".join(f"[{r}] {(results[r].get('text') or '')[:1000]}" for r in ("market", "fundamental", "news", "bull", "bear", "risk"))
    if use_llm:
        results["manager"] = run_agent("manager", evidence_text, synthesis_src[:4000])
    else:
        results["manager"] = {
            "role": "manager",
            "ok": True,
            "text": _llm.deterministic_extract("manager", evidence_text),
            "model": "extractive",
            "provider": "none",
            "fallback": True,
        }
    emit("manager", "done" if results["manager"].get("ok") else "failed")
    return results


def failed_kind(results: dict[str, dict]) -> str | None:
    for role in AGENT_ORDER:
        res = results.get(role) or {}
        if not res.get("ok"):
            return str(res.get("error_kind") or "LLM_API_ERROR")
    return None
