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
from services import store

ROOT = os.path.dirname(os.path.abspath(__file__))
TERMINAL_DIR = os.path.join(ROOT, "terminal")

DEFAULT_SYMBOLS = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "TATAMOTORS.NS",
    "AAPL",
    "MSFT",
    "NVDA",
    "^NSEI",
    "^BSESN",
    "^GSPC",
    "^FTSE",
]


def _send_json(handler: BaseHTTPRequestHandler, obj, status: int = 200) -> None:
    body = json.dumps(obj).encode("utf-8")
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
    return 200 if env.get("status") in ("live", "delayed", "unavailable") else 502


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
            env = registry.market_data.get_historical_prices(
                qs.get("symbol", [""])[0],
                qs.get("range", ["1M"])[0],
                qs.get("interval", ["1d"])[0],
            )
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/company":
            env = registry.company.get_company_profile(qs.get("symbol", [""])[0])
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/fundamentals":
            env = registry.fundamentals.get_financial_statements(
                qs.get("symbol", [""])[0],
                qs.get("statement", ["income"])[0],
                qs.get("period", ["annual"])[0],
            )
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/ratios":
            env = registry.fundamentals.get_ratios(qs.get("symbol", [""])[0])
            return _send_json(self, env, _envelope_status(env))
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
            env = registry.news.get_news(
                qs.get("symbol", [""])[0] or None,
                qs.get("topic", [""])[0] or None,
                limit=limit,
            )
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/actions":
            env = registry.corporate_actions.get_corporate_actions(
                qs.get("symbol", [""])[0]
            )
            return _send_json(self, env, _envelope_status(env))
        if path == "/api/estimates":
            env = registry.estimates.get_estimates(qs.get("symbol", [""])[0])
            return _send_json(self, env, _envelope_status(env))
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

    def _handle_screener(self, qs):
        """Honest screener: only filters backed by live quote data.

        Supported: min_change_pct, max_change_pct, min_price, max_price.
        Fundamental filters (P/E, ROE, margins...) require a fundamentals
        provider and are reported as unsupported — never faked.
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

        min_ch, max_ch = _f("min_change_pct"), _f("max_change_pct")
        min_px, max_px = _f("min_price"), _f("max_price")
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
                        "pass": False,
                    }
                )
                continue
            ch = q.get("change_pct")
            px = q.get("price")
            ok = True
            if min_ch is not None and (ch is None or ch < min_ch):
                ok = False
            if max_ch is not None and (ch is None or ch > max_ch):
                ok = False
            if min_px is not None and (px is None or px < min_px):
                ok = False
            if max_px is not None and (px is None or px > max_px):
                ok = False
            rows.append(
                {"symbol": sym, "status": env.get("status"), "quote": q, "pass": ok}
            )
        return _send_json(
            self,
            {
                "ok": True,
                "results": [r for r in rows if r.get("pass")],
                "skipped": [r for r in rows if not r.get("pass")],
                "backed_by": ["price", "change_pct"],
                "unsupported": [
                    "market_cap",
                    "pe",
                    "pb",
                    "roe",
                    "roce",
                    "debt_equity",
                    "margins",
                    "growth",
                    "dividend_yield",
                    "ev_ebitda",
                ],
                "unsupported_note": "Fundamental screens require a fundamentals "
                "provider (ALPHA_VANTAGE_API_KEY).",
            },
        )

    # -- static ---------------------------------------------------------
    def _serve_static(self, path: str):
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
            # SPA fallback for terminal client routes
            if path.startswith("/terminal/"):
                full = os.path.join(TERMINAL_DIR, "index.html")
            else:
                return _send_json(self, {"ok": False, "error": "not found"}, 404)
            if not os.path.isfile(full):
                return _send_json(self, {"ok": False, "error": "not found"}, 404)
        ctype, _ = mimetypes.guess_type(full)
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
