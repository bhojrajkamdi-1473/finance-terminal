"""Smoke test: build checks + live server + critical-path API verification.

Run: python scripts/smoke.py [--port 8100] [--base http://host:port]
Exit 0 only when every check passes. Never prints PASS without testing.
"""

import json
import os
import py_compile
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn

    return deco


def http_json(base, path, method="GET", data=None, timeout=25):
    req = urllib.request.Request(
        base + path, method=method, headers={"User-Agent": "Mozilla/5.0"}
    )
    if data is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw.decode())
            except Exception:
                return r.status, {"_raw_len": len(raw)}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


@check("compile: all python files")
def c_compile(ctx):
    for dp, _, fns in os.walk(ROOT):
        if ".git" in dp:
            continue
        for fn in fns:
            if fn.endswith(".py"):
                py_compile.compile(os.path.join(dp, fn), doraise=True)


@check("tests: unittest suite green")
def c_tests(ctx):
    r = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    if r.returncode != 0:
        raise AssertionError("unittest failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])


@check("server: starts and /api/health ok")
def c_health(ctx):
    code, body = http_json(ctx["base"], "/api/health")
    assert code == 200 and body.get("ok") is True, body


@check("static: /terminal/ serves SPA shell")
def c_static(ctx):
    import urllib.request as _u

    with _u.urlopen(ctx["base"] + "/terminal/", timeout=25) as r:
        assert r.status == 200
        html = r.read().decode("utf-8", "replace")
    assert "FINANCE TERMINAL" in html, html[:200]
    # Root route opens the Finance Terminal (legacy portfolio at /portfolio/).
    with _u.urlopen(ctx["base"] + "/", timeout=25) as r:
        assert r.status == 200
        root = r.read().decode("utf-8", "replace")
    assert "FINANCE TERMINAL" in root, root[:200]
    with _u.urlopen(ctx["base"] + "/portfolio/", timeout=25) as r:
        assert r.status == 200
    for asset in (
        "js/app.js",
        "js/pages.js",
        "js/api.js",
        "js/charts.js",
        "js/analysis.js",
        "js/format.js",
        "styles.css",
    ):
        code, _ = http_json(ctx["base"], "/terminal/" + asset)
        assert code == 200, asset


@check("security: secrets/db/vcs paths are not served")
def c_blocked_paths(ctx):
    import urllib.request as _u

    for p in ("/.git/config", "/.env", "/.env.example", "/terminal-data/terminal.db"):
        try:
            with _u.urlopen(ctx["base"] + p, timeout=25) as r:
                code = r.status
        except Exception as e:
            code = getattr(e, "code", None)
        assert code in (404, 403), f"{p} -> {code}"


@check("search: 'reliance' returns results envelope")
def c_search(ctx):
    code, body = http_json(ctx["base"], "/api/search?q=reliance")
    assert code == 200, body
    assert body.get("status") in ("live", "unavailable", "error"), body
    if body.get("status") == "live":
        assert body["data"]["results"], body


@check("providers: free-mode chain checklist")
def c_providers(ctx):
    code, body = http_json(ctx["base"], "/api/providers")
    assert code == 200 and body.get("ok"), body
    ids = [p["id"] for p in body.get("providers", [])]
    for want in ("yahoo", "alphavantage", "twelvedata", "nse", "tradingview", "upstox"):
        assert want in ids, body
    assert body.get("chain", {}).get("quote") == [
        "upstox",
        "indian-api",
        "yahoo",
        "twelvedata",
        "alphavantage",
    ], body
    assert body.get("chain", {}).get("history") == [
        "upstox",
        "yahoo",
        "stooq",
        "twelvedata",
        "alphavantage",
    ], body
    # schema: status checklist only — the endpoint must never carry
    # credential values (registry only emits booleans + help text).
    for p in body.get("providers", []):
        for k in ("id", "label", "state", "detail"):
            assert k in p, p
        assert isinstance(p.get("key_configured"), bool), p


@check("quote: RELIANCE.NS envelope has price or honest status")
def c_quote(ctx):
    code, body = http_json(ctx["base"], "/api/quote?symbol=RELIANCE.NS")
    assert code in (200, 502), body
    assert body.get("status") in ("live", "delayed", "unavailable", "error"), body
    if body.get("status") in ("live", "delayed"):
        assert isinstance(body["data"]["price"], (int, float)), body


@check("history: bars array or honest status")
def c_history(ctx):
    code, body = http_json(
        ctx["base"], "/api/history?symbol=RELIANCE.NS&range=1M&interval=1d"
    )
    assert code in (200, 502), body
    if body.get("status") in ("live", "delayed"):
        bars = body["data"]["bars"]
        assert isinstance(bars, list) and len(bars) >= 5, (
            f"expected a month of daily bars, got {len(bars)}"
        )


@check("company: profile envelope")
def c_company(ctx):
    code, body = http_json(ctx["base"], "/api/company?symbol=RELIANCE.NS")
    assert code in (200, 502), body
    assert "status" in body and "source" in body, body


@check("watchlist: add -> list -> delete round-trip")
def c_watchlist(ctx):
    base = ctx["base"]
    http_json(base, "/api/watchlist?symbol=SMOKE.NS", method="DELETE")
    code, body = http_json(
        base,
        "/api/watchlist",
        method="POST",
        data={"symbol": "SMOKE.NS", "name": "Smoke"},
    )
    assert code == 200 and body.get("ok"), body
    code, body = http_json(base, "/api/watchlist")
    assert any(i["symbol"] == "SMOKE.NS" for i in body["items"]), body
    code, body = http_json(base, "/api/watchlist?symbol=SMOKE.NS", method="DELETE")
    assert body.get("ok"), body


@check("portfolio: upsert -> summary math")
def c_portfolio(ctx):
    base = ctx["base"]
    code, body = http_json(
        base,
        "/api/portfolio",
        method="POST",
        data={"symbol": "SMOKE.NS", "quantity": 10, "avg_price": 100},
    )
    assert code == 200 and body.get("ok"), body
    code, body = http_json(base, "/api/portfolio")
    row = next((p for p in body["positions"] if p["symbol"] == "SMOKE.NS"), None)
    assert row and row["invested_value"] == 1000.0, body
    http_json(base, "/api/portfolio?symbol=SMOKE.NS", method="DELETE")


@check("research: save -> list")
def c_research(ctx):
    base = ctx["base"]
    code, body = http_json(
        base,
        "/api/research",
        method="POST",
        data={
            "symbol": "SMOKE.NS",
            "section": "thesis",
            "title": "smoke",
            "body": "smoke note",
        },
    )
    assert code == 200 and body.get("ok"), body
    nid = body["item"]["id"]
    code, body = http_json(base, "/api/research?symbol=SMOKE.NS")
    assert any(n["id"] == nid for n in body["notes"]), body
    http_json(base, f"/api/research?id={nid}", method="DELETE")


@check("error states: bad range -> error envelope, not crash")
def c_errors(ctx):
    code, body = http_json(ctx["base"], "/api/history?symbol=AAPL&range=NOPE")
    assert code == 502 and body.get("status") == "error", body
    code, body = http_json(ctx["base"], "/api/estimates?symbol=AAPL")
    assert code == 200 and body.get("status") == "unavailable", body


def main(argv):
    port = 8100
    base_override = None
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
        if a == "--base" and i + 1 < len(argv):
            base_override = argv[i + 1]
    ctx = {}
    httpd = None
    if base_override:
        ctx["base"] = base_override.rstrip("/")
    else:
        tmp = tempfile.mkdtemp(prefix="smoke-")
        os.environ["TERMINAL_DB"] = os.path.join(tmp, "smoke.db")
        from http.server import ThreadingHTTPServer

        from server import Handler

        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        ctx["base"] = f"http://127.0.0.1:{port}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.5)
    failures = []
    for name, fn in CHECKS:
        try:
            fn(ctx)
            print(f"PASS  {name}")
        except Exception as e:  # noqa: BLE001
            # Console-safe: bodies may carry non-ASCII (e.g. arrows in
            # provider detail text) on cp1252 Windows consoles.
            print(f"FAIL  {name}: {str(e).encode('ascii', 'replace').decode()}"[:2000])
            failures.append(name)
    if httpd:
        httpd.shutdown()
    print("---")
    print(f"{len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed")
    if failures:
        print("FAILURES:", failures)
        return 1
    print("SMOKE: READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
