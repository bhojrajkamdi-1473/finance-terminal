# Finance Terminal — providers, analytics methodology, operations

Free-first market-data terminal. Python stdlib backend (`server.py`),
vanilla JS SPA (`terminal/`), SQLite storage, Render deployment
(`python server.py --port $PORT`, bind `0.0.0.0`).

## Provider matrix

| Provider | Capabilities | Tier | Auth | Cache TTL | Rate limit | Delay | Limitations |
|---|---|---|---|---|---|---|---|
| Upstox | quote V3, historical-candle V3, /v2/fundamentals/:isin suite (profile, statements, key-ratios, holdings, actions), /v2/news (7-day), batch quotes | key-gated analytics | `UPSTOX_ANALYTICS_TOKEN` (Bearer, server-side only) | quote 30s, news 10m, history 4h, domains 24h | 50/s + 500/min documented; TTLs + batching keep usage far below | delayed | ISIN-mapped Indian names + NSE_INDEX keys only; no trading/orders; missing key → pass-through unavailable |

### Upstox — verified endpoint inventory (official docs, Sep 2026)

Analytics Token: 1-year, read-only, GET-only, Developer Apps > Analytics,
no OAuth redirect, no static IP for market-data categories.

| Capability | Endpoint | Version | Token | Routed |
|---|---|---|---|---|
| Full market quotes (≤500 keys) | `GET /v3/market-quote/quotes?instrument_key=` | v3 | yes | quote fan-out first leg; batch API |
| Historical candles | `GET /v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}` | v3 | yes | history fan-out first leg (1d/1wk/1mo) |
| Company profile | `GET /v2/fundamentals/:isin/profile` | v2 | yes | profile sector/description fallback |
| Key ratios | `GET /v2/fundamentals/:isin/key-ratios` | v2 | yes | valuation fallback (P/E,P/B,ROE,ROA,ROCE,EV/EBITDA) |
| Income / balance / cash-flow | `GET /v2/fundamentals/:isin/{income-statement,balance-sheet,cash-flow}` | v2 | yes | statements fan-out (canonical INR reports) |
| Shareholding | `GET /v2/fundamentals/:isin/share-holdings` | v2 | yes | holdings primary (canonical ownership) |
| Corporate actions | `GET /v2/fundamentals/:isin/corporate-actions` | v2 | yes | actions merge (canonical div/split rows) |
| News (past 7 days, ≤30 keys) | `GET /v2/news?category=instrument_keys` | v2 | yes | news merge (same dedup pipeline) |
| Option chain / WebSocket / IPO apply / competitors / market-information | — | — | — | NOT integrated (no terminal need / account-bound) |

V3 quote nodes are keyed by `EXCHANGE:SYMBOL` (resolved via
`instrument_token`); statement money is INR-crore (x1e7, EPS unscaled);
errors map 401/403→AUTH, 429→rate_limited, 400/404/UDAPI1206→unavailable.
| Yahoo Finance | quote, history, search, profile, RSS news, dividends/splits | free, no key | none | quote 30s, intraday 15m, daily 4h, search 10m | 429 backoff + 5m cooldown | delayed (~15m) | crumb-gated endpoints (options, holders, SEC) not used |
| Alpha Vantage | overview, statements, earnings, estimates, news, IPO, macro, dividends, splits, shares, quote, daily history | free, key-gated | `ALPHA_VANTAGE_API_KEY` | quotes 6h, overview 24h, statements/IPO/macro 7d, earnings/news 24h/10m | 25 req/day shared; premium notices → honest unavailable | delayed | NSE coverage discovered per symbol via SYMBOL_SEARCH; never assumed |
| Twelve Data | quote, history, search, statistics, earnings, dividends, splits, statements | free Basic, key-gated | `TWELVE_DATA_API_KEY` | quotes 30s, history 4h, statements 7d | 8 credits/min + 800/day token bucket | US real-time per plan claim, else delayed | NSE/BSE uncovered on free; statements cost ~100 credits |
| Indian Stock Market API (`stock.indianapi.in`) | quote, profile, statements (/stock + /statement + /historical_stats), history (/historical_data), actions, news, forecasts, targets, ownership (NSE/BSE only; keyed) — free no-auth fallback: quote + market fundamentals (market cap, P/E, EPS, book value, dividend yield, sector, industry, 52W) | free, keyed full / no-auth subset | `INDIAN_STOCK_MARKET_API_KEY` (x-api-key header; absent → no-auth subset) | quote 5m, domains 24h, statements 7d | 30/min + 2000/day self-imposed guard | delayed snapshot | Indian symbols only; quarterly statements only where the API returns them (never annual-substituted); ROE/margins only from keyed keyMetrics |
| Stooq | daily history CSV (US suffix-less only) | free, no key | none | 4h (history chain) | failures → pass-through | end-of-day | bot-wall/401 → honest unavailable; mapping unverified elsewhere |
| TradingView | chart widget ONLY | embed, no key | none for widget | n/a | n/a | delayed | data feeds disabled without `TRADINGVIEW_ENABLED=1` + documented scope |
| Moneycontrol | none (research landing link) | n/a | none | n/a | n/a | n/a | site bot-gated; navigation only, never scraped |
| Google Finance | none (reference quote link) | n/a | none | n/a | n/a | n/a | navigation only for verified venue mappings |

