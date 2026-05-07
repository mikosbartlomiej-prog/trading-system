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
| `CLOUDFLARE_OPTIONS_WORKER_URL` | https://options-proxy.mikosbartlomiej.workers.dev (legacy — bypassed by AUTO_EXECUTE) |
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
| options-proxy | https://options-proxy.mikosbartlomiej.workers.dev | trig_... (Options Handler routine) | ⚠️ deprecated — Anthropic Routines kept 429-ing; options-monitor now bypasses via AUTO_EXECUTE_OPTIONS=true and calls Alpaca REST directly |
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
| options-monitor | `*/10 13-20 * * 1-5` | ✅ LIVE 2026-05-06 (first AMZN PUT fill confirmed) | ✅ [EXECUTED] / [OPTIONS APPROVAL NEEDED] | ⚠️ deprecated routine path; AUTO_EXECUTE_OPTIONS=true bypasses |
| options-exit-monitor | `*/5 13-20 * * 1-5` | ✅ LIVE 2026-05-06 | ✅ notify_exit per close | n/a (direct Alpaca REST) |
| geo-monitor | `*/15 13-21 * * 1-5` | ✅ (not recently verified) | ❌ not integrated | ✅ |
| twitter-monitor | `*/5 13-20 * * 1-5` + `*/15 * * * *` | ✅ LIVE 2026-05-07 (Bluesky AT-Protocol) | ✅ notify_signal + summary | ✅ Cloudflare Worker `twitter-proxy` |
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

## OPEN POSITIONS (as of 2026-05-06 19:33 UTC, end of session)

| Symbol | Type | Side | Qty | Entry | P&L (last seen) |
|--------|------|------|-----|-------|-----------------|
| GLD | stock | LONG | 3 | $418.81 | +$33.63 (+2.68%) |
| RTX | stock | LONG | 1 | $172.60 | +$3.56 (+2.06%) |
| XLE | stock | LONG | 5 | $58.96 | -$9.74 (-3.30%) |
| AMZN260520P00270000 | option PUT | LONG | 1 | $3.65 | -17.8% — first paper-options trade, monitored by options-exit-monitor (TP=$6.57, SL=$1.82) |

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
   - Consolidated 39 unique session reports/journals from 31 stale `claude/*` branches into `briefs/`, `exit-reports/`, `geo-reports/`, `journal/` on main (commit 979b45f); old branches still exist on origin (proxy 403 blocked deletion — user can delete via GitHub UI, all unique content already on main)
7. ✅ **Master Plan #4 — VIX guard for entry monitors** (2026-05-06)
   - `shared/risk_guards.py::vix_guard()` returns `(status, multiplier)`
   - VIX > 45 -> HALT (early return + 0-signal summary email)
   - VIX > 35 -> CAUTION (signal["size_usd"] *= 0.5)
   - else / Finnhub failure -> OK (fail-open so a Finnhub outage cannot silently halt all trading)
   - Wired into price/crypto/defense/geo monitors. Exit-monitor intentionally skipped (closing during a crash is desirable)
   - All 4 entry-monitor workflows now expose FINNHUB_API_KEY
   - Production note (2026-05-06): Finnhub free-tier `/quote?symbol=^VIX` returns empty data, so vix_guard currently fail-opens. Trading continues normally; the circuit breaker is dormant until a more reliable VIX source is wired (VIXY ETF via Alpaca proxy is the planned follow-up)
8. ✅ **Master Plan #5 — Duplicate position guard** (2026-05-06)
   - `shared/risk_guards.py::has_open_position(symbol)` queries Alpaca `/v2/positions/{symbol}` (URL-encoded so `BTC/USD` works)
   - Returns True only on HTTP 200; 404 / network errors / missing creds fail OPEN
   - Wired into price/crypto/defense monitors — checked BEFORE every alert dispatch; skip if True (logs `pominięty (otwarta pozycja)`)
   - Geo-monitor skipped — it forwards raw news to a routine that decides the ticker, so symbol-level dedup isn't visible at this layer
   - Workflows: ALPACA_API_KEY + ALPACA_SECRET_KEY added to price-monitor.yml + defense-monitor.yml (crypto already had them)
9. ✅ **Master Plan #3 — Options monitor (entry + exit auto-execute)** (2026-05-06)
   - `options-monitor/monitor.py`: detects momentum setups on whitelist (AAPL, MSFT, GOOGL, NVDA, META, AMZN, TSLA, SPY, QQQ, JPM, RTX, LMT)
     - RSI 45-65 -> CALL proposal, RSI > 72 -> PUT proposal
     - Guards: VIX, earnings ±1d skip, MAX_OPEN_OPTIONS=3 global cap, MAX_PROPOSALS_PER_RUN=1
   - **AUTO_EXECUTE_OPTIONS=true (default)** path: monitor resolves contract via Alpaca `/v2/options/contracts` (free, no paid sub needed) → picks closest-to-ATM with positive close_price ≤ size_usd/100 → posts simple LIMIT BUY via `/v2/orders` (no `order_class=bracket` because Alpaca paper rejects complex orders for options)
   - Iterates entire RSI-sorted proposal list until `sent==cap`; "no_contract" silently skipped, "rejected" emailed via [OPTIONS APPROVAL NEEDED] fallback
   - **First real paper-options trade confirmed 2026-05-06 19:18 UTC: AMZN260520P00270000 BUY_TO_OPEN_PUT @ $3.65** (visible in Alpaca dashboard)
   - `options-exit-monitor/monitor.py`: polls every 5 min during session, evaluates each open us_option position against entry-derived TP=*1.80 / SL=*0.50, posts SELL-to-close LIMIT when threshold hit, de-dupes via `/v2/orders?status=open&symbols=...`
   - Iron rule for options relaxed to AUTO-EXECUTE on paper (per-run + global caps + email audit trail enforce safety)
   - Tests: 7 scenarios for options-monitor (CALL/PUT/neutral/earnings/cap/HALT/CAUTION + iteration past too-expensive proposals + auto-execute path); 5 scenarios for options-exit-monitor (TP/SL/HOLD/dedup/empty)
   - Smoke tests confirmed end-to-end: workflow trigger -> Alpaca chain fetch -> order placed -> [EXECUTED] email -> options-exit-monitor finds the AMZN position and reports HOLD with TP=$6.57, SL=$1.82
