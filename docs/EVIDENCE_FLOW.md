# Evidence Flow — v3.22.0

**Version:** v3.22.0 (2026-06-15)
**Status:** signal-production spine wired end-to-end.
**Live trading:** NOT supported. `ALLOW_BROKER_PAPER` remains `false`.

---

## TL;DR

Before v3.22 the only signals that produced durable evidence were
the ones that *reached* the broker (or the shadow simulator). Every
BLOCKED, DEFERRED, or downsized signal was logged to stderr and
effectively lost. The learning loop could not reason about *why*
we did not take a trade.

v3.22 closes that loop. Every monitor now emits a
`SignalEvent` → `emit_signal_opportunity(...)` → `record_opportunity(...)`
→ opportunity ledger → confidence engine → risk officer →
broker-paper canary preflight → (eventually) evidence.

The chain is wired. **The chain does not yet produce trades.**
`ALLOW_BROKER_PAPER` stays `false`. The canary stays preflight-only.
`EDGE_GATE_ENABLED` stays `false`. Live remains unsupported.

---

## The chain (ASCII)

```
   ┌──────────────┐
   │   monitor    │   price / crypto / options / defense / geo /
   │   (cron)     │   twitter / reddit / politician
   └──────┬───────┘
          │ 1. build SignalEvent (frozen dataclass)
          ▼
   ┌──────────────────────────────────┐
   │ shared.signal_event.SignalEvent  │ ← canonical signal carrier
   └──────┬───────────────────────────┘
          │ 2. validate(...)   pure function, returns errors list
          ▼
   ┌──────────────────────────────────────────┐
   │ shared.signal_emitter                    │
   │   .emit_signal_opportunity(event)        │
   │                                          │
   │   ▸ validate event                       │
   │   ▸ compute_confidence(**conf_inputs)    │ advisory only
   │   ▸ record_opportunity(...)              │ ← always persists
   │   ▸ idempotency check                    │ FIFO cache, 1024 keys
   │   ▸ NEVER places trades                  │
   │   ▸ NEVER imports alpaca_orders          │
   └──────┬───────────────────────────────────┘
          │ 3. persisted to disk
          ▼
   ┌──────────────────────────────────────────┐
   │ learning-loop/opportunity_ledger/        │
   │   <UTC-date>.jsonl                       │ ← single source of evidence
   │                                          │
   │   row carries: signal_id, strategy,      │
   │   symbol, confidence_score, components,  │
   │   risk_decision, gate_decisions,         │
   │   rejection_reasons, raw_signal          │
   └──────┬───────────────────────────────────┘
          │ 4. downstream consumers (read-only)
          ▼
   ┌─────────────────────┬──────────────────────┐
   │ confidence          │ risk_officer          │ ← optional downstream
   │ calibration         │ (advisory)            │   gates that may
   │                     │                       │   eventually run on
   │ canary preflight    │ canary actual         │   ledger rows
   │ (PREFLIGHT_OK?)     │ (gated by             │
   │                     │  ALLOW_BROKER_PAPER)  │
   └──────────┬──────────┴──────────────────────┘
              │ 5. evidence aggregation (future)
              ▼
   ┌──────────────────────────────────┐
   │ learning-loop/                   │
   │   broker_paper_canary/           │ ← evidence written here
   │   unlock_readiness_latest.json   │   AFTER preflight + paper
   │                                  │   evidence accumulates
   └──────────────────────────────────┘
```

---

## What each layer does

### 1. Monitor

Cron-driven. Reads market data (cached, per-call cap). Runs its
strategy. If it would have emitted a signal (in any direction —
BUY, SELL, BLOCKED, HALTED) it constructs a `SignalEvent` and hands
it to the emitter.

Wired in v3.22:

- `price-monitor`
- `crypto-monitor`
- `options-monitor`
- `defense-monitor`
- `geo-monitor`
- `twitter-monitor` (Bluesky)
- `reddit-monitor` (no-API path)
- `politician-monitor`

### 2. `SignalEvent`

See [`docs/SIGNAL_EVENT.md`](SIGNAL_EVENT.md). Frozen, validated,
JSON-safe.

### 3. `emit_signal_opportunity`

Single-entry helper. Always:

- validates the event (errors block entry-capable events)
- best-effort confidence compute (never raises)
- always persists via the ledger
- idempotent within a 1024-key FIFO cache

The emitter is hard-pinned NOT to import any broker module. The
v3.22 E2E test
(`tests/test_signal_pipeline_e2e_v3220.py::TestHappyPathE2E::test_happy_path`)
includes an AST scan that fails the build if any new broker call
sneaks in.

### 4. Opportunity ledger

Schema v3.20.0. One JSONL row per opportunity. Columns:

```
signal_id, strategy, symbol, timestamp, raw_signal,
confidence_score, confidence_components, risk_decision,
gate_decisions, rejection_reasons, market_regime,
universe_status, paper_action, shadow_action, audit_link,
schema_version
```

Note: `source_monitor` and `evidence_source` are NOT top-level
columns in v3.20. They ride in `raw_signal` so downstream tools
can find them while keeping the ledger schema stable.

### 5. Downstream

Read-only consumers reason about the ledger rows. The
confidence-calibration workflow, the canary preflight, the unlock
evaluator, the LLM Senior PM persona — all read from the ledger.

**None of them place trades in v3.22.**

---

## Idempotency contract

`emit_signal_opportunity(event, idempotency_key=K)` will only write
one ledger row per `K` per process lifetime. The cache is a 1024-key
FIFO (`shared/signal_emitter.py::IDEMPOTENCY_CACHE_SIZE`). Cron
restarts re-arm the cache.

For monitors that fire every 5 minutes on the same bar, use a key
like `f"{strategy_id}:{symbol}:{bar_ts}"` to suppress duplicate
emits when a cron tick overlaps a bar boundary.

---

## Throughput SLA

v3.22 ships `scripts/check_evidence_throughput_sla.py` which scans
today's ledger and warns if the per-strategy opportunity-rate falls
under target. Run from `scripts/system_health_workflow_quiet_hours.sh`.

---

## Hard-safety invariants (re-asserted)

- System is **NOT live-ready**.
- System has **NOT yet proven edge**.
- v3.22 wires the production layer but does **NOT generate evidence
  by itself** — evidence accumulates only after the canary is
  enabled, and the canary stays preflight-only in this revision.
- Confidence score **without data is not proof of edge**.
- `EDGE_GATE_ENABLED` remains `false`.
- `ALLOW_BROKER_PAPER` remains `false`.
- **LIVE TRADING forbidden.** System remains free to operate.

---

## Related docs

- [`docs/SIGNAL_EVENT.md`](SIGNAL_EVENT.md)
- [`docs/SHADOW_EVIDENCE_RUNNER.md`](SHADOW_EVIDENCE_RUNNER.md)
- [`docs/RUNBOOK.md`](RUNBOOK.md) (Scenario AA.4 — `emit_signal_opportunity` dry-run)
- [`docs/AUTONOMY_CONTRACT.md`](AUTONOMY_CONTRACT.md) (v3.22 invariants)
