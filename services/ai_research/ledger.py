"""AI research run ledger: append-only audit trail + daily budget guard.

Concept debt (no code copied):
- Paperclip (MIT): activity/audit log, per-agent budget hard-stops.
  Every executed (non-cached) research run is recorded with its
  ticker, depth, model, context hash, stage outcomes and timestamps,
  and a daily run budget fails closed with an honest message.
- OpenBB Platform (AGPL-3.0 — deliberately NOT reused): standardized
  provider interface discipline; our adapter/registry already follows
  it, so no OpenBB code or dependency enters this stdlib-only runtime.

The ledger lives in the same SQLite file as watchlist/portfolio
(services/store.py) but owns its table, so existing domains and
their tests are untouched. Ledger failures must never break research:
all writes are best-effort and wrapped by callers.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  depth TEXT NOT NULL DEFAULT 'standard',
  sections TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '',
  context_hash TEXT NOT NULL DEFAULT '',
  stages TEXT NOT NULL DEFAULT '{}',
  grounding TEXT NOT NULL DEFAULT '{}',
  provider_count INTEGER NOT NULL DEFAULT 0,
  llm_backed INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
"""


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def _day_start_utc() -> int:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def daily_budget() -> int:
    """Max executed (non-cached) runs per UTC day. 0 = unlimited."""
    try:
        return max(0, int((os.environ.get("AI_DAILY_RUN_BUDGET") or "100").strip() or 100))
    except ValueError:
        return 100


def count_today(conn: sqlite3.Connection) -> int:
    ensure(conn)
    row = conn.execute(
        "SELECT COUNT(*) FROM ai_runs WHERE created_at >= ?", (_day_start_utc(),)
    ).fetchone()
    return int(row[0]) if row else 0


def budget_exhausted(conn: sqlite3.Connection) -> bool:
    limit = daily_budget()
    return limit > 0 and count_today(conn) >= limit


def record_run(conn: sqlite3.Connection, *, ticker: str, depth: str,
               sections: list, model: str, provider: str, context_hash: str,
               stages: dict, grounding: dict, provider_count: int,
               llm_backed: bool) -> int | None:
    """Best-effort insert. Returns row id or None on any failure."""
    try:
        ensure(conn)
        cur = conn.execute(
            "INSERT INTO ai_runs (ticker, depth, sections, model, provider,"
            " context_hash, stages, grounding, provider_count, llm_backed,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ((ticker or "").upper(), depth or "standard", ",".join(sections or []),
             model or "", provider or "", context_hash or "",
             json.dumps(stages or {}), json.dumps(grounding or {}),
             int(provider_count or 0), 1 if llm_backed else 0, int(time.time())),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        return None


def recent_runs(conn: sqlite3.Connection, ticker: str = "",
                limit: int = 20) -> list[dict]:
    """Run metadata only — never report bodies, never secrets."""
    ensure(conn)
    limit = max(1, min(int(limit or 20), 100))
    if (ticker or "").strip():
        rows = conn.execute(
            "SELECT id, ticker, depth, sections, model, provider, context_hash,"
            " stages, grounding, provider_count, llm_backed, created_at"
            " FROM ai_runs WHERE ticker = ? ORDER BY id DESC LIMIT ?",
            ((ticker or "").strip().upper(), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, ticker, depth, sections, model, provider, context_hash,"
            " stages, grounding, provider_count, llm_backed, created_at"
            " FROM ai_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sections"] = [s for s in (d.get("sections") or "").split(",") if s]
        d["llm_backed"] = bool(d.get("llm_backed"))
        out.append(d)
    return out
