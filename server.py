"""Finance terminal HTTP server — Python stdlib only.

Serves:
  /terminal/*   the finance terminal SPA (./terminal/)
  /api/*        JSON API backed by the provider layer
  /*            the existing static portfolio site (repo root)

Run:
  python server.py [--port 8000]

Env:
  TERMINAL_DB            sqlite path (default ./terminal-data/terminal.db)
  ALPHA_VANTAGE_API_KEY  optional fundamentals feed (never sent to client)
  FUNDAMENTALS_API_KEY   alias for the above
  TERMINAL_HOST          bind host (default 0.0.0.0; localhost still reaches it)
  PORT                   port (default 8000)
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from providers import registry
from services import calculations as calc
from services import refresh, store

ROOT = os.path.dirname(os.path.abspath(__file__))
TERMINAL_DIR = os.path.join(ROOT, "terminal")

DEFAULT_SYMBOLS = [
    # India equities
    "RELIANCE.NS",
    "TATASTEEL.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "TATAMOTORS.NS",
    "ITC.NS",
    "LT.NS",
    "BHARTIARTL.NS",
    # US equities
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    # Indian indices (verified Yahoo symbols)
    "^NSEI",  # NIFTY 50
    "^NSEBANK",  # NIFTY BANK
    "^BSESN",  # SENSEX
    "^CNXIT",  # NIFTY IT
    "^CNXAUTO",  # NIFTY AUTO
    "NIFTY_FIN_SERVICE.NS",  # NIFTY FINANCIAL SERVICES
    "^CNXFMCG",  # NIFTY FMCG
    "^CNXPHARMA",  # NIFTY PHARMA
    # US + global indices
    "^GSPC",
    "^IXIC",
    "^RUT",
    "^FTSE",
    "^STOXX50E",
    "^N225",
    "^HSI",
]


def _send_json(handler: BaseHTTPRequestHandler, obj, status: int = 200) -> None:
    body = json.dumps(_redact(obj)).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler):
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _envelope_status(env: dict) -> int:
    status = env.get("status")
    if status in ("live", "delayed", "unavailable"):
        return 200
    if status == "rate_limited":
        return 429
    return 502


def _reported_num(value) -> float | None:
    """Parse a provider-reported figure; placeholders become None."""
    if value in (None, "-", "None", "N/A", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Slow-domain caches (Alpha Vantage free = 25 req/day TOTAL).
_domain_cache = refresh.TTLCache()


# ---------------------------------------------------------------------------
# Secret redaction: some upstream error texts echo the caller's API key
# (e.g. Alpha Vantage rate-limit notices include the key). Every JSON
# response is scrubbed so credential values can never reach clients.
_SECRET_VALUES: list[str] = []
for _secret_name in (
    "ALPHA_VANTAGE_API_KEY",
    "FUNDAMENTALS_API_KEY",
    "TWELVE_DATA_API_KEY",
    "INDIAN_STOCK_MARKET_API_KEY",
):
    _secret_val = (os.environ.get(_secret_name) or "").strip()
    if len(_secret_val) >= 8:
        _SECRET_VALUES.append(_secret_val)


def _redact(obj):
    """Deep-scrub provider responses: known credential values become
    [REDACTED] wherever they appear (message text, payloads, errors)."""
    if isinstance(obj, str):
        out = obj
        for _s in _SECRET_VALUES:
            if _s in out:
                out = out.replace(_s, "[REDACTED]")
        return out
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


class Handler(BaseHTTPRequestHandler):
    server_version = "FinanceTerminal/1.0"

    # -- routing -----------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path == "/api/health":
            return _send_json(self, {"ok": True, "service": "finance-terminal"})
        if path == "/api/search":
            env = registry.market_data.search(qs.get("q", [""])[0], limit=12)
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/quote":
            env = registry.market_data.get_quote(qs.get("symbol", [""])[0])
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/history":
            env = registry.history.get_historical_prices(
                qs.get("symbol", [""])[0],
                qs.get("range", ["1M"])[0],
                qs.get("interval", ["1d"])[0],
            )
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/company":
            return self._handle_company(qs)
        if path == "/api/fundamentals":
            env = registry.manager.get_statements(
                qs.get("symbol", [""])[0],
                qs.get("statement", ["income"])[0],
                qs.get("period", ["annual"])[0],
            )
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/ratios":
            return self._handle_valuation(qs)
        if path == "/api/news":
            try:
                limit = int(qs.get("limit", ["20"])[0] or 20)
            except (ValueError, TypeError):
                return _send_json(
                    self,
                    {
                        "status": "error",
                        "source": "terminal",
                        "message": "Invalid limit parameter.",
                    },
                    400,
                )
            env = self._handle_news(
                qs.get("symbol", [""])[0] or None,
                qs.get("topic", [""])[0] or None,
                limit=limit,
            )
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/actions":
            return self._handle_actions(qs)
        if path == "/api/holdings":
            env = registry.manager.get_shareholding(qs.get("symbol", [""])[0])
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/estimates":
            env = registry.estimates.get_estimates(qs.get("symbol", [""])[0])
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/earnings":
            env = registry.manager.get_earnings(qs.get("symbol", [""])[0])
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/quality":
            return self._handle_quality(qs)
        if path == "/api/ipo":
            return self._handle_cached_domain(
                "ipo:calendar",
                refresh.IPO_TTL,
                lambda: registry.fundamentals.get_ipo_calendar(),
            )
        if path == "/api/earnings-calendar":
            return self._handle_cached_domain(
                "earnings:calendar",
                refresh.IPO_TTL,
                lambda: registry.fundamentals.get_earnings_calendar(),
            )
        if path == "/api/macro":
            indicator = (qs.get("indicator", ["GDP"])[0] or "GDP").upper()
            return self._handle_cached_domain(
                f"macro:{indicator}",
                refresh.MACRO_TTL,
                lambda: registry.fundamentals.get_economic(indicator),
            )
        if path == "/api/technical":
            return self._handle_technical(qs)
        if path == "/api/screener":
            return self._handle_screener(qs)
        if path == "/api/watchlist":
            return self._handle_watchlist_list(qs)
        if path == "/api/portfolio":
            return self._handle_portfolio_list()
        if path == "/api/research":
            return self._handle_research_list(qs)
        if path == "/api/market-overview":
            return self._handle_market_overview()
        if path == "/api/providers":
            return _send_json(self, {"ok": True, **registry.providers_status()})
        return self._serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = _read_json_body(self)
        conn = store.connect()
        try:
            if path == "/api/watchlist":
                try:
                    item = store.watchlist_add(
                        conn, body.get("symbol", ""), body.get("name", "")
                    )
                except ValueError as exc:
                    return _send_json(self, {"ok": False, "error": str(exc)}, 400)
                return _send_json(self, {"ok": True, "item": item})
            if path == "/api/portfolio":
                try:
                    item = store.portfolio_upsert(
                        conn,
                        body.get("symbol", ""),
                        body.get("quantity", 0),
                        body.get("avg_price", 0),
                        body.get("name", ""),
                    )
                except (ValueError, TypeError) as exc:
                    return _send_json(self, {"ok": False, "error": str(exc)}, 400)
                return _send_json(self, {"ok": True, "item": item})
            if path == "/api/research":
                try:
                    item = store.research_save(
                        conn,
                        body.get("symbol", ""),
                        body.get("section", "thesis"),
                        body.get("title", ""),
                        body.get("body", ""),
                        body.get("id"),
                    )
                except (ValueError, TypeError) as exc:
                    return _send_json(self, {"ok": False, "error": str(exc)}, 400)
                return _send_json(self, {"ok": True, "item": item})
            if path == "/api/watchlist/reorder":
                symbols = body.get("symbols", [])
                if not isinstance(symbols, list):
                    return _send_json(
                        self, {"ok": False, "error": "symbols[] required"}, 400
                    )
                store.watchlist_reorder(conn, symbols)
                return _send_json(self, {"ok": True})
        finally:
            conn.close()
        return _send_json(self, {"ok": False, "error": "unknown endpoint"}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        conn = store.connect()
        try:
            if path == "/api/watchlist":
                store.watchlist_remove(conn, qs.get("symbol", [""])[0])
                return _send_json(self, {"ok": True})
            if path == "/api/portfolio":
                store.portfolio_remove(conn, qs.get("symbol", [""])[0])
                return _send_json(self, {"ok": True})
            if path == "/api/research":
                try:
                    store.research_delete(conn, qs.get("id", [""])[0])
                except (ValueError, TypeError) as exc:
                    return _send_json(self, {"ok": False, "error": str(exc)}, 400)
                return _send_json(self, {"ok": True})
        finally:
            conn.close()
        return _send_json(self, {"ok": False, "error": "unknown endpoint"}, 404)

    # PUT is treated like POST for reorder convenience
    def do_PUT(self):
        return self.do_POST()

    # -- domain handlers ----------------------------------------------
    def _handle_watchlist_list(self, qs):
        conn = store.connect()
        try:
            items = store.watchlist_all(conn)
        finally:
            conn.close()
        enriched = []
        for it in items:
            quote_env = registry.market_data.get_quote(it["symbol"])
            q = quote_env.get("data") if quote_env.get("data") else None
            enriched.append(
                {
                    "symbol": it["symbol"],
                    "name": it.get("name") or (q or {}).get("name"),
                    "quote": q,
                    "quote_status": quote_env.get("status"),
                }
            )
        return _send_json(self, {"ok": True, "items": enriched})

    def _handle_portfolio_list(self):
        conn = store.connect()
        try:
            rows = store.portfolio_all(conn)
        finally:
            conn.close()
        positions = []
        for r in rows:
            quote_env = registry.market_data.get_quote(r["symbol"])
            q = quote_env.get("data") if quote_env.get("data") else None
            px = q.get("price") if q else None
            pos = calc.portfolio_position(
                float(r["quantity"]), float(r["avg_price"]), px
            )
            positions.append(
                {
                    "symbol": r["symbol"],
                    "name": r.get("name") or (q or {}).get("name"),
                    **pos,
                    "quote_status": quote_env.get("status"),
                }
            )
        return _send_json(self, {"ok": True, **calc.portfolio_summary(positions)})

    def _handle_research_list(self, qs):
        conn = store.connect()
        try:
            notes = store.research_list(conn, qs.get("symbol", [""])[0])
        finally:
            conn.close()
        return _send_json(self, {"ok": True, "notes": notes})

    def _handle_market_overview(self):
        from concurrent.futures import ThreadPoolExecutor

        def one(sym):
            env = registry.market_data.get_quote(sym)
            return {
                "symbol": sym,
                "status": env.get("status"),
                "quote": env.get("data"),
            }

        with ThreadPoolExecutor(max_workers=8) as pool:
            out = list(pool.map(one, DEFAULT_SYMBOLS))
        return _send_json(self, {"ok": True, "items": out})

    def _handle_company(self, qs):
        """Company profile via the orchestrator: AV overview + TD
        statistics + quote-chain identity, reconciled per field."""
        symbol = (qs.get("symbol", [""])[0] or "").strip().upper()
        quote_env = registry.market_data.get_quote(symbol)
        env = registry.manager.get_profile(symbol, quote_env)
        return _send_json(self, env, _envelope_status(env))

    def _handle_actions(self, qs):
        symbol = (qs.get("symbol", [""])[0] or "").strip().upper()
        env = registry.manager.get_actions(symbol)
        return _send_json(self, env, _envelope_status(env))

    def _handle_valuation(self, qs):
        """Valuation via the orchestrator. data keeps the flat overview
        shape the UI reads (r.PERatio ...), plus metrics + reconciliation."""
        symbol = (qs.get("symbol", [""])[0] or "").strip().upper()
        quote_env = registry.market_data.get_quote(symbol)
        env = registry.manager.get_valuation(symbol, quote_env)
        if env.get("status") != "live":
            return _send_json(self, env, _envelope_status(env))
        metrics = (env.get("data") or {}).get("metrics") or {}
        overview = (env.get("data") or {}).get("overview") or {}
        out = dict(env)
        out["data"] = overview
        out["valuation"] = metrics
        return _send_json(self, out, _envelope_status(out))

    def _handle_quality(self, qs):
        """Data Quality panel: per-provider connectivity, last response,
        capabilities, budgets — never key values."""
        symbol = (qs.get("symbol", [""])[0] or "").strip().upper()
        chain_health = {}
        for chain in (registry.market_data, registry.history):
            try:
                chain_health.update(chain.health())
            except Exception:
                continue
        rows = []
        for p in registry.providers_status().get("providers", []):
            pid = p.get("id")
            h = chain_health.get(pid, {})
            rows.append(
                {
                    "id": pid,
                    "label": p.get("label"),
                    "state": p.get("state"),
                    "detail": p.get("detail"),
                    "capabilities": p.get("capabilities"),
                    "last_ok": h.get("last_ok"),
                    "last_error": h.get("last_error"),
                    "last_latency_ms": h.get("last_latency_ms"),
                    "consecutive_errors": h.get("consecutive_errors", 0),
                }
            )
        summary = None
        if symbol:
            q = registry.manager.get_quote(symbol)
            rec = (q.get("reconciliation") or {}).get("summary")
            summary = {
                "symbol": symbol,
                "quote_source": q.get("source"),
                "quote_status": q.get("status"),
                "quote_timeliness": q.get("timeliness"),
                "reconciliation": rec,
            }
        return _send_json(
            self,
            {"ok": True, "symbol": symbol or None, "providers": rows, "quote": summary},
        )

    def _handle_cached_domain(self, cache_key: str, ttl: float, fetch):
        """Slow-domain wrapper: serve TTLCache unless refresh is allowed."""
        hit = _domain_cache.get(cache_key)
        if hit is not None:
            env = dict(hit)
            env["served_from"] = "cache"
            return _send_json(self, env, _envelope_status(env))
        env = fetch()
        if env.get("status") == "live":
            _domain_cache.set(cache_key, env, ttl)
            env = dict(env)
        env["served_from"] = "provider"
        return _send_json(self, env, _envelope_status(env))

    def _handle_news(self, symbol, topic, limit: int = 20):
        """NEWS via the orchestrator: Yahoo RSS + AV sentiment, deduped."""
        env = registry.manager.get_news(symbol, topic, limit)
        return env

    def _handle_technical(self, qs):
        """CALCULATED technicals from verified daily history."""
        from services import technicals as _t

        symbol = (qs.get("symbol", [""])[0] or "").strip().upper()
        bench = (qs.get("bench", [""])[0] or "").strip().upper()
        if not symbol:
            return _send_json(
                self,
                {"status": "error", "source": "terminal", "message": "symbol required"},
                400,
            )
        cache_key = f"technical:{symbol}:{bench}"
        hit = _domain_cache.get(cache_key)
        if hit is not None:
            env = dict(hit)
            env["served_from"] = "cache"
            return _send_json(self, env, _envelope_status(env))
        hist = registry.history.get_historical_prices(symbol, "1Y", "1d")
        if not hist.get("data") or not (hist["data"].get("bars") or []):
            env = {
                "status": "unavailable",
                "source": hist.get("source", "history"),
                "as_of": None,
                "data": None,
                "message": f"Technicals need history: {hist.get('message')}",
                "served_from": "none",
            }
            return _send_json(self, env, _envelope_status(env))
        bars = hist["data"]["bars"]
        closes = [b.get("c") for b in bars]
        highs = [b.get("h") for b in bars]
        lows = [b.get("l") for b in bars]
        bench_closes = None
        bench_source = None
        if bench:
            bh = registry.history.get_historical_prices(bench, "1Y", "1d")
            if bh.get("data") and bh["data"].get("bars"):
                bbars = {b["t"]: b.get("c") for b in bh["data"]["bars"]}
                bench_closes = [bbars.get(b["t"]) for b in bars]
                bench_source = bh.get("source")
        snap = _t.compute_all(
            closes,
            highs,
            lows,
            bench_closes,
            source=f"history:{hist.get('source')}",
        )
        snap["symbol"] = symbol
        snap["benchmark"] = bench or None
        snap["benchmark_source"] = bench_source
        snap["history_range"] = hist["data"].get("range")
        env = {
            "status": "live",
            "source": "terminal-calc",
            "as_of": snap["calculated_at"],
            "timeliness": "CALCULATED",
            "timeliness_note": (
                "Calculated locally from verified backend history "
                f"({hist.get('source')}); not provider-reported."
            ),
            "data": snap,
            "message": None,
            "served_from": "calculated",
        }
        _domain_cache.set(cache_key, env, refresh.TECHNICAL_TTL)
        return _send_json(self, env, _envelope_status(env))

    def _handle_screener(self, qs):
        """Real screener over verified data only.

        Quote-backed: min/max change_pct, min/max price, min_volume.
        Technical (CALCULATED from backend history): rsi_min/max,
          above_sma (20/50/200). Fundamental (REPORTED, Alpha Vantage
          overview cached 24 h, consumes the 25/day free quota):
          max_pe, min_roe.
        Missing values exclude the symbol with a reason — never invented.
        """
        raw = qs.get("symbols", [""])[0]
        symbols = [
            s.strip().upper() for s in raw.split(",") if s.strip()
        ] or DEFAULT_SYMBOLS

        def _f(name):
            try:
                return float(qs.get(name, [""])[0])
            except (ValueError, IndexError):
                return None

        def _s(name):
            v = (qs.get(name, [""])[0] or "").strip()
            return v or None

        min_ch, max_ch = _f("min_change_pct"), _f("max_change_pct")
        min_px, max_px = _f("min_price"), _f("max_price")
        min_vol = _f("min_volume")
        rsi_min, rsi_max = _f("rsi_min"), _f("rsi_max")
        above_sma = _s("above_sma")  # "20" | "50" | "200"
        max_pe, min_roe = _f("max_pe"), _f("min_roe")
        want_tech = rsi_min is not None or rsi_max is not None or above_sma is not None
        want_fund = max_pe is not None or min_roe is not None
        if above_sma not in (None, "20", "50", "200"):
            return _send_json(
                self,
                {"ok": False, "error": "above_sma must be 20, 50 or 200"},
                400,
            )
        backed = ["price", "change_pct", "volume", "52w_high", "52w_low"]
        if want_tech:
            backed += ["rsi14", "sma20", "sma50", "sma200"]
        if want_fund:
            backed += ["pe_reported", "roe_reported"]
        rows = []
        for sym in symbols[:30]:
            env = registry.market_data.get_quote(sym)
            q = env.get("data")
            if not q:
                rows.append(
                    {
                        "symbol": sym,
                        "status": env.get("status"),
                        "message": env.get("message"),
                        # Unavailable symbols are excluded from
                        # filtering, with the reason attached.
                        "excluded_reason": env.get("message") or "No quote data.",
                        "pass": False,
                    }
                )
                continue
            ch, px, vol = q.get("change_pct"), q.get("price"), q.get("volume")
            row: dict = {
                "symbol": sym,
                "status": env.get("status"),
                "timeliness": env.get("timeliness"),
                "as_of": env.get("as_of"),
                "stale": bool(env.get("stale")) or refresh.is_stale(env.get("as_of")),
                "quote": q,
                "pass": True,
            }
            checks = [
                (min_ch, ch, lambda v, lim: v is not None and v >= lim),
                (max_ch, ch, lambda v, lim: v is not None and v <= lim),
                (min_px, px, lambda v, lim: v is not None and v >= lim),
                (max_px, px, lambda v, lim: v is not None and v <= lim),
                (min_vol, vol, lambda v, lim: v is not None and v >= lim),
            ]
            for lim, val, test in checks:
                if lim is not None and not test(val, lim):
                    row["pass"] = False
            if want_tech and row["pass"]:
                tech = self._screener_technical(sym)
                if tech is None:
                    row["pass"] = False
                    row["excluded_reason"] = "No verified history for technicals."
                else:
                    row["technical"] = tech["values"]
                    row["technical_kind"] = "CALCULATED"
                    v = tech["values"]
                    if rsi_min is not None and (
                        v.get("rsi14") is None or v["rsi14"] < rsi_min
                    ):
                        row["pass"] = False
                    if rsi_max is not None and (
                        v.get("rsi14") is None or v["rsi14"] > rsi_max
                    ):
                        row["pass"] = False
                    if above_sma is not None:
                        sma_v = v.get(f"sma{above_sma}")
                        if sma_v is None or px is None or px <= sma_v:
                            row["pass"] = False
            if want_fund and row["pass"]:
                fund = self._screener_fundamental(sym)
                if fund is None:
                    row["pass"] = False
                    row["excluded_reason"] = (
                        "Fundamentals need ALPHA_VANTAGE_API_KEY "
                        "(25 req/day free quota)."
                    )
                else:
                    row["fundamental"] = fund
                    row["fundamental_kind"] = "REPORTED"
                    pe_v = _reported_num(fund.get("PERatio"))
                    roe_v = _reported_num(
                        fund.get("ROE") or fund.get("ReturnOnEquityTTM")
                    )
                    if max_pe is not None and (pe_v is None or pe_v > max_pe):
                        row["pass"] = False
                    if min_roe is not None and (roe_v is None or roe_v < min_roe):
                        row["pass"] = False
            rows.append(row)
        return _send_json(
            self,
            {
                "ok": True,
                "results": [r for r in rows if r.get("pass")],
                "skipped": [r for r in rows if not r.get("pass")],
                "backed_by": backed,
                "unsupported": [
                    "market_cap",
                    "pb",
                    "roce",
                    "debt_equity",
                    "margins",
                    "growth",
                    "dividend_yield",
                    "ev_ebitda",
                ],
                "unsupported_note": "Only the backed_by metrics can filter. "
                "Fundamental screens consume Alpha Vantage free quota "
                "(25/day, cached 24 h).",
            },
        )

    def _screener_technical(self, symbol: str) -> dict | None:
        from services import technicals as _t

        key = f"screener-tech:{symbol}"
        hit = _domain_cache.get(key)
        if hit is not None:
            return hit  # type: ignore[return-value]
        hist = registry.history.get_historical_prices(symbol, "1Y", "1d")
        if not hist.get("data") or not (hist["data"].get("bars") or []):
            return None
        closes = [b.get("c") for b in hist["data"]["bars"]]
        snap = _t.compute_all(closes, source=f"history:{hist.get('source')}")
        out = {"values": snap, "as_of": snap["calculated_at"]}
        _domain_cache.set(key, out, refresh.TECHNICAL_TTL)
        return out

    def _screener_fundamental(self, symbol: str) -> dict | None:
        key = f"screener-fund:{symbol}"
        hit = _domain_cache.get(key)
        if hit is not None:
            return hit  # type: ignore[return-value]
        env = registry.fundamentals.get_ratios(symbol)
        if env.get("status") != "live" or not env.get("data"):
            return None
        _domain_cache.set(key, env["data"], refresh.FUNDAMENTALS_TTL)
        return env["data"]

    # -- static ---------------------------------------------------------
    def _serve_static(self, path: str):
        # Primary product: "/" opens the Finance Terminal.
        if path == "/":
            return self._send_file(
                os.path.join(TERMINAL_DIR, "index.html"), "text/html"
            )
        # Legacy personal portfolio site, preserved under /portfolio/.
        # Its relative links (assets/..., about.html) keep working because
        # everything stays under the /portfolio/ prefix.
        if path == "/portfolio":
            self.send_response(302)
            self.send_header("Location", "/portfolio/")
            self.end_headers()
            return
        if path.startswith("/portfolio/"):
            base = ROOT
            rel = path[len("/portfolio/") :] or "index.html"
            return self._serve_from_base(base, rel, path, spa_fallback=False)
        if path == "/terminal":
            self.send_response(302)
            self.send_header("Location", "/terminal/")
            self.end_headers()
            return
        if path.startswith("/terminal/"):
            base = TERMINAL_DIR
            rel = path[len("/terminal/") :] or "index.html"
        else:
            base = ROOT
            rel = path.lstrip("/") or "index.html"
        return self._serve_from_base(base, rel, path, spa_fallback=True)

    def _serve_from_base(self, base: str, rel: str, path: str, spa_fallback: bool):
        # block path traversal + hidden dirs
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            return _send_json(self, {"ok": False, "error": "forbidden"}, 403)
        # deployment guard: never serve secrets, VCS internals, or the
        # runtime database over HTTP (respond 404, do not confirm existence)
        if any(p.startswith(".") for p in parts):
            return _send_json(self, {"ok": False, "error": "not found"}, 404)
        if parts and parts[0].lower() == "terminal-data":
            return _send_json(self, {"ok": False, "error": "not found"}, 404)
        if parts and (
            parts[-1].lower().endswith(".db") or parts[-1].lower().startswith(".env")
        ):
            return _send_json(self, {"ok": False, "error": "not found"}, 404)
        full = os.path.abspath(os.path.join(base, *parts))
        if not full.startswith(os.path.abspath(base)):
            return _send_json(self, {"ok": False, "error": "forbidden"}, 403)
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            # SPA fallback for terminal client routes only
            if spa_fallback and path.startswith("/terminal/"):
                full = os.path.join(TERMINAL_DIR, "index.html")
            else:
                return _send_json(self, {"ok": False, "error": "not found"}, 404)
            if not os.path.isfile(full):
                return _send_json(self, {"ok": False, "error": "not found"}, 404)
        return self._send_file(full)

    def _send_file(self, full: str, ctype: str | None = None):
        ctype = ctype or mimetypes.guess_type(full)[0]
        try:
            with open(full, "rb") as fh:
                body = fh.read()
        except OSError:
            return _send_json(self, {"ok": False, "error": "read failed"}, 500)
        self.send_response(200)
        self.send_header("Content-Type", (ctype or "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("terminal: " + fmt % args + "\n")


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    port = int(os.environ.get("PORT", "8000"))
    # Default to all interfaces so container/hosted deploys (Render, etc.)
    # are reachable without extra config; localhost still works locally.
    host = os.environ.get("TERMINAL_HOST", "0.0.0.0")
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"finance-terminal on http://{host}:{port}/terminal/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
