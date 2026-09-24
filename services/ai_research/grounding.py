"""Claim grounding: verify numeric/factual statements against evidence.

Approach: extract candidate numbers (percentages, multiples like P/E,
plain decimals) from agent text and check each appears within tolerance
in the evidence pack. Verdicts: grounded | unverified | data_unavailable.
Unverifiable sentences are NOT deleted (analyst voice matters) but the
section gains an explicit UNCERTAIN marker listing them.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"(?<!\w)(\d[\d,]*(?:\.\d+)?)(?:\s*(%|percent|x))?(?!\w)", re.IGNORECASE)


def _evidence_numbers(evidence_text: str) -> list[float]:
    out: list[float] = []
    for match in _NUM.finditer(evidence_text or ""):
        try:
            out.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return out


def _close(candidate: float, evidence: list[float], tol: float = 0.06) -> bool:
    for val in evidence:
        denom = abs(val) if val != 0 else 1.0
        if abs(candidate - val) / denom <= tol:
            return True
        if abs(candidate - val) <= 0.015:
            return True
    return False


def ground_text(text: str, evidence_text: str, *, evidence_missing: bool = False) -> dict:
    """Ground one agent text. Returns verdict + unverified numbers."""
    if not text:
        return {"verdict": "data_unavailable", "numbers": [], "unverified": [], "note": "Empty analysis."}
    if evidence_missing:
        return {"verdict": "data_unavailable", "numbers": [], "unverified": [], "note": "Evidence legs unavailable."}
    candidates: list[float] = []
    for match in _NUM.finditer(text):
        try:
            candidates.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    if not candidates:
        return {"verdict": "grounded", "numbers": [], "unverified": [], "note": "No numeric claims."}
    evidence = _evidence_numbers(evidence_text)
    unverified = [c for c in candidates if not _close(c, evidence)]
    if not unverified:
        return {"verdict": "grounded", "numbers": candidates, "unverified": [], "note": f"{len(candidates)} numeric claims verified."}
    return {
        "verdict": "unverified",
        "numbers": candidates,
        "unverified": unverified,
        "note": f"{len(unverified)} of {len(candidates)} numbers not found in evidence; treat as unverified.",
    }


def ground_all(agent_results: dict, evidence_text: str, legs: dict) -> dict:
    """Ground every role text. Returns {role: grounding}."""
    missing = not any((legs.get(k) or {}).get("ok") for k in ("quote", "valuation", "income_annual", "technicals"))
    return {role: ground_text((res or {}).get("text", ""), evidence_text, evidence_missing=missing) for role, res in agent_results.items()}
