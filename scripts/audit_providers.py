"""Live provider audit — verifies real connectivity, symbol resolution,
rate limits and plan restrictions for every configured feed.

Reads real env keys but NEVER prints them. Only the configured-state
booleans leave this script.

Run:  python scripts/audit_providers.py [TATASTEEL.NS MSFT ...]
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

UA = {"User-Agent": "Mozilla/5.0 (finance-terminal audit tool)"}

SYMBOLS = ["TATASTEEL.NS", "MSFT"]


def _has(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def _timeit(fn):
    t0 = time.time()
    try:
        out = fn()
        err = None
    except Exception as exc:  # noqa: BLE001
        out, err = None, exc
    return out, err, round((time.time() - t0) * 1000, 1)


def probe_yahoo(provider, symbol: str) -> dict:
    env, err, ms = _timeit(lambda: provider.get_quote(symbol))
    if err is not None:
        return {"provider": "yahoo", "symbol": symbol, "status": "crash",
                "latency_ms": ms, "message": f"{type(err).__name__}: {err}"}
    q = env.get("data") or {}
    return {
        "provider": "yahoo",
        "symbol": symbol,
        "status": env.get("status"),
        "latency_ms": ms,
        "price": q.get("price"),
        "echoed_symbol": q.get("symbol"),
        "currency": q.get("currency"),
        "timeliness": env.get("timeliness"),
        "message": env.get("message"),
    }


def probe_twelvedata(provider, symbol: str) -> dict:
    env, err, ms = _timeit(lambda: provider.get_quote(symbol))
    if err is not None:
        return {"provider": "twelvedata", "symbol": symbol, "status": "crash",
                "latency_ms": ms, "message": f"{type(err).__name__}: {err}"}
    q = env.get("data") or {}
    return {
        "provider": "twelvedata",
        "symbol": symbol,
        "status": env.get("status"),
        "latency_ms": ms,
        "price": q.get("price"),
        "echoed_symbol": q.get("symbol"),
        "currency": q.get("currency"),
        "timeliness": env.get("timeliness"),
        "message": env.get("message"),
    }


def probe_alphavantage(provider, symbol: str) -> dict:
    """AV quote probe. Uses GLOBAL_QUOTE only (cheap, resolves symbol
    first via cached discovery when needed)."""
    from providers.fundamentals import _av_get

    out = {"provider": "alphavantage", "symbol": symbol}

    def quote_call():
        py = _av_get({"function": "GLOBAL_QUOTE", "symbol": symbol})
        info = (
            str(py.get("Information") or "")
            if isinstance(py, dict)
            else ""
        )
        if info and "premium" in info.lower():
            out["plan_block"] = "premium-required"
            return {"status": "unavailable",
                    "message": info[:200]}
        gq = (py or {}).get("Global Quote") or {}
        if not gq:
            return {"status": "unavailable",
                    "message": str((py or {}).get("Note") or (py or {}).get(
                        "Information") or "no quote")[:200]}
        return {"status": "live",
                "price": (gq.get("05. price") or "").strip(),
                "echoed_symbol": (gq.get("01. symbol") or "").strip()}

    try:
        env, err, ms = _timeit(quote_call)
    except Exception as exc:  # noqa: BLE001
        out.update({"status": "crash", "latency_ms": ms,
                    "message": f"{type(exc).__name__}: {exc}"})
        return out
    out["latency_ms"] = ms
    if err is not None:
        out.update({"status": "crash", "message": f"{type(err).__name__}: {err}"})
        return out
    out.update(env)
    return out


def probe_av_resolution(symbol: str) -> dict:
    from providers import symbols as _sym
    from providers.fundamentals import _av_get

    def _search(query: str) -> list[dict]:
        try:
            py = _av_get({"function": "SYMBOL_SEARCH", "keywords": query})
            return [
                {"symbol": m.get("1. symbol"), "name": m.get("2. name")}
                for m in (py.get("bestMatches") or [])
                if isinstance(m, dict) and m.get("1. symbol")
            ]
        except Exception:
            return []

    res = _sym.resolve_alphavantage(symbol, _search)
    return {"provider": "alphavantage", "symbol": symbol,
            "resolution": res}


def probe_stooq(provider, symbol: str) -> dict:
    env, err, ms = _timeit(lambda: provider.get_historical_prices(symbol, "1M", "1d"))
    if err is not None:
        return {"provider": "stooq", "symbol": symbol, "status": "crash",
                "latency_ms": ms, "message": f"{type(err).__name__}: {err}"}
    bars = (env.get("data") or {}).get("bars") or []
    return {
        "provider": "stooq",
        "symbol": symbol,
        "status": env.get("status"),
        "latency_ms": ms,
        "bars": len(bars),
        "currency": (env.get("data") or {}).get("currency"),
        "message": env.get("message"),
    }


def probe_indianapi(symbol: str) -> dict:
    """indianapi.in hosted 'Indian Stock Market' API (X-API-Key header)."""
    key = (os.environ.get("INDIAN_STOCK_MARKET_API_KEY") or "").strip()
    out = {"provider": "indianapi.in", "symbol": symbol,
           "key_configured": bool(key)}
    if not key:
        out.update({"status": "no_key", "message": "INDIAN_STOCK_MARKET_API_KEY unset"})
        return out
    attempts = [
        ("https://dev.indianapi.in/stock", {"name": symbol.replace(".NS", "")}),
        ("https://stock.indianapi.in/stock", {"name": symbol.replace(".NS", "")}),
        ("https://dev.indianapi.in/search", {"query": symbol.replace(".NS", "")}),
    ]
    for url, params in attempts:
        def call():
            u = url + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(u, headers={**UA, "X-API-Key": key})
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode("utf-8", "replace")

        env, err, ms = _timeit(call)
        if err is not None:
            out.setdefault("attempts", []).append(
                {"url": url.split("/")[2], "latency_ms": ms,
                 "status": "unreachable", "message": f"{type(err).__name__}: {err}"}
            )
            continue
        code, text = env
        out["attempts"] = out.get("attempts") or [
            {"url": url.split("/")[2], "latency_ms": ms, "status": code,
             "status_line": text[:120].replace("\n", " ")}
        ]
        if code == 200:
            try:
                body = json.loads(text)
            except Exception:
                body = text
            out.update({"status": "live", "http": code, "latency_ms": ms,
                        "body_keys": list(body.keys()) if isinstance(body, dict)
                        else type(body).__name__,
                        "price": (body or {}).get("price")
                        if isinstance(body, dict) else None})
            return out
    return out


def main(argv: list[str]) -> int:
    symbols = argv or SYMBOLS
    from providers.fundamentals import AlphaVantageFundamentalsProvider
    from providers.indian import IndianMarketApiProvider
    from providers.stooq import StooqProvider
    from providers.twelvedata import TwelveDataProvider
    from providers.yahoo import YahooMarketDataProvider

    print("== Credentials (booleans only, values never printed) ==")
    print(f"  ALPHA_VANTAGE_API_KEY configured:     {_has('ALPHA_VANTAGE_API_KEY')}")
    print(f"  TWELVE_DATA_API_KEY configured:         {_has('TWELVE_DATA_API_KEY')}")
    print(f"  INDIAN_STOCK_MARKET_API_KEY configured: {_has('INDIAN_STOCK_MARKET_API_KEY')}")
    print()

    yah = YahooMarketDataProvider()
    td = TwelveDataProvider()
    av = AlphaVantageFundamentalsProvider()
    stooq = StooqProvider()
    ind_leg = IndianMarketApiProvider()

    results = []
    for sym in symbols:
        print(f"===== {sym} =====")
        r = probe_yahoo(yah, sym)
        results.append(r)
        print(f"  yahoo:         {r['status']:12s} {r.get('latency_ms')}ms "
              f"price={r.get('price')} echoed={r.get('echoed_symbol')}")
        r = probe_twelvedata(td, sym)
        results.append(r)
        print(f"  twelvedata:    {r['status']:12s} {r.get('latency_ms')}ms "
              f"price={r.get('price')} echoed={r.get('echoed_symbol')} "
              f"timeliness={r.get('timeliness')} msg={r.get('message')}")
        r = probe_av_resolution(sym)
        results.append(r)
        print(f"  av-resolve:    {r.get('resolution')}")
        time.sleep(1.2)
        r = probe_alphavantage(av, sym)
        results.append(r)
        print(f"  alphavantage:  {r.get('status')} {r.get('latency_ms')}ms "
              f"price={r.get('price')} echoed={r.get('echoed_symbol')} "
              f"msg={r.get('message')}")
        time.sleep(1.2)
        if sym == "MSFT":
            r = probe_stooq(stooq, sym)
            results.append(r)
            print(f"  stooq:         {r['status']:12s} {r.get('latency_ms')}ms "
                  f"bars={r.get('bars')} msg={r.get('message')}")
        if sym.endswith(".NS"):
            r = probe_indianapi(sym)
            results.append(r)
            for a in r.get("attempts", []):
                print(f"                 {a.get('url')}: {a.get('status')} "
                      f"{a.get('latency_ms')}ms {a.get('status_line') or a.get('message')}")
            print(f"  indianapi.in:  {r.get('status')} price={r.get('price')} "
                  f"body_keys={r.get('body_keys')}")
        echo = ind_leg.get_quote(sym)
        print(f"  indian-leg:    {echo.get('status')} (existing provider; "
              f"host via {ind_leg.base_url() if hasattr(ind_leg, 'base_url') else 'n/a'})")
        print()

    print("== Summary ==")
    for r in results:
        print(f"  {r['provider']:22s} {r['symbol']:12s} {str(r.get('status')):12s}"
              f" {r.get('latency_ms')}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))