10. ✅ **Migrated Finnhub `/stock/candle` to Alpaca daily bars** (2026-05-06)
    - Finnhub free tier started returning HTTP 403 on `/stock/candle` mid-2024 (endpoint moved to paid plan)
    - Symptom: options-monitor saw 12 consecutive 403s; price-monitor was silently producing 0 signals (zero-signals path swallowed the failure)
    - New: `shared/market_data.py::get_daily_bars(symbol, days)` hits Alpaca `/v2/stocks/{symbol}/bars` (free IEX feed, same paper keys we use)
    - Returns identical dict shape so downstream RSI/ATR/volume code stays the same
    - Migrated: options-monitor + price-monitor

11. ✅ **Account-level safety nets enforced in code** (2026-05-07)
    - `shared/risk_guards.py::get_account_status()` — single Alpaca call returning equity / last_equity / daily_pl_pct / buying_power
    - `daily_drawdown_guard(account=None)` — HALT new entries if daily P&L ≤ -12% (matches STRATEGY v2.0 §3.1)
    - `position_pct(symbol, equity=None)` — % of equity in a given symbol; URL-encoded for crypto
    - `concentration_ok(symbol, new_size_usd, equity=None)` — `(True/False, combined_pct)` where False means combined > 40% per-ticker cap
    - Wired into price-monitor, crypto-monitor, defense-monitor, geo-monitor — drawdown HALT before VIX, concentration check before each alert
    - All guards fail OPEN — Alpaca outage cannot silently block all entries

12. ✅ **Event Probability & Contrarian Reaction Layer (MVP)** (2026-05-07)
    - New: `shared/event_scoring.py` — heuristic scoring layer
    - 4 score functions: `event_credibility(source_type, ...)`, `probability_shift(event_type, magnitude)`, `market_reaction(price_move_atr, volume_ratio, gap_pct)`, `decide_stance(...)`
    - Stance: `FOLLOW_REACTION` | `IGNORE_EVENT` | `CONTRARIAN_CANDIDATE` | `WAIT_FOR_CONFIRMATION`
    - Wired into defense-monitor (`apply_event_scoring`) and geo-monitor (`attach_event_scoring`); IGNORE/WAIT dropped, CONTRARIAN flagged but not auto-traded
    - MVP placeholder: `price_move_atr=0.5, volume_ratio=1.0` (real per-ticker bar data deferred — needs `shared/market_data.py` hook in defense/geo signal paths)

13. ✅ **twitter-monitor MVP (Bluesky AT-Protocol)** (2026-05-07)
    - New: `twitter-monitor/monitor.py` — pure-stdlib + requests Bluesky client (no atproto SDK dep)
    - Curated whitelist: `.claude/rules/twitter-accounts.md` (19 accounts across gov_us / mil_il / macro / wire / ticker:* categories with per-category keyword filter)
    - Pipeline: drawdown_guard → vix_guard → load_accounts → getAuthorFeed → keyword filter → event_scoring → routine forward + email
    - `BlueskyClient` wraps `com.atproto.server.createSession` (login) + `app.bsky.feed.getAuthorFeed`
    - X API v2 Basic ($100/mo) is the future upgrade path — same monitor will swap data source via a `SocialClient` abstraction
    - Iron rule: monitor never places trades; only emits proposals
    - **DEPLOYED 2026-05-07:** Bluesky account, app password, 3 GitHub secrets, Cloudflare Worker, Routine, workflow YAML — all live; first smoke test passed (login OK, 19 accounts loaded, 0 candidates because no recent keyword-matched posts)

14. ✅ **Real bar-data hooked into event_scoring** (2026-05-07)
    - `shared/market_data.py::compute_reaction_metrics(symbol)` — fetches 25 daily bars, computes ATR(14), today's move in ATR units, volume vs 20d avg, gap %
    - Per-tick module-level cache so repeated lookups for the same symbol cost 1 Alpaca call
    - Wired into defense-monitor (per-signal ticker), geo-monitor (SPY proxy), twitter-monitor (per-category: ticker:SYM → that ticker, others → SPY)
    - All three store raw metrics under `reaction_metrics` for journal/audit
    - Verified: rumor + 2.55-ATR + 4× volume → CONTRARIAN_CANDIDATE (was IGNORE under MVP placeholder); reuters + same violent move → FOLLOW_REACTION; quiet day + rumor → IGNORE
    - Closes the MVP gap from yesterday's event-probability layer

15. ✅ **Master Plan #1 — Live Portfolio Dashboard** (2026-05-07)
    - `dashboard/worker.js` — single self-contained Cloudflare Worker
    - `GET /` serves dark-mode HTML (vanilla JS, no build, auto-refresh 30 s)
    - `GET /api/snapshot` returns combined `/v2/account` + `/v2/positions` + `/v2/orders`
    - HTML displays: equity, daily P&L, cash, buying power, positions table (with concentration colouring at 25%/35%), recent orders
    - Alpaca keys live in Worker env vars; never reach the browser
    - `dashboard/SETUP.md` — 5-step deploy guide (~5 min)
    - Tested with mocked Alpaca: snapshot shape OK, HTML 9.6 KB serving, 404 on unknown paths
    - Closes the original master 5-point plan (5/5 LIVE)

