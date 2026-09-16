"""SQLite storage for watchlist, portfolio and research notes.

Stdlib sqlite3 only. One table per domain, JSON-friendly rows.
Database path configurable via TERMINAL_DB env var (default:
./terminal-data/terminal.db next to the server).
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
  symbol TEXT PRIMARY KEY,
  name TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  added_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio (
  symbol TEXT PRIMARY KEY,
  name TEXT,
  quantity REAL NOT NULL,
  avg_price REAL NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS research (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  section TEXT NOT NULL DEFAULT 'thesis',
  title TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  updated_at INTEGER NOT NULL
);
"""


def db_path() -> str:
    return os.environ.get("TERMINAL_DB", os.path.join("terminal-data", "terminal.db"))


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or db_path()
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> int:
    return int(time.time())


# -- watchlist -------------------------------------------------------
def watchlist_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT symbol, name, position, added_at FROM watchlist ORDER BY position, added_at"
    ).fetchall()
    return [dict(r) for r in rows]


def watchlist_add(conn: sqlite3.Connection, symbol: str, name: str = "") -> dict:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol required")
    row = conn.execute(
        "SELECT symbol FROM watchlist WHERE symbol = ?", (symbol,)
    ).fetchone()
    if row is None:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM watchlist"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO watchlist (symbol, name, position, added_at) VALUES (?, ?, ?, ?)",
            (symbol, name, pos, _now()),
        )
        conn.commit()
    return {"symbol": symbol, "name": name}


def watchlist_remove(conn: sqlite3.Connection, symbol: str) -> None:
    conn.execute(
        "DELETE FROM watchlist WHERE symbol = ?", ((symbol or "").strip().upper(),)
    )
    conn.commit()


def watchlist_reorder(conn: sqlite3.Connection, symbols: list[str]) -> None:
    symbols = [(s or "").strip().upper() for s in symbols]
    for i, sym in enumerate(symbols):
        conn.execute("UPDATE watchlist SET position = ? WHERE symbol = ?", (i, sym))
    conn.commit()


# -- portfolio -------------------------------------------------------
def portfolio_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT symbol, name, quantity, avg_price FROM portfolio ORDER BY symbol"
    ).fetchall()
    return [dict(r) for r in rows]


def portfolio_upsert(
    conn: sqlite3.Connection,
    symbol: str,
    quantity: float,
    avg_price: float,
    name: str = "",
) -> dict:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol required")
    qty, px = float(quantity), float(avg_price)
    if qty < 0 or px < 0:
        raise ValueError("quantity and avg_price must be >= 0")
    conn.execute(
        "INSERT INTO portfolio (symbol, name, quantity, avg_price, updated_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(symbol) DO UPDATE SET name=excluded.name,"
        " quantity=excluded.quantity, avg_price=excluded.avg_price,"
        " updated_at=excluded.updated_at",
        (symbol, name, qty, px, _now()),
    )
    conn.commit()
    return {"symbol": symbol, "quantity": qty, "avg_price": px, "name": name}


def portfolio_remove(conn: sqlite3.Connection, symbol: str) -> None:
    conn.execute(
        "DELETE FROM portfolio WHERE symbol = ?", ((symbol or "").strip().upper(),)
    )
    conn.commit()


# -- research --------------------------------------------------------
VALID_SECTIONS = {
    "thesis",
    "business",
    "industry",
    "financials",
    "growth",
    "margins",
    "capital",
    "management",
    "governance",
    "valuation",
    "catalysts",
    "risks",
    "technical",
    "observations",
    "assumptions",
}


def research_list(conn: sqlite3.Connection, symbol: str = "") -> list[dict]:
    if symbol:
        rows = conn.execute(
            "SELECT id, symbol, section, title, body, updated_at FROM research"
            " WHERE symbol = ? ORDER BY updated_at DESC",
            (symbol.strip().upper(),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, symbol, section, title, body, updated_at FROM research"
            " ORDER BY updated_at DESC LIMIT 200"
        ).fetchall()
    return [dict(r) for r in rows]


def research_save(
    conn: sqlite3.Connection,
    symbol: str,
    section: str,
    title: str,
    body: str,
    note_id: Any = None,
) -> dict:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol required")
    section = (section or "thesis").strip().lower()
    if section not in VALID_SECTIONS:
        raise ValueError(f"unknown section '{section}'")
    if note_id:
        conn.execute(
            "UPDATE research SET section=?, title=?, body=?, updated_at=? WHERE id=?",
            (section, title or "", body or "", _now(), int(note_id)),
        )
        conn.commit()
        return {"id": int(note_id), "symbol": symbol}
    cur = conn.execute(
        "INSERT INTO research (symbol, section, title, body, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (symbol, section, title or "", body or "", _now()),
    )
    conn.commit()
    return {"id": cur.lastrowid, "symbol": symbol}


def research_delete(conn: sqlite3.Connection, note_id: Any) -> None:
    conn.execute("DELETE FROM research WHERE id = ?", (int(note_id),))
    conn.commit()
