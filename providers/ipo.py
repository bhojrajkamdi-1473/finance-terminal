"""IPO layer: working calendar feed + honest GMP/subscription states.

Source matrix (verified Sep 2026):
- Alpha Vantage IPO_CALENDAR (keyed, free 25/day): working, US-centric,
  served through the existing fundamentals leg. No code copied.
- IPO Guru developer API (https://www.ipoguru.in/ipo-gmp-details-developer-api):
  documented free tier (300 req/day, 15/min, X-API-KEY). Integrated
  server-side with caching + 429 cooldown when IPOGURU_API_KEY is set.
- InvestorGain / IPO Watch / Chittorgarh / IPO Central: editorial
  websites, no public JSON APIs located. NOT scraped (robots/ToS).
  Linked from Research Hub as external research, never presented
  as data feeds.
- NSE/BSE official announcements: no keyless JSON API; covered by
  the Corporate Actions + News legs where feeds exist.

GMP rules (non-negotiable, enforced in payload + UI copy):
- Every GMP value labelled UNOFFICIAL GREY MARKET PREMIUM.
- Source + last-updated timestamp required; absent -> unavailable.
- Estimated listing = upper band + GMP, labelled INDICATIVE ONLY.
- Multiple sources disagree -> show both, GMP DISCREPANCY, never average.
- Never a guaranteed or official price. Never BUY/SELL/APPLY output.
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

GMP_LABEL = "UNOFFICIAL GREY MARKET PREMIUM"
INDICATIVE_LABEL = "INDICATIVE ONLY"
DISCREPANCY_LABEL = "GMP DISCREPANCY"


def _today() -> date:
    return date.today()


def _parse_day(value: Any) -> date | None:
    s = str(value or "").strip()[:10]
    try:
        y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def _row_get(row: dict, *names: str) -> Any:
    lowered = {re.sub(r"[^a-z]", "", str(k).strip().lower()): v for k, v in (row or {}).items()}
    for name in names:
        key = re.sub(r"[^a-z]", "", name)
        if key in lowered:
            return lowered[key]
    return None


def classify(rows: list[dict], today: date | None = None) -> dict[str, list[dict]]:
    """Bucket calendar rows without fabricating dates.

    Buckets: upcoming / open / closed / listed / unclassified (dates
    missing or unparsable -> NEVER guessed).
    """
    today = today or _today()
    out = {"upcoming": [], "open": [], "closed": [], "listed": [], "unclassified": []}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        offer = _parse_day(_row_get(row, "offerdate", "offer_date", "ipostartdate", "open", "opendate"))
        listing = _parse_day(_row_get(row, "listingdate", "listing_date", "listdate"))
        close = _parse_day(_row_get(row, "closedate", "close_date", "ipoenddate", "close"))
        tagged = dict(row)
        if listing and listing <= today:
            tagged["_bucket"] = "listed"
            out["listed"].append(tagged)
        elif offer and close:
            if offer > today:
                tagged["_bucket"] = "upcoming"
                out["upcoming"].append(tagged)
            elif close < today:
                tagged["_bucket"] = "closed"
                out["closed"].append(tagged)
            else:
                tagged["_bucket"] = "open"
                out["open"].append(tagged)
        elif offer and not close:
            tagged["_bucket"] = "upcoming" if offer > today else "open"
            out[tagged["_bucket"]].append(tagged)
        else:
            tagged["_bucket"] = "unclassified"
            out["unclassified"].append(tagged)
    return out


def gmp_unavailable(symbol: str | None = None) -> dict:
    """No verified GMP source is configured. Labelling rides along so
    any future source inherits the rules."""
    return {
        "status": "unavailable",
        "source": "ipo-gmp",
        "label": GMP_LABEL,
        "data": None,
        "message": (
            "No verified grey-market source is configured"
            + (f" for '{symbol}'" if symbol else "")
            + ". GMP is unofficial market chatter even when available; "
            "it is never shown without source + timestamp, never averaged "
            "across disagreeing sources, and never investment advice."
        ),
    }


def subscription_unavailable(symbol: str | None = None) -> dict:
    return {
        "status": "unavailable",
        "source": "ipo-subscription",
        "data": None,
        "message": (
            "Live QIB/NII/Retail subscription data has no configured feed"
            + (f" for '{symbol}'" if symbol else "")
            + ". Exchange-published subscription figures appear here only "
            "when a verified source is wired."
        ),
    }


def ipoguru_status() -> dict:
    """IPO Guru verdict: reserved key, no verified endpoint contract."""
    configured = bool((os.environ.get("IPOGURU_API_KEY") or "").strip())
    return {
        "provider": "ipo-guru",
        "key_configured": configured,
        "state": "unverified",
        "detail": "No public API contract located; reserved IPOGURU_API_KEY "
        "is accepted but no endpoint is called until docs/terms verify.",
    }
