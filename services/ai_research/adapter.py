"""FinanceTerminalDataAdapter: the ONLY bridge between AI research and data.

TradingAgents-style agents must never call providers directly. They call
these get_* helpers and receive normalized, provenance-aware results:

    {"ok": True/False, "data": <normalized>, "source": ...,
     "as_of": ..., "status": ..., "reason": "KEY_REQUIRED"|... }

One provider failure never raises: the adapter records the reason and
the research workflow continues with partial data.
"""

from __future__ import annotations

from typing import Any


def _safe(fn, *args, **kwargs) -> dict:
    try:
        env = fn(*args, **kwargs)
        if not isinstance(env, dict):
            return {"ok": False, "reason": "EMPTY_RESPONSE", "detail": "Bad envelope."}
        status = env.get("status")
        if status in ("live", "delayed"):
            return {
                "ok": True,
                "data": env.get("data"),
                "source": env.get("source"),
                "as_of": env.get("as_of"),
                "status": status,
                "timeliness": env.get("timeliness"),
                "providers_queried": env.get("providers_queried"),
                "reconciliation": env.get("reconciliation"),
            }
        return {
            "ok": False,
            "reason": _classify(env),
            "detail": str(env.get("message") or env.get("status") or "unavailable")[:300],
            "source": env.get("source"),
            "as_of": env.get("as_of"),
            "status": status,
        }
    except Exception as exc:
        return {"ok": False, "reason": "TIMEOUT" if "timed out" in str(exc).lower() else "ERROR", "detail": str(exc)[:200]}


def _classify(env: dict) -> str:
    msg = str(env.get("message") or "").upper()
    if "KEY" in msg and ("NOT CONFIGURED" in msg or "REQUIRED" in msg or "MISSING" in msg):
        return "KEY_REQUIRED"
    if "QUOTA" in msg or "25/DAY" in msg or "BUDGET" in msg or "RATE" in msg or env.get("status") == "rate_limited":
        return "PLAN_LIMITATION"
    if "TIMEOUT" in msg or env.get("code") == "TIMEOUT":
        return "TIMEOUT"
    if env.get("status") == "unavailable":
        return "UNAVAILABLE"
    return "ERROR"


class FinanceTerminalDataAdapter:
    """Thin facade over the existing orchestrator + history chain."""

    def __init__(self, manager: Any = None, history: Any = None) -> None:
        if manager is None or history is None:
            from providers import registry as _reg

            manager = manager or _reg.manager
            history = history or _reg.history
        self.manager = manager
        self.history = history

    # -- primitives -------------------------------------------------
    def get_quote(self, symbol: str) -> dict:
        return _safe(self.manager.get_quote, symbol)

    def get_history(self, symbol: str, range_: str = "1Y", interval: str = "1d") -> dict:
        return _safe(self.history.get_historical_prices, symbol, range_, interval)

    def get_fundamentals(self, symbol: str) -> dict:
        quote_env = None
        try:
            quote_env = self.manager.get_quote(symbol)
        except Exception:
            quote_env = None
        out = _safe(self.manager.get_profile, symbol, quote_env)
        return out

    def get_financials(self, symbol: str, statement: str = "income", period: str = "annual") -> dict:
        return _safe(self.manager.get_statements, symbol, statement, period)

    def get_earnings(self, symbol: str) -> dict:
        return _safe(self.manager.get_earnings, symbol)

    def get_estimates(self, symbol: str) -> dict:
        return _safe(self.manager.get_estimates, symbol)

    def get_news(self, symbol: str, limit: int = 10) -> dict:
        return _safe(self.manager.get_news, symbol, None, limit)

    def get_actions(self, symbol: str) -> dict:
        return _safe(self.manager.get_actions, symbol)

    def get_ownership(self, symbol: str) -> dict:
        return _safe(self.manager.get_shareholding, symbol)

    def get_technicals(self, symbol: str, bench: str = "") -> dict:
        """Reuse the terminal's calculated technical engine (no rebuild)."""
        try:
            from services import technicals as _t

            hist = self.get_history(symbol, "1Y", "1d")
            if not hist.get("ok"):
                return {"ok": False, "reason": hist.get("reason", "UNAVAILABLE"), "detail": hist.get("detail")}
            bars = ((hist.get("data") or {}).get("bars")) or []
            closes = [b.get("c") for b in bars]
            highs = [b.get("h") for b in bars]
            lows = [b.get("l") for b in bars]
            vols = [b.get("v") for b in bars]
            snap = _t.compute_all(closes, highs, lows, None, source=f"history:{hist.get('source')}")
            bo = _t.breakout(closes, highs, vols)
            data = {
                "phase": _t.phase(closes),
                "relative_strength": _t.relative_strength(closes, None, bench or "", 63),
                "vcp": _t.vcp(closes, highs, lows, vols),
                "breakout": bo,
                "trend_template": _t.trend_template(closes, None, bench or ""),
                "snapshot": snap,
                "history_source": hist.get("source"),
                "calculated_at": snap.get("calculated_at"),
            }
            return {
                "ok": True,
                "data": data,
                "source": "terminal-calc",
                "as_of": snap.get("calculated_at"),
                "status": "live",
                "timeliness": "CALCULATED",
            }
        except Exception as exc:
            return {"ok": False, "reason": "ERROR", "detail": str(exc)[:200]}

    def get_valuation(self, symbol: str) -> dict:
        quote_env = None
        try:
            quote_env = self.manager.get_quote(symbol)
        except Exception:
            quote_env = None
        return _safe(self.manager.get_valuation, symbol, quote_env)
