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


def _apply_op(val: float, op: str, v1: float, v2) -> bool:
    """Filter operators: gt/gte/lt/lte/eq/between. Exact equality uses a
    small relative tolerance so float noise never excludes a match."""
    if op == "gt":
        return val > v1
    if op == "gte":
        return val >= v1
    if op == "lt":
        return val < v1
    if op == "lte":
        return val <= v1
    if op == "eq":
        denom = abs(v1) if v1 != 0 else 1.0
        return abs(val - v1) / denom < 1e-9
    if op == "between":
        lo, hi = (v1, v2) if v1 <= v2 else (v2, v1)
        return lo <= val <= hi
    return False


# Slow-domain caches (Alpha Vantage free = 25 req/day TOTAL).
_domain_cache = refresh.TTLCache()


def _secret_values() -> list[str]:
    """Read credential values fresh on every call: keys may be configured
    after process start (tests, Render env changes), and rotation must
    take effect immediately."""
    out = []
    for _secret_name in (
        "ALPHA_VANTAGE_API_KEY",
        "FUNDAMENTALS_API_KEY",
        "TWELVE_DATA_API_KEY",
        "INDIAN_STOCK_MARKET_API_KEY",
    ):
        _secret_val = (os.environ.get(_secret_name) or "").strip()
        if len(_secret_val) >= 8:
            out.append(_secret_val)
    return out


