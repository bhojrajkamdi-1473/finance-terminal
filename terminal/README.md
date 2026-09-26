# FINSIGHT — Financial Intelligence, Reconciled

Institutional-style equity research terminal. Zero third-party dependencies —
Python 3 stdlib on the backend, vanilla HTML/CSS/JS on the frontend.

**Open:** `http://localhost:8000/terminal/` (after starting the server).
The existing portfolio site at `/` is untouched.

## Quick start

```bash
python server.py --port 8000
# tests
python -m unittest discover -s tests -v
# smoke test (build + API + critical path, live data)
python scripts/smoke.py --port 8100
```

## Data & honesty rules

- **Live/delayed prices:** Yahoo Finance public chart/search API (no key).
  Quotes are labelled DELAYED with source + timestamp on every number.
- **Financial statements / ratios:** optional Alpha Vantage feed.
  Without `ALPHA_VANTAGE_API_KEY` these sections render
  "Provider not configured" — numbers are never invented.
- **Estimates / shareholding / IPOs:** no feed wired → explicit
  unavailable states (estimates are never synthesised).
- **News:** Yahoo Finance RSS (no key); failures show "News unavailable".
- Every envelope is `{status, source, as_of, data, message}` with
  `status ∈ live|delayed|unavailable|error`.

## Provider layer

`providers/base.py` defines the interfaces
(`MarketDataProvider`, `CompanyProvider`, `FundamentalsProvider`,
`NewsProvider`, `CorporateActionsProvider`, `EstimatesProvider`).
Swap implementations in `providers/registry.py` — the UI only speaks
envelopes. API keys live in server-side env vars, never reach the browser.

## Storage

SQLite via stdlib (`services/store.py`):
watchlist, portfolio holdings, research notes.
Path: `TERMINAL_DB` (default `./terminal-data/terminal.db`).

## API (all JSON)

`GET /api/health|search|quote|history|company|fundamentals|ratios|news|actions|estimates|screener|market-overview|watchlist|portfolio|research`
`POST /api/watchlist|portfolio|research|watchlist/reorder`
`DELETE /api/watchlist|portfolio|research`

## Deploy

Any host that runs Python 3.10+: copy the repo, set env from
`.env.example`, run `python server.py --port $PORT`.
No build step, no npm, no secrets in the repo.
