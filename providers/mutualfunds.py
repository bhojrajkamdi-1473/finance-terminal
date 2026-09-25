"""Indian mutual fund NAV leg via mfapi.in — free, no key, no rate limit.

Docs: https://www.mfapi.in/docs/ (community mirror of AMFI-published
NAV data, refreshed through the day). Endpoints used:
- GET /mf/search?q=      scheme search (code + name)
- GET /mf/{code}/latest  latest NAV + date
- GET /mf/{code}         full NAV history (for charts; capped client-side)

Honest envelopes throughout; NAV is always date-stamped, never
presented as a live tradable price.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base import error_envelope, live_envelope, unavailable

SOURCE = "mfapi"
BASE = "https://api.mfapi.in"
UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}

_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 6 * 3600.0


def _http_json(url: str, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(url, headers=UA)
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} from mfapi.in")
        except Exception as exc:  # DNS blips / transient network
            last = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"mfapi.in unreachable: {last}")


def _cache_get(key: str):
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < CACHE_TTL:
        return hit[1]
    return None


def _cache_set(key: str, value: dict) -> None:
    _cache[key] = (time.time(), value)


class MutualFundProvider:
    """MF search + NAV history. Indian schemes only, by construction."""

    name = "mfapi"
    capabilities: dict[str, bool] = {"search": True, "history": True}

    def search_schemes(self, query: str, limit: int = 10) -> dict:
        query = (query or "").strip()
        if not query:
            return unavailable(SOURCE, "Empty MF search query.")
        n = max(1, min(limit, 25))
        url = BASE + "/mf/search?q=" + urllib.parse.quote(query)
        try:
            payload = _http_json(url)
        except Exception as exc:
            return error_envelope(SOURCE, f"MF search failed: {exc}")
        results = []
        for item in (payload or [])[:n]:
            try:
                code = int(item.get("schemeCode"))
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "symbol": f"MF:{code}",
                    "code": code,
                    "name": item.get("schemeName"),
                    "type": "MF",
                    "exchange": "AMFI",
                }
            )
        if not results:
            return unavailable(SOURCE, f"No mutual fund schemes found for '{query}'.")
        return live_envelope(SOURCE, {"results": results}, delayed=True)

    def get_nav_history(self, code: int | str, max_points: int = 365) -> dict:
        try:
            code = int(str(code).removeprefix("MF:"))
        except (TypeError, ValueError):
            return unavailable(SOURCE, f"Invalid scheme code '{code}'.")
        cached = _cache_get(f"nav:{code}")
        if cached is not None:
            return cached
        try:
            payload = _http_json(f"{BASE}/mf/{code}")
        except Exception as exc:
            return error_envelope(SOURCE, f"NAV history failed for {code}: {exc}")
        if not isinstance(payload, dict) or payload.get("status") != "SUCCESS":
            return unavailable(SOURCE, f"No NAV history for scheme {code}.")
        meta = payload.get("meta") or {}
        bars = []
        for row in (payload.get("data") or [])[:max_points]:
            try:
                nav = float(str(row.get("nav")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            bars.append({"date": row.get("date"), "nav": nav})
        if not bars:
            return unavailable(SOURCE, f"No NAV points for scheme {code}.")
        bars.sort(key=lambda b: str(b["date"] or ""))
        env = live_envelope(
            SOURCE,
            {
                "code": code,
                "scheme_name": meta.get("scheme_name"),
                "fund_house": meta.get("fund_house"),
                "scheme_type": meta.get("scheme_type"),
                "scheme_category": meta.get("scheme_category"),
                "latest_nav": bars[-1]["nav"],
                "latest_date": bars[-1]["date"],
                "bars": bars,
                "note": "AMFI-published NAV (not a live tradable price).",
            },
            delayed=True,
        )
        env["timeliness"] = "END-OF-DAY"
        _cache_set(f"nav:{code}", env)
        return env
