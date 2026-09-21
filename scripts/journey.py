"""End-to-end journey verification with headless Chrome (real DOM + console).

Boots the terminal in production mode (PORT/HOST env, throwaway DB),
then for each route asserts rendered markers in the post-JS DOM,
fails on any uncaught console error, and saves screenshots.

Run: python scripts/journey.py [--port 8200] [--keep]
Exit 0 only if every journey step passes.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

ROUTES = [
    ("dashboard", "dashboard", ["Dashboard", "Movers — tracked universe"]),
    ("markets", "markets", ["Markets", "RELIANCE.NS"]),
    ("screener", "screener", ["Screener", "Apply filters"]),
    ("companies", "companies", ["Companies", "Search"]),
    (
        "company-overview",
        "company/RELIANCE.NS",
        ["RELIANCE", "Overview", "Last updated", "52W high", "Research Hub"],
    ),
    (
        "company-meta",
        "company/META",
        ["META", "Overview", "Last updated"],
    ),
    (
        "company-msft",
        "company/MSFT",
        ["MSFT", "Overview", "Last updated"],
    ),
    (
        "company-charts",
        "company/RELIANCE.NS/Charts",
        ["1Y", "SMA20", "TradingView"],
    ),
    (
        "company-technicals",
        "company/RELIANCE.NS/Technicals",
        ["Technical regime", "Trend template", "Methodology"],
    ),
    (
        "company-earnings",
        "company/RELIANCE.NS/Earnings",
        ["Earnings"],
    ),
    ("company-financials", "company/RELIANCE.NS/Financials", ["Financial statements"]),
    ("company-valuation", "company/RELIANCE.NS/Valuation", ["Valuation"]),
    ("company-news", "company/RELIANCE.NS/News", ["News"]),
    ("watchlist", "watchlist", ["Watchlist"]),
    ("portfolio", "portfolio", ["Portfolio", "Add / update holding"]),
    ("news", "news", ["News", "Research feed"]),
    ("research", "research", ["Research"]),
    ("compare", "compare", ["Compare"]),
    ("macro", "macro", ["Macro"]),
    ("settings", "settings", ["Data providers", "Refresh policy", "Twelve Data"]),
]


def api(base, path, method="GET", data=None, timeout=40):
    req = urllib.request.Request(base + path, method=method)
    body = None
    if data is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def chrome_dump(url, shot_path, timeout=120):
    profile = tempfile.mkdtemp(prefix="chrome-prof-")
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--user-data-dir={profile}",
        "--window-size=1600,1000",
        "--virtual-time-budget=30000",
        "--enable-logging=stderr",
        "--log-level=0",
        f"--screenshot={shot_path}",
        "--dump-dom",
        url,
    ]
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return p


def main(argv):
    port = 8200
    keep = False
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
        if a == "--keep":
            keep = True
    work = tempfile.mkdtemp(prefix="journey-")
    shots = os.path.join(work, "shots")
    os.makedirs(shots, exist_ok=True)
    env = dict(os.environ)
    env["PORT"] = str(port)
    env["TERMINAL_HOST"] = "127.0.0.1"
    env["TERMINAL_DB"] = os.path.join(work, "journey.db")
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "server.py")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    failures = []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=5).read()
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("FAIL  server did not start")
            return 1

        def check(name, cond, detail=""):
            print(
                ("PASS  " if cond else "FAIL  ")
                + name
                + (f" ({detail})" if detail and not cond else "")
            )
            if not cond:
                failures.append(name)

        # ---- API journey ------------------------------------------------
        code, body = api(base, "/api/search?q=reliance")
        check(
            "api: search returns live results",
            code == 200
            and body.get("status") == "live"
            and bool(body.get("data", {}).get("results")),
            str(body)[:150],
        )
        code, body = api(base, "/api/quote?symbol=RELIANCE.NS")
        price = (body.get("data") or {}).get("price")
        check(
            "api: quote has real price + delayed label",
            code == 200
            and body.get("status") == "delayed"
            and isinstance(price, (int, float)),
            str(body)[:200],
        )
        check(
            "api: quote carries currency+source",
            bool((body.get("data") or {}).get("currency"))
            and body.get("source") in ("yahoo", "indian-api"),
        )
        code, body = api(base, "/api/history?symbol=RELIANCE.NS&range=1M&interval=1d")
        bars = (body.get("data") or {}).get("bars", [])
        check(
            "api: history bars are real OHLCV",
            code == 200
            and len(bars) > 10
            and all(b.get("c") is not None for b in bars[:5]),
            f"n={len(bars)}",
        )
        code, body = api(base, "/api/ratios?symbol=RELIANCE.NS")
        # No-auth Indian leg covers NSE ratios without keys: live with
        # real reported fields, else honest unavailable — never fabricated.
        if body.get("status") in ("live", "delayed"):
            _rdata = body.get("data") or {}
            check(
                "api: ratios report real NSE fundamentals without key",
                code == 200
                and isinstance(_rdata.get("MarketCapitalization"), (int, float))
                and isinstance(_rdata.get("PERatio"), (int, float)),
                str(body)[:150],
            )
        else:
            check(
                "api: ratios honestly unavailable without key",
                code == 200 and body.get("status") == "unavailable",
                str(body)[:150],
            )
        code, body = api(base, "/api/estimates?symbol=RELIANCE.NS")
        check(
            "api: estimates never fabricated",
            code == 200 and body.get("status") == "unavailable",
        )
        code, body = api(base, "/api/screener?min_change_pct=-50")
        check(
            "api: screener runs on live quotes",
            code == 200 and body.get("ok") is True and "unsupported" in body,
            str(body)[:150],
        )
        api(
            base,
            "/api/watchlist",
            method="POST",
            data={"symbol": "JOURNEY.NS", "name": "Journey"},
        )
        code, body = api(base, "/api/watchlist")
        check(
            "api: watchlist persists",
            any(i["symbol"] == "JOURNEY.NS" for i in body.get("items", [])),
        )
        api(base, "/api/watchlist?symbol=JOURNEY.NS", method="DELETE")
        api(
            base,
            "/api/portfolio",
            method="POST",
            data={"symbol": "JOURNEY.NS", "quantity": 5, "avg_price": 10},
        )
        code, body = api(base, "/api/portfolio")
        row = next(
            (p for p in body.get("positions", []) if p["symbol"] == "JOURNEY.NS"), {}
        )
        check(
            "api: portfolio math (5x10=50 invested)",
            row.get("invested_value") == 50.0,
            str(row)[:150],
        )
        api(base, "/api/portfolio?symbol=JOURNEY.NS", method="DELETE")
        api(
            base,
            "/api/research",
            method="POST",
            data={
                "symbol": "JOURNEY.NS",
                "section": "risks",
                "title": "j",
                "body": "jb",
            },
        )
        code, body = api(base, "/api/research?symbol=JOURNEY.NS")
        check(
            "api: research notes round-trip",
            any(n["body"] == "jb" for n in body.get("notes", [])),
        )

        # ---- secrets scan -------------------------------------------------
        leaked = []
        for asset in [
            "",
            "js/app.js",
            "js/pages.js",
            "js/api.js",
            "js/charts.js",
            "js/analysis.js",
            "js/format.js",
            "styles.css",
        ]:
            raw = (
                urllib.request.urlopen(base + "/terminal/" + asset, timeout=20)
                .read()
                .decode("utf-8", "replace")
            )
            for pat in [
                "ALPHA_VANTAGE_API_KEY=",
                "FUNDAMENTALS_API_KEY=",
                "sk-",
                "BEGIN PRIVATE KEY",
                "passwd",
                "mongodb://",
            ]:
                if pat in raw:
                    leaked.append(f"{asset}:{pat}")
        check("security: no secrets in served frontend", not leaked, str(leaked))

        # ---- headless Chrome: DOM + console + screenshots ------------------
        for name, frag, markers in ROUTES:
            url = base + "/terminal/#/" + frag
            shot = os.path.join(shots, name + ".png")
            try:
                p = chrome_dump(url, shot)
            except Exception as e:
                check(f"page: {name} renders", False, f"chrome failed: {e}")
                continue
            dom = p.stdout or ""
            stderr = p.stderr or ""
            uncaught = [
                ln
                for ln in stderr.splitlines()
                if "Uncaught" in ln or "ERROR:CONSOLE" in ln
            ]
            check(
                f"page: {name} renders markers",
                all(m in dom for m in markers),
                f"missing={[m for m in markers if m not in dom]}",
            )
            check(
                f"page: {name} no uncaught console errors",
                not uncaught,
                "; ".join(uncaught[:2]),
            )
            check(
                f"page: {name} no failed API in console",
                "Failed to load resource" not in stderr and "net::" not in stderr,
                [ln for ln in stderr.splitlines() if "net::" in ln][:1],
            )
        print(f"shots: {shots}")
        if keep:
            print(f"workdir kept: {work}")
    finally:
        srv.terminate()
    print("---")
    print(f"{len(failures)} failures: {failures}" if failures else "JOURNEY: ALL PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
