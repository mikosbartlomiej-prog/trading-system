# Shadow Evidence Progress (v3.26.1)

**Generated:** 2026-06-09 (D+1 daily run check)
**Source:** `learning-loop/shadow_evidence/evidence_counters_latest.json`
**Status:** v3.26.1 added the `evidence_quality` distinction. The
5 scaffold records from 2026-06-09's `--allow-without-market-data`
smoke run are now correctly counted as
`scaffold_no_market_data_records_count`, NOT as real-market
opportunities. Real-market evidence collection has NOT begun.

## Progress toward broker-paper canary readiness

| Metric | Current | Target |
|---|---:|---:|
| **`real_market_opportunities_count`** ← canary gate | **0** | **50** |
| `completed_shadow_outcomes_count` | **0** | **20** |
| `audit_bypass_findings_count` | 0 | 0 |
| `exposure_cap_breach_count` | 0 | 0 |
| `repeated_buy_violation_count` | 0 | 0 |
| `unexplained_broker_state_conflicts_count` | 0 | 0 |

## Observational counters (informational only)

| Metric | Current | Note |
|---|---:|---|
| `scaffold_no_market_data_records_count` | 5 | scaffold smoke-test records; do NOT count toward canary |
| `halt_path_records_count` | 3 | runs that skipped due to no market data |
| `halt_path_opportunities_count` | 3 | same — observational |
| `normal_non_halt_opportunities_count` (legacy) | 0 | preserved for backward compat; superseded by `real_market_opportunities_count` |
| `would_block_by_crypto_exposure_count` | 0 | observational |
| `would_block_by_drawdown_guard_count` | 0 | observational |
| `would_block_by_recent_loss_cooldown_count` | 0 | observational |

## Readiness verdicts

| Tier | Verdict |
|---|---|
| Signal/shadow unlock | `SIGNAL_SHADOW_UNLOCK_READY` |
| Broker paper canary | **`BROKER_PAPER_CANARY_NOT_READY`** |
| Live trading | `LIVE_TRADING_NOT_SUPPORTED` |

## Blocker list (from `evaluate_from_current_repo_state`)

- `real_market_opportunities_count` below 50 (currently 0) — v3.26.1 gate
- `completed_shadow_outcomes_count` below 20 (currently 0)
- `daily_learning_stable=False` (waiting for v3.26 evidence)
- `trade_reconstruction_stable=False` (waiting for v3.26 evidence)
- `explicit_operator_approval_for_broker_paper=False`

## Next run instructions

```sh
# Always run preflight via the collector script:
python3 scripts/run_signal_shadow_evidence_collection.py --max-records 10
```

Default mode (no market data available):
- preflight passes
- collector returns `SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA`
- `halt_path_opportunities_count` increments by 1

Scaffold-only mode (smoke / wiring tests):
```sh
python3 scripts/run_signal_shadow_evidence_collection.py \
    --max-records 5 --allow-without-market-data
```
- emits 5 placeholder records to today's `records_YYYY-MM-DD.jsonl`
  with `evidence_quality=SCAFFOLD_NO_MARKET_DATA`
- increments `scaffold_no_market_data_records_count` by 5 (v3.26.1+)
- does NOT increment `real_market_opportunities_count`
- does NOT count toward broker-paper canary readiness
- still does NOT submit any orders or touch the broker

## What to inspect after each run

1. `learning-loop/shadow_evidence/evidence_counters_latest.json`
   — confirm counters are monotonic (non-decreasing).
2. `learning-loop/shadow_evidence/records_YYYY-MM-DD.jsonl` —
   spot-check: every record must show
   `broker_order_submitted: false` and
   `broker_execution_enabled: false`.
3. Re-run preflight:
   ```python
   from shared.signal_shadow_preflight import run_preflight
   r = run_preflight()
   assert r.verdict == "SIGNAL_SHADOW_PREFLIGHT_PASS"
   ```

## Forbidden operations during evidence collection

- Do NOT enable broker paper.
- Do NOT enable live trading.
- Do NOT set `EDGE_GATE_ENABLED=true`.
- Do NOT reset the equity baseline.
- Do NOT lower the drawdown guard threshold.
- Do NOT restore quarantined `emergency_close_*.py.disabled`
  scripts to active `.py`.
- Do NOT add the quarantine directory to the audit-bypass
  ALLOW_LIST.
- Do NOT infer or invent `client_order_id` for AMD or any other
  position.
- Do NOT close or modify ETH / AVAX / SOL / LTC open crypto
  positions.

## When this report should be re-generated

The counters file is the source of truth — operator may re-
generate this markdown by re-reading the JSON. A future iteration
can ship a `scripts/refresh_shadow_progress_report.py` that reads
the JSON and emits this Markdown automatically. v3.26 does not
ship that helper to keep scope tight.

