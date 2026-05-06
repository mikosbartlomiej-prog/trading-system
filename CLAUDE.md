# Trading System — Master Reference for Claude Code
# READ THIS ENTIRE FILE BEFORE DOING ANYTHING

---

## ENVIRONMENT & ACCOUNTS

**Broker:** Alpaca Paper Trading only (PAPER — not live)
- Account ID: PA3KNZV29BP5
- Equity: ~$100,032 (as of 2026-05-06)
- Paper API: https://paper-api.alpaca.markets
- Dashboard: https://app.alpaca.markets/paper/dashboard/overview
- Shorting: ENABLED (no_shorting=false)
- Options: Level 3 (all strategies permitted)
- Buying power: ~$198,000 (4x margin)

**MCP Server (Alpaca):**
- Deployed on Render.com: https://alpaca-mcp-server-fchb.onrender.com/mcp
- Local repo: ~/Documents/alpaca-mcp-server
- Render env vars (DIFFERENT names than GitHub Secrets):
  - `APCA_API_KEY_ID` = Alpaca key
  - `APCA_API_SECRET_KEY` = Alpaca secret

---

## REPOSITORY STRUCTURE

**One repo for everything:** `~/Documents/Git/trading-system`
- Remote: git@github.com:mikosbartlomiej-prog/trading-system.git
- Branch: main
- Push commands: `cd ~/Documents/Git/trading-system && git add -A && git commit -m "..." && git push`

**WARNING:** `~/Downloads/investing` is NOT a git repo. It is only the Cowork workspace.
Any code there is a stale copy — the real files are in `~/Documents/Git/trading-system`.

---

## GITHUB SECRETS (trading-system repo)

| Secret | Value / Purpose |
|--------|----------------|
| `ALPACA_API_KEY` | Alpaca paper API Key ID |
| `ALPACA_SECRET_KEY` | Alpaca paper Secret Key |
| `GMAIL_USER` | Gmail address for email notifications |
| `GMAIL_APP_PASSWORD` | Google App Password (16 chars, spaces stripped in code) |
| `NOTIFY_EMAIL` | mikosbartlomiej@gmail.com |
| `NEWSAPI_KEY` | NewsAPI.org free tier key |
| `FINNHUB_API_KEY` | Finnhub API key |
| `CLOUDFLARE_WORKER_URL` | https://tradingview-proxy.mikosbartlomiej.workers.dev |
| `CLOUDFLARE_GEO_WORKER_URL` | https://geopolitical-proxy.mikosbartlomiej.workers.dev |
| `CLOUDFLARE_EXIT_WORKER_URL` | https://exit-monitor-proxy.mikosbartlomiej.workers.dev |
| `CLOUDFLARE_CRYPTO_WORKER_URL` | https://crypto-proxy.mikosbartlomiej.workers.dev |
| `CLOUDFLARE_LEARNING_WORKER_URL` | https://learning-loop-proxy.mikosbartlomiej.workers.dev |
| `CLOUDFLARE_DEFENSE_WORKER_URL` | https://defense-proxy.mikosbartlomiej.workers.dev |
| `REDDIT_CLIENT_ID` | Reddit app client_id (pending API approval) |
| `REDDIT_CLIENT_SECRET` | Reddit app client_secret (pending API approval) |

---

## CLOUDFLARE WORKERS → CLAUDE ROUTINES

Each monitor sends signals to a Cloudflare Worker, which triggers a Claude Routine via API.

**Cloudflare account:** mikosbartlomiej — https://dash.cloudflare.com

| Worker | URL | Claude Routine trigger (trig_...) | Status |
|--------|-----|-----------------------------------|--------|
| tradingview-proxy | https://tradingview-proxy.mikosbartlomiej.workers.dev | (from earlier session) | ✅ |
| geopolitical-proxy | https://geopolitical-proxy.mikosbartlomiej.workers.dev | (from earlier session) | ✅ |
| exit-monitor-proxy | https://exit-monitor-proxy.mikosbartlomiej.workers.dev | trig_01QL21osTHsnNvpyawXCdkiQ | ✅ |
| crypto-proxy | https://crypto-proxy.mikosbartlomiej.workers.dev | trig_01Y1QB5MCF1jtrGS51QixSrR | ✅ |
| learning-loop-proxy | https://learning-loop-proxy.mikosbartlomiej.workers.dev | trig_0175V2oDoLMn9y75HoDx8NGd | ✅ |
| defense-proxy | https://defense-proxy.mikosbartlomiej.workers.dev | (set up but defense-monitor now sends email directly too) | ✅ |
| reddit-proxy | https://reddit-proxy.mikosbartlomiej.workers.dev | (pending Reddit API approval) | ⏳ |

