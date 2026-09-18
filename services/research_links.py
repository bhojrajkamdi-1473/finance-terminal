"""External research destinations registry (links only, never scraped).

Central configuration for every outbound research destination. Each
resolver is a PURE string builder: no HTTP requests, no content
extraction, no authentication, no paywall interaction. The user clicks
through to the original source in a new tab.

URL patterns below were individually verified (HTTP 200 + canonical
redirect where applicable, bogus-input 404 control) — see tests.
Unverifiable patterns are deliberately NOT deep links (landing pages
or explicit unavailable states instead).

Classification:
- "official": exchange / regulator / company-controlled destination.
- "external": third-party research site (never our data).
Badges shown in UI: OFFICIAL / EXTERNAL / MARKET DATA.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

OFFICIAL = "official"
EXTERNAL = "external"


def _bare(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def _country(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s.endswith((".NS", ".BO")) or s.startswith("^"):
        return "IN"
    if s and "." not in s and "/" not in s and " " not in s:
        return "US"
    return "??"


def _is_index(symbol: str) -> bool:
    return (symbol or "").strip().upper().startswith("^")


def _dest(
    id: str,
    name: str,
    category: str,
    badge: str,
    description: str,
    url: str | None,
    verified: bool = True,
    reason: str | None = None,
) -> dict:
    return {
        "id": id,
        "name": name,
        "category": category,
        "badge": badge,
        "description": description,
        "url": url,
        "verified": verified,
        "reason": reason,
        "external": True,
        "opens_new_tab": True,
    }


def destinations(symbol: str, company_name: str = "") -> dict:
    """Build the Research Hub destination list for a symbol.

    Never raises; unknown symbols get search/landing fallbacks or
    explicit unavailable entries — never invented deep links.
    """
    symbol = (symbol or "").strip().upper()
    country = _country(symbol)
    bare = _bare(symbol)
    is_index = _is_index(symbol)
    official: list[dict] = []
    research: list[dict] = []

    if country == "IN" and not is_index:
        official.append(
            _dest(
                "nse",
                "NSE",
                OFFICIAL,
                "OFFICIAL",
                "Official NSE quote, announcements and filings",
                "https://www.nseindia.com/get-quotes/equity?symbol="
                + urllib.parse.quote(bare),
            )
        )
        official.append(
            _dest(
                "bse",
                "BSE",
                OFFICIAL,
                "OFFICIAL",
                "Official BSE security search",
                "https://www.bseindia.com/search?query=" + urllib.parse.quote(bare),
            )
        )
        official.append(
            _dest(
                "annual-reports",
                "Annual Reports",
                OFFICIAL,
                "OFFICIAL",
                "Official NSE corporate-filings archive",
                "https://www.nseindia.com/companies-listing/"
                "corporate-filings-annual-reports",
            )
        )
        official.append(
            _dest(
                "ir",
                "Company IR",
                OFFICIAL,
                "OFFICIAL",
                "Investor Relations — no verified URL in provider metadata",
                None,
                verified=False,
                reason="No verified IR URL from provider metadata. "
                "Domains are never guessed.",
            )
        )
        research.append(
            _dest(
                "screener",
                "Screener",
                EXTERNAL,
                "EXTERNAL",
                "Open company research page (original source, not our data)",
                f"https://www.screener.in/company/{bare}/",
            )
        )
        research.append(
            _dest(
                "trendlyne",
                "Trendlyne",
                EXTERNAL,
                "EXTERNAL",
                "Trendlyne research landing (per-company URLs use "
                "site slugs we do not derive)",
                "https://trendlyne.com/stock-screeners/by-type/",
            )
        )
        research.append(
            _dest(
                "tickertape",
                "Tickertape",
                EXTERNAL,
                "EXTERNAL",
                "Tickertape research landing (per-company URLs use "
                "site slugs we do not derive)",
                "https://www.tickertape.in/screener/equity",
            )
        )
    elif country == "US" and not is_index:
        q = urllib.parse.quote(company_name or bare)
        official.append(
            _dest(
                "sec",
                "SEC Filings",
                OFFICIAL,
                "OFFICIAL",
                "Official SEC EDGAR company filing search",
                "https://www.sec.gov/cgi-bin/browse-edgar?"
                "action=getcompany&CIK=&type=&dateb=&owner=include"
                f"&count=40&company={q}",
            )
        )
        official.append(
            _dest(
                "annual-reports",
                "Annual Reports",
                OFFICIAL,
                "OFFICIAL",
                "10-K/annual filings via official SEC EDGAR search",
                "https://www.sec.gov/cgi-bin/browse-edgar?"
                "action=getcompany&CIK=&type=10-K&dateb=&owner=include"
                f"&count=10&company={q}",
            )
        )
        official.append(
            _dest(
                "ir",
                "Company IR",
                OFFICIAL,
                "OFFICIAL",
                "Investor Relations — no verified URL in provider metadata",
                None,
                verified=False,
                reason="No verified IR URL from provider metadata. "
                "Domains are never guessed.",
            )
        )
    else:
        official.append(
            _dest(
                "nse",
                "NSE",
                OFFICIAL,
                "OFFICIAL",
                "Official NSE landing (symbol type has no company page)",
                "https://www.nseindia.com/",
            )
        )
        official.append(
            _dest(
                "bse",
                "BSE",
                OFFICIAL,
                "OFFICIAL",
                "Official BSE landing (symbol type has no company page)",
                "https://www.bseindia.com/",
            )
        )

    return {
        "symbol": symbol,
        "bare": bare,
        "country": country,
        "is_index": is_index,
        "official": official,
        "research": research,
        "notice": "External research links open the original source. "
        "The terminal does not scrape or mirror proprietary research "
        "databases.",
    }


def describe_destinations() -> list[dict[str, Any]]:
    """Static directory for the Data Sources section (no symbol needed)."""
    sample = destinations("TATASTEEL.NS", "Tata Steel")
    out = []
    for group in ("official", "research"):
        for d in sample[group]:
            out.append(
                {
                    "name": d["name"],
                    "category": d["category"],
                    "badge": d["badge"],
                    "description": d["description"],
                    "example_url": d["url"],
                }
            )
    return out