---

## v3.26.1 daily run check (2026-06-09)

**Daily run date:** 2026-06-09 (D+1 after v3.26.0 scaffold smoke).

**Collector status:** `SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA`.

**Evidence quality this run:** `HALT_PATH_ONLY` — normal collector
was invoked without `--allow-without-market-data` and no market
data source was available, so no records were emitted. The
halt-path counter incremented by 1 per invocation.

**Real market records emitted this run:** 0.

**Scaffold records emitted this run:** 0 (only halt-path).

**Halt path count this run:** +2 (from two test invocations of the
collector). Cumulative: 3.

**Carry-over from yesterday's scaffold smoke run:**
- 5 `SHADOW_SCAFFOLD_NOOP` records dated 2026-06-09 carry
  `evidence_quality=SCAFFOLD_NO_MARKET_DATA` (backfilled by
  v3.26.1).
- 5 corresponding counts now live in
  `scaffold_no_market_data_records_count`, not in the legacy
  `normal_non_halt_opportunities_count`.

**Progress toward 50 real opportunities:** 0 / 50.

**Progress toward 20 completed shadow outcomes:** 0 / 20.

**Broker paper canary verdict:** `BROKER_PAPER_CANARY_NOT_READY`
— unchanged. Promotion still requires:

- 50 real-market opportunities,
- 20 completed shadow outcomes,
- 0 audit-bypass findings,
- 0 exposure cap breaches,
- 0 repeated buy-loop violations,
- daily learning stable,
- trade reconstruction stable,
- explicit operator approval.

**Live verdict:** `LIVE_TRADING_NOT_SUPPORTED` — permanent.

**Safety invariants from counters file:**

- `broker_order_submitted_ever`: false
- `live_trading_enabled`: false
- `broker_paper_enabled`: false
- `edge_gate_enabled`: false
- `baseline_reset`: false
- `drawdown_guard_lowered`: false

**Decision:** `SIGNAL_SHADOW_DAILY_RUN_RECORDED` +
`SCAFFOLD_EVIDENCE_NOT_COUNTED_AS_REAL_MARKET_DATA` +
`BROKER_PAPER_CANARY_STILL_BLOCKED` + `LIVE_TRADING_UNSUPPORTED`.

**Next run recommendation:** schedule a normal collector
invocation during US market session (13:30-20:00 UTC) once the
real-data hook is wired. Until then, the collector correctly
returns `SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA` and no records
accumulate toward the canary gate.

<!-- v3.27 auto-progress-start -->

## Automated progress snapshot (v3.27)

**Last auto-update:** `2026-06-09T15:39:35.042208+00:00`
**Source:** `learning-loop/shadow_evidence/evidence_counters_latest.json`
**Generator:** `scripts/update_shadow_evidence_progress.py`

### Canary-gate counters

| Metric | Current | Target |
|---|---:|---:|
| `real_market_opportunities_count` | **0** | 50 |
| `completed_shadow_outcomes_count` | **0** | 20 |
| `audit_bypass_findings_count` | 0 | 0 |
| `exposure_cap_breach_count` | 0 | 0 |
| `repeated_buy_violation_count` | 0 | 0 |
| `unexplained_broker_state_conflicts_count` | 0 | 0 |

### Observational counters

| Metric | Current |
|---|---:|
| `scaffold_no_market_data_records_count` | 5 |
| `halt_path_records_count` | 5 |
| `halt_path_opportunities_count` | 6 |
| `normal_non_halt_opportunities_count` (legacy) | 0 |
| `would_block_by_crypto_exposure_count` | 0 |
| `would_block_by_drawdown_guard_count` | 0 |
| `would_block_by_recent_loss_cooldown_count` | 0 |

### Readiness verdicts

| Tier | Verdict |
|---|---|
| Signal/shadow unlock | `SIGNAL_SHADOW_UNLOCK_READY` |
| Broker paper canary | **`BROKER_PAPER_CANARY_NOT_READY`** |
| Live trading | `LIVE_TRADING_NOT_SUPPORTED` |

### Automated run telemetry

| Field | Value |
|---|---|
| Last collector status | `SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA` |
| Last outcome resolver status | `RESOLVED` |
| `daily_learning_stable` | `false` |
| `trade_reconstruction_stable` | `false` |

### Safety invariants from counters file

- `broker_order_submitted_ever`: `false`
- `live_trading_enabled`: `false`
- `broker_paper_enabled`: `false`
- `edge_gate_enabled`: `false`
- `baseline_reset`: `false`
- `drawdown_guard_lowered`: `false`

<!-- v3.27 auto-progress-end -->