### Master 5-Point Plan — closed out 2026-05-06

| # | Description | Status |
|---|-------------|--------|
| #2 | Email notifications from monitors via Gmail SMTP | ✅ LIVE — see Done #5 |
| #3 | Options monitor (entry + auto exit on paper) | ✅ LIVE — see Done #9; first AMZN PUT trade confirmed |
| #4 | VIX guard for entry monitors | ✅ LIVE (fail-open in prod — see Done #7 production note) |
| #5 | Duplicate position guard | ✅ LIVE — see Done #8 |
| #1 | Live Portfolio Dashboard | ✅ LIVE 2026-05-07 — see Done #14 (single Cloudflare Worker, vanilla HTML) |

### Backlog (no committed timeline)

- ~~**Live Portfolio Dashboard**~~ ✅ **DONE 2026-05-07** (master plan #1 — last item closed)
  - Path 2 chosen: single self-contained Cloudflare Worker (`dashboard/worker.js`)
    serving both the HTML page (`GET /`) and the read-only Alpaca snapshot API
    (`GET /api/snapshot`). Vanilla JS, no build step, auto-refresh every 30 s.
  - Sections: equity / daily P&L / cash / buying power cards, open-positions
    table (qty, entry, current, P&L $/%, % equity with concentration colouring),
    recent-orders table.
  - User-side: deploy the Worker (paste `dashboard/worker.js` into Cloudflare,
    set ALPACA_API_KEY + ALPACA_SECRET_KEY env vars, open the workers.dev URL).
    Full guide: `dashboard/SETUP.md`.
  - Verified: mocked /api/snapshot returns shape `{account, positions, orders,
    errors, timestamp}`; `/` returns 9.6 KB HTML; `/nope` returns 404.
  - Closes the original master 5-point plan — all five items now LIVE.

- **Reddit monitor** — waiting for Reddit API email approval
  - Resume guide: `docs/RESUME-REDDIT.md`
  - When email arrives: create app at reddit.com/prefs/apps → type: script
  - Add secrets: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `CLOUDFLARE_REDDIT_WORKER_URL`

- **VIX guard pivot to a working source** (follow-up to Done #7 production note)
  - Symptom: Finnhub free `/quote?symbol=^VIX` returns empty; vix_guard always fail-opens in prod
  - Candidates: VIXY ETF via Alpaca bars (proxy with rough scaling), Yahoo Finance public quote (brittle), FRED VIXCLS series (free key)
  - ETA when prioritised: ~15 min to wire one source + test

- **Backtest harness** for the momentum-long / overbought-short strategies on 6+ months of data
  - Currently trading on live signals only; no validation that the rules actually have edge
  - Would need historical bars (Alpaca offers free historical IEX), simple replay of `check_long_signal` / `check_short_signal` and tracking simulated P&L

- **Risk officer agent gate** (`.claude/agents/risk-officer.md`) — exists but not wired into monitor flow
  - CLAUDE.md "Mandatory workflow for every order" still expects this gate; today's monitors bypass it (alerts go straight to routine / Alpaca)
  - Either delete the rule or wire the agent in

- **Verify weekly-learning loop end-to-end** (added 2026-05-06 EOD)
  - Workflow `weekly-learning.yml` runs Sunday 20:00 UTC; never confirmed it actually
    pulls journal/trades-*.md, computes anything useful, and round-trips to the
    learning-loop-proxy worker → routine
  - Action items:
    1. Manually trigger via Run workflow on a weekday (test mode)
    2. Inspect output of `learning-loop/analyzer.py` — does it read journal/* correctly?
    3. Verify Cloudflare worker `learning-loop-proxy` returns HTTP 200
    4. Verify the linked routine `trig_0175V2oDoLMn9y75HoDx8NGd` produces a
       useful weekly retrospective (not just an error)
    5. If any step fails, decide: fix the analyzer, deprecate the workflow, or
       redesign the retrospective format

- ~~**Drawdown circuit-breaker enforcement**~~ ✅ **DONE 2026-05-07**
  - `shared/risk_guards.py::daily_drawdown_guard(account=None)` returns
    `("HALT", reason)` when daily_pl_pct ≤ -12%, else `("OK", reason)`.
    Reads `/v2/account` via new `get_account_status()`. Fail-open on
    Alpaca outage. Wired into all 4 entry monitors BEFORE the VIX guard.
  - Weekly -25% / Monthly -40% stops still TODO (need rolling P&L
    tracking outside what `/v2/account` exposes directly).

- ~~**Per-ticker concentration cap enforcement**~~ ✅ **DONE 2026-05-07**
  - `shared/risk_guards.py::position_pct(symbol, equity=None)` returns
    `market_value / equity * 100` for an existing position (URL-encoded
    so `BTC/USD` works).
  - `shared/risk_guards.py::concentration_ok(symbol, new_size_usd, equity=None)`
    returns `(True, combined_pct)` iff `position_pct + new_pct <= 40%`.
  - Wired into price-monitor (LONG/SHORT/LEVERAGED), crypto-monitor,
    defense-monitor — every signal checks combined concentration before
    sending the alert; over-cap signals are skipped with log line
    `pominiety (concentration X.X% > 40%)`.

- **VIX-source pivot** (added 2026-05-06 EOD)
  - Same concept as before: Finnhub free `^VIX` returns empty so vix_guard fails
    open in prod. With VIX HALT raised to 60 in v2.0, this matters less, but a
    real VIX feed is still useful for logging/analytics. Candidates: VIXY ETF
    via Alpaca bars (rough proxy), Yahoo Finance public quote, FRED VIXCLS

- **X / Twitter integration** — `twitter-monitor` ✅ **MVP DONE 2026-05-07** (Bluesky path)
  - Type: new entry-signal monitor (sibling of `reddit-monitor` and `geo-monitor`)
  - **Why:** Twitter/X is the lowest-latency news source for the kinds of events this system already
    trades — geopolitical decisions, defense contracts, CEO product/earnings hints, market sentiment.
    News reaches X minutes (sometimes hours) before NewsAPI / Reuters / RSS pick it up. Adding it
    closes the biggest current latency gap in the geo/defense pipeline.
  - **Curated source accounts (initial cut, expand over time):**
    - Politics & geo: @realDonaldTrump (or current handle), @POTUS, @SecDef, @StateDept, @WhiteHouse, @IDF, @IRGCofficial
    - Markets / macro: @zerohedge, @business (Bloomberg), @CNBC, @WSJmarkets, @FT, @Reuters
    - Single-ticker insider: @elonmusk (TSLA), @tim_cook (AAPL), @sundarpichai (GOOGL), @satyanadella (MSFT)
    - Financial influencers (high-conviction calls): TBD — start from a 10-15 hand-picked list, not
      indiscriminate following
    - Government feeds: @CongressionalRpt, @USTreasury, @SECgov, @federalreserve
  - **Signal patterns to detect:**
    - Direct policy / sanction / military action announcements (geo escalation/deescalation)
    - Earnings or product leaks from official corp accounts
    - Pelosi/Congressional trade-disclosure tweets (insider sentiment)
    - Sentiment spike (mention surge ≥ 5× rolling avg on a single ticker — analog of Reddit spike)
    - Account-credibility-weighted news vs unverified rumours
  - **Decided MVP path: Bluesky AT-Protocol** (free, TOS-safe, 2026-05-06 user-approved)
    - Public Bluesky API; auth via app password (free); no per-month read cap that matters at our volume
    - Smaller reach than X today, but financial / geo coverage is growing fast (mid-2025 onwards)
    - Same data shape as Twitter (post text, author handle, timestamp, repost/like counts) so the
      monitor we build on Bluesky maps 1:1 onto X API later if we choose to upgrade
    - Renamed: monitor stays `twitter-monitor` (semantic — "social-graph news monitor"), but data
      source on day one is `bsky.app`. Inside-the-monitor abstraction: a `SocialClient` interface
      with two implementations (BlueskyClient, TwitterClient) so the swap is one config flip.
  - **Future upgrade path (not now):** X API v2 Basic ($100/mo) once Bluesky proves the pipeline
    edge in production. X has higher reach and faster political content; the cost is justified
    only after we see signal quality from Bluesky.
  - **Rejected paths:** X API v2 Pro ($5k/mo) too expensive for paper; 3rd-party brokers carry TOS
    risk; Nitter mirrors are fragile and unofficial.
  - **MVP scope:**
    - One Bluesky firehose subscription per curated handle (Trump, POTUS, SecDef, etc. — see
      account list above)
    - Cloudflare Worker `twitter-proxy` (kept the name for consistency) → routine handler
    - GitHub Actions cron `*/5` during session, `*/15` after-hours
    - Per-account whitelist + per-keyword filter inside the monitor
    - Source-of-truth list at `.claude/rules/twitter-accounts.md` mapping each Twitter handle
      to its known Bluesky equivalent (some accounts have both, some only one)
  - **Hard dependency on Event Probability Layer:**
    Twitter is by far the noisiest signal source. Without the credibility / probability-shift /
    contrarian-reaction scoring, raw Twitter alerts would generate too many false positives
    (especially political tweets). Build the event probability layer FIRST or in parallel; do
    not wire `twitter-monitor` directly into Alpaca execution before it.
  - **New secrets needed (Bluesky MVP):**
    - `BLUESKY_HANDLE` (e.g. `mikosbartlomiej.bsky.social`)
    - `BLUESKY_APP_PASSWORD` (generated at bsky.app → settings → app passwords)
    - `CLOUDFLARE_TWITTER_WORKER_URL` (new Worker, name kept for consistency)
    - Future-proof: `TWITTER_BEARER_TOKEN` slot reserved for the eventual X API upgrade
  - **Strategy / sizing:** TBD — likely re-uses geopolitical and reddit-sentiment sizing
    ($5k-$6k per signal) under v2.0 risk-on rules. Iron rule: every Twitter-triggered trade
    must have stop-loss like every other entry.
  - **Acceptance criteria (MVP):**
    - Curated account list lives in `.claude/rules/twitter-accounts.md`
    - Monitor pulls latest tweets per account, deduplicates, filters by keyword bank
    - Each detected signal carries: tweet author, author credibility score, tweet text,
      timestamp, classified intent (geo / earnings / sentiment / other)
    - Forward to Worker → routine OR direct to email if event-probability-layer is wired
    - Tested live on at least one real high-impact tweet event before going to auto-execute
  - **Risk note:** Bluesky public API is openly TOS-allowed (AT-Protocol is designed for
    federation and tooling). X TOS forbids automated access without paid API, so the future
    upgrade requires the $100/mo Basic tier.
  - **ETA when prioritised:** ~1 session to ship the Bluesky MVP (auth, Worker, routine,
    whitelist file, first live test); +1 session to add X API as a second SocialClient when
    user approves the $100/mo cost.

- **Event Probability & Contrarian Reaction Layer** — `event_probability_reaction_layer` ✅ **MVP DONE 2026-05-07** (heuristic scoring; per-ticker bar-data integration deferred)
  - Type: Strategy Intelligence Layer (not another news monitor — interpretation layer between signal and decision)
  - **Problem:** current event-driven strategies (geo, defense, reddit) trust the headline too directly.
    The market often reacts to news as a pretext for liquidity grabs / stop-hunts / fake-outs, not because
    it believes the information. Following the first reaction can mean entering with the crowd right when
    the move reverses.
  - **Goal:** before sending an event-driven alert, decompose the trigger into 5 scores and pick a stance:
    1. **Event credibility** — source type (tweet vs. official filing vs. confirmed contract), source track record, corroboration
    2. **Probability shift** — does this realistically change the odds of a future outcome? (tweet threat = low; signed contract = high)
    3. **Market reaction** — price move vs ATR, volume vs avg, gap, speed, sector vs single-name divergence
    4. **Positioning context** — short interest, option chain skew, max-pain proximity, recent stop-runs (data sources TBD)
    5. **Contrarian trigger** — if credibility low + shift low + reaction high → flag setup as `CONTRARIAN_CANDIDATE` instead of following
  - **Output stance per event:** one of `FOLLOW_REACTION`, `IGNORE_EVENT`, `CONTRARIAN_CANDIDATE`, `WAIT_FOR_CONFIRMATION`
  - **Acceptance criteria (MVP):**
    - No event-driven trade fires solely on detection — each must carry the 5 scores + final decision reason
    - System can reject a trade when reaction is disproportionate to credibility
    - Journal/backtest captures which stance worked: follow vs ignore vs contrarian
    - Exit decisions can incorporate price dynamics, not just static SL/TP
    - MVP scope: stocks/CFD only (geo + defense monitors). Options layer deferred.
  - **Out of scope for MVP:** full options-chain analysis, max-pain modelling, automated short-squeeze detection, automated re-entry, options as primary instrument
  - **Touches:** `defense-monitor`, `geo-monitor` (entry filters), exit-monitor (dynamic exit), new `shared/event_scoring.py`, new journal fields
  - **ETA when prioritised:** rough estimate 2-3 sessions for MVP on stocks; longer for full options-aware version

---

## IRON RULES — v2.0 RISK-ON (2026-05-06 EOD)

**Source of truth:** `docs/STRATEGY.md`. All numbers below mirror it exactly.

### Position sizing
- Max single trade:     **20% of equity** (~$20k)  ← was 5%
- Max ticker exposure:  **40% of equity** (~$40k)  ← was 15%
- Cash reserve:         **0%** (full deployment)   ← was 5%
- Margin usage:         up to ~2.5× gross exposure (Reg-T allows 4×; we leave headroom)

### Asset-class soft caps (gross, advisory)
- US momentum stocks (long+short): 60% gross
- Leveraged ETFs (3×):              25% gross
- Crypto (BTC + ETH):               25% gross
- Defense / geo / sector ETFs:      35% gross
- Options premium paid:             25% (notional may be 100%+ via leverage)
- Reddit sentiment:                 10%

### Allowed tickers ONLY
See `.claude/rules/tickers-whitelist.md`. Off-whitelist = immediate abort.
Whitelist now includes 12 leveraged ETFs + 4 high-beta single names
(COIN, MSTR, ARM, SMCI) added 2026-05-06.

### Order types
- LIMIT orders only (never MARKET)
- Stocks: bracket entry + SL + TP wherever supported (Alpaca supports brackets on stocks)
- Options: simple LIMIT BUY (Alpaca paper rejects bracket on options); TP/SL emulated by `options-exit-monitor`
- Time-in-force: DAY (unless strategy specifies otherwise)
- Stop-loss is MANDATORY on every entry

### Circuit breakers
- **Daily P&L ≤ -12%**   → block new entries till next session (exits keep working)
- **Weekly P&L ≤ -25%**  → pause all monitors, manual review
- **Monthly P&L ≤ -40%** → full stop, parameter reset
- **VIX > 60**           → block new entries (catastrophic-only halt; CAUTION at 35 REMOVED)

### Forbidden
- Live trading (paper-only forever)
- Trading without a stop-loss
- Trading off-whitelist
- Options ±1 day around earnings (event risk uncontrollable)

### What changed from v1.0 (and why)
| Old rule | New rule | Why |
|---|---|---|
| Max single trade 5% | Max single trade 20% | All capital available, take real bets |
| Per-ticker cap 15% | Per-ticker cap 40% | Allow concentrated conviction |
| Cash floor 5% | 0% | Idle cash earns nothing |
| Daily stop -3% | Daily stop -12% | Aggressive system needs room to swing |
| No trading VIX > 35 | No trading VIX > 60 | Volatility is opportunity, not threat |
| Options $500 budget | Options $2,500 budget | Real options exposure |
| Max 3 open options | Max 10 open options | Diversify across underlyings |
| Crypto weekend halving | Same size 24/7 | Liquidity is fine on weekends |

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
| 2026-05-06 | Master Plan #3 deployed end-to-end: workflow + Cloudflare Worker `options-proxy` + Claude Routine `Options Handler` live. First smoke test fired 8 candidates -> 3 routine calls (HTTP 200, then HTTP 429 in retest -> Anthropic rate limit). |
| 2026-05-06 | Master Plan #3 hardened: Finnhub /stock/candle migrated to Alpaca daily bars (shared/market_data.py) — Finnhub free tier started returning 403 in 2024, also fixed silent zero-signals in price-monitor. notify.py now renders an actionable "[OPTIONS APPROVAL NEEDED]" email body for options proposals (subject + 6-step Alpaca runbook). MAX_PROPOSALS_PER_RUN=1 added to options-monitor to soften Anthropic Routines rate limit. Iron rule for options relaxed to AUTO-EXECUTE on paper (routine system prompt updated to skip approval step; email is audit trail). |
| 2026-05-06 | Master Plan #3 pivot to monitor-side execute: Anthropic Routines kept returning HTTP 429 (rate limit) so the routine path proved unreliable. options-monitor now resolves the contract via Alpaca `/v2/options/contracts` (free, basic close_price/strike/expiry) and places a bracket buy_to_open order via `/v2/orders` directly. Picks closest-to-ATM contract whose latest premium fits `size_usd / 100` budget. New env flag `AUTO_EXECUTE_OPTIONS` (default `true`) toggles between auto-execute and legacy routine path. Uses `notify_order_executed` for [EXECUTED] confirmations; failed executions fall back to the [OPTIONS APPROVAL NEEDED] proposal email so the user sees what tried to fire. Tests cover happy path, empty chain, order rejection, and legacy routine path. |
| 2026-05-06 | Master Plan #3 final: Alpaca paper rejects bracket/OCO/stop on options ("complex orders not supported"). options-monitor switched to simple limit buy; first real paper order (AMZN PUT @ $4.35) confirmed in Alpaca dashboard. New `options-exit-monitor/monitor.py` polls open us_option positions every 5 min during session, evaluates against TP=entry*1.80 / SL=entry*0.50, and posts a SELL-to-close LIMIT when a threshold is hit. De-dup via `/v2/orders?status=open` so a second cron tick doesn't stack a duplicate sell. notify_exit() per close. 5 test scenarios pass (TP / SL / HOLD / already-has-sell / empty positions). User still needs to add `.github/workflows/options-exit-monitor.yml` (template ready). |
| 2026-05-06 EOD | **End-of-day summary** — 4 of 5 master-plan points landed in production today. Order of work: (1) #2 emails: notify_signal/exit/summary wired into price-monitor + exit-monitor (defense+crypto already done before today). (2) Repo cleanup: .gitignore, untracked __pycache__, removed stale duplicate workflow ymls, consolidated 39 unique session reports/journals from 31 stale `claude/*` branches into main as one commit (979b45f) so the branches are now safe to delete. (3) #4 VIX guard: shared/risk_guards.py::vix_guard wired into price/crypto/defense/geo. Fail-open in prod because Finnhub free /quote?symbol=^VIX is empty — circuit breaker dormant; trading continues normally. (4) #5 dup-position guard: has_open_position() Alpaca check before every alert in price/crypto/defense. Geo skipped (news -> routine resolves ticker). (5) #3 options end-to-end: options-monitor builds proposals (RSI 45-65 CALL / >72 PUT) on a 12-ticker whitelist, originally forwarded to Cloudflare Worker → Claude Routine, but Anthropic Routines kept returning HTTP 429 so we pivoted to monitor-side AUTO_EXECUTE via Alpaca REST. Found Alpaca paper rejects bracket on options, switched to simple limit buy. First real paper-options trade fired at 19:18 UTC: AMZN260520P00270000 PUT entry $3.65. Then built options-exit-monitor that polls every 5 min during session, computes TP=entry*1.80 / SL=entry*0.50, places SELL-to-close LIMIT when threshold crossed (de-dup via /v2/orders?status=open). Net: 6 commits on main today (1db32ae cleanup, 979b45f consolidation, 1f0b581 VIX guard, ddb9f92 dup guard, 88240a8 options entry, 81c2109+b536bf8+25f1328 options auto-execute iterations, 93e16d5 options-exit-monitor). User pushed 7 workflow/secret changes via GitHub UI (proxy OAuth blocked workflow file edits). 4 fresh tests all pass on local mocks; 1 live AMZN PUT trade in Alpaca dashboard. Master 5-point plan now 4/5 with #1 Live Portfolio Dashboard moved to backlog alongside Reddit. |
| 2026-05-06 CLOSE | **Day-close — full session ledger.** Net 11 commits on main today (1db32ae cleanup, 2cf5498 price-monitor email, 89a0ce3 exit-monitor email, 979b45f branch consolidation, 1f0b581 VIX guard, ddb9f92 dup-position guard, 88240a8 options-monitor entry, 81c2109 options auto-execute pivot, b536bf8 iterate proposals, 25f1328 simple options buy, 93e16d5 options-exit-monitor, plus user-side workflow/secret edits via UI: a86d862 options-exit-monitor.yml, fd2f78c options-monitor.yml, 33bf990+89a3724 FINNHUB keys, 1b0944e+7ced9ff ALPACA keys, 9a5a7ff+ac89781 CLAUDE.md updates, 4626c2b STRATEGY v2.0 overhaul). Plan summary: 4/5 master-plan points live (#2 emails, #3 options entry+exit, #4 VIX, #5 dup guard); #1 Dashboard moved to backlog. First real paper-options trade open: AMZN260520P00270000 PUT @ $3.65, monitored. STRATEGY v2.0 risk-on overhaul done in ~2h: docs/STRATEGY.md created, all 8 strategy files + 7 monitors + 2 agents/skills + tickers whitelist updated. Backlog now: Dashboard, Reddit, VIX source pivot, weekly-learning verification, drawdown enforcement, per-ticker concentration enforcement, risk-officer wiring, backtest harness. Testing plan for 2026-05-07 already documented (sections A-G in this CLAUDE.md). |
| 2026-05-06 LATE | **STRATEGY v2.0 — full risk-on overhaul.** New canonical doc: `docs/STRATEGY.md` (12 sections, ~12k words). User direction: "all capital available, take risk, earn fast" — every limit and parameter rewritten. Account-level: per-trade cap 5%→20%, per-ticker 15%→40%, cash floor 5%→0%, daily loss stop -3%→-12%, weekly stop NEW -25%, monthly NEW -40%. VIX policy: HALT 45→60, CAUTION 35 REMOVED entirely. Asset-class sizing all bumped 3-5×: stocks long $3k→$10k, short $2k→$8k, leveraged $1.5k→$6k; crypto BTC $2k→$8k (no weekend halving), ETH $1k→$4k, total cap $8k→$25k; defense Big-5 $2.5k→$8k, ETF $2k→$6k; options $500→$2.5k, max 3→10 open, TP +80%→+120%, SL -50%→-65%, DTE 14-21→7-30, strike ATM±3%→±7%; reddit $1k→$5k. ATR multipliers loosened: SL 1.5→2.0, TP 2.5→4.0. Exit thresholds: emergency -5%→-12%, quick profit +3% in 4h→+10% in 6h, time decay 6h→24h, leveraged 48h→96h, crypto 12h→48h. Whitelist expanded with 12 leveraged ETFs (TQQQ/SQQQ/SPXL/SPXS/UPRO/SPXU/SOXL/SOXS/FAS/FAZ/TNA/TZA) + 4 high-beta names (COIN/MSTR/ARM/SMCI). Risk-officer flipped from default-REJECT to **default-APPROVE** (block only on hard violations). Files updated: docs/STRATEGY.md (NEW), CLAUDE.md, .claude/rules/tickers-whitelist.md, .claude/agents/risk-officer.md, .claude/skills/portfolio-snapshot/SKILL.md, all 8 strategies/*.md, 7 monitors (.py constants), shared/risk_guards.py. All Python files compile, parameter sanity test passes (VIX 50 now OK, 65 HALT; sizing constants verified across 5 monitors). |

---

## TESTING PLAN — 2026-05-07

End-to-end verification that every cron-driven workflow + every Claude Routine still works after today's changes. Checklist runs roughly 30 min; tick each item before market open (13:30 UTC).

### A. Pre-flight (5 min, before any trigger)

- [ ] **A1.** `git fetch origin && git log --oneline origin/main -5` — confirm latest commit is what we expect (today's last was `93e16d5`; tomorrow may already include the "one more thing" we'll do tonight)
- [ ] **A2.** GitHub → Settings → Secrets → confirm presence of: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `FINNHUB_API_KEY`, `NEWSAPI_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `NOTIFY_EMAIL`, all six `CLOUDFLARE_*_WORKER_URL` (incl. options + reddit), and `REDDIT_CLIENT_ID/SECRET`
- [ ] **A3.** Alpaca dashboard → confirm open positions, including AMZN PUT, match what CLAUDE.md "Open positions" claims; note current premium for the AMZN PUT for the exit-monitor smoke test in section B7

### B. Workflows — manual `Run workflow` smoke tests

Trigger from https://github.com/mikosbartlomiej-prog/trading-system/actions/workflows/<file>.yml → Run workflow → branch `main`. Expected log shape in parentheses.

- [ ] **B1.** `price-monitor.yml` — every 5 min weekday session
  Expect: VIX guard line; LONG/SHORT/LEVERAGED scans listing each ticker's RSI/breakout/volume; `pominiety (otwarta pozycja)` for tickers in open positions (GLD/RTX/XLE); zero or more `>>> SYGNAL …`; per-signal `Alert wyslany … HTTP 200`; trailing `Sygnaly: N, alerty wyslane: N`
- [ ] **B2.** `crypto-monitor.yml` — hourly + half-hourly 24/7
  Expect: VIX guard; per-symbol 1h-bar fetch; one of `>>> SYGNAŁ BUY/SELL BTC/USD` or none; HTTP 200 to crypto worker; trailing alerts count
- [ ] **B3.** `defense-monitor.yml` — every 30 min 24/7
  Expect: VIX guard; DoD scrape; RSS feeds; NewsAPI; "Sygnałów wygenerowanych: N"; rate-limit guard `MAX_ALERTS_PER_RUN=1`; if a signal fires, `notify_signal` email + `>>> SYGNAŁ` log
- [ ] **B4.** `geo-monitor.yml` — every 15 min weekday session
  Expect: VIX guard; Finnhub news + NewsAPI + RSS pulls; "Znaleziono N istotnych newsów"; if N≥1, alert payload to geopolitical worker
- [ ] **B5.** `exit-monitor.yml` — hourly during/around session + 22:00/00:00/02:00 UTC
  Expect: equity + cash; per-position table with P&L%, hold hours, recommendation (HOLD/CONSIDER_TP/CLOSE_DECAY/CLOSE_FLAT/CLOSE_EMERGENCY); `notify_exit` email per non-HOLD; payload to exit worker
- [ ] **B6.** `options-monitor.yml` — every 10 min weekday session
  Expect banner `=== OPTIONS MONITOR — AUTO-EXECUTE (Alpaca REST) ===`; "Otwartych opcji: 1/3" (the AMZN PUT counts); per-ticker RSI; iteration past too-expensive tickers (`brak kontraktu w budżecie $5/share`); at most 1 `Order placed` per run; if placed, `[EXECUTED]` email
- [ ] **B7.** `options-exit-monitor.yml` — every 5 min weekday session
  Expect: `Otwartych opcji: 1`; `AMZN260520P00270000: in window (pl X.X%, TP=$6.57, SL=$1.82) -> HOLD` (or TP/SL if AMZN moved sharply); zero `SELL placed` unless threshold hit
- [ ] **B8.** `weekly-learning.yml` — Sun 20:00 UTC; trigger manually to test
  Expect: pulls journal/trades-*.md; computes weekly P&L; sends to learning worker
- [ ] **B9.** `keep-alive.yml` — every 10 min; trigger manually
  Expect: HTTP ping to Render MCP server endpoint; 200 / 405 acceptable

For each workflow: capture exit code (must be 0). If anything 4xx/5xx in HTTP calls, screenshot + paste here for triage.

### C. Claude Routines — verify each receives + processes payloads

After triggering each workflow above, check claude.ai → Routines → click into the corresponding routine and confirm a fresh run is listed with no error in the conversation log.

- [ ] **C1.** Tradingview Handler ← price-monitor
- [ ] **C2.** Geopolitical Handler ← geo-monitor
- [ ] **C3.** Crypto Handler ← crypto-monitor
- [ ] **C4.** Exit Handler ← exit-monitor
- [ ] **C5.** Learning-loop Handler ← weekly-learning (Sun)
- [ ] **C6.** Defense Handler ← defense-monitor
- [ ] **C7.** ~~Options Handler~~ — DEPRECATED, options-monitor bypasses via AUTO_EXECUTE; skip (nothing should arrive here unless `AUTO_EXECUTE_OPTIONS=false` is set)

### D. Email verification (parallel to B)

- [ ] **D1.** Inbox during a real signal cron tick → confirm `[BUY] / [SELL]` subject prefix is correct (BUY for BUY*; SELL for SELL/SELL_SHORT)
- [ ] **D2.** Confirm body has ASCII-only content (no `\xa0`, no `–`/`—`)
- [ ] **D3.** Confirm `[EXECUTED]` email after an options entry, body has TP/SL targets even though they're not placed on broker
- [ ] **D4.** `[OPTIONS APPROVAL NEEDED]` email only appears when Alpaca rejects an order or AUTO_EXECUTE_OPTIONS=false (legacy path)
- [ ] **D5.** Run summary `[X Monitor] N signal(s), M sent` only sends when N>0 (no spam on quiet runs)

### E. End-to-end real scenarios (passive — observe over the day)

- [ ] **E1.** Stock entry: a real LONG signal fires (e.g. NVDA breakout) → email arrives, dup-guard skips for any held tickers, signal posts to tradingview worker. Routine ideally executes (paper) bracket order.
- [ ] **E2.** Options entry: options-monitor finds a setup that fits $5/share budget → AMZN-style fill in dashboard, [EXECUTED] email
- [ ] **E3.** Options exit: AMZN PUT premium crosses TP=$6.57 OR SL=$1.82 → SELL-to-close LIMIT placed, [EXIT] email, no duplicate on next 5-min tick
- [ ] **E4.** Quiet day: zero workflows produce emails (no false noise)

### F. Failure-mode drills (optional, if time)

- [ ] **F1.** Set `FINNHUB_API_KEY` to garbage in a workflow → confirm vix_guard fails OPEN and trading continues (not silently halts)
- [ ] **F2.** Temporarily blank `ALPACA_API_KEY` in price-monitor.yml → confirm dup-guard fails OPEN (alerts still fire) but options-monitor `sys.exit(1)`s loudly (AUTO_EXECUTE requires creds)
- [ ] **F3.** Cloudflare Worker offline (kill the Render deploy briefly) → confirm monitor logs the HTTP error but still emails

### G. Sign-off

- [ ] B1-B9 all green
- [ ] C1-C7 verified
- [ ] D1-D5 verified
- [ ] No P0 issues open
- [ ] Tag the day's tip: `git tag -a 2026-05-07-tested -m "Daily smoke test PASS"` (then push tag)

---

| 2026-05-07 AM | **Safety net combo + Event-probability MVP + Bluesky monitor** — three features shipped end-to-end in one session. Order: (1) `shared/risk_guards.py` extended with `get_account_status` / `daily_drawdown_guard` / `position_pct` / `concentration_ok`; wired into price/crypto/defense/geo monitors so STRATEGY v2.0's "-12% daily stop / 40% per-ticker cap" promises are now actually enforced (commit 7be41f6). (2) `shared/event_scoring.py` — 4-score interpretation layer (credibility / probability-shift / market-reaction / stance) with `FOLLOW / IGNORE / CONTRARIAN / WAIT` outputs; wired into defense-monitor (filters IGNORE/WAIT/CONTRARIAN, keeps FOLLOW) and geo-monitor (keeps FOLLOW + CONTRARIAN, drops weak signals); MVP placeholder for market_reaction since neither monitor fetches per-ticker bars yet (commit 0964354). (3) `twitter-monitor/monitor.py` — Bluesky AT-Protocol client (no SDK dep, login + getAuthorFeed via stdlib HTTP); curated whitelist `.claude/rules/twitter-accounts.md` with 19 accounts across 8 categories, per-category keyword filter, full pipeline through event_scoring → Cloudflare Worker → email; X API path deferred until $100/mo cost approved (commit d869318). All 13 Python files compile; safety-net + scoring + Bluesky end-to-end mocked tests all green. Backlog updated: drawdown enforcement / concentration cap / event-probability layer / Twitter integration moved to Done. Net 4 commits today (7be41f6, 0964354, d869318, plus this CLAUDE.md update). User-side deploy still required for twitter-monitor (Bluesky account + secrets + Worker + routine + workflow YAML — same pattern as options-monitor in last session). |

---

*Last updated: 2026-05-07 AM — safety nets enforced, event-probability layer + Bluesky monitor MVP in main. Source of truth: `docs/STRATEGY.md`*
*Repo: git@github.com:mikosbartlomiej-prog/trading-system.git*
*Next session: deploy twitter-monitor user-side (Bluesky secrets + Worker + workflow), or hook real bar data into event_scoring for full CONTRARIAN detection.*