**Cloudflare Worker code (same for all workers):**
```javascript
export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }
    const body = await request.json();
    const routinePayload = { text: JSON.stringify(body) };
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
    return new Response(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  },
};
```
Worker secrets per worker: `ROUTINE_ENDPOINT` (trig_... URL) and `ANTHROPIC_TOKEN` (from claude.ai routine's "Call via API" section).

---

## MONITORS — STATUS & SCHEDULE

All monitors run via GitHub Actions in the trading-system repo.

| Monitor | Cron | Status | Sends email | Sends to Cloudflare |
|---------|------|--------|-------------|---------------------|
| defense-monitor | `0,30 * * * *` (24/7) | ✅ WORKING | ✅ CONFIRMED 2026-05-06 | ✅ |
| crypto-monitor | `0 * * * *` + `30 * * * *` (24/7) | ✅ | ✅ integrated | ✅ |
| price-monitor | `*/5 13-20 * * 1-5` | ✅ | ✅ integrated 2026-05-06 (notify_signal + notify_summary) | ✅ |
| exit-monitor | `30 12-21 * * 1-5` + `0 22,0,2 * * *` | ✅ | ✅ integrated 2026-05-06 (notify_exit + notify_summary) | ✅ |
| geo-monitor | `*/15 13-21 * * 1-5` | ✅ (not recently verified) | ❌ not integrated | ✅ |
| weekly-learning | `0 20 * * 0` (Sunday 20:00 UTC) | ✅ | ❌ not integrated | ✅ |
| keep-alive | `*/10 * * * *` | ✅ | ❌ (not needed) | pings Render |
| reddit-monitor | `0 7,13,16,20 * * 1-5` | ⏳ waiting for Reddit API approval | ❌ | ⏳ |

**All workflow env blocks must include:**
```yaml
PYTHONIOENCODING: utf-8
LC_ALL: C
LANG: C
```

---

## EMAIL NOTIFICATIONS — shared/notify.py

**Status: WORKING ✅** (confirmed 2026-05-06, defense-monitor sent two emails successfully)

**Root cause of the long-running \xa0 crash (SOLVED):**
The GMAIL_APP_PASSWORD GitHub Secret contained \xa0 (non-breaking space) from copy-pasting Google's App Password UI (which formats as "xxxx xxxx xxxx xxxx" with non-breaking spaces). smtplib encodes SMTP AUTH as ASCII — crashed at position 31 (first space in the password).

**Fix in notify.py:** GMAIL_APP_PASSWORD is stripped of all whitespace variants at load time.

**Key functions:**
- `send_email(subject, body)` — sends via Gmail SMTP SSL port 465
- `notify_signal(signal_dict, alert_sent)` — trading signal email
- `notify_exit(symbol, action, reason, pl_pct)` — position closed email
- `notify_order_executed(symbol, side, qty, price, size_usd, sl, tp, strategy, order_id)` — bracket order confirmation
- `notify_summary(monitor, signals_found, alerts_sent)` — run summary (only if signals > 0)

**Integration status:**
- defense-monitor/monitor.py — ✅ calls notify_signal() and notify_summary()
- crypto-monitor/monitor.py — ✅ integrated
- price-monitor/monitor.py — ✅ integrated 2026-05-06 (notify_signal per LONG/SHORT/leveraged alert + notify_summary at end)
- exit-monitor/monitor.py — ✅ integrated 2026-05-06 (notify_exit per flagged position + notify_summary at end)

---

## OPEN POSITIONS (as of 2026-05-06 18:14 UTC)

| Symbol | Side | Qty | Entry | P&L |
|--------|------|-----|-------|-----|
| GLD | LONG | 3 | $418.81 | +$33.63 (+2.68%) |
| RTX | LONG | 1 | $172.60 | +$3.56 (+2.06%) |
| XLE | LONG | 5 | $58.96 | -$9.74 (-3.30%) |

---

## TODO LIST (in priority order)

### Done ✅
1. ✅ Fix email \xa0 encoding crash — root cause was non-breaking space in GMAIL_APP_PASSWORD secret
2. ✅ Confirm email works end-to-end — tested 2026-05-06 with defense-monitor
3. ✅ Fix all workflow files — merged duplicate env blocks, added PYTHONIOENCODING/LC_ALL/LANG
4. ✅ English email strings throughout notify.py
5. ✅ **Master Plan #2 — Email notifications integrated in all 4 active monitors** (2026-05-06)
   - price-monitor: notify_signal() per LONG/SHORT/leveraged alert + notify_summary() at end of run
   - exit-monitor:  notify_exit() per flagged (non-HOLD) position + notify_summary() at end of run
   - In-process integration tests passed (mocked Alpaca/Finnhub + spy on notify hooks)
   - Workflows already exposed GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_EMAIL — no workflow change required
6. ✅ **Repo cleanup** (2026-05-06)
   - Added `.gitignore` (covers `__pycache__/`, `.venv/`, `.DS_Store`, `.env*`, etc.)
   - Untracked all `__pycache__/*.pyc` files (build artifacts that should never be in git)
   - Deleted stale duplicate workflow files: `crypto-monitor/crypto-monitor.yml`, `exit-monitor/exit-monitor.yml`, `learning-loop/weekly-learning.yml` (canonical copies live in `.github/workflows/` — only those are picked up by GitHub Actions)

### Pending — THE MASTER 5-POINT PLAN

**#2 — Email notifications from Claude Routines — DONE ✅** (see Done section above)

**#3 — Options monitor — CODE DONE ✅, deployment PENDING** (2026-05-06)
- New: `options-monitor/monitor.py` + `requirements.txt`
- Detects momentum setups on a curated whitelist (AAPL, MSFT, GOOGL, NVDA,
  META, AMZN, TSLA, SPY, QQQ, JPM, RTX, LMT):
  - RSI 45-65 -> CALL proposal (BUY_TO_OPEN_CALL)
  - RSI > 72  -> PUT proposal  (BUY_TO_OPEN_PUT)
- Emits a *proposal* payload (the routine resolves the actual contract via
  Alpaca MCP and asks the user for explicit approval before placing the
  order — iron rule "Options require explicit user approval each time")
- Guards: VIX guard (HALT/CAUTION/OK), earnings calendar (±1d -> skip),
  global cap of MAX_OPEN_OPTIONS=3 across all underlyings
- Strategy params (strategies/options-strategy.md):
  size_usd $500, max_contracts 1-2 per signal, DTE 14-21,
  strike ATM ±3%, IV<35% (call) / IV<45% (put),
  TP +80% premium, SL -50% premium
- Integration tests passed (7 scenarios: CALL/PUT/neutral/earnings/cap/HALT/CAUTION)
- USER STILL NEEDS:
  1. Add `.github/workflows/options-monitor.yml` via GitHub UI (template ready)
  2. Create Cloudflare Worker `options-proxy` + add `CLOUDFLARE_OPTIONS_WORKER_URL` secret
  3. Create Claude Routine `Options Handler` (system prompt template ready)

**#5 — Duplicate position guard — DONE ✅** (2026-05-06)
- `shared/risk_guards.py::has_open_position(symbol)` queries Alpaca
  `/v2/positions/{symbol}` (URL-encoded so `BTC/USD` works)
- Returns True only on HTTP 200; 404 / network errors / missing creds fail OPEN
  (a single Alpaca outage cannot silently block all signals)
- Wired into: price-monitor, crypto-monitor, defense-monitor
  - Each monitor: when a signal fires, check `has_open_position(symbol)`
    BEFORE sending the alert; skip if True (logs `pominięty (otwarta pozycja)`)
- Geo-monitor INTENTIONALLY skipped — sends raw news to a routine that
  decides the ticker, so dedup at this layer wouldn't see the symbol
- Workflow note: ALPACA_API_KEY + ALPACA_SECRET_KEY must be present in
  price-monitor.yml and defense-monitor.yml env blocks (crypto already
  has them); without the keys the guard fails open and is a no-op

**#4 — VIX guard for all entry monitors — DONE ✅** (2026-05-06)
- `shared/risk_guards.py` exposes `vix_guard()` returning `(status, multiplier)`:
  - VIX > 45 -> `("HALT", 0.0)` -> monitor returns early, sends 0-signal summary
  - VIX > 35 -> `("CAUTION", 0.5)` -> monitor multiplies `signal["size_usd"]` by 0.5
  - otherwise -> `("OK", 1.0)` -> normal sizing
- Fail-open: if Finnhub unreachable / `FINNHUB_API_KEY` unset, returns OK (a Finnhub
  outage cannot silently halt all trading)
- Wired into: price-monitor, crypto-monitor, defense-monitor, geo-monitor
- Exit-monitor INTENTIONALLY skipped — closing positions during a crash is desirable
- All 4 workflows now expose `FINNHUB_API_KEY` (added to crypto + defense)
- VIX source: Finnhub `/quote?symbol=^VIX`
- Integration tests passed (HALT/CAUTION/OK paths verified across 3 monitors)

**#1 — Live Portfolio Dashboard** (~20 min, highest ROI for daily use)
- Goal: artifact that shows current positions, P&L, latest alerts — open once, refresh anytime
- Uses Alpaca MCP directly via Cowork artifact
- Problem: UUID connector (`mcp__aaf463f1-cb15-4654-9680-1f0b41af56f5__`) works in Cowork chat
  but NOT inside artifacts. Stable `mcp__alpaca__` returns 401.
- Current workaround: static dashboard.html in ~/Downloads/investing/dashboard.html, refresh on demand
- Real fix needed: either fix stable connector auth, or find another approach

### Other pending
- **Reddit monitor** — waiting for Reddit API email approval
  - Resume guide: docs/RESUME-REDDIT.md
  - When email arrives: create app at reddit.com/prefs/apps → type: script
  - Add secrets: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, CLOUDFLARE_REDDIT_WORKER_URL

---

## IRON RULES — NEVER VIOLATE

### Position sizing
- Maximum single trade: 5% of account equity
- Maximum exposure per ticker: 15% equity
- Minimum cash: always keep 5% as cash
- Daily loss limit: if total day loss > 3% equity → STOP, no new positions

### Allowed tickers ONLY
See .claude/rules/tickers-whitelist.md for full list.
Attempting to trade outside the list = immediate abort.

### Order types
- Always LIMIT orders (never MARKET)
- Every entry = bracket order: entry + stop loss + take profit
- Time in force: DAY (unless strategy specifies otherwise)

### Forbidden
- Options — require explicit user approval each time
- Margin / leveraging
- Trading when VIX > 35
- Trading 30 minutes before/after earnings releases

---

## MANDATORY WORKFLOW FOR EVERY ORDER

1. Delegate to sub-agent risk-officer (.claude/agents/risk-officer.md)
2. If APPROVE → execute via skill place-bracket-order
3. If REJECT → log reason, do NOT trade
4. Always → write to journal/trades-YYYY-MM-DD.md

---

## COMMUNICATION FORMAT

- Reports in Polish (but email content in English)
- Every executed/rejected order → Slack #trading (if configured)
- Report format: .claude/rules/report-format.md

---

## KEY TECHNICAL DETAILS

### crypto-monitor API quirks
- Alpaca crypto symbol format: `BTC/USD` (with slash, NOT `BTCUSD`)
- Timeframe: `1Hour` (NOT `1H` — causes 400 error)
- Always include `start=5 days ago` in request (default returns only ~17 bars)

### exit-monitor API calls
- Uses Alpaca REST directly (not MCP) with ALPACA_API_KEY / ALPACA_SECRET_KEY
- Auth headers: `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`
- Base URL: https://paper-api.alpaca.markets
- Endpoints: /v2/positions, /v2/account, /v2/orders

### Monitor signal flow
```
GitHub Actions cron
  → monitor.py runs
    → detects signal
    → HTTP POST to Cloudflare Worker URL
      → Worker adds auth headers
        → POST to Claude Routine (trig_... endpoint)
          → Routine executes trade via Alpaca MCP
    → sends email via shared/notify.py → Gmail SMTP
```

### Shared notify.py import pattern
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from notify import notify_signal, notify_exit, notify_summary
```

---

## SESSION HISTORY QUICK REFERENCE

| Date | What happened |
|------|--------------|
| 2026-04-29 | Initial setup: Alpaca account, MCP server on Render, first routines |
| 2026-05-04 | Reddit monitor, geo-monitor, leveraged ETF strategy |
| 2026-05-05 | Exit monitor, crypto monitor fixes, all Cloudflare workers working |
| 2026-05-06 | Defense monitor, email notifications — root cause found and fixed |
| 2026-05-06 | Master Plan #2 done: notify_signal/notify_exit/notify_summary wired into price-monitor + exit-monitor (defense + crypto already done). Repo cleanup: .gitignore added, __pycache__ untracked, stale duplicate workflow ymls removed. |
| 2026-05-06 | Master Plan #4 done: VIX guard (`shared/risk_guards.py::vix_guard`) wired into all 4 entry monitors (price/crypto/defense/geo). HALT @VIX>45, CAUTION @VIX>35 (50% sizing). Fail-open on Finnhub outage. FINNHUB_API_KEY added to crypto + defense workflows. |
| 2026-05-06 | Master Plan #5 done: duplicate-position guard (`shared/risk_guards.py::has_open_position`) wired into price/crypto/defense monitors. Hits Alpaca `/v2/positions/{symbol}` (URL-encoded) before each alert; skips signals for tickers already held. Fail-open. ALPACA_API_KEY + ALPACA_SECRET_KEY required in price-monitor.yml + defense-monitor.yml (crypto already had them). |
| 2026-05-06 | Master Plan #3 code done: `options-monitor/monitor.py` emits CALL/PUT proposals (RSI 45-65 / RSI>72) with VIX guard + earnings guard + global cap of 3 open options. Forwards to a routine that resolves the contract and asks user for approval before trading. Pending: workflow YAML, Cloudflare Worker, Claude Routine setup (all user-side). |

---

*Last updated: 2026-05-06 by Claude (Cowork session)*
*Repo: git@github.com:mikosbartlomiej-prog/trading-system.git*