def _redact(obj):
    """Deep-scrub provider responses: known credential values become
    [REDACTED] wherever they appear (message text, payloads, errors)."""
    if isinstance(obj, str):
        out = obj
        for _s in _secret_values():
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
        if path == "/api/research-links":
            return self._handle_research_links(qs)
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

    def _handle_research_links(self, qs):
        """Research Hub destinations: pure URL construction, zero external
        fetching. Company name comes from the cached quote chain."""
        from services import research_links as _rl

        symbol = (qs.get("symbol", [""])[0] or "").strip().upper()
        if not symbol:
            return _send_json(self, {"ok": False, "error": "symbol required"}, 400)
        name = ""
        try:
            q = registry.market_data.get_quote(symbol)
            name = (q.get("data") or {}).get("name") or ""
        except Exception:
            name = ""
        return _send_json(self, {"ok": True, **_rl.destinations(symbol, name)})

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

    # Screener metric registry: getter kind + value extractor.
    # Quote metrics are REPORTED (delayed); technical CALCULATED;
    # fundamental REPORTED (Alpha Vantage overview, quota-noted).
    SCREENER_METRICS = {
        "price": ("quote", lambda q, t, f: q.get("price")),
        "change_pct": ("quote", lambda q, t, f: q.get("change_pct")),
        "volume": ("quote", lambda q, t, f: q.get("volume")),
        "high_52w": ("quote", lambda q, t, f: q.get("fifty_two_week_high")),
        "low_52w": ("quote", lambda q, t, f: q.get("fifty_two_week_low")),
        "rsi14": ("technical", lambda q, t, f: (t or {}).get("rsi14")),
        "sma20": ("technical", lambda q, t, f: (t or {}).get("sma20")),
        "sma50": ("technical", lambda q, t, f: (t or {}).get("sma50")),
        "sma200": ("technical", lambda q, t, f: (t or {}).get("sma200")),
        "pe": ("fundamental", lambda q, t, f: _reported_num((f or {}).get("PERatio"))),
        "pb": (
            "fundamental",
            lambda q, t, f: _reported_num((f or {}).get("PriceToBookRatio")),
        ),
        "roe": (
            "fundamental",
            lambda q, t, f: _reported_num(
                (f or {}).get("ROE") or (f or {}).get("ReturnOnEquityTTM")
            ),
        ),
        "eps": ("fundamental", lambda q, t, f: _reported_num((f or {}).get("EPS"))),
        "div_yield": (
            "fundamental",
            lambda q, t, f: _reported_num((f or {}).get("DividendYield")),
        ),
        "market_cap": (
            "fundamental",
            lambda q, t, f: _reported_num((f or {}).get("MarketCapitalization")),
        ),
    }
    SCREENER_OPS = ("gt", "gte", "lt", "lte", "eq", "between")

    def _handle_screener(self, qs):
        """Rule-engine screener over verified data only.

        Rules arrive as repeated `f=metric:op:value[:value2]` params, e.g.
        f=pe:lt:25&f=roe:gt:15&f=market_cap:gt:50000. Legacy min_/max_
        scalar params are mapped to equivalent rules. Sort via
        sort_by=<metric>&sort_dir=asc|desc. Universes: all|nse|us.
        Missing values exclude the symbol with a reason — never invented.
        """
        raw = qs.get("symbols", [""])[0]
        explicit = [s.strip().upper() for s in raw.split(",") if s.strip()]
        universe = (qs.get("universe", ["all"])[0] or "all").lower()
        if explicit:
            symbols = explicit
            universe_label = f"Custom ({len(symbols)} securities)"
        elif universe == "nse":
            symbols = [s for s in DEFAULT_SYMBOLS if s.endswith((".NS", ".BO"))]
            universe_label = f"Tracked NSE ({len(symbols)} securities)"
        elif universe == "us":
            symbols = [
                s
                for s in DEFAULT_SYMBOLS
                if not s.endswith((".NS", ".BO")) and not s.startswith("^")
            ]
            universe_label = f"Tracked US ({len(symbols)} securities)"
        else:
            symbols = [s for s in DEFAULT_SYMBOLS if not s.startswith("^")]
            universe_label = f"Tracked Universe ({len(symbols)} securities)"

        def _legacy_rules():
            out = []

            def _f(name):
                try:
                    return float(qs.get(name, [""])[0])
                except (ValueError, IndexError):
                    return None

            pairs = [
                ("min_change_pct", ("change_pct", "gte")),
                ("max_change_pct", ("change_pct", "lte")),
                ("min_price", ("price", "gte")),
                ("max_price", ("price", "lte")),
                ("min_volume", ("volume", "gte")),
                ("rsi_min", ("rsi14", "gte")),
                ("rsi_max", ("rsi14", "lte")),
                ("max_pe", ("pe", "lte")),
                ("min_roe", ("roe", "gte")),
            ]
            for param, (metric, op) in pairs:
                v = _f(param)
                if v is not None:
                    out.append((metric, op, v, None))
            sma = (qs.get("above_sma", [""])[0] or "").strip()
            if sma in ("20", "50", "200"):
                out.append((f"sma{sma}", "lt", "__PRICE__", None))
            elif sma:
                return None  # invalid marker handled below
            return out

        rules: list[tuple] = []
        bad_rule = None
        for item in qs.get("f", []):
            parts = item.split(":")
            if len(parts) not in (3, 4):
                bad_rule = item
                break
            metric, op = parts[0].strip(), parts[1].strip()
            if metric not in self.SCREENER_METRICS or op not in self.SCREENER_OPS:
                bad_rule = item
                break
            try:
                v1 = float(parts[2])
                v2 = float(parts[3]) if len(parts) == 4 else None
            except ValueError:
                bad_rule = item
                break
            if op == "between" and v2 is None:
                bad_rule = item
                break
            rules.append((metric, op, v1, v2))
        if bad_rule is not None:
            return _send_json(
                self, {"ok": False, "error": f"Bad filter rule: {bad_rule}"}, 400
            )
        legacy = _legacy_rules()
        if legacy is None:
            return _send_json(
                self,
                {"ok": False, "error": "above_sma must be 20, 50 or 200"},
                400,
            )
        rules.extend(legacy)
        sort_by = (qs.get("sort_by", [""])[0] or "").strip() or None
        sort_dir = (qs.get("sort_dir", ["asc"])[0] or "asc").lower()
        if sort_by is not None and sort_by not in self.SCREENER_METRICS:
            return _send_json(
                self, {"ok": False, "error": f"Cannot sort by '{sort_by}'"}, 400
            )
        if sort_dir not in ("asc", "desc"):
            return _send_json(
                self, {"ok": False, "error": "sort_dir must be asc or desc"}, 400
            )
        need_tech = any(
            self.SCREENER_METRICS[m][0] == "technical" for m, _, _, _ in rules
        ) or sort_by in ("rsi14", "sma20", "sma50", "sma200")
        need_fund = any(
            self.SCREENER_METRICS[m][0] == "fundamental" for m, _, _, _ in rules
        ) or sort_by in ("pe", "pb", "roe", "eps", "div_yield", "market_cap")
        backed = ["price", "change_pct", "volume", "high_52w", "low_52w"]
        if need_tech:
            backed += ["rsi14", "sma20", "sma50", "sma200"]
        if need_fund:
            backed += ["pe", "pb", "roe", "eps", "div_yield", "market_cap"]
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
                        "excluded_reason": env.get("message") or "No quote data.",
                        "pass": False,
                    }
                )
                continue
            row: dict = {
                "symbol": sym,
                "status": env.get("status"),
                "timeliness": env.get("timeliness"),
                "as_of": env.get("as_of"),
                "stale": bool(env.get("stale")) or refresh.is_stale(env.get("as_of")),
                "quote": q,
                "pass": True,
            }
            tech = fund = None
            if need_tech:
                tech = self._screener_technical(sym)
                if tech is None:
                    row["pass"] = False
                    row["excluded_reason"] = "No verified history for technicals."
                    rows.append(row)
                    continue
                row["technical"] = tech["values"]
                row["technical_kind"] = "CALCULATED"
            if need_fund:
                fund = self._screener_fundamental(sym)
                if fund is None:
                    row["pass"] = False
                    row["excluded_reason"] = (
                        "Fundamentals need ALPHA_VANTAGE_API_KEY "
                        "(25 req/day free quota)."
                    )
                    rows.append(row)
                    continue
                row["fundamental"] = fund
                row["fundamental_kind"] = "REPORTED"
            for metric, op, v1, v2 in rules:
                _, get = self.SCREENER_METRICS[metric]
                if metric.startswith("sma") and v1 == "__PRICE__":
                    pv, sv = (
                        q.get("price"),
                        get(q, tech["values"] if tech else None, fund),
                    )
                    ok = pv is not None and sv is not None and pv > sv
                else:
                    val = get(q, tech["values"] if tech else None, fund)
                    ok = val is not None and _apply_op(val, op, v1, v2)
                if not ok:
                    row["pass"] = False
                    break
            if sort_by:
                _, get = self.SCREENER_METRICS[sort_by]
                row["_sort"] = get(q, tech["values"] if tech else None, fund)
            rows.append(row)
        results = [r for r in rows if r.get("pass")]
        if sort_by:
            results.sort(
                key=lambda r: (
                    r.get("_sort") is None,
                    r.get("_sort") if r.get("_sort") is not None else 0,
                ),
                reverse=(sort_dir == "desc"),
            )
        return _send_json(
            self,
            {
                "ok": True,
                "universe": universe_label,
                "coverage": len(symbols[:30]),
                "results": results,
                "skipped": [r for r in rows if not r.get("pass")],
                "backed_by": backed,
                "unsupported": ["sector", "industry", "margins", "growth"],
                "unsupported_note": "Sector/industry screens need a "
                "fundamentals feed with classification data; only the "
                "backed_by metrics can filter. Fundamental screens consume "
                "Alpha Vantage free quota (25/day, cached 24 h).",
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