Fallback chains — quote: upstox → indian-api → yahoo → twelvedata → alphavantage;
history: upstox → yahoo → stooq → twelvedata → alphavantage. Definitive
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
`INDIAN_STOCK_MARKET_API_KEY` (keyed Indian domains; absent → free
no-auth quote + market fundamentals subset),
`FUNDAMENTALS_API_KEY` (alias), `TRADINGVIEW_ENABLED` (data feeds stay off
unless `1` with documented scope), `TERMINAL_DB`, `TERMINAL_HOST`, `PORT`.
`.env` and `*.db` are git-ignored; every JSON response passes deep secret
redaction.

## Data quality matrix (field-level superior provider)

Served live at `GET /api/data-matrix` (same table as `services/kpi.py: FIELD_PROVIDERS`).

| Data type | Best provider | Secondary | Why | Fallback | Status |
|---|---|---|---|---|---|
| Indian quotes | Upstox | Indian API | Exchange-native snapshot + ISIN identity; Yahoo cross-check | Yahoo | Upstox key-gated, else Indian-API/Yahoo |
| Global quotes | Yahoo | Twelve Data | Free global breadth; TD US real-time per plan | Alpha Vantage | live |
| Indian history | Upstox | Yahoo | Candle-V3 depth (2000+); Yahoo breadth cross-check | Indian-API historical_data | Upstox key-gated |
| Global history | Yahoo | Stooq | Range/interval breadth; US EOD fallback | Twelve Data / Alpha Vantage | live |
| Indices | Yahoo | Upstox | Verified index symbols; NSE_INDEX cross-check | none | live |
| Fundamentals | Yahoo fundamentals | Alpha Vantage | No-key timeseries, NSE+global; AV depth when keyed | Twelve Data | live |
| Ratios | Alpha Vantage | Upstox | Overview authority; ISIN key-ratios for Indian names | Yahoo fundamentals / Indian-API | mixed key-gated |
| Statements | Yahoo fundamentals | Alpha Vantage | Free annual+quarterly; audited depth when keyed | Upstox / Indian-API (ISIN) | live |
| Shareholding | Upstox | Indian API | ISIN-linked patterns; keyed Indian fallback | none | key-gated |
| Corporate actions | Upstox | Yahoo events | ISIN-linked actions; free chart-event fallback | Alpha Vantage / Twelve Data | mixed |
| News | Yahoo RSS | Alpha Vantage | Freshness + entity match; sentiment depth | Indian-API (keyed) | live |
| IPO | IPO Guru | Alpha Vantage | Lifecycle/subscription; calendar cross-check (GMP separate) | none | key-gated |
| GMP | IPO Guru | none | Dedicated GMP feed only; never synthesised | none | key-gated |
| Technical inputs | terminal-calc | none | Local calc from verified history; never provider-reported | none | live |

Centralized KPI engine (`services/kpi.py` + `GET /api/kpi`): one
normalized bundle per symbol backs the stock page, compare, screener
and research — values match everywhere. Missing metrics are omitted
(no key), never placeholder cards.

## Known limitations

- No keys configured in this environment → AV/TD honestly
  unavailable for their domains; Yahoo covers quotes/history/news/actions,
  the Indian leg covers NSE/BSE quote + market fundamentals without a key
  (statements/ownership/forecasts need the key).
- Twelve Data free plan: no NSE/BSE coverage; statements expensive.
- Breadth universe = tracked symbols only, never presented as whole market.
