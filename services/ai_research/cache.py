"""Research-result cache (cost control, stdlib only).

Key: ticker + date(UTC) + depth + sections + data-context hash + model.
TTL: standard 4h, deep 2h (deeper reports go stale faster relative to
cost). Explicit [RUN AI RESEARCH] bypasses the read path only when the
caller passes force=True.
"""

from __future__ import annotations

import threading
import time

_TTL = {"standard": 4 * 3600.0, "deep": 2 * 3600.0}

_lock = threading.Lock()
_store: dict[str, tuple[float, float, object]] = {}


def cache_key(
    ticker: str,
    depth: str,
    sections: list[str],
    context_hash: str,
    model: str,
    date_utc: str,
) -> str:
    return "|".join(
        [
            "airesearch",
            (ticker or "").upper(),
            date_utc,
            depth,
            ",".join(sorted(sections)),
            context_hash,
            model,
        ]
    )


def ttl_for(depth: str) -> float:
    return _TTL.get(depth, _TTL["standard"])


def get(key: str):
    with _lock:
        hit = _store.get(key)
        if hit is None:
            return None
        fetched_at, ttl, value = hit
        if time.time() - fetched_at >= ttl:
            del _store[key]
            return None
        return value


def set(key: str, value: object, depth: str) -> None:
    with _lock:
        _store[key] = (time.time(), ttl_for(depth), value)


def invalidate_ticker(ticker: str) -> int:
    prefix = f"airesearch|{(ticker or '').upper()}|"
    with _lock:
        doomed = [k for k in _store if k.startswith(prefix)]
        for k in doomed:
            del _store[k]
        return len(doomed)
