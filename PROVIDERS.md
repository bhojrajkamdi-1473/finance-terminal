# Finance Terminal — providers, analytics methodology, operations

Free-first market-data terminal. Python stdlib backend (`server.py`),
vanilla JS SPA (`terminal/`), SQLite storage, Render deployment
(`python server.py --port $PORT`, bind `0.0.0.0`).

## Provider matrix

| Provider | Capabilities | Tier | Auth | Cache TTL | Rate limit | Delay | Limitations |
|---|---|---|---|---|---|---|---|
| Yahoo Finance | quote, history, search, profile, RSS news, dividends/splits | free, no key | none | quote 30s, intraday 15m, daily 4h, search 10m | 429 backoff + 5m cooldown | delayed (~15m) | crumb-gated endpoints (options, holders, SEC) not used |
| Alpha Vantage | overview, statements, earnings, estimates, news, IPO, macro, dividends, splits, shares, quote, daily history | free, key-gated | `ALPHA_VANTAGE_API_KEY` | quotes 6h, overview 24h, statements/IPO/macro 7d, earnings/news 24h/10m | 25 req/day shared; premium notices → honest unavailable | delayed | NSE coverage discovered per symbol via SYMBOL_SEARCH; never assumed |
| Twelve Data | quote, history, search, statistics, earnings, dividends, splits, statements | free Basic, key-gated | `TWELVE_DATA_API_KEY` | quotes 30s, history 4h, statements 7d | 8 credits/min + 800/day token bucket | US real-time per plan claim, else delayed | NSE/BSE uncovered on free; statements cost ~100 credits |
| Indian Stock Market API (free, no-auth; MIT upstream v3.0) | quote, profile (sector/industry), market fundamentals: market cap, P/E, EPS, book value, dividend yield, 52W range, volume (NSE/BSE only) | free, NO key | none | quote 5m, fundamentals 24h | Yahoo crumb handshake cached ~50m; 429 → backoff + honest fallback | delayed snapshot | NO statements, NO estimates, NO earnings series, NO ownership, NO news; ROE never supplied; Indian symbols only |
| Stooq | daily history CSV (US suffix-less only) | free, no key | none | 4h (history chain) | failures → pass-through | end-of-day | bot-wall/401 → honest unavailable; mapping unverified elsewhere |
| TradingView | chart widget ONLY | embed, no key | none for widget | n/a | n/a | delayed | data feeds disabled without `TRADINGVIEW_ENABLED=1` + documented scope |
| Moneycontrol | none (research landing link) | n/a | none | n/a | n/a | n/a | site bot-gated; navigation only, never scraped |
| Google Finance | none (reference quote link) | n/a | none | n/a | n/a | n/a | navigation only for verified venue mappings |

Fallback chains — quote: indian-api → yahoo → twelvedata → alphavantage;
history: yahoo → stooq → twelvedata → alphavantage. Definitive
`unavailable` answers never trigger cooldown; transport errors cool a
leg for 5 minutes. Company domains fan out in parallel via
`ProviderManager`, normalize into `providers/schema.py` fields, and
reconcile (`CROSS_CHECK_OK` / `PROVIDER_DISCREPANCY` / `SINGLE_SOURCE` /
`NOT_COMPARABLE`, 2% tolerance, currency+period guards, never averaged).

## Analytics methodology (`services/technicals.py`, all local + labeled CALCULATED)

- **SMA 50/150/200 + slopes**: standard moving averages; slope = % change over 20 bars.
- **Phase**: Weinstein stage rules — Phase 2 = price>SMA150>SMA200, rising slopes, price within +25%/−3% of SMA200; Phase 4 = mirror below falling averages; else Phase 3/1; UNKNOWN under 200 bars. Descriptive, never a forecast.
- **Relative strength**: stock % return minus benchmark % return over 63 bars + cumulative-RS slope. Benchmark configurable (`bench` param); defaults NSE→`^NSEI`, US→`^GSPC`.
- **VCP**: swing highs with 3-bar confirmation over 150 bars; ≥2 contractions of shrinking depth (≤35% first); volume trend diagnostic. INSUFFICIENT_DATA under 60 bars.
- **Breakout**: trailing 252-bar high (excl. today), distance %, volume vs 20-day median (≥1.5× = confirmed). Statuses ABOVE/AT/BELOW_LEVEL.
- **Trend template**: 9 documented conditions (price vs SMAs, SMA relationships, slopes, 52w position, RS sign), each pass/fail/unknown.
- **Breadth**: explicit universe only (default: tracked non-index symbols), Phase 2/4 %, advancers/decliners, universe size + timestamp attached.
- **Market regime**: benchmark vs 200-day average + slope, breadth may only downgrade to MIXED. RISK_ON/RISK_OFF/MIXED/UNKNOWN, measurements exposed.
- **Risk/reward**: entry=price, stop=price−2×ATR, target=real resistance level only; labeled TECHNICAL REFERENCE, never advice; INSUFFICIENT_DATA otherwise.
- **Scoring**: equal-weighted transparent components (trend/momentum/volume/pattern/risk-reward) with value/max/state each; descriptive labels only.
- **Fundamental trends**: revenue/profit/EPS growth + net margin across aligned fiscal periods; mixed annual/quarterly → NOT_COMPARABLE.

## Research destinations (links only, never scraped)

Screener company pages (`screener.in/company/<BARE>/`, verified + 404 control),
NSE quote pages, BSE search, NSE filings archive, SEC EDGAR company search,
Trendlyne/Tickertape/Moneycontrol landings, Google Finance reference pages
(verified venue mappings only), TradingView widget. Investor-relations URLs
are shown only from verified provider metadata — otherwise explicit
"Not available". Full contract in `services/research_links.py`.

## Environment variables (names only — values never committed/logged)

`ALPHA_VANTAGE_API_KEY`, `TWELVE_DATA_API_KEY`,
`FUNDAMENTALS_API_KEY` (alias), `TRADINGVIEW_ENABLED` (data feeds stay off
unless `1` with documented scope), `TERMINAL_DB`, `TERMINAL_HOST`, `PORT`.
(The former `INDIAN_STOCK_MARKET_API_KEY` is obsolete: the Indian leg is
a free no-auth feed and ignores it.)
`.env` and `*.db` are git-ignored; every JSON response passes deep secret
redaction.

## Known limitations

- No keys configured in this environment → AV/TD honestly
  unavailable for their domains; Yahoo covers quotes/history/news/actions
  and the no-auth Indian leg covers NSE/BSE market fundamentals.
- Twelve Data free plan: no NSE/BSE coverage; statements expensive.
- Breadth universe = tracked symbols only, never presented as whole market.
