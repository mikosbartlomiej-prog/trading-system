# Trading System — Product Documentation

**Wersja dokumentu:** 1.4 (2026-05-22)
**Stan systemu:** v3.9.5.1 (crypto oversold boost wired + LLM poll headroom + first live GIVEBACK_WARN verification)
**Recent increments:** 3.9.5.1 (LLM POLL_MAX_S 480→600 + SILENT-grace [x]), 3.9.5 (PR #8 crypto oversold boost merged + wired), 3.9.4 → 3.9.4.4 (daily-learning cherry-pick retry), 3.9.3.1 (politician-monitor email + sync fix), 3.9.3 (EDGAR XML discovery + 3-tier STOCK Act fallback), 3.9.2 (politician-monitor MVP), 3.9.1 (NOW + software_quality), 3.9.0 (SILENT grace), 3.8.9 (aggressive entry + equity-gap + RSI alerts), 3.8 (PDT intent-aware), 3.7 (PDT + Routine budget), 3.6 (full autonomy + Strategy Coherence Agent), 3.5 (IntradayProfitGovernor)
**Tryb:** Alpaca Paper Trading (NIE live)
**Repo:** `git@github.com:mikosbartlomiej-prog/trading-system.git`
**Branch produkcyjny:** `main`

---

## Spis treści

1. [Cel produktu i filozofia](#1-cel-produktu-i-filozofia)
2. [Architektura wysokopoziomowa](#2-architektura-wysokopoziomowa)
3. [Stos technologiczny](#3-stos-technologiczny)
4. [Serwisy zewnętrzne i konta](#4-serwisy-zewnętrzne-i-konta)
5. [Struktura repozytorium](#5-struktura-repozytorium)
6. [Workflows GitHub Actions](#6-workflows-github-actions)
7. [Monitory wejścia](#7-monitory-wejścia)
8. [Monitory wyjścia](#8-monitory-wyjścia)
9. [Learning Loop — dwustopniowa adaptacja](#9-learning-loop--dwustopniowa-adaptacja)
10. [Routines (LLM personas)](#10-routines-llm-personas)
11. [Risk management](#11-risk-management)
12. [Order execution flow](#12-order-execution-flow)
13. [Persistencja i audit trail](#13-persistencja-i-audit-trail)
14. [Cloudflare Workers](#14-cloudflare-workers)
15. [Powiadomienia email](#15-powiadomienia-email)
16. [Operacje i runbook](#16-operacje-i-runbook)
17. [Zmienne środowiskowe i sekrety](#17-zmienne-środowiskowe-i-sekrety)
18. [Migration notes — vNext (2026-05-14)](#18-migration-notes--vnext-2026-05-14-super-session)

---

## 1. Cel produktu i filozofia

### 1.1 Mission

Aktywnie zarządzany, w pełni zautomatyzowany system tradingowy operujący na koncie paper Alpaca, którego zadaniem jest **maksymalizacja zwrotu skorygowanego o ryzyko w krótkim horyzoncie** (intraday → 30 dni) poprzez kombinację:

- momentum / breakout na akcjach mega-cap + AI semis
- event-driven trades na newsach geopolitycznych, defensywnych i firmowych
- crypto predator strategy (BTC, ETH + 9 mid-cap alts)
- options momentum (entry przez RSI, exit przez TP/SL/trailing)
- sentiment monitoring (Reddit + Bluesky/Twitter)
- 4-state regime detection (RISK_ON / NEUTRAL / RISK_OFF / INFLATION_SHOCK)

### 1.2 Postawa

| Wymiar | Wartość |
|---|---|
| Apetyt na ryzyko | **Agresywny** — akceptujemy wysoką dzienną zmienność |
| Horyzont czasowy | Intraday → 30 dni |
| Wykorzystanie kapitału | **0% rezerwy gotówkowej**, aktywne wykorzystanie margin (1.5×-2.5×) |
| Koncentracja pozycji | **Wysoka** — do 40% equity w jednym tickerze |
| Częstotliwość | Cron co 5 min na większości monitorów |
| Bias | Long-biased w momentum, short na overbought reversals |

### 1.3 Twarde ograniczenia (iron rules)

1. **Paper trading TYLKO** — system nigdy nie dotyka konta live
2. **Stop-loss zawsze obowiązkowy** — żadne wejście bez SL
3. **Whitelist instrumentów** — handel poza listą `.claude/rules/tickers-whitelist.md` = abort
4. **Bez tradingu wokół earnings** — ±1 dzień, niemierzalne ryzyko event
5. **Tylko LIMIT orders** dla wejść (MARKET tylko dla emergency close)

---

## 2. Architektura wysokopoziomowa

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       GitHub Actions (cron-driven)                       │
│  • 21 workflows                                                          │
│  • Większość cron */5 lub */15 min                                       │
│  • Trzymane sekrety: Alpaca, Gmail, Anthropic, Cloudflare, Finnhub, etc.│
└──────────┬──────────────────────────────────────────────────────────────┘
           │
   ┌───────┴───────────────────────────────────────────────────────────┐
   │                                                                    │
   ▼                                                                    ▼
┌─────────────────────────┐        ┌──────────────────────────────────────┐
│  Entry monitors (×6)    │        │  Exit monitors (×3)                  │
│  • price-monitor        │        │  • exit-monitor (stocks/crypto)      │
│  • crypto-monitor       │        │  • options-exit-monitor              │
│  • defense-monitor      │        │  • emergency-close-positions         │
│  • geo-monitor          │        │                                      │
│  • twitter-monitor      │        │  → REST → Alpaca DELETE /v2/positions│
│  • reddit-monitor       │        │           POST /v2/orders MARKET     │
│  • options-monitor      │        │                                      │
└──────────┬──────────────┘        └──────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│  Shared infrastructure (shared/*.py)                          │
│  • risk_guards     — VIX, drawdown, concentration             │
│  • risk_officer    — synchronous trade validation             │
│  • alpaca_orders   — bracket + simple LIMIT placement         │
│  • instrument_wins — per-symbol trade-window gate             │
│  • peak_tracker    — intraday P&L peak + PROFIT_LOCK          │
│  • allocator       — daily capital deployment plan            │
│  • notify          — Gmail SMTP email                         │
│  • event_scoring   — 4-score credibility / reaction filter    │
│  • profile/regime  — config + 4-state regime FSM              │
└──────────────────────────────────────────────────────────────┘
           │
           ├──► Alpaca Paper REST API ──► trades executed
           ├──► Cloudflare Workers ──► Claude Routines (LLM)
           └──► Gmail SMTP ──► operator notifications

                       ┌──────────────────────────────────┐
                       │  Daily learning loop (21:00 UTC) │
                       │                                  │
                       │  analyzer.py:                    │
                       │   1. fetch 24h orders + trades   │
                       │   2. compute statistics          │
                       │   3. Senior PM round 1 (LLM)     │
                       │   4. Challenger round 2 (LLM)    │
                       │   5. Senior PM round 3 revise    │
                       │   6. adapter.adapt() heuristics  │
                       │   7. write state.json            │
                       │   8. allocator.compute_plan()    │
                       └──────────────────────────────────┘
```

### 2.1 Wzorzec rdzeniowy: monitor → guard → execute → notify

Każdy monitor wejścia:
1. Wczytuje `learning_state` (multi-day adaptive params)
2. Sprawdza `daily_drawdown_guard` (-3% blok wejść)
3. Sprawdza `vix_guard` (VIX > 60 = HALT)
4. Skanuje rynek (Alpaca daily bars + per-monitor data sources)
5. Per kandydat: `can_trade_now()` + `has_open_position()` + `concentration_ok()`
6. Per emit: `risk_officer.evaluate_trade()` (9 hard checks + 4 soft)
7. `alpaca_orders.place_*` → wysyła do Alpaca
8. `notify.notify_signal()` → email

### 2.2 Cykle uczenia

System ma **dwie pętle uczenia**:

- **Pętla szybka** (per-cron, ~5 min) — instrument_windows + state.json sprawdzenia bez LLM, deterministic
- **Pętla wolna** (daily 21:00 UTC) — 3-rundowy dialog LLM (Senior PM ↔ Challenger ↔ Revise) → modyfikuje `state.json` na następny dzień

---

## 3. Stos technologiczny

### 3.1 Język i runtime

- **Python 3.11** — wszystkie monitory, shared, learning-loop, scripts
- **Standard library + pojedyncze zależności:**
  - `requests` — HTTP do Alpaca/Cloudflare/Finnhub/Yahoo
  - `pyyaml` — parsowanie workflow templates (tylko narzędzia)
  - **Brak frameworków** (no Django, no Flask, no FastAPI) — system jest CLI-first

### 3.2 Compute

- **GitHub Actions** — cała orkiestracja
  - Ubuntu-latest runners
  - Timeout per job: 3-30 min
  - Repo public (od 2026-05-13) → unlimited minutes

### 3.3 Storage

- **Git** — pełny audit log (state.json + rationale.md + history/*.md commitowane po każdym runie)
- **GitHub commits = source of truth** dla:
  - Learning loop state (`learning-loop/state.json`)
  - Daily reports (`learning-loop/history/YYYY-MM-DD.md`)
  - Rationale append-only log (`learning-loop/rationale.md`)
  - Exit reports (`exit-reports/YYYY-MM-DD-HH.md`)
  - Health snapshots (`learning-loop/health/`)
  - Allocation plans (`learning-loop/allocations/YYYY-MM-DD.json`)
  - Trade journals (`journal/trades-YYYY-MM-DD.md`)

### 3.4 LLM

- **Anthropic Claude** via:
  - claude.ai Routines (`trig_...` endpoints) — wszystkie LLM calls
  - Modele używane:
    - `claude-opus-4-7` — Learning Loop Strategist (Senior PM), Challenger
    - `claude-haiku-4-5` lub `claude-sonnet-4-6` — Reddit Curator, Crypto Curator (filter, nie deep analysis)

### 3.5 Komunikacja

- **Cloudflare Workers** (5×) — proxy między GitHub Actions a claude.ai Routines (dodaje auth headers + anthropic-version)
- **Gmail SMTP SSL port 465** — wszystkie notyfikacje operatora
- **HTTPS Alpaca REST** — `https://paper-api.alpaca.markets`

### 3.6 Dashboard (opcjonalny)

- **Cloudflare Worker** (`dashboard/worker.js`) — vanilla JS, no build step
- Auto-refresh co 30s, czyta `/v2/account` + `/v2/positions` + `/v2/orders` + (NEW) `learning-loop/state.json` via GitHub Contents API

---

## 4. Serwisy zewnętrzne i konta

### 4.1 Alpaca Markets (Paper Trading)

| Pole | Wartość |
|---|---|
| Konto | Paper PA3KNZV29BP5 |
| Base URL | `https://paper-api.alpaca.markets` |
| Equity | ~$95,000-$100,000 |
| Buying power | ~$200,000 (Reg-T 4×) |
| Shorting | enabled |
| Options level | 3 (long/short single-leg permitted) |
| Auth headers | `APCA-API-KEY-ID` + `APCA-API-SECRET-KEY` |
| Endpointy używane | `/v2/account`, `/v2/positions`, `/v2/orders`, `/v2/positions/{symbol}` (DELETE), `/v2/options/contracts`, `/v2/stocks/{sym}/bars`, `/v2beta3/crypto/us/bars` |

**Quirki:**
- Crypto symbol format: `BTC/USD` (ze slashem)
- Crypto timeframe: `1Hour` (NIE `1H`)
- Options: paper API odrzuca bracket/OCO/stop → używamy simple LIMIT BUY, exit przez `options-exit-monitor`
- DELETE /v2/positions/{symbol} bypassuje "insufficient options buying power" bug paper API

### 4.2 Anthropic (Claude)

| Pole | Wartość |
|---|---|
| Endpoint | claude.ai Routines (`trig_...`) |
| Beta header | `anthropic-beta: experimental-cc-routine-2026-04-01` |
| Wersja | `anthropic-version: 2023-06-01` |
| Dziennie | ~3-14 calls (limit 15/day) |
| Trigger | HTTP POST z body `{"text": "<json payload>"}` |

**Routines aktualnie wdrożone (5):**

| Routine | Model | Cel | Trigger |
|---|---|---|---|
| Learning Loop Strategist | opus-4-7 | Senior PM round 1 + round 3 revise (daily + weekly retro) | `learning-loop-proxy` |
| Learning Loop Challenger | opus-4-7 | Adversarial review round 2 | `learning-loop-challenger-proxy` |
| Reddit Signal Curator | haiku-4-5 / sonnet-4-6 | Filtruje raw Reddit candidates → top 0-3 picks | `reddit-curator-proxy` |
| Crypto Signal Curator | haiku-4-5 / sonnet-4-6 | Filtruje crypto 11-coin scan → top 0-3 picks | `crypto-curator-proxy` |
| Exit Handler | opus-4-7 / sonnet | CONSIDER_TP decisions (rzadko używane od v2.2 routine bypass) | `exit-monitor-proxy` |

### 4.3 Finnhub

| Pole | Wartość |
|---|---|
| Plan | Free tier |
| Wykorzystanie | News dla geo-monitor + defense-monitor (VIX nieaktualny, fallback do Yahoo) |
| Endpoint | `https://finnhub.io/api/v1/...` |
| Limit | 60 req/min |

### 4.4 NewsAPI.org

| Pole | Wartość |
|---|---|
| Plan | Free tier |
| Wykorzystanie | defense-monitor + geo-monitor — news scrape |
| Limit | 100 req/day |

### 4.5 Yahoo Finance (`/v8/finance/chart/^VIX`)

- Bez klucza, publiczny endpoint
- Fallback dla VIX gdy Finnhub free `/quote?symbol=^VIX` zwraca 0
- Wywoływany z `shared/risk_guards.py::_vix_from_yahoo()`

### 4.6 Reddit (no-API path)

| Pole | Wartość |
|---|---|
| Endpointy | `https://www.reddit.com/r/<sub>/top.json` + `/hot.json` + `/.rss` + `/user/<u>/submitted.json` |
| Limit | ~60 req/min anonimowo |
| Proxy | Cloudflare Worker `reddit-fetch-proxy` (Reddit blokuje IP-egress data centerów) |
| User-Agent | Wymagany (custom string) |

### 4.7 Bluesky (AT-Protocol)

| Pole | Wartość |
|---|---|
| Endpoint | `bsky.social` API |
| Auth | App password (free, generated at bsky.app) |
| Wykorzystanie | twitter-monitor — 68 curated accounts (T1-T3) |
| Brak SDK | Czysty `requests` w Python stdlib |
| Operacje | `com.atproto.server.createSession` + `app.bsky.feed.getAuthorFeed` |

### 4.8 Gmail SMTP

| Pole | Wartość |
|---|---|
| Host | smtp.gmail.com |
| Port | 465 (SSL) |
| Auth | App Password (16-char, whitespace stripped przy załadowaniu) |
| Adresat | `NOTIFY_EMAIL` env (mikosbartlomiej@gmail.com) |

### 4.9 Cloudflare Workers

Konto: mikosbartlomiej (https://dash.cloudflare.com). Patrz §14.

### 4.10 Render.com

| Pole | Wartość |
|---|---|
| Co | Alpaca MCP server `alpaca-mcp-server-fchb.onrender.com/mcp` |
| Stan | Legacy — używany przez stare routines; nowe ścieżki bypassują przez direct REST |
| Env vars | `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY` (różne nazwy niż w GitHub Secrets!) |

---

## 5. Struktura repozytorium

```
trading-system/
├── .github/workflows/        # 21 workflowów GitHub Actions
├── .claude/rules/            # whitelist tickerów, social accounts
├── config/                   # JSON: aggressive_profile, watchlists,
│                             # instrument_windows, capital_deployment
├── shared/                   # 15 modułów Python — wspólna infrastruktura
│   ├── risk_guards.py
│   ├── risk_officer.py
│   ├── alpaca_orders.py
│   ├── instrument_windows.py
│   ├── peak_tracker.py
│   ├── allocator.py
│   ├── notify.py
│   ├── event_scoring.py
│   ├── learning_state.py
│   ├── market_data.py
│   ├── market_hours.py
│   ├── profile.py
│   ├── regime.py
│   ├── momentum_score.py
│   └── defensive_mode.py
├── price-monitor/            # Stocks long/short scanner
├── crypto-monitor/           # 11-coin predator + LLM Curator
├── defense-monitor/          # Big-5 + mid-cap defense + DoD scrape
├── geo-monitor/              # Geopolitical news + Finnhub + NewsAPI
├── twitter-monitor/          # Bluesky 68 accounts
├── reddit-monitor/           # 6 subs + tracked users + LLM Curator
├── options-monitor/          # CALL/PUT auto-execute via Alpaca REST
├── options-exit-monitor/     # TP/SL/trailing/NEARDTH for open options
├── exit-monitor/             # Stocks/crypto position exits + PROFIT_LOCK
├── learning-loop/            # Daily learning + LLM dialog
│   ├── analyzer.py           # Orchestrator: orders → stats → LLM → state
│   ├── adapter.py            # 14 deterministic heuristics
│   ├── llm_client.py         # Poll-based routine calls
│   ├── lane2_pr.py           # Auto-PR for adapter heuristics
│   ├── weekly_retro.py       # Sunday 22:00 UTC
│   ├── routine-prompts.md    # Senior PM system prompt
│   ├── challenger-prompts.md # Challenger system prompt
│   ├── test_adapter.py       # 34 unit tests
│   ├── state.json            # Adaptive parameters
│   ├── rationale.md          # Append-only narrative
│   ├── heuristic_proposals.md # Lane 3 backlog
│   ├── history/              # Daily reports YYYY-MM-DD.md
│   ├── weekly-retros/        # Weekly reports
│   ├── allocations/          # Allocator plans
│   └── health/               # monitor-health snapshots
├── strategies/               # 10 strategy markdown docs
├── docs/                     # STRATEGY.md (source of truth) + this file
├── scripts/                  # CLI tools + workflow-templates/
│   ├── workflow-templates/   # Master templates → synced to .github/workflows/
│   ├── monitor_health.py     # Workflow introspection
│   ├── emergency_close_*.py  # Per-day emergency close scripts
│   ├── cancel_stale_emergency_orders.py
│   └── execute_allocation_plan.py
├── dashboard/                # Cloudflare Worker (single-file)
├── backtest/                 # Walk-forward replay harness
├── tests/                    # 93 unit tests (instrument_windows + peak_tracker + aggressive)
├── exit-reports/             # Generated exit-monitor reports
├── geo-reports/, briefs/     # Historical artifacts
├── journal/                  # Trade journals trades-YYYY-MM-DD.md
└── CLAUDE.md                 # Master reference (~150k tokens)
```

---

## 6. Workflows GitHub Actions

System ma 21 workflowów. Wszystkie korzystają z `ubuntu-latest`, Python 3.11, single shared `requests` pip install.

### 6.1 Lista workflowów

| # | Workflow | Cron | Trigger | Rola |
|---|---|---|---|---|
| 1 | `price-monitor.yml` | `*/5 13-20 * * 1-5` | schedule | Stocks scan (long + short + leveraged) |
| 2 | `crypto-monitor.yml` | `*/5 * * * *` | schedule (24/7) | Crypto 11-coin predator scan |
| 3 | `defense-monitor.yml` | `*/5 * * * *` | schedule (24/7) | DoD scrape + NewsAPI + RSS |
| 4 | `geo-monitor.yml` | `*/15 * * * *` | schedule (24/7) | Finnhub news + NewsAPI + RSS |
| 5 | `twitter-monitor.yml` | `*/5 * * * *` | schedule (24/7) | Bluesky 68 accounts |
| 6 | `reddit-monitor.yml` | `*/30 * * * *` | schedule (24/7) | 6 subs + tracked users |
| 7 | `options-monitor.yml` | `*/5 13-20 * * 1-5` | schedule | CALL/PUT auto-execute |
| 8 | `options-exit-monitor.yml` | `*/5 13-20 * * 1-5` | schedule | TP/SL/trailing/NEARDTH |
| 9 | `exit-monitor.yml` | `*/5 13-20 1-5` + `*/15 0-12,21-23 *` + `*/15 * * * 0,6` | schedule | Position exits + PROFIT_LOCK |
| 10 | `emergency-close-positions.yml` | `*/3 * * * *` | schedule + push | Autonomous position closer |
| 11 | `cancel-stale-emergency-orders.yml` | — | manual | Cleanup unfilled LIMITs |
| 12 | `daily-learning.yml` | `0 21 * * *` | schedule | 3-round LLM dialog + adapt state |
| 13 | `daily-learning-watchdog.yml` | `30 22 * * *` + `30 23 * * *` | schedule | Auto-trigger if 21:00 UTC missed |
| 14 | `weekly-retro.yml` | `0 22 * * 0` | schedule (Sun) | Weekly retrospective |
| 15 | `morning-allocator.yml` | `35 13 * * 1-5` | schedule | Execute pending allocator plan |
| 16 | `learning-loop-ci.yml` | — | pull_request + push | Run `test_adapter.py` |
| 17 | `monitor-health.yml` | `*/30 * * * *` | schedule | Workflow introspection → snapshot |
| 18 | `sync-workflows.yml` | `*/15 * * * *` + push | schedule + push | Mirror templates → .github/workflows/ |
| 19 | `auto-merge.yml` | — | push | FF-merge `claude/*` branches → main |
| 20 | `backtest.yml` | — | manual | Walk-forward strategy replay |
| 21 | `snapshot.yml` | — | manual | Repo state snapshot |

### 6.2 Wzorzec workflowa monitorującego

```yaml
name: <Monitor Name>

on:
  schedule:
    - cron: '*/5 * * * *'
  workflow_dispatch:

permissions:
  contents: write    # commit state back to repo

jobs:
  scan:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install requests
      - name: Run monitor
        env:
          ALPACA_API_KEY:      ${{ secrets.ALPACA_API_KEY }}
          ALPACA_SECRET_KEY:   ${{ secrets.ALPACA_SECRET_KEY }}
          GMAIL_USER:          ${{ secrets.GMAIL_USER }}
          GMAIL_APP_PASSWORD:  ${{ secrets.GMAIL_APP_PASSWORD }}
          NOTIFY_EMAIL:        ${{ secrets.NOTIFY_EMAIL }}
          CLOUDFLARE_*_URL:    ${{ secrets.CLOUDFLARE_*_URL }}
          PYTHONIOENCODING:    utf-8
          LC_ALL:              C
          LANG:                C
        run: python <module>/monitor.py
      - name: Commit state (optional)
        run: |
          git add learning-loop/state.json journal/
          git diff --cached --quiet || git commit -m "<monitor>: state $(date -u +%H%M) [automerge]"
          git push origin main
```

### 6.3 Special workflows

#### auto-merge.yml
Trigger: push do `claude/*` branch z `[automerge]` w wiadomości commita. Wykonuje:
1. `git fetch origin main`
2. `git merge --ff-only <branch>`
3. `git push origin main`
4. Retry on non-FF rejection (3 attempts with `git pull --rebase`)

Cel: Claude.ai OAuth proxy nie pozwala pushować bezpośrednio do main — agenci pushują do feature branch, auto-merge.yml używa GITHUB_TOKEN (inny scope) do FF-merge.

#### sync-workflows.yml
Trigger: `*/15` cron + push do `scripts/workflow-templates/*.yml`. Wymaga **WORKFLOW_PAT** (Classic PAT z `repo` + `workflow` scope — fine-grained PATs nie mają workflow scope).

Workflow:
1. Diff `scripts/workflow-templates/*.yml` vs `.github/workflows/*.yml`
2. Jeśli różnice — kopiuj template → workflow file
3. Commit + push z PAT (OAuth proxy odrzuca writes do `.github/workflows/`)

#### daily-learning-watchdog.yml
Trigger: `30 22 UTC` + `30 23 UTC`. Sprawdza czy daily-learning fired dziś. Jeśli NIE — triggeruje workflow_dispatch via GitHub API z curl.

Po co: 21:00 UTC cron jest GH Actions-best-effort, czasem opóźnia o godziny lub gubi tick. Watchdog gwarantuje że codzienny dialog LLM się odbędzie przed północą UTC.

---

## 7. Monitory wejścia

### 7.1 price-monitor (stocks)

**Plik:** `price-monitor/monitor.py` (563 linie)
**Cron:** `*/5 13-20 * * 1-5` (US market hours only)
**Sygnały:** BUY (momentum-long), SELL_SHORT (overbought-short — currently OFF), LEVERAGED (lev3x ETFs)

**Pipeline:**
1. `vix_guard()` → HALT @VIX>60
2. `daily_drawdown_guard()` → HALT @-3% daily
3. **regime detection** (`shared/regime.py::detect_regime`) → RISK_ON / NEUTRAL / RISK_OFF / INFLATION_SHOCK
4. **Bucket-allowlist** filter per regime — RISK_ON używa `ai_nasdaq_semis` + `momentum_growth`; RISK_OFF używa `hedge_bonds` + `defense`
5. **Score** każdego candidate (`shared/momentum_score.py::score_symbol`): composite = 0.25×mom_5d + 0.25×mom_10d + 0.15×RS vs SPY + 0.15×vol_expansion + 0.10×breakout + 0.10×trend
6. **Top-N** (default 7) skanowane → tylko score ≥ 0.35 emitowane
7. Per emit: `concentration_ok` + `has_open_position` + `risk_officer.evaluate_trade` + `place_stock_bracket`
8. `notify_signal()` per alert

**State.json reads:** `strategies.<name>.enabled`, `size_multiplier`, `tickers.<symbol>`

### 7.2 crypto-monitor

**Plik:** `crypto-monitor/monitor.py` (538 linie)
**Cron:** `*/5 * * * *` (24/7)
**Sygnały:** BUY (momentum), SELL (breakdown)

**Predator architecture (v2.4):**
- **Tier 1** (BTC/USD, ETH/USD): $8k / $4k, TP+20% / SL-7%
- **Tier 2** (SOL, AVAX, LINK, DOT, MATIC, LTC, BCH, UNI, AAVE): $2.5k each, TP+10% / SL-8%, vol expansion 3.0×
- Per-tier params w `COIN_TIERS` dict

**Predator filters:**
- 24h move bracket [3%, 15%] — skip stalls + late-pumps
- BTC dominance guard: -3% w 1h blokuje alt longs (cached per-run)
- Max 3 simultaneous Tier 2 positions

**LLM Curator (`crypto-monitor/llm_curator.py`):**
- Poll-based call do `crypto-curator-proxy` Cloudflare Worker
- Fail-soft: gdy 429 / timeout / no key → heurystyczny ranking
- 5-step process: HUNT → VALIDATE → RANK → SIZE (0.5-1.5×) → OUTPUT 0-3

### 7.3 defense-monitor

**Plik:** `defense-monitor/monitor.py` (759 linii)
**Cron:** `*/5 * * * *` (24/7 — news scanning)
**Sygnały:** BUY na Big-5 + mid-cap defense

**Sources:**
- DoD contracts scrape (`defense.gov`)
- NewsAPI: keywords "defense contract", "missile", "drone", "Pentagon", ...
- RSS feeds: aviationweek, breakingdefense, defensenews

**Event scoring** (`shared/event_scoring.py`):
- credibility 0-100 (source type + corroboration)
- probability_shift (low/med/high)
- market_reaction (price ATR + volume + gap)
- stance: FOLLOW_REACTION / IGNORE_EVENT / CONTRARIAN_CANDIDATE / WAIT_FOR_CONFIRMATION

Tylko FOLLOW (i czasem CONTRARIAN_CANDIDATE) emituje sygnał.

**MAX_ALERTS_PER_RUN=1** — rate-limit guard.

### 7.4 geo-monitor

**Plik:** `geo-monitor/monitor.py` (358 linii)
**Cron:** `*/15 * * * *` (24/7)
**Sygnały:** BUY (defense ramp), SHORT (sanctions/escalation against specific tickers)

**Sources:** Finnhub news + NewsAPI + RSS (Reuters, AP, Bloomberg)

**Status:** `geo-xom` strategy disabled (`state.json::strategies.geo-xom.enabled=false`) bo używa deprecated routine path. Refactor na direct REST execution na backlogu (revisit 2026-05-20).

### 7.5 twitter-monitor (Bluesky AT-Protocol)

**Plik:** `twitter-monitor/monitor.py` (614 linii)
**Cron:** `*/5 * * * *` (24/7)
**Sygnały:** BUY/SHORT z 4-tier source-type weighting

**Curated whitelist:** `.claude/rules/twitter-accounts.md` — 68 kont w 8 kategoriach:
- **T1** (high_priority_pol): Trump admin, conflict leaders (Israel/Iran/Russia/Ukraine), NATO/China → bypass keyword filter, bypass event_scoring filter
- **T1.5** (high_priority_pol): Conflict ministers + presidents
- **T2** (ticker:SYM): Tech CEOs Musk/Cook/Pichai/Nadella/Jassy → tied to specific ticker
- **T2.5** (high_priority_corp): Defense corporate accounts (Lockheed, RTX, etc.)
- **T3** (tracked_anon_trader): Manually-curated influencers
- Plus: gov_us, macro, wire, mil_il (standard tiers)

**Source-type credibility map:**
| Tier | source_type | cred | bypass keyword? | bypass FOLLOW-only? |
|---|---|---|---|---|
| T1 | `official_government` | 80 | ✓ | ✓ |
| T2 | `tracked_corp_ceo` | 75 | ✓ | ✓ |
| T3 | `tracked_anon_trader` | 55 | ✓ | ✓ |
| Standard | `tweet_verified_pol` / `major_outlet` / `reuters_ap` | 45/60/70 | ✗ | ✗ |

**Bluesky client:**
- `BlueskyClient` wraps `com.atproto.server.createSession` + `app.bsky.feed.getAuthorFeed`
- Pure stdlib + `requests` (no atproto SDK)
- Auth: `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` secrets

### 7.6 reddit-monitor

**Plik:** `reddit-monitor/monitor.py` (1125 linii)
**Cron:** `*/30 * * * *` (24/7)
**Sygnały:** BUY/SELL_SHORT/UNCLEAR z bilingualnym vocabulary

**No-API path:**
- Public endpoints `/r/<sub>/{top,hot,new}.json` + `/user/<u>/submitted.json`
- Cloudflare Worker `reddit-fetch-proxy` (Reddit blokuje data-center IPs)
- ToS-friendly: poll co ≥30 min, custom User-Agent, 60s edge cache

**Curated subs** (`.claude/rules/reddit-subs.md`):
- wallstreetbets, options, stocks, investing, securityanalysis, valueinvesting
- Per-sub: `min_upvotes`, `min_comments`, `weight` (size_multiplier)

**Detection patterns:**
- **Pattern A — sub spike:** mentions w 24h ≥3× rolling 7d avg + sentiment skew |≥0.3|
- **Pattern B — tracked user:** single high-quality post od tracked DD writer (lista empty obecnie — wszyscy seed users dead)

**LLM Curator (`reddit-monitor/llm_curator.py`):**
- 5-step: HUNT → VALIDATE → RANK → SIZE → OUTPUT
- Encyklopedyczna wiedza: gamma squeezes, options unusual flow, defense pops, leveraged ETF path-dependence, mega-cap AI cycle, Reddit slang
- 130-word expanded vocab (quantitative finance + momentum slang + options + crypto + macro)
- Fail-soft: gdy 429/timeout → heurystyczny rank

**Sentiment:**
- Bilingual `BULLISH` / `BEARISH` keyword sets (`±30 słów wokół ticker mention`)
- `|skew| < 0.10` → `UNCLEAR` (nie generuje false SELL_SHORT)

### 7.7 options-monitor

**Plik:** `options-monitor/monitor.py` (542 linii)
**Cron:** `*/5 13-20 * * 1-5`
**Sygnały:** CALL (RSI 45-65 momentum), PUT (RSI > 72 overbought reversal)

**AUTO_EXECUTE pathway** (default `AUTO_EXECUTE_OPTIONS=true`):
1. RSI scan na 12-ticker whitelist (AAPL, MSFT, GOOGL, NVDA, META, AMZN, TSLA, SPY, QQQ, JPM, RTX, LMT)
2. Per candidate: VIX guard + earnings ±1d skip + MAX_OPEN_OPTIONS=10
3. Alpaca `/v2/options/contracts` — find closest-to-ATM strike (within ±7%)
4. DTE 7-30 dni
5. Premium ≤ `size_usd / 100` (size_usd default $2,500)
6. **Simple LIMIT BUY** via `/v2/orders` (paper API odrzuca bracket na options)
7. `client_order_id = options-momentum-<contract>-<ts>`
8. TP/SL emulowane przez `options-exit-monitor`

**MAX_PROPOSALS_PER_RUN=1** — soft rate-limit.

### 7.8 options-exit-monitor

**Plik:** `options-exit-monitor/monitor.py` (554 linii)
**Cron:** `*/5 13-20 * * 1-5`

**Decision tree per open us_option position:**
1. **TP**: current price ≥ entry × 1.8 (lub `suggested_tp_multiplier` z state.json) → LIMIT SELL @market_mid
2. **SL**: current price ≤ entry × 0.5 → MARKET SELL
3. **NEARDTH**: DTE ≤ 5 AND loss > 40% → MARKET SELL (near-expiry capitulation)
4. **TRAIL** (v3.3): peak_premium tracking — 8% trail off peak, 12h min-hold, only if `TRAILING_STOP_ENABLED=true`
5. **REGIME mismatch** (v3.3): side_bias=long AND PUT AND pl ≤ -15% AND SPY 5d ≥ +1.5% → MARKET SELL
6. Else: HOLD

**Dedup:** `/v2/orders?status=open&symbols=...` — don't stack duplicate SELL.

**client_order_id format:** `exit-{tp|sl|near-dth|trail|regime}-options-momentum-<contract>-<ts>`

---

## 8. Monitory wyjścia

### 8.1 exit-monitor (stocks/crypto)

**Plik:** `exit-monitor/monitor.py` (487 linii)
**Cron:** dual:
- `*/5 13-20 * * 1-5` (market hours, 5-min)
- `*/15 0-12,21-23 * * *` (off-hours weekdays, 15-min)
- `*/15 * * * 0,6` (weekends, 15-min)

**Per-position decision** (`enrich_position`):
- HOLD (default)
- CONSIDER_TP (price >= entry × 1.8 dla stocks, 1.20 dla crypto)
- CLOSE_FLAT (hold_hours > 96 AND |pl| < 1%)
- CLOSE_DECAY (leveraged ETF + hold_hours > 96, lub crypto + hold_hours > 48)
- CLOSE_EMERGENCY (pl ≤ -12%)
- PROFIT_LOCK (peak_tracker fires)

**Peak tracker integration (v3.3):**
- `shared/peak_tracker.py::update_peak()` — śledzi intraday daily P&L
- Verdict: NORMAL / WARN (30% retrace) / PROFIT_LOCK (50% retrace)
- PROFIT_LOCK ma priorytet nad CLOSE_EMERGENCY
- Harvest winners ≥+8% via MARKET sell, tag `exit-profit-lock-*`

**Trade-window aware (v3.4.5):**
- `_emergency_close_window_ok(ep)` sprawdza `can_trade_now()` PRZED próbą close
- Gdy market closed → defer (skip routine fallback)
- Zero noise overnight

**REST DELETE flow:**
- PRIMARY: `DELETE /v2/positions/{symbol}` (bypassuje options buying-power bug)
- FALLBACK: `POST /v2/orders` MARKET sell (gdy DELETE non-2xx)

### 8.2 emergency-close-positions

**Workflow:** `.github/workflows/emergency-close-positions.yml`
**Cron:** `*/3 * * * *`
**Scripts:** `scripts/emergency_close_YYYYMMDD[_suffix].py`

**Architektura:**
1. Operator/agent tworzy nowy skrypt `emergency_close_<date>.py` z konkretnymi pozycjami w `TARGETS`
2. Commit z tagiem `[auto-execute]` → push event → workflow fires
3. Schedule cron poluje co 3 min:
   - **Script picker (v3.4.5):** `ls scripts/emergency_close_*.py | sort -r | head -1` (filename-date sort, lexicographic)
   - **Idempotency:** skip jeśli `exit-reports/${basename}-*.log` istnieje
   - **Age check:** skip jeśli filename date > 2 dni temu (using YYYYMMDD-in-filename, nie mtime)
4. Run script:
   - Cancel stale SELL orders (cleanup LIMIT @stale price)
   - DELETE /v2/positions/{symbol} (canonical close)
   - Log `MACHINE_READABLE_RESULT: {failed: N, ok: M}`
5. **Commit log ONLY on success** (`failed == 0`) → idempotency engaged

**Use case (2026-05-14):**
- QQQ260518P00714000 stuck z 4 nieudanymi close attempts (paper API "insufficient options buying power for cash-secured put" bug)
- Manual script z DELETE bypass
- Standing LIMIT @$5.80 może fill first → DELETE returns 404 (idempotent OK)

### 8.3 cancel-stale-emergency-orders

**Workflow:** `.github/workflows/cancel-stale-emergency-orders.yml`
**Trigger:** manual only
**Script:** `scripts/cancel_stale_emergency_orders.py`

Cleanup unfilled `exit-emergency-*` LIMIT orders (status=open, age > X hours). Idempotent. Wykrywany przez `heuristic_stale_exit_emergency` w adapter.py (4 placed / 0 filled / 0 canceled → surface w rationale.md).

---

## 9. Learning Loop — dwustopniowa adaptacja

### 9.1 Daily (21:00 UTC)

**Workflow:** `.github/workflows/daily-learning.yml`
**Cron:** `0 21 * * *`
**Module:** `learning-loop/analyzer.py::run`
**Timeout:** 30 min (3 sequential LLM calls × ~8 min budget)

**Pipeline:**

```
┌────────────────────────────────────────────────────────────┐
│ 1. fetch                                                    │
│    - get_orders_window(after=now-24h)                      │
│    - get_account() → equity, daily_pl                      │
│    - load_state() → previous adaptive params               │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 2. analyze                                                  │
│    - reconstruct_trades(orders) → FIFO pair opens/closes   │
│    - compute_strategy_stats() — per-strategy WR, P&L, etc. │
│    - compute_asset_stats()                                 │
│    - compute_fill_rate(orders) — placed/filled/canceled     │
│    - compute_tp_hit_rate(orders) — per-strategy TP success │
│    - compute_rsi_snapshot() — SPY, BTC/USD, ETH/USD RSI(14)│
│    - compute_position_audit(positions, orders) — flag      │
│      positions w/o exit orders                             │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 3. LLM Round 1 — Senior PM Strategist                       │
│    - call_senior_pm_round1(payload)                        │
│    - payload includes: today_stats + rationale tail        │
│      + open_positions snapshot + state.json                │
│    - LLM thinks ~5 min, commits pending-llm-daily-draft1   │
│      .json to feature branch (via routine self-commit)      │
│    - Poll origin/<feature_branch> 300s for the file        │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 4. LLM Round 2 — Challenger                                 │
│    - call_challenger(draft1_payload + critique_prompt)     │
│    - Adversarial review: P&L scoring 1-10 per claim,       │
│      stress test, decision (SURVIVED/MODIFIED/REJECTED)    │
│    - Writes pending-llm-daily-challenge.json               │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 5. LLM Round 3 — Senior PM Revise                           │
│    - call_senior_pm_revise(draft1 + critique)              │
│    - PM defends or accepts critique per proposal           │
│    - Final pending-llm-daily.json with revision_log[]      │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 6. adapter.adapt(state, today_stats)                        │
│    Pure-Python deterministic adapter:                      │
│    - per-strategy: warm-up / cool-down / pause             │
│    - _apply_tp_feedback() — TP < 0.20 → tighter mult       │
│    - _flag_silent_strategies()                             │
│    - _prune_uuid_keys()                                    │
│    - _reset_options_bias_if_no_data()                      │
│    - heuristic_fill_rate_alert() / size_cut() / chronic()  │
│    - heuristic_stale_exit_emergency() ← NEW v3.4.5        │
│    - heuristic_spy_overbought_options_block() ← NEW v3.4.5│
│    Returns (new_state, rationale_lines[])                  │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 7. safe_apply_overrides(new_state, llm_overrides)           │
│    Whitelist-protected:                                    │
│      - size_multiplier clamp [0.30, 2.00]                  │
│      - enabled must be bool                                │
│      - side_bias enum                                      │
│      - silently drop hallucinated keys                     │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 8. route_proposals(llm_proposals) — three lanes             │
│    Lane 1: state_overrides → already applied               │
│    Lane 2: auto_pr → lane2_pr.create_pr_from_proposal()    │
│            - validate patch (AST)                          │
│            - apply to learning-loop/adapter.py             │
│            - run tests                                     │
│            - git checkout -b learning-loop/auto-<slug>     │
│            - gh pr create                                  │
│    Lane 3: structured backlog → append to                   │
│            heuristic_proposals.md                          │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 9. Persist                                                  │
│    - peak_equity = max(prior, today_eq) ← NEW v3.4.5      │
│    - save_state(new_state) → state.json                    │
│    - append_rationale(lines) → rationale.md                │
│    - write_history_report() → history/YYYY-MM-DD.md        │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 10. Allocator (post-learning)                               │
│     - AccountAwareAllocator.compute_plan(state, account)   │
│     - Save allocations/YYYY-MM-DD.json + .log              │
│     - Email plan via notify_allocation_plan()              │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│ 11. Commit + push                                           │
│     git add learning-loop/state.json rationale.md          │
│             learning-loop/history/ learning-loop/health/   │
│             learning-loop/allocations/                     │
│     git commit -m "...[automerge]"                         │
│     git push origin <feature-branch>                       │
│     → auto-merge.yml FF-merges to main                     │
└────────────────────────────────────────────────────────────┘
```

### 9.2 Weekly (Sunday 22:00 UTC)

**Workflow:** `.github/workflows/weekly-retro.yml`
**Module:** `learning-loop/weekly_retro.py`

Similar structure ale tylko 1-round LLM (Senior PM tylko). Persona: 6-pass framework (P&L story → strategy scorecard → asset class allocation → source quality → mistakes → next-week experiments).

Output: `learning-loop/weekly-retros/<week_end>.md`.

### 9.3 Adapter heuristics (14 funkcji w `adapter.py`)

| # | Funkcja | Wejście | Wyjście |
|---|---|---|---|
| 1 | `adapt_strategy` | (name, old, stats, equity) | new dict per strategy z size/enabled/side_bias |
| 2 | `_apply_tp_feedback` | (state, today_stats) | rationale lines (TP < 0.20 → mult 1.4) |
| 3 | `_flag_silent_strategies` | (state, today_stats, min_days=10) | rationale lines per zombie strategy |
| 4 | `_prune_uuid_keys` | (state) | (count_pruned, list) — usuwa UUID artifacts |
| 5 | `_reset_options_bias_if_no_data` | (state, today_stats) | bool — reset bias gdy trades_7d<3 |
| 6 | `heuristic_fill_rate_alert` | (fill_rate_data, ...) | alert list — warn na low fill rate |
| 7 | `heuristic_fill_rate_size_cut` | (canceled, placed) | (cut, factor, reason) |
| 8 | `heuristic_options_chronic_fill` | (fill_rate, ...) | (bool, reason) — multi-day deficit |
| 9 | `heuristic_options_limit_too_tight` | (fill_stats) | (bool, reason) — pojedynczy dzień |
| 10 | `heuristic_stale_exit_emergency` | (fill_stats) | (bool, reason) — **NEW v3.4.5** — placed≥2/filled=0/canceled=0 |
| 11 | `heuristic_spy_overbought_options_block` | (today_stats) | (bool, reason) — **NEW v3.4.5** — SPY RSI > 75 |
| 12 | `_adjust_size` | (current, factor) | bounded [0.30, 2.00] |
| 13 | `adapt` | (state, today_stats) | (new_state, rationale[]) — top-level orchestrator |
| 14 | `_is_uuid_key` | (name) | bool — detect Alpaca bracket ID artifacts |

**Adaptation rules (per-strategy):**
- Win-rate 7d < 35% → size × 0.8
- Win-rate 7d > 60% → size × 1.10
- P&L 7d < -2% equity → size × 0.7
- P&L 7d > +3% equity → size × 1.05
- 5 consecutive losses → pause 3 days
- Lifetime ROI < -10% → DISABLE (manual review)

---

## 10. Routines (LLM personas)

System ma 5 deployed routines na claude.ai. Każdy ma identyczny pattern: routine ↔ Cloudflare Worker proxy ↔ GitHub Actions / Python client.

### 10.1 Learning Loop Strategist (Senior PM)

**Persona:** Senior Portfolio Manager z 20+ latami doświadczenia, prowadzi $100k paper account z 4× margin
**Mission:** Maksymalizacja risk-adjusted return na krótkim horyzoncie (1d-4w hold)
**System prompt:** `learning-loop/routine-prompts.md` (590 linii)
**Wywoływany:** Daily 21:00 UTC + Sunday 22:00 UTC

**Type-dispatch w payloadzie:**
- `payload.type = "daily_learning_annotation"` → round 1 daily framework (6 passes)
- `payload.type = "daily_revise"` → round 3 revision z critique
- `payload.type = "weekly_retrospective"` → weekly framework (6 passes)

**Output JSON schema:**
- `narrative` (markdown, dla rationale.md)
- `state_overrides` (Lane 1 — whitelist-validated)
- `lane2_proposals` (z `code_patch` + `test_addition` dla adapter.py)
- `lane3_proposals` (structured backlog z risk/effort/revisit)
- `revision_log[]` (DEFENDED/ACCEPTED/MODIFIED/ADDED per proposal — round 3 only)

### 10.2 Learning Loop Challenger

**Persona:** Adversarial reviewer — drugi głos w 3-rundowym dialogu
**Cel:** Force Senior PM to break down each proposal, demand evidence, frame everything as profit max vs loss min
**System prompt:** `learning-loop/challenger-prompts.md` (276 linii)
**Wywoływany:** Daily 21:00 UTC (między round 1 i round 3)

**5-step process:**
1. DECOMPOSE — rozbij każdą Senior PM proposal na sub-claims
2. RESEARCH — porównaj z historical data / state.json
3. P&L SCORING — 1-10 per sub-claim (profit_score + risk_score)
4. DECISION — SURVIVED (≥70%), MODIFIED (50-69%), REJECTED (<50%)
5. STRESS TEST — symuluj >2% equity loss scenario

**Output JSON:**
- `critique[]` per proposal z decision
- `open_questions[]` — czego Senior PM nie rozważył
- `stress_test_results`

### 10.3 Reddit Signal Curator

**Persona:** Super-aggressive momentum trader z encyklopedyczną wiedzą Reddit instruments
**Wiedza:** gamma squeezes (GME archetype), short squeezes >20% SI, meme rotation, options unusual flow, defense contract pops, leveraged ETF path-dependence (TQQQ/SOXL), high-beta single names (COIN ~2.5×BTC, MSTR ~1.8×BTC, ARM-SMCI ~2×NVDA), mega-cap AI earnings cycle, Reddit slang fluency
**System prompt:** `reddit-monitor/curator-prompts.md` (429 linii)
**Wywoływany:** każdy reddit-monitor scan z candidates

**5-step:** HUNT (skim 15 candidates) → VALIDATE (real catalyst?) → RANK → SIZE (0.5/1.0/1.3/1.5×) → OUTPUT 0-3

**Filozofia:** boring=zero edge, full conviction OR kill, ZERO emit acceptable output

**Curator-trust pattern:** signal z `curator_rationale` field skipuje wszelkie dalsze veto gates (LLM już zrobił smart filtering).

### 10.4 Crypto Signal Curator

**Persona:** Super-aggressive crypto momentum trader, predator on-chain
**Wiedza:** BTC dominance dynamics, altseason vs winter, per-coin beta, ETH gas cycles, memecoin rotation, liquidation cascades, supply unlocks, stablecoin flow
**System prompt:** `crypto-monitor/curator-prompts.md` (329 linii)

### 10.5 Exit Handler

**Status:** Legacy. Od v2.2 routine bypass większość exit logic jest w Pythonie (`shared/alpaca_orders.py` direct REST). Routine używany tylko dla CONSIDER_TP cases.

---

## 11. Risk management

### 11.1 Trzy linie obrony

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: shared/risk_guards.py — fail-open guards       │
│   - vix_guard()              VIX > 60 → HALT            │
│   - daily_drawdown_guard()   daily P&L ≤ -3% → HALT     │
│   - weekly_drawdown_guard()  weekly ≤ -7% → DEFENSIVE   │
│   - max_drawdown_guard()     ≤-12% DEFENSIVE / -20% STOP│
│   - position_pct()           per-symbol exposure        │
│   - concentration_ok()       new+existing ≤ 40%         │
│   - has_open_position()      dup-position skip          │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 2: shared/risk_officer.py::evaluate_trade()       │
│   9 HARD checks (fail = REJECT):                        │
│     1. whitelist            (.claude/rules/...)         │
│     2. size cap             ≤ 20% equity                │
│     3. SL exists            mandatory                   │
│     4. R:R ratio            ≥ 1.5                       │
│     5. concentration        per-ticker ≤ 40%            │
│     6. daily drawdown                                   │
│     7. VIX HALT                                         │
│     8. instrument window    can_trade_now()             │
│     9. asset-class soft cap                             │
│   4 SOFT warnings (log but allow)                       │
│   Returns: {decision, passed[], failed[], warnings[]}   │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 3: shared/instrument_windows.py::can_trade_now()  │
│   Per-symbol gate at execution time:                    │
│     1. instrument_overrides.enabled=false → block       │
│     2. paused_until future → block                      │
│     3. asset-class window market-closed → block         │
│     4. else allow                                       │
└─────────────────────────────────────────────────────────┘
```

### 11.2 Iron rules (v3.0 risk-on, hardened with v3.4.5 gates)

| Limit | Wartość |
|---|---|
| Max single trade | 20% equity |
| Max ticker exposure | 40% equity |
| Cash reserve | 0% (active deployment) |
| Margin usage | 1.5×-2.5× (Reg-T allows 4×) |
| Daily loss stop | -3% (v3.0 tightened from -12%) |
| Weekly loss stop | -7% (NEW v3.0) |
| Defensive mode | -12% drawdown from peak |
| Full stop | -20% drawdown (manual confirm) |
| VIX HALT | > 60 |
| Trailing stop | 8% off intraday peak, 12h min-hold |
| PROFIT_LOCK | peak ≥$1k AND retrace ≥50% |
| Max open options | 10 |
| Options DTE | 7-30 days |

### 11.3 Forbidden

- Live trading (paper only forever)
- Trading bez stop-loss
- Trading poza whitelistą
- Options ±1 dzień wokół earnings

---

## 12. Order execution flow

### 12.1 Stock entry (bracket order)

```python
shared/alpaca_orders.py::place_stock_bracket(
    symbol, side, qty,
    limit_price, sl_price, tp_price,
    strategy="momentum-long"
) -> dict | None
```

**HTTP request:**
```
POST /v2/orders
{
  "symbol": "NVDA",
  "qty": "20",
  "side": "buy",
  "type": "limit",
  "limit_price": "750.50",
  "time_in_force": "day",
  "order_class": "bracket",
  "stop_loss": {"stop_price": "705.45"},
  "take_profit": {"limit_price": "885.10"},
  "client_order_id": "momentum-long-NVDA-20260514103012"
}
```

**client_order_id format:** `{strategy}-{symbol}-{YYYYMMDDhhmmss}`
Used by `learning-loop/analyzer.py::_strategy_from_client_id` for attribution.

### 12.2 Crypto entry

Bracket nie wspierany na crypto na paper. Single LIMIT + manual exit przez exit-monitor.

```python
shared/alpaca_orders.py::place_crypto_order(
    symbol="BTC/USD", side, qty,
    limit_price, time_in_force="gtc"
)
```

### 12.3 Options entry

Paper API odrzuca bracket/OCO/stop dla options → simple LIMIT BUY:

```python
options-monitor/monitor.py::place_options_buy(contract, ...)
```

TP/SL emulated przez `options-exit-monitor`.

### 12.4 Exit flow

**Stocks/Crypto:**
1. `exit-monitor/monitor.py::run_exit_check` polluje co 5-15 min
2. Per position: `enrich_position` → recommendation
3. Jeśli recommendation in `(CLOSE_EMERGENCY, PROFIT_LOCK, CLOSE_FLAT, CLOSE_DECAY)`:
   - `_emergency_close_window_ok(ep)` — czy market open?
   - `place_emergency_close(ep)` → DELETE /v2/positions OR fallback POST MARKET sell
4. Routine fallback tylko dla CONSIDER_TP (rzadkie)

**Options:**
1. `options-exit-monitor/monitor.py` polluje co 5 min
2. Per us_option position: oblicz TP/SL/TRAIL/NEARDTH/REGIME thresholds
3. Place SELL via LIMIT (TP) lub MARKET (SL/NEARDTH/REGIME)

### 12.5 Emergency manual close

Operator/agent tworzy `scripts/emergency_close_<date>.py` z konkretnymi pozycjami:

```python
TARGETS = [
    {"symbol": "QQQ260518P00714000", "reason": "..."},
]
```

Commit z `[auto-execute]` w wiadomości → push event → workflow fires within 3 min.

---

## 13. Persistencja i audit trail

### 13.1 learning-loop/state.json

**Struktura (top-level keys):**

```json
{
  "last_updated": "2026-05-14T01:24:14Z",
  "days_tracked": 15,
  "peak_equity": 95035.0,
  "strategies": {
    "momentum-long":     {"enabled": true,  "size_multiplier": 1.0, ...},
    "options-momentum":  {"enabled": false, "paused_until": "2026-05-15", ...},
    "overbought-short":  {"enabled": false, "paused_until": null,         ...},
    "crypto-momentum":   {"enabled": true,  "size_multiplier": 1.0, ...},
    "crypto-breakdown":  {"enabled": true,  "size_multiplier": 1.0, ...},
    "geo-xom":           {"enabled": false, ...}
  },
  "tickers": {
    "MSTR": {"enabled": false, "rationale": "backtest 0% WR / -$2364"},
    "SMCI": {"enabled": false, ...}
  },
  "asset_classes": {...},
  "sources": {...},
  "global_overrides": {
    "options_side_bias": null
  },
  "daily_peak": {
    "date": "2026-05-14",
    "peak_pl_usd": 56.08,
    "peak_equity": 95034.87,
    "retrace_from_peak": 0.0,
    "verdict": "NORMAL",
    "alerts_sent": {}
  },
  "trailing_state": {},
  "reddit_state": {"AAPL": {"mentions_per_day": {...}, "last_signal": "..."}}
}
```

### 13.2 learning-loop/rationale.md

Append-only narrative. Każdy daily-learning run dodaje ~5-20 linii. Format:
```
2026-05-14 · options-momentum: SPY-overbought gate · SPY RSI 82.4 > 75
2026-05-14 · exit-emergency: 4 placed / 0 filled / 0 canceled — stale ...
2026-05-14 · peak_equity advanced $0 -> $95,035
```

Nigdy nie usuwany. "Wieczność" (per user request 2026-05-07).

### 13.3 learning-loop/history/YYYY-MM-DD.md

Per-day full report. Sections:
- Account snapshot (equity, daily P&L)
- Per-strategy: trades 7d/lifetime, WR, P&L
- Per-asset-class breakdown
- Fill rate per strategy
- TP hit rate per strategy
- RSI snapshot (SPY, BTC, ETH)
- Position audit (positions without exit orders)
- Senior PM narrative
- Challenger critique
- Revision log

### 13.4 Other paths

| Path | Co |
|---|---|
| `learning-loop/weekly-retros/YYYY-MM-DD.md` | Weekly Senior PM retro |
| `learning-loop/heuristic_proposals.md` | Lane 3 backlog (LLM-proposed but not auto-applied) |
| `learning-loop/allocations/YYYY-MM-DD.json` | Allocator plan (evening) + `.execution.json` (morning) |
| `learning-loop/health/{latest,YYYY-MM-DD_HHMM}.{md,json}` | Monitor health snapshots |
| `exit-reports/YYYY-MM-DD-HH.md` | Per-run exit-monitor reports |
| `exit-reports/<script-base>-<ts>.log` | Emergency-close execution logs |
| `journal/trades-YYYY-MM-DD.md` | Daily trade journal |

---

## 14. Cloudflare Workers

### 14.1 Wzorzec proxy

Każdy Worker ma identyczny pattern: dodaje auth headers (Bearer token z Anthropic Routine "Call via API") i forwardu do routine endpoint.

```javascript
export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("Method not allowed", {status: 405});
    const body = await request.json();
    const routinePayload = {text: JSON.stringify(body)};
    const response = await fetch(env.ROUTINE_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type":      "application/json",
        "Authorization":     `Bearer ${env.ANTHROPIC_TOKEN}`,
        "anthropic-version": "2023-06-01",
        "anthropic-beta":    "experimental-cc-routine-2026-04-01",
      },
      body: JSON.stringify(routinePayload),
    });
    return new Response(await response.text(), {status: response.status});
  }
};
```

### 14.2 Deployed Workers

| Worker | URL secret | Cel | Routine trigger |
|---|---|---|---|
| tradingview-proxy | `CLOUDFLARE_WORKER_URL` | price-monitor → Tradingview Handler | (legacy) |
| geopolitical-proxy | `CLOUDFLARE_GEO_WORKER_URL` | geo-monitor → Geopolitical Handler | (legacy) |
| exit-monitor-proxy | `CLOUDFLARE_EXIT_WORKER_URL` | exit-monitor CONSIDER_TP → Exit Handler | trig_01QL21os... |
| crypto-proxy | `CLOUDFLARE_CRYPTO_WORKER_URL` | crypto-monitor → Crypto Handler | trig_01Y1QB5M... |
| crypto-curator-proxy | `CLOUDFLARE_CRYPTO_CURATOR_WORKER_URL` | crypto-monitor LLM Curator | (separate) |
| learning-loop-proxy | `CLOUDFLARE_LEARNING_WORKER_URL` | Senior PM Strategist | trig_0175V2oD... |
| learning-loop-challenger-proxy | `CLOUDFLARE_LEARNING_CHALLENGER_WORKER_URL` | Challenger | (separate) |
| defense-proxy | `CLOUDFLARE_DEFENSE_WORKER_URL` | defense-monitor → routine (lub direct email) | (set up) |
| options-proxy | `CLOUDFLARE_OPTIONS_WORKER_URL` | options-monitor (legacy, bypassed by AUTO_EXECUTE) | (deprecated) |
| reddit-fetch-proxy | `CLOUDFLARE_REDDIT_WORKER_URL` | reddit-monitor data fetch (Reddit IP block bypass) | (data only) |
| reddit-curator-proxy | `CLOUDFLARE_REDDIT_CURATOR_WORKER_URL` | reddit-monitor LLM Curator | (separate) |
| twitter-proxy | `CLOUDFLARE_TWITTER_WORKER_URL` | twitter-monitor → Twitter Handler | (separate) |
| dashboard-proxy | (URL in dashboard/SETUP.md) | Dashboard `/api/snapshot` | (no LLM) |

**Worker secrets per Worker:**
- `ROUTINE_ENDPOINT` — `trig_...` URL z claude.ai routine "Call via API"
- `ANTHROPIC_TOKEN` — Bearer token z tej samej zakładki

---

## 15. Powiadomienia email

### 15.1 shared/notify.py functions

```python
send_email(subject, body, html=False) -> bool
notify_signal(signal_dict, alert_sent, reason="") -> bool
notify_exit(symbol, action, reason, pl_pct=None) -> bool
notify_order_executed(symbol, side, qty, price, ...) -> bool
notify_summary(monitor, signals_found, alerts_sent) -> bool
notify_peak_retrace(verdict, peak_dict) -> bool   # v3.3
notify_pr_open(pr_url, proposal_dict) -> bool      # Lane 2
notify_allocation_plan(plan_dict) -> bool          # v3.1
notify_allocation_execution(execution_dict) -> bool
```

### 15.2 Subject prefixes (operator może filtrować w Gmail)

| Prefix | Co |
|---|---|
| `[BUY] / [SELL] / [SELL_SHORT]` | Trade signal — order placed |
| `[QUEUED]` | Order placed but market closed (will fill at open) |
| `[DEFERRED]` | Per-symbol pause / instrument-window blocked |
| `[NOT-SENT]` | Hard fail (auth, API error) |
| `[EXIT]` | Position closed |
| `[EXECUTED]` | Bracket order filled |
| `[OPTIONS APPROVAL NEEDED]` | Options-monitor legacy path (rare) |
| `[PEAK-WARN]` | Daily peak retraced 30-50% |
| `[PROFIT-LOCK]` | Daily peak retraced 50%+, harvesting winners |
| `[allocator PLAN]` | Evening allocation plan |
| `[allocator EXEC]` | Morning execution result |
| `[learning-loop AUTO-PR]` | Lane 2 PR opened |
| `[emergency-close: ...]` | Emergency-close workflow fired |
| `[<Monitor>] N signal(s), M sent` | Per-run summary (only if N > 0) |

### 15.3 Email send technical

- Host: smtp.gmail.com:465 SSL
- Auth: `GMAIL_APP_PASSWORD` (16-char, whitespace stripped — critical fix from 2026-05-06)
- ASCII-only subject + body (no `\xa0`, no `–`/`—`)

---

## 16. Operacje i runbook

### 16.1 Typowy dzień

```
06:00 UTC                    | exit-monitor (off-hours 15-min)
                              | crypto-monitor */5 24/7
                              | defense-monitor */5 24/7
                              | twitter-monitor */5 24/7
                              | geo-monitor */15 24/7
                              | reddit-monitor */30 24/7
                              | monitor-health */30 24/7

11:18-13:24 UTC              | Pre-market: scanners only, no trade execution
                              | exit-monitor defers options closes

13:30 UTC                    | US market open
                              | price-monitor */5 starts firing
                              | options-monitor */5 starts firing
                              | options-exit-monitor */5 starts firing
                              | exit-monitor switches to 5-min cron

13:35 UTC                    | morning-allocator (if pending plan)

13:30-20:00 UTC              | Active trading window
                              | All entry/exit monitors active

20:00 UTC                    | US market close
                              | exit-monitor → 15-min off-hours cron

21:00 UTC                    | daily-learning fires
                              | LLM round 1 (Senior PM)
                              | LLM round 2 (Challenger)
                              | LLM round 3 (Senior PM revise)
                              | adapter.adapt() applies heuristics
                              | state.json updated
                              | history report written
                              | allocator plan computed
                              | Email: [allocator PLAN]
                              | Potential Lane 2 PRs created

22:00 UTC (Sun only)         | weekly-retro fires

22:30 UTC + 23:30 UTC        | daily-learning-watchdog
                              | Triggers daily-learning if 21:00 missed

00:00 UTC                    | daily_peak resets in peak_tracker
```

### 16.2 Operator runbook (typowe akcje)

#### Sprawdzenie stanu systemu
```bash
# Repo HEAD
git log --oneline origin/main -10

# state.json
python3 -c "import json; s=json.load(open('learning-loop/state.json')); print(json.dumps({k:v for k,v in s.items() if k in ['last_updated','days_tracked','peak_equity']}, indent=2))"

# Otwarte pozycje (Alpaca dashboard)
# → https://app.alpaca.markets/paper/dashboard/overview

# Najnowszy exit report
ls -lt exit-reports/*.md | head -3

# Monitor health
cat learning-loop/health/latest.md
```

#### Wyłączenie strategii ręcznie

```bash
# Edit learning-loop/state.json
"strategies": {
  "<name>": {
    "enabled": false,
    "paused_until": null,    # null = manual re-enable
    "rationale": "manual disable — <reason>"
  }
}
```

Commit + push z `[automerge]` w wiadomości.

#### Wymuszenie emergency close

```bash
# Stwórz nowy skrypt
cp scripts/emergency_close_20260514.py scripts/emergency_close_<date>.py
# Edytuj TARGETS = [...]

# Commit + push
git add scripts/emergency_close_<date>.py
git commit -m "emergency-close <date> [automerge] [auto-execute]"
git push origin <feature-branch>
```

Workflow zfires within 3 min schedule cron.

#### Anulowanie stale orders

```
GitHub Actions → cancel-stale-emergency-orders → Run workflow
```

#### Sprawdzenie LLM dialogu z ostatniej nocy

```bash
cat learning-loop/history/$(date -u +%Y-%m-%d).md
# Sekcje: Senior PM narrative, Challenger critique, revision log
```

### 16.3 Backtest

```
GitHub Actions → Backtest → Run workflow
Inputs:
  - strategy:  momentum-long | overbought-short | crypto-momentum
  - tickers:   "AAPL MSFT NVDA"
  - days:      180

Output: backtest/results/<strategy>-YYYYMMDD-HHMM.json
```

Walk-forward replay z bracket SL/TP simulation. Per-ticker + aggregate stats.

---

## 17. Zmienne środowiskowe i sekrety

### 17.1 GitHub Secrets (repo)

| Secret | Cel |
|---|---|
| `ALPACA_API_KEY` | Alpaca paper API Key ID |
| `ALPACA_SECRET_KEY` | Alpaca paper Secret Key |
| `GMAIL_USER` | Gmail address |
| `GMAIL_APP_PASSWORD` | Google App Password (16-char) |
| `NOTIFY_EMAIL` | mikosbartlomiej@gmail.com |
| `NEWSAPI_KEY` | NewsAPI.org free tier |
| `FINNHUB_API_KEY` | Finnhub free tier |
| `BLUESKY_HANDLE` | Bluesky account handle |
| `BLUESKY_APP_PASSWORD` | Bluesky app password |
| `REDDIT_CLIENT_ID` | Reddit OAuth (pending — no-API path active) |
| `REDDIT_CLIENT_SECRET` | Reddit OAuth (pending) |
| `WORKFLOW_PAT` | **Classic PAT** z `repo` + `workflow` scope (90-day cycle, rotate by 2026-08-11) |
| `CLOUDFLARE_WORKER_URL` | Tradingview proxy |
| `CLOUDFLARE_GEO_WORKER_URL` | Geo proxy |
| `CLOUDFLARE_EXIT_WORKER_URL` | Exit proxy |
| `CLOUDFLARE_CRYPTO_WORKER_URL` | Crypto proxy |
| `CLOUDFLARE_CRYPTO_CURATOR_WORKER_URL` | Crypto Curator proxy |
| `CLOUDFLARE_LEARNING_WORKER_URL` | Learning Loop Strategist proxy |
| `CLOUDFLARE_LEARNING_CHALLENGER_WORKER_URL` | Challenger proxy |
| `CLOUDFLARE_DEFENSE_WORKER_URL` | Defense proxy |
| `CLOUDFLARE_OPTIONS_WORKER_URL` | Options proxy (legacy) |
| `CLOUDFLARE_REDDIT_WORKER_URL` | Reddit fetch proxy |
| `CLOUDFLARE_REDDIT_CURATOR_WORKER_URL` | Reddit Curator proxy |
| `CLOUDFLARE_TWITTER_WORKER_URL` | Twitter proxy |

### 17.2 Cloudflare Worker env vars (per worker)

| Var | Cel |
|---|---|
| `ROUTINE_ENDPOINT` | `trig_...` URL z claude.ai |
| `ANTHROPIC_TOKEN` | Bearer token z routine "Call via API" |

Plus dla `dashboard-proxy` i `reddit-fetch-proxy`:
| Var | Cel |
|---|---|
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Read-only Alpaca snapshot |
| `GITHUB_TOKEN` | Fine-grained PAT (Contents:Read only) dla state.json access |

### 17.3 Per-monitor common env block

```yaml
env:
  PYTHONIOENCODING:    utf-8
  LC_ALL:              C
  LANG:                C
  ALPACA_API_KEY:      ${{ secrets.ALPACA_API_KEY }}
  ALPACA_SECRET_KEY:   ${{ secrets.ALPACA_SECRET_KEY }}
  GMAIL_USER:          ${{ secrets.GMAIL_USER }}
  GMAIL_APP_PASSWORD:  ${{ secrets.GMAIL_APP_PASSWORD }}
  NOTIFY_EMAIL:        ${{ secrets.NOTIFY_EMAIL }}
```

### 17.4 Render env vars (Alpaca MCP server — legacy)

**UWAGA: różne nazwy niż w GitHub Secrets:**
- `APCA_API_KEY_ID` (nie `ALPACA_API_KEY`)
- `APCA_API_SECRET_KEY` (nie `ALPACA_SECRET_KEY`)

---

## Appendix A: Source-of-truth dokumenty

| Plik | Co |
|---|---|
| `CLAUDE.md` | Master reference for agentic sessions, change log, decisions |
| `docs/STRATEGY.md` | Strategy specification (v3.0 risk-on, 12 sections) |
| `docs/PRODUCT.md` | **Ten dokument** |
| `.claude/rules/tickers-whitelist.md` | Allowed tickers per asset class |
| `.claude/rules/twitter-accounts.md` | 68 Bluesky accounts (T1-T3) |
| `.claude/rules/reddit-subs.md` | 6 curated subs + filters |
| `.claude/rules/reddit-users.md` | Tracked DD writers (empty) |
| `.claude/rules/report-format.md` | Email/report formatting |
| `learning-loop/routine-prompts.md` | Senior PM system prompt |
| `learning-loop/challenger-prompts.md` | Challenger system prompt |
| `reddit-monitor/curator-prompts.md` | Reddit Curator system prompt |
| `crypto-monitor/curator-prompts.md` | Crypto Curator system prompt |
| `config/aggressive_profile.json` | Single source of truth dla risk limits |
| `config/watchlists.json` | Bucket-organized universes |
| `config/instrument_windows.json` | Per-symbol trading hours |
| `config/capital_deployment.json` | Allocator config |

## Appendix B: Test suites

| Suite | Count | Path |
|---|---|---|
| Adapter heuristics | 34 | `learning-loop/test_adapter.py` |
| Instrument windows | 26 | `tests/test_instrument_windows.py` |
| Peak tracker | 14 | `tests/test_peak_tracker.py` |
| Allocator (plan + execute) | 30 | `tests/aggressive/test_allocator*.py` |
| v3 modules (profile, regime, momentum, risk_guards) | 23 | `tests/aggressive/test_v3.py` |
| **TOTAL** | **127** | |

Run all: `python3 -m unittest discover -s tests -v && (cd learning-loop && python3 -m unittest test_adapter)`

## Appendix C: Versioning history (skrót)

| Wersja | Data | Highlights |
|---|---|---|
| v1.0 | 2026-04-29 | Initial setup, MCP server, basic routines |
| v2.0 | 2026-05-06 | Risk-on overhaul, options live, 5-point master plan |
| v2.2 | 2026-05-07 | Routine bypass — direct REST execution |
| v2.3 | 2026-05-07 | Daily learning loop with permanent memory |
| v2.3.1 | 2026-05-07 | LLM augmentation on learning loop |
| v2.3.3 | 2026-05-08 | Three-lane LLM proposal architecture |
| v2.3.4+ | 2026-05-09 | Pipeline production-ready, 15 LLM proposals |
| v2.4 | 2026-05-12 | Crypto Predator (11 coins) + LLM Curator |
| v3.0 | 2026-05-12 | Aggressive Momentum + Event Switch (4-state regime) |
| v3.1 | 2026-05-12 | Full execute_orders allocator + verbose trace |
| v3.2 | 2026-05-12 | Per-instrument trading windows |
| v3.3 | 2026-05-13 | Peak tracker + PROFIT_LOCK + trailing stops |
| v3.4 | 2026-05-13 | Repo public + PAT-based workflow auto-sync |
| **v3.4.5** | **2026-05-14** | **Emergency-close picker fix + SPY RSI gate + monitor-health OFF_HOURS + Lane 2 CI + peak_equity persistence** |
| **vNext** | **2026-05-14** | **ARCHITECTURE_VNEXT** — see §17 for migration. Full autonomy contract + code-autonomy loop + system_consistency_agent (99.1/100) + e2e_system_test_agent (220 tests). |
| **v3.5** | **2026-05-14 LATE** | IntradayProfitGovernor — 7-state FSM defending intraday peak. Per-state gross caps + profit floor tiers + position MFE harvest. `docs/INTRADAY_PROTECTION.md` |
| **v3.6** | **2026-05-14 NIGHT** | Full autonomy chain end-to-end + Strategy Coherence Agent (98.0/100). `auto_execute_rebalance=true` + `entry-monitors-watchdog.yml` + risk_officer BP check |
| **v3.7** | **2026-05-14 LATE-NIGHT** | PDT/BP guard + Anthropic Routine 15/day budget. 4 modes + 3 priority tiers. Emergency-close bypass invariant |
| **v3.8** | **2026-05-14 EOD** | PDT guard intent-aware redesign. Day-trade = OPEN+CLOSE same day. Opens NEVER blocked on PDT count. Crypto exempt. Intent enum (swing/intraday/emergency) |
| **v3.8.5–7** | **2026-05-16 EOD** | UUID artifact prevention + LLM 04:00 UTC + bucket cap 60→65 + IntradayGovernor min_profit 1000→500 + geo-monitor direct execution refactor + emergency-close pre-market defer |
| **v3.8.9** | **2026-05-19** | daily-learning push retry + aggressive entry pricing (BUY@ask/SHORT@bid) + equity-gap alert + RSI extreme alerts |
| **v3.9.0** | **2026-05-20** | SILENT-warning grace period (5 days post-enabled_at) |
| **v3.9.1** | **2026-05-21** | NOW + new `software_quality` bucket (Senior PM diversification recommendation). New `software_cloud` correlated bucket @65% cap |
| **v3.9.2** | **2026-05-21 LATE** | **NEW MONITOR — politician-monitor**: Trump family Form 4 (DJT auto-execute) + bipartisan STOCK Act PTRs (20-name whitelist, sector cluster aggregation, Capitol Trader Curator). 10 new files, 40 tests, free data sources only |
| **v3.9.3** | **2026-05-21 LATE** | politician-monitor production fixes: EDGAR XML discovery via `/index.json`; 3-tier STOCK Act fallback (CapitolTrades → housewatcher → House Clerk official XML) bo CapitolTrades Lambda down |
| **v3.9.3.1** | **2026-05-21 LATE** | politician-monitor email subject fix (`[POL-FILING]` zamiast misleading `[SELL]`) + workflow template moved to `scripts/workflow-templates/` for sync-workflows propagation |
| **v3.9.4 → 4.4** | **2026-05-21 PM** | daily-learning push race condition resolved via cherry-pick retry (4 iterations) — system was NEVER in cash idle, 7 positions including NOW @ +0.79% had been at-target |
| **v3.9.5** | **2026-05-22** | **PR #8 (Lane 2 LLM) crypto oversold bounce boost wired** — boost crypto-momentum size_multiplier to 1.3× when ETH RSI ≤30 AND BTC RSI ≤45. Function + 5 unit tests from LLM, 4 integration tests + adapt() wire-in commit (8a899d7). Triggers today live (ETH RSI 27.5, BTC RSI 40.4). 43/43 tests green |
| **v3.9.5.1** | **2026-05-22** | LLM `POLL_MAX_S` 480→600 (+25% headroom for claude.ai latency spikes after today's 04:00 UTC routine timeout at 517s) + closed `[2026-05-17] SILENT grace` backlog item ([x] with verification note) |

---

## 18. Migration notes — vNext (2026-05-14 super-session)

Architectural changes introduced in a single multi-iteration session.
Earlier sections describe v3.4.5 conventions; vNext supersedes them.

### 18.1 What changed

| Layer | Before | After |
|---|---|---|
| **LLM kill switch** | env-var per workflow | `shared/runtime_config.py::llm_enabled()` — default **False** |
| **OPTIONS kill switch** | always-on with AUTO_EXECUTE | `OPTIONS_ENABLED=false` by default; options-monitor safe no-op when off |
| **Risk profile** | hardcoded "v2.0 risk-on" | env `RISK_PROFILE`: SAFE_FREE / **BALANCED_PAPER (default)** / AGGRESSIVE_PAPER |
| **State writes** | every monitor could commit state.json | `state_policy.assert_can_write_state(actor)` enforces allowlist (daily-learning / daily-report / weekly-retro / manual-maintenance) |
| **State schema** | implicit | `state_schema.validate_state()` clamps + drops hallucinated keys |
| **Portfolio risk** | per-symbol cap only | `portfolio_risk.evaluate_portfolio_risk()` with 7 correlated buckets + gross/net/options-premium/cash caps |
| **Signal confirmation** | news/social could trigger directly | `signal_confirmation.confirm_event_signal()` requires price+volume+dedupe+cooldown+freshness |
| **Emergency close** | manual `scripts/emergency_close_<date>.py` | `shared/emergency_engine.py::scan_emergency_conditions()` + `execute_emergency_close()` autoselect |
| **Approval emails** | `[OPTIONS APPROVAL NEEDED]` + 6-step Alpaca runbook | `[OPTIONS REJECTED]` audit-trail-only; no human in lifecycle |
| **Panic close** | `CONFIRM_PANIC_CLOSE_OPTIONS=true` operator-only | also `AUTONOMOUS_PANIC_CLOSE_OPTIONS=true` for autonomous remediation |
| **Code autonomy** | manual review | `patch_validator.py` + `code_autonomy.py` + `autonomous-code-loop.yml` daily; deterministic LOW/MEDIUM/HIGH_RISK validator |
| **Audit** | `journal/trades-*.md` daily | + `journal/autonomy/YYYY-MM-DD.jsonl` + `learning-loop/code-autonomy/history/YYYY-MM-DD.{jsonl,md}` |

### 18.2 New deliverables (highlights)

**Foundation (shared/):** `runtime_config.py`, `state_policy.py`,
`state_schema.py`, `portfolio_risk.py`, `signal_confirmation.py`,
`autonomy.py`, `audit.py`, `emergency_engine.py`, `remediation.py`.

**Learning loop:** `validation.py`, `patch_validator.py`,
`code_autonomy.py`.

**Scripts:** `audit_workflows.py`, `secret_scan_light.py`,
`trading_health.py`, `panic_close_options.py`,
`autonomous_remediation.py`, `autonomous_code_review.py`,
`system_consistency_agent.py`, `e2e_system_test_agent.py`.

**Workflows:** `autonomous-code-loop.yml`,
`autonomous-remediation.yml`, `security-audit.yml`,
`system-consistency-audit.yml`, `e2e-system-tests.yml`.

**Two autonomous agents** (full guide:
`docs/AGENTS_DOCUMENTATION.md`):

- `tools/system_consistency_agent/` — 15 categories, 74 checks; first
  run on this repo: **99.1/100 (WARN, 8/8 principles PASS)**.
- `tools/e2e_system_test_agent/` — 8 fake clients, 40-capability map,
  65 E2E tests; first run: **PASS, 220 tests green, 28/40 capabilities
  fully covered**.

**Test harness:** `tests/architecture_vnext/` (155 tests),
`tests/e2e/` (65 tests with no-network conftest), `pytest.ini` with
markers.

**Configuration:** `config/autonomy_bounds.json` — bounds for
self-modification (daily step / patch cap / loosening forbidden).

**Documentation:** `docs/ARCHITECTURE_VNEXT.md`,
`docs/AUTONOMY_CONTRACT.md`, `docs/CODE_AUTONOMY_CONTRACT.md`,
`docs/RISK_PROFILE.md`, `docs/FREE_TIER_LIMITS.md`,
`docs/OPERATIONS_RUNBOOK.md` (extended),
`docs/SYSTEM_CONSISTENCY_AGENT.md`,
`docs/E2E_SYSTEM_TEST_AGENT.md`,
`docs/AGENTS_DOCUMENTATION.md`.

### 18.3 Operator implications

- **Default trade behaviour is conservative**: LLM_ENABLED=false,
  OPTIONS_ENABLED=false, RISK_PROFILE=BALANCED_PAPER. Operators
  upgrading from v3.4.5 must explicitly opt in to LLM and options via
  workflow env vars.
- **No operator approval is ever required** in the trading lifecycle
  (verified by `tools/system_consistency_agent/`). The old `[OPTIONS
  APPROVAL NEEDED]` email is gone — every signal ends APPROVE or
  REJECT automatically; emails are audit-trail only.
- **Emergency close** no longer requires hand-rolled
  `scripts/emergency_close_<date>.py`. `emergency_engine` selects
  targets autonomously; `autonomous-remediation.yml` executes them
  every 15 minutes during session.
- **Code self-improvement** is part of the system —
  `autonomous-code-loop.yml` runs daily 21:30 UTC, validates candidate
  patches deterministically, auto-merges LOW_RISK without review.

### 18.4 First-run agent results

System Consistency Agent (`scripts/system_consistency_agent.py`):
- Overall: **WARN** (score 99.1/100)
- Principles: 8/8 PASS
- Findings: 72 PASS + 2 WARN (signal_confirmation monitor wiring
  backlog; options-exit dedup statically unobservable) + 0 FAIL

E2E System Test Agent (`scripts/e2e_system_test_agent.py`):
- Overall: **PASS**
- Tests: 220 green (155 architecture_vnext + 65 e2e)
- Coverage: 28/40 fully covered + 9 partial + 3 uncovered
- Network: blocked in tests

### 18.5 Backlog after vNext

| Priority | Item | Effort |
|---|---|---|
| P1 | Wire `signal_confirmation.confirm_event_signal()` into defense/geo/twitter/reddit monitors (5 lines × 4 files) → closes SIGCONF_MONITORS_WIRED WARN | 2h |
| P1 | Add `tests/e2e/test_exit_lifecycle_e2e.py` covering standalone exit-monitor decisions → closes 1 of 3 UNCOVERED capabilities | 2h |
| P2 | Migrate `peak_tracker` `daily_peak` + `trailing_state` to `learning-loop/runtime_state.json` + separate workflow with `STATE_WRITE_ACTOR=manual-maintenance` | 3h |
| P2 | Tighten `OPTIONS_EXIT_DEDUP` static check regex to recognise the existing dedup pattern → closes second WARN | 30 min |
| P3 | Workflow dispatcher consolidation (21 cron workflows → 6 dispatcher workflows) | 1 day |
| P3 | `from __future__ import annotations` in `shared/instrument_windows.py` + `shared/peak_tracker.py` for Python 3.9 local-test parity | 5 min |
| P3 | `tests/e2e/test_workflow_introspection_e2e.py` — verify all schedule workflows pass static checks → closes second UNCOVERED capability | 1h |

---

*Dokument zaktualizowany 2026-05-14 (vNext). Source of truth:
`docs/STRATEGY.md` (strategia) + `docs/ARCHITECTURE_VNEXT.md`
(architektura) + `docs/AGENTS_DOCUMENTATION.md` (agenty). Dla zmian
dnia-do-dnia: `CLAUDE.md`. Dla LLM personas:
`learning-loop/routine-prompts.md` + `challenger-prompts.md` +
`*/curator-prompts.md`.*
