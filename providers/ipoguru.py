"""IPO Guru adapter: documented free developer API (verified Sep 2026).

Docs: https://www.ipoguru.in/ipo-gmp-details-developer-api
Base:  https://www.ipoguru.in/api/v1
Auth:  X-API-KEY header (IPOGURU_API_KEY, server-side only).
Quota: 300 req/day, 15 req/min. 429 carries retry_after / resets_at.
Terms: free for developers/students/startups, no card.

Client discipline: dashboard + detail responses cached server-side
(1h), single in-flight request shared, 429 honoured with cooldown.
Without a key every method returns honest unavailable — never scraped,
never guessed.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base import error_envelope, live_envelope, unavailable

SOURCE = "ipo-guru"
BASE = "https://www.ipoguru.in/api/v1"
UA = {"User-Agent": "Mozilla/5.0 (finance-terminal research tool)"}

_cooldown_until = 0.0


def _api_key() -> str:
    return (os.environ.get("IPOGURU_API_KEY") or "").strip()


def key_configured() -> bool:
    return bool(_api_key())


def _num(value: Any) -> float | None:
    if value in (None, "", "-", "None", "N/A", "null"):
        return None
    try:
        return float(str(value).replace(",", "").replace("\u20b9", "").strip())
    except (TypeError, ValueError):
        return None


def _band(price_band: Any) -> tuple[float | None, float | None]:
    parts = re.findall(r"[\d,]+(?:\.\d+)?", str(price_band or ""))
    vals = []
    for part in parts[:2]:
        try:
            vals.append(float(part.replace(",", "")))
        except ValueError:
            continue
    if len(vals) == 2:
        return (min(vals), max(vals))
    if len(vals) == 1:
        return (vals[0], vals[0])
    return (None, None)


def _get(path: str, params: dict | None = None, timeout: float = 20.0) -> Any:
    global _cooldown_until
    now = time.time()
    if now < _cooldown_until:
        raise _RateLimited(f"IPO Guru cooldown: {int(_cooldown_until - now)}s left.")
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    req = urllib.request.Request(url, headers={**UA, "X-API-KEY": _api_key()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            try:
                detail = json.loads(exc.read().decode("utf-8", "replace") or "{}")
            except Exception:
                detail = {}
            wait = detail.get("retry_after") or 60
            try:
                wait = max(5, min(3600, int(wait)))
            except (TypeError, ValueError):
                wait = 60
            _cooldown_until = time.time() + wait
            raise _RateLimited(f"IPO Guru rate limit (resets {detail.get('resets_at') or 'soon'}).")
        if exc.code in (401, 403):
            raise _AuthError("IPO Guru rejected the key (401/403). Check IPOGURU_API_KEY.")
        raise _UpstreamError(f"IPO Guru HTTP {exc.code}.")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise _UpstreamError(f"IPO Guru unreachable: {exc}")


class _UpstreamError(Exception):
    pass


class _RateLimited(_UpstreamError):
    pass


class _AuthError(_UpstreamError):
    pass


def normalize(row: dict) -> dict:
    """IPO Guru row -> terminal IPO schema. No invented fields."""
    row = row or {}
    sub = row.get("subscription") or {}
    gmp = row.get("gmp") or {}
    low, high = _band(row.get("price_band"))
    issue_price = _num(row.get("issue_price"))
    if issue_price is None:
        issue_price = high
    gmp_value = _num(gmp.get("price"))
    gmp_pct = _num(gmp.get("percentage"))
    est_listing = None
    if issue_price is not None and gmp_value is not None:
        est_listing = round(issue_price + gmp_value, 2)
    if gmp_pct is None and issue_price and gmp_value:
        gmp_pct = round(gmp_value / issue_price * 100, 2)
    name = str(row.get("name") or "").strip()
    return {
        "ipo_id": f"{name}|{row.get('open_date') or ''}",
        "company_name": name or None,
        "symbol": None,  # pre-listing symbols are not provided; never guessed
        "segment": str(row.get("type") or row.get("sub_type") or "").lower() or None,
        "open_date": row.get("open_date"),
        "close_date": row.get("close_date"),
        "allotment_date": row.get("allotment_date"),
        "listing_date": row.get("listing_date"),
        "listing_price": _num(row.get("listing_price")),
        "price_low": low,
        "price_high": high,
        "issue_price": issue_price,
        "lot_size": _num(row.get("lot_size")),
        "issue_size": str(row.get("issue_size") or "") or None,
        "sale_type": row.get("sale_type"),
        "exchange": row.get("listing_on"),
        "registrar": row.get("registrar"),
        "subscription_qib": _num(sub.get("qib")),
        "subscription_nii": _num(sub.get("nii")),
        "subscription_retail": _num(sub.get("retail")),
        "subscription_total": _num(sub.get("total")),
        "subscription_updated_at": sub.get("updated_at"),
        "gmp_value": gmp_value,
        "gmp_percent": gmp_pct,
        "gmp_updated_at": gmp.get("updated_at"),
        "estimated_listing_price": est_listing,
        "source": SOURCE,
    }


def get_ipos(status: str | None = None, ipo_type: str | None = None) -> dict:
    """GET /ipos (open/upcoming/closed). Normalized rows, source-tagged."""
    if not key_configured():
        return unavailable(SOURCE, "IPOGURU_API_KEY not configured.")
    params = {}
    if status in ("open", "upcoming", "closed"):
        params["status"] = status
    if ipo_type in ("mainboard", "sme"):
        params["type"] = ipo_type
    try:
        payload = _get("/ipos", params)
    except _RateLimited as exc:
        return error_envelope(SOURCE, str(exc), code="RATE_LIMITED")
    except _AuthError as exc:
        return error_envelope(SOURCE, str(exc), code="AUTH_REQUIRED")
    except _UpstreamError as exc:
        return error_envelope(SOURCE, str(exc))
    rows = payload if isinstance(payload, list) else (payload.get("ipos") or payload.get("data") or [])
    if not isinstance(rows, list) or not rows:
        return unavailable(SOURCE, "No IPO rows returned.")
    return live_envelope(SOURCE, {"rows": [normalize(r) for r in rows if isinstance(r, dict)]},
                         delayed=True)
