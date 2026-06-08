# Shadow Evidence Progress (v3.26)

**Generated:** 2026-06-09
**Source:** `learning-loop/shadow_evidence/evidence_counters_latest.json`
**Status:** evidence collection scaffolding in place; no real
runs yet.

## Progress toward broker-paper canary readiness

| Metric | Current | Target |
|---|---:|---:|
| `normal_non_halt_opportunities_count` | **0** | **50** |
| `completed_shadow_outcomes_count` | **0** | **20** |
| `audit_bypass_findings_count` | 0 | 0 |
| `exposure_cap_breach_count` | 0 | 0 |
| `repeated_buy_violation_count` | 0 | 0 |
| `unexplained_broker_state_conflicts_count` | 0 | 0 |
| `halt_path_opportunities_count` | 0 | n/a (observational) |
| `would_block_by_crypto_exposure_count` | 0 | n/a (observational) |
| `would_block_by_drawdown_guard_count` | 0 | n/a (observational) |
| `would_block_by_recent_loss_cooldown_count` | 0 | n/a (observational) |

## Readiness verdicts

| Tier | Verdict |
|---|---|
| Signal/shadow unlock | `SIGNAL_SHADOW_UNLOCK_READY` |
| Broker paper canary | **`BROKER_PAPER_CANARY_NOT_READY`** |
| Live trading | `LIVE_TRADING_NOT_SUPPORTED` |

## Blocker list (from `evaluate_from_current_repo_state`)

- `normal_non_halt_opportunities_count` below 50 (currently 0)
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
- increments `normal_non_halt_opportunities_count` by 5
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
