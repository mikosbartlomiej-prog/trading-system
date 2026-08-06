# Full System Forensic Audit

- Scope: 2026-06-16 → 2026-07-03
- Generated at: `2026-07-03T17:46:30.849378+00:00`
- Read-only. No broker mutations. No secret values printed.

## Summary

- Git commits since 2026-06-16: **25985**
- HEAD `ec421f464bf7` vs origin/main `ec421f464bf7`
- Workflows on disk: **44**
- Failed workflow runs in scope: **2**
- Allocation plans generated: **18**
- Execution records: **16**
- **Total orders placed: 0**
- **Total orders skipped: 22**
- **Total orders failed: 56**
- Rejection categories: `{'UNKNOWN_BROKER_REJECTION': 56}`
- Autonomy journal files scanned: **18**
- CLOSE_POSITION FAILED events: **156**
- SAFE_MODE events: **22**
- BROKER_REPAIR events: **104**
- Opportunity ledger files: **18**, rows: **51573**, entry-capable: **0**
- Shadow evidence root: yes, jsonl rows: **2081**, observations: **0**
- LLM advisory role files: **17**
- Alpaca GET verification NOT ATTEMPTED — ALPACA_API_KEY/ALPACA_SECRET_KEY not in local env — Alpaca GET verification skipped. Truth-of-record for broker state is

## Per-day allocation outcomes

| Date | Plan | Notional | Placed | Skipped | Failed | Rejection categories |
|---|---|---:|---:|---:|---:|---|
| 2026-06-16 | 3 | 27151 | 0 | 0 | 6 | `{'UNKNOWN_BROKER_REJECTION': 5}` |
| 2026-06-17 | 4 | 43442 | 0 | 0 | 3 | `{'UNKNOWN_BROKER_REJECTION': 3}` |
| 2026-06-18 | 6 | 76024 | 0 | 0 | 4 | `{'UNKNOWN_BROKER_REJECTION': 4}` |
| 2026-06-19 | 6 | 76024 | 0 | 6 | 0 | `{}` |
| 2026-06-20 | 6 | 76024 | — | — | — | `{}` |
| 2026-06-21 | 6 | 76024 | 0 | 6 | 0 | `{}` |
| 2026-06-22 | 5 | 59733 | 0 | 0 | 6 | `{'UNKNOWN_BROKER_REJECTION': 5}` |
| 2026-06-23 | 3 | 27151 | 0 | 0 | 5 | `{'UNKNOWN_BROKER_REJECTION': 5}` |
| 2026-06-24 | 3 | 27151 | 0 | 0 | 3 | `{'UNKNOWN_BROKER_REJECTION': 3}` |
| 2026-06-25 | 6 | 76024 | 0 | 0 | 3 | `{'UNKNOWN_BROKER_REJECTION': 3}` |
| 2026-06-26 | 4 | 43442 | 0 | 0 | 6 | `{'UNKNOWN_BROKER_REJECTION': 5}` |
| 2026-06-27 | 4 | 43442 | — | — | — | `{}` |
| 2026-06-28 | 4 | 43442 | 0 | 4 | 0 | `{}` |
| 2026-06-29 | 5 | 59733 | 0 | 0 | 4 | `{'UNKNOWN_BROKER_REJECTION': 4}` |
| 2026-06-30 | 5 | 59733 | 0 | 0 | 5 | `{'UNKNOWN_BROKER_REJECTION': 5}` |
| 2026-07-01 | 6 | 76024 | 0 | 0 | 5 | `{'UNKNOWN_BROKER_REJECTION': 5}` |
| 2026-07-02 | 6 | 76024 | 0 | 0 | 6 | `{'UNKNOWN_BROKER_REJECTION': 5}` |
| 2026-07-03 | 6 | 76024 | 0 | 6 | 0 | `{}` |

## Workflow health (in scope)

- **Autonomous Remediation — health-driven self-heal**: 1 runs, last=`success`, conclusions=`{'success': 1}`
- **Crypto Monitor — 11 coins predator scan (24/7)**: 20 runs, last=`success`, conclusions=`{'success': 19, 'failure': 1}`
- **Defense Market Monitor — 5min scan 24/7**: 20 runs, last=`success`, conclusions=`{'success': 20}`
- **Emergency Close — autonomous position closer**: 1 runs, last=`success`, conclusions=`{'success': 1}`
- **Entry Monitors — Watchdog (re-trigger if missed)**: 8 runs, last=`success`, conclusions=`{'success': 8}`
- **Exit Monitor — dual cron (market 5min + off-hours 15min)**: 20 runs, last=`success`, conclusions=`{'success': 20}`
- **Geopolitical News Monitor — 15min scan 24/7**: 8 runs, last=`success`, conclusions=`{'success': 8}`
- **Incident Pattern Detector — Layer 1 real-time anomaly watcher**: 20 runs, last=`success`, conclusions=`{'success': 20}`
- **Monitor Health — workflow runs introspection**: 8 runs, last=`success`, conclusions=`{'success': 8}`
- **Options Exit Monitor — TP/SL polling + governor-driven options-first close**: 20 runs, last=`success`, conclusions=`{'success': 20}`
- **Options Monitor — CALL/PUT proposals**: 20 runs, last=`success`, conclusions=`{'success': 20}`
- **Price Monitor — Momentum Breakout**: 21 runs, last=`success`, conclusions=`{'success': 20, 'cancelled': 1}`
- **Reddit Monitor — sentiment + tracked-user scan**: 8 runs, last=`success`, conclusions=`{'success': 8}`
- **Signal Shadow Evidence (v3.27)**: 1 runs, last=`success`, conclusions=`{'success': 1}`
- **Sync Workflow Templates → .github/workflows**: 1 runs, last=`success`, conclusions=`{'success': 1}`
- **Twitter Monitor — Bluesky social-graph 24/7**: 20 runs, last=`success`, conclusions=`{'success': 20}`
- **doj-monitor**: 1 runs, last=`success`, conclusions=`{'success': 1}`
- **politician-monitor**: 2 runs, last=`success`, conclusions=`{'success': 2}`

## Critical discrepancies observed

- **Execution contradiction**: 56 orders failed with `UNKNOWN_BROKER_REJECTION` (no HTTP status, no Alpaca message) — suggests rejection happens BEFORE the HTTP call reaches Alpaca, but dashboard reports TRADING_EXECUTION_ON=false.
- **Zero orders placed since scope start** — either the mode is functionally OFF or every attempt has been rejected.

---
This report is read-only. It does not mutate state, place orders, or print secrets.