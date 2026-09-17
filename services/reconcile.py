"""Cross-provider reconciliation.

For an overlapping field with values from N providers:
- Guards first: same company is assumed (callers validate symbols);
  same currency, same period and numeric units are REQUIRED for a
  comparison — otherwise NOT_COMPARABLE with the exact reason.
- Within tolerance (default 2 %): CROSS_CHECK_OK.
- Beyond tolerance: PROVIDER_DISCREPANCY (values shown side by side,
  never averaged, never hidden).
- Single provider: SINGLE_SOURCE.

Numbers only. Text fields are reported per-source without comparison.
"""

from __future__ import annotations

from typing import Any

DEFAULT_TOL_PCT = 2.0


def _num(v: Any) -> float | None:
    if v in (None, "", "-", "None", "N/A", "NA"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compare(
    label: str,
    primary: dict[str, Any],
    others: list[dict[str, Any]],
    tol_pct: float = DEFAULT_TOL_PCT,
) -> dict[str, Any]:
    """Compare one normalized field across providers.

    Each field: {value, source, as_of, period, currency, kind}.
    """
    pv = _num(primary.get("value"))
    others = [o for o in others if o.get("source") != primary.get("source")]
    comp: dict[str, Any] = {
        "field": label,
        "primary": primary,
        "cross_check": [],
        "status": "SINGLE_SOURCE",
        "difference_pct": None,
        "reason": None,
    }
    if pv is None:
        comp["status"] = "NOT_COMPARABLE"
        comp["reason"] = "Primary value missing or non-numeric."
        comp["cross_check"] = others
        return comp
    worst: float | None = None
    blocked: str | None = None
    for o in others:
        ov = _num(o.get("value"))
        entry: dict[str, Any] = {
            "source": o.get("source"),
            "value": o.get("value"),
            "as_of": o.get("as_of"),
            "period": o.get("period"),
            "currency": o.get("currency"),
        }
        if ov is None:
            entry["comparable"] = False
            entry["reason"] = "No numeric value from this provider."
            comp["cross_check"].append(entry)
            continue
        pc, oc = primary.get("currency"), o.get("currency")
        if pc and oc and str(pc).upper() != str(oc).upper():
            entry["comparable"] = False
            entry["reason"] = f"Currency differs ({pc} vs {oc})."
            blocked = blocked or entry["reason"]
            comp["cross_check"].append(entry)
            continue
        pp, op = primary.get("period"), o.get("period")
        if pp and op and str(pp) != str(op):
            entry["comparable"] = False
            entry["reason"] = f"Period differs ({pp} vs {op})."
            blocked = blocked or entry["reason"]
            comp["cross_check"].append(entry)
            continue
        denom = abs(pv) if pv != 0 else None
        diff = None if denom is None else abs(ov - pv) / denom * 100.0
        entry["comparable"] = True
        entry["difference_pct"] = diff
        comp["cross_check"].append(entry)
        if diff is not None:
            worst = diff if worst is None else max(worst, diff)
    comp["difference_pct"] = worst
    comparable = [e for e in comp["cross_check"] if e.get("comparable")]
    if not comparable:
        comp["status"] = "NOT_COMPARABLE" if comp["cross_check"] else "SINGLE_SOURCE"
        comp["reason"] = blocked or (comp["reason"] if comp["cross_check"] else None)
    elif worst is not None and worst > tol_pct:
        comp["status"] = "PROVIDER_DISCREPANCY"
        comp["reason"] = (
            f"Providers differ by {worst:.2f}% (tolerance {tol_pct}%). "
            "Both values shown; neither averaged nor hidden."
        )
    else:
        comp["status"] = "CROSS_CHECK_OK"
    return comp


def summarize(comparisons: list[dict]) -> dict:
    """Counts for the Data Quality panel."""
    counts = {
        "CROSS_CHECK_OK": 0,
        "PROVIDER_DISCREPANCY": 0,
        "SINGLE_SOURCE": 0,
        "NOT_COMPARABLE": 0,
    }
    disc = []
    for c in comparisons:
        st = c.get("status", "SINGLE_SOURCE")
        counts[st] = counts.get(st, 0) + 1
        if st == "PROVIDER_DISCREPANCY":
            disc.append(c.get("field"))
    return {
        "fields_compared": len(comparisons),
        "cross_check_ok": counts["CROSS_CHECK_OK"],
        "discrepancies": counts["PROVIDER_DISCREPANCY"],
        "discrepancy_fields": disc,
        "single_source": counts["SINGLE_SOURCE"],
        "not_comparable": counts["NOT_COMPARABLE"],
    }
