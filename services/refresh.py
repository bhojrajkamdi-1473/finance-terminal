"""Refresh governance + freshness helpers.

TTL policy (single source of truth lives in providers/fallback.py):
- quotes: 30 s server-side minimum between upstream refreshes
- intraday history: 15 min; daily+ history: 4 h
- search: 10 min; news: 10 min; fundamentals: 24 h

The browser may poll every 10 s; the backend serves cache unless a
refresh is allowed, so free-tier budgets are never hammered.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo

    IST: tzinfo = ZoneInfo("Asia/Kolkata")
except Exception:  # minimal fallback if tzdata missing
    IST = timezone(timedelta(hours=5, minutes=30))

NEWS_TTL = 10 * 60.0
FUNDAMENTALS_TTL = 24 * 3600.0
QUOTE_STALE_AFTER = 120.0  # screener marks quotes older than this STALE
EARNINGS_TTL = 24 * 3600.0
IPO_TTL = 7 * 24 * 3600.0
MACRO_TTL = 7 * 24 * 3600.0
TECHNICAL_TTL = 3600.0


def now_ist_str() -> str:
    """Current time as HH:MM:SS IST (the freshness clock)."""
    return datetime.now(IST).strftime("%H:%M:%S IST")


def as_of_ist_str(as_of_iso: str | None) -> str:
    if not as_of_iso:
        return "unavailable"
    try:
        dt = datetime.fromisoformat(as_of_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST).strftime("%H:%M:%S IST")
    except (ValueError, TypeError):
        return "unavailable"


def age_seconds(as_of_iso: str | None) -> float | None:
    if not as_of_iso:
        return None
    try:
        dt = datetime.fromisoformat(as_of_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except (ValueError, TypeError):
        return None


def is_stale(as_of_iso: str | None, ttl_s: float = QUOTE_STALE_AFTER) -> bool:
    age = age_seconds(as_of_iso)
    return True if age is None else age > ttl_s


class TTLCache:
    """Tiny thread-safe TTL cache for slow domains (earnings/IPO/macro).

    Free-tier quotas (AV 25/day) make this load-bearing, not cosmetic.
    """

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, float, object]] = {}

    def get(self, key: str):
        import time

        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                return None
            fetched_at, ttl, value = hit
            if time.time() - fetched_at >= ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: object, ttl: float) -> None:
        import time

        with self._lock:
            self._store[key] = (time.time(), ttl, value)
