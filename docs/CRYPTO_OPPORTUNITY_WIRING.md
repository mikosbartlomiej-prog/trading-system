# Crypto Opportunity Ledger Wiring (v3.22.0 — ETAP 4)

**Incident:** 2026-06-07 — crypto-momentum silent 62 days despite
BTC RSI ≈ 7.6.

## Why

`crypto-monitor/monitor.py` evaluated signals at every cron tick but
never wrote a single line to `shared/signal_opportunity_ledger`. Result:
the learning loop had zero durable evidence on WHY trades did not fire
and the operator was blind to gate-rejection patterns. The 62-day
silence was invisible to every audit channel except the empty
`learning-loop/state.json::strategies.crypto-*.placed_lifetime` counter.

ETAP 4 closes the observability gap. It is non-auto-apply by design —
the ledger only records what the existing risk engines already decided.
Decision logic is governed by `risk_officer.evaluate_trade` and the
in-monitor gates, NOT by this wiring.

## What changed

### `crypto-monitor/monitor.py`

1. New helper `_emit_opportunity(...)` near the top of the module.
   - Imports `shared/signal_opportunity_ledger.record_opportunity`
     inside a `try/except` so the monitor still runs when the ledger
     module is unavailable.
   - Builds a stable `signal_id` (strategy + symbol + microsecond UTC
     timestamp).
   - Calls `record_opportunity(...)` with no side effects.
2. Six call sites instrumented inside `check_crypto_signal(...)` and
   `run_scan(...)`. Each call site emits exactly one entry per outcome.

| Call site | `signal_state` | `paper_action` | Strategy tag |
|---|---|---|---|
| Oversold-bounce setup detected | `DETECTED` | `signal_detected` | `crypto-oversold-bounce` |
| Oversold-bounce alt-long blocked by BTC dominance guard | `REJECT` | `rejected` | `crypto-oversold-bounce` |
| Predator-bracket 24h-move outside `[3%, 15%]` | `REJECT` | `rejected` | `crypto-momentum` |
| Breakout long detected | `DETECTED` | `signal_detected` | `crypto-momentum` |
| Breakout long blocked by BTC dominance | `REJECT` | `rejected` | `crypto-momentum` |
| Breakdown short detected | `DETECTED` | `signal_detected` | `crypto-breakdown` |
| Breakdown short blocked (Alpaca paper LONG-only) | `REJECT` | `rejected` | `crypto-breakdown` |
| No setup at all (terminal log path) | `NO_SIGNAL` | `rejected` | `crypto-momentum` |
| Alt-cap limit reached | `REJECT` | `rejected` | inherited |
| Duplicate position (`has_open_position`) | `REJECT` | `rejected` | inherited |
| Concentration cap exceeded | `REJECT` | `rejected` | inherited |
| Order placed via `execute_crypto_signal` | `APPROVE` | `executed` | inherited |
| Order rejected by broker / deferred | `REJECT` | `rejected` | inherited |

The previously-existing decision logic is unchanged — only the
observability writes are new. Risk engine, Alpaca calls, and email
notifications behave identically.

## Invariants

- `_emit_opportunity` NEVER places a trade, NEVER mutates
  `signal["action"]`, NEVER short-circuits a gate.
- Every emit is fail-soft: any exception during the ledger call is
  caught and logged but never raised.
- No live-trading endpoints are reached: the ledger writes to a local
  JSONL under `learning-loop/opportunity_ledger/<date>.jsonl`. Paper-
  only invariant preserved.
- Determinism: the ledger entry uses UTC microsecond timestamp, sorted-
  JSON serialisation. Replays of the same scan produce stable ordering.
- Free-tier compatible: no network calls, no paid APIs.

## Test coverage

`tests/test_crypto_monitor_opportunity_emit_v3220.py` covers:

1. BTC RSI ≈ 10 deep-oversold scan records at least one opportunity
   entry that carries the RSI in `raw_signal`.
2. ETH RSI ≈ 10 deep-oversold scan also records.
3. Sunday execution (weekend) still evaluates and still records — there
   is no equity-market-hours guard in crypto-monitor.
4. BTC dominance guard rejection still emits an entry with the
   `btc_dominance_guard` reason.
5. Quiet sideways markets ("no setup") still leave a ledger trail.
6. When `signal_opportunity_ledger` is not importable, the monitor
   still runs to completion — the emit helper is fully fail-soft.

Mocking strategy:
- `monitor.execute_crypto_signal` is patched so no Alpaca order is
  attempted during the unit suite.
- `monitor.get_crypto_bars` is patched with synthetic bar lists.
- `OPPORTUNITY_LEDGER_DIR` env var is redirected to a per-test
  `tempfile.TemporaryDirectory` so entries are read back from disk
  for assertion.

## Operational impact

- Next cron tick after deploy: each scan writes one or more lines to
  `learning-loop/opportunity_ledger/<UTC-date>.jsonl`.
- The learning loop can now answer questions like
  "how many crypto-momentum setups did we reject because of
  `btc_dominance_guard` last week?" deterministically.
- No state-policy actor change required — the ledger writes to its
  own dedicated directory.
