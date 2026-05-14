# Free-tier limits & failure modes

Everything in this system runs free. This doc lists the actual limits
and what happens when each free tier hiccups.

## GitHub Actions

| Plan | Minutes/month | Concurrent jobs | Storage |
|---|---|---|---|
| Free public repo | unlimited | 20 | 0.5 GB |
| Free private repo | 2 000 | 20 | 0.5 GB |

This repo is **public** — minutes are unlimited. Each scheduled run is
≤5 minutes; even at 5-minute cadence we use ~12 minutes/hour ≈ 288/day.
Plenty of headroom.

**Failure modes:**
- GitHub Actions outage (rare, hours not days) → all monitors idle;
  `scripts/trading_health.py` flags DEGRADED if last-monitor-run is
  >2× the cron period.
- Concurrent job limit → handled by per-workflow `concurrency:` block
  (added by this PR). A long-running run cancels older ones.

## Cloudflare Workers (free tier)

| Limit | Free |
|---|---|
| Requests/day | 100 000 |
| CPU/request | 10 ms |
| Memory | 128 MB |

We use ~6 workers, each fronts a Routine. At ~5-minute cron cadence
per worker → ~280 requests/day → 0.3% of quota.

**Failure modes:**
- Worker 5xx → monitor logs the HTTP error and falls back to
  `shared/alpaca_orders.py` deterministic path (after this PR). No
  trade is lost.
- Worker URL secret missing → monitor logs `BRAK CLOUDFLARE_*_WORKER_URL`
  and continues without the LLM curation step.

## Alpaca Paper

| Limit | Paper |
|---|---|
| API calls/min | 200 |
| WebSocket connections | 2 |
| Data: IEX feed | free |
| Data: SIP feed | $99/mo (not used) |

We use IEX feed (`feed=iex` in quote calls). One quote = one API call.
At ~10 quote calls per cron + ~12 crons/hour × 6 active monitors
≈ 720 calls/hour, well under the 200/min cap.

**Failure modes:**
- Alpaca 429 (rate limit) → `shared/alpaca_orders.py` returns None;
  monitor falls back to email-only logging.
- Alpaca outage → portfolio_risk and risk_officer both **fail-open**
  (warn, approve). Trading continues but caps aren't enforced. Health
  check flags BLOCKED.

## Finnhub (free tier)

| Limit | Free |
|---|---|
| Calls/min | 60 |
| Calls/day | unlimited (mid-2024 update) |
| `/quote` | works |
| `/stock/candle` | **403** since mid-2024 (moved to paid plan) |
| `/news` | works for company news |

We replaced all daily-bar Finnhub usage with Alpaca's IEX bars in
`shared/market_data.py::get_daily_bars`.

**Failure modes:**
- `/quote?symbol=^VIX` returns empty → `vix_guard()` fails-open OK.
  No HALT on missing data.
- Earnings calendar 5xx → options-monitor skips the
  `is_earnings_imminent` check for that ticker (default to "imminent
  unknown — don't skip").

## NewsAPI (free dev tier)

| Limit | Free |
|---|---|
| Requests/day | 100 |
| Search delay | up to 24h |
| HTTPS | only with paid |

`NewsAPI is a FALLBACK / DEV source.` Per spec §F.7, articles older
than the configured `max_age_hours` are rejected by
`signal_confirmation.article_fresh()`. Default cutoff is 12h, so a
24h-delayed free-tier article never triggers a trade.

**Failure modes:**
- 429 quota exhausted → monitor logs error, skips news for that run.

## Yahoo Finance (public, no key)

Used as a fallback for VIX (`shared/risk_guards.py::get_vix`).
Aggressive scrapers get IP-throttled; we run 1 request/cron tick.

**Failure modes:**
- 429 / 5xx → `vix_guard` falls back to fail-open OK.

## Bluesky AT-Protocol

Public API, free, app-password auth. No documented per-account limits;
our cadence (~50 accounts × `*/5` cron) is well within "reasonable".

**Failure modes:**
- 5xx for individual account fetch → monitor logs and continues with
  remaining accounts.
- App password rotation / login failure → monitor exits 0 with 0
  signals; health check flags WARN if recurring.

## Reddit (public .json endpoints)

No API key. ToS allows reads with a proper User-Agent at ~10 req/h.
Cron `*/30 * * * *` with batching over ~6 subs stays under that.

**Failure modes:**
- 403 → monitor logs `Reddit refused (likely UA / rate limit)`.
  Continues. Per the README, full API approval is "pending"; the
  monitor uses public `.json` URLs in the meantime.

## Anthropic API (LLM)

Only invoked from the learning loop. Defaults to **OFF**.

| Limit | Free | Paid |
|---|---|---|
| Routines / day | 15 | configurable |

If we hit 15, the learning loop **fail-soft**: deterministic adapter
output is still written to state.json. Spec §A requires that the
trading path NEVER blocks on LLM, so this is by design.

**Failure modes:**
- 429 → llm_client logs and skips that round (round 1/2/3 of the
  daily dialog). The next round still runs if the previous succeeded.
- HTTP timeout → poll loop expires after `POLL_MAX_S=480` (spec
  §A.5 calibration); deterministic baseline still applied.

## When everything is on fire

Health check (`scripts/trading_health.py`) exit codes:

- 0 = OK or WARN (system can trade)
- 2 = DEGRADED (some checks failed but trading still possible)
- 3 = BLOCKED (Alpaca auth fails — don't trade)

Operator runbook for "system silent past expected cron":
1. Open https://github.com/<repo>/actions — check workflow status
2. Run `scripts/trading_health.py --out-json health.json --out-md health.md`
3. Check Alpaca dashboard for unexpected open orders
4. If options panic needed: `scripts/panic_close_options.py` (dry-run)
   then `CONFIRM_PANIC_CLOSE_OPTIONS=true python scripts/panic_close_options.py`
