# Confidence Pre-Calibration Readiness (v3.26.0)

**Generated:** `2026-06-15T14:27:43.508765+00:00`
**As of:** `2026-06-15T14:27:43.368085+00:00`
**Git HEAD:** `0546ad4d80b0eecbbf4524264e943aa2904d8750`
**Window:** last 7 days
**Rows total:** `16358`
**Positive rows (non-null confidence_score):** `0`

## Verdict

**`NOT_READY_NO_POSITIVE_ROWS`**

No entry-capable ledger row carries a non-null confidence_score yet. Verify Phase-2 wiring once monitors begin emitting positive-path rows.

## Confidence-score distribution

| Stat | Value |
|---|---|
| `count` | 0 |
| `min` | None |
| `median` | None |
| `p95` | None |
| `max` | None |
| `mean` | None |

## Builder completeness

| Stat | Value |
|---|---|
| `count` | 0 |
| `min` | None |
| `median` | None |
| `mean` | None |

## Per-component variance

Total components observed: `0`
Varying components: `0`
Default-only components: `0`

| Component | Samples | Min | Max | Mean | Variance | Varying |
|---|---|---|---|---|---|---|
| (none) | | | | | | |

## Confidence decision counts

| Decision | Count |
|---|---|
| `ALLOW` | 0 |
| `ALERT_ONLY` | 0 |
| `BLOCK` | 0 |
| `ERROR` | 0 |

## Thresholds used

| Param | Value |
|---|---|
| `min_positive_rows` | `30` |
| `min_varying_components` | `4` |
| `variance_epsilon` | `1e-09` |

## Safety contract

- This reporter NEVER imports `alpaca_orders`.
- This reporter NEVER makes a network call.
- This reporter NEVER mutates strategy thresholds.
- Verdicts are descriptive — they do not gate execution.
- Pre-calibration outputs do NOT count as real-market evidence.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `CONFIDENCE_PRECALIBRATION_DOES_NOT_TRADE`
- `REPORTER_NEVER_MUTATES_STATE`
