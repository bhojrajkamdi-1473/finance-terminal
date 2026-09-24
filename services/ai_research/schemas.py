"""Structured research-report schemas + validation (stdlib only).

The report is research-oriented. Recommendation-style language
(BUY/SELL/STRONG BUY/...) is rejected at validation time.
"""

from __future__ import annotations

import re

STANDARD_SECTIONS = (
    "fundamentals",
    "valuation",
    "technical",
    "news",
    "bull",
    "bear",
    "risk",
)

ALL_SECTIONS = STANDARD_SECTIONS + ("catalysts", "unknowns", "conclusion")

REPORT_FIELDS = (
    "executive_snapshot",
    "fundamentals",
    "valuation",
    "technical",
    "news_sentiment",
    "bull_case",
    "bear_case",
    "risks",
    "catalysts",
    "unknowns",
    "data_gaps",
    "conclusion",
    "sources",
)

_BANNED = re.compile(
    r"\b(strong\s+buy|strong\s+sell|you\s+should\s+buy|you\s+should\s+sell)\b"
    r"|^\s*(buy|sell)\s*$",
    re.IGNORECASE,
)


def normalize_sections(sections: object | None, depth: str) -> list[str]:
    if sections is None:
        if depth == "deep":
            return list(ALL_SECTIONS)
        return list(STANDARD_SECTIONS)
    if not isinstance(sections, list):
        raise ValueError("sections must be a list")  # noqa: TRY004 — API contract uses ValueError
    out: list[str] = []
    for s in sections:
        name = str(s or "").strip().lower()
        if name in ("news_sentiment", "sentiment"):
            name = "news"
        if name not in ALL_SECTIONS:
            raise ValueError(f"Unknown research section: {s!r}")
        if name not in out:
            out.append(name)
    if not out:
        raise ValueError("sections must not be empty")
    return out


def validate_report(report: dict) -> list[str]:
    """Return a list of problems (empty == valid). Never raises."""
    problems: list[str] = []
    try:
        if not isinstance(report, dict):
            return ["report must be an object"]
        for field in REPORT_FIELDS:
            if field not in report:
                problems.append(f"missing field: {field}")
        # Banned directional language anywhere in conclusion/snapshot.
        for field in ("executive_snapshot", "conclusion", "bull_case", "bear_case"):
            node = report.get(field)
            texts: list[str] = []
            if isinstance(node, dict):
                t = node.get("text") or node.get("summary")
                if isinstance(t, str):
                    texts.append(t)
                for item in node.get("points") or []:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        texts.append(item["text"])
            elif isinstance(node, str):
                texts.append(node)
            for t in texts:
                if _BANNED.search(t):
                    problems.append(f"directional recommendation in {field}")
                    break
        return problems
    except Exception:
        return ["validation crashed"]
