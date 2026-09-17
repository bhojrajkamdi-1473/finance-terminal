"""Normalized internal schema for multi-provider data.

Every important value is a field dict carrying its own provenance —
no bare numbers cross provider boundaries:

    {"value": ..., "source": "alphavantage",
     "as_of": ISO-timestamp, "period": "FY2025" | "Q3-2025" | None,
     "currency": "INR" | "USD" | None,
     "kind": "REPORTED" | "CALCULATED"}

Normalization never invents: unparseable inputs become None (caller
marks the field unavailable), units/currency/period mismatches are
preserved so reconciliation can refuse invalid comparisons.
"""

from __future__ import annotations

from typing import Any

REPORTED = "REPORTED"
CALCULATED = "CALCULATED"


def field(
    value: Any,
    source: str,
    as_of: str | None = None,
    period: str | None = None,
    currency: str | None = None,
    kind: str = REPORTED,
) -> dict:
    return {
        "value": value,
        "source": source,
        "as_of": as_of,
        "period": period,
        "currency": currency,
        "kind": kind,
    }


def num(value: Any) -> float | None:
    """Strict numeric coercion. Placeholders and junk become None."""
    if value in (None, "", "-", "None", "N/A", "NA", "null"):
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def same_company(requested: str, echoed: str | None) -> bool:
    """Echoed-symbol guard reused from the normalization layer."""
    from . import symbols as _sym

    return _sym.symbols_match(requested, echoed)
