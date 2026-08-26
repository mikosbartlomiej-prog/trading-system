# Confidence Pre-Calibration Readiness (v3.27.0)

**Generated:** `2026-08-26T05:06:34.998452+00:00`
**As of:** `2026-08-26T05:06:34.693017+00:00`
**Git HEAD:** `ae8b8a2cb495791804280b3db2d1c7ab03d83c61`
**Window:** last 7 days
**Rows total:** `19653`
**Positive rows (non-null confidence_score):** `24`

## v3.27 Source separation

**Verdict (v3.27):** `NOT_READY_NO_OUTCOMES`

24 production positive row(s) present BUT no outcomes attached yet. Calibration remains explicitly NOT recommended until outcomes are collected via the shadow-outcome cycle.

| Source | Count | Counts as production? |
|---|---|---|
| PRODUCTION_POSITIVE_ROWS | `24` | yes |
| REPLAY_POSITIVE_ROWS     | `0` | NO (review-only) |
| NEAR_MISS_ROWS           | `28676` | NO (advisory) |
| FIXTURE_ONLY_ROWS        | `0` | NO (test artefacts) |
| OUTCOMES_AVAILABLE       | `False` | gate for calibration |

> Calibration is **NEVER** recommended without real outcomes.
> Replay rows, near-miss rows, and fixture rows are surfaced for
> operator situational awareness only — they never count as
> production positives.

## Verdict (v3.26, retained for back-compat)

**`NEEDS_MORE_ENTRY_CANDIDATES`**

Only 24 positive row(s); need >= 30 to begin pre-calibration.

## Confidence-score distribution

| Stat | Value |
|---|---|
| `count` | 24 |
| `min` | 0.3244 |
| `median` | 0.3335 |
| `p95` | 0.6051 |
| `max` | 0.6127 |
| `mean` | 0.4545 |

## Builder completeness

| Stat | Value |
|---|---|
| `count` | 0 |
| `min` | None |
| `median` | None |
| `mean` | None |

## Per-component variance

Total components observed: `12`
Varying components: `3`
Default-only components: `9`

| Component | Samples | Min | Max | Mean | Variance | Varying |
|---|---|---|---|---|---|---|
| `anomaly_penalty` | 24 | 0.6 | 1.0 | 0.7833 | 0.041449 | yes |
| `data_quality` | 24 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `edge_evidence` | 24 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `event_risk_penalty` | 24 | 1.0 | 1.0 | 1.0 | 0.0 | no |
| `liquidity_quality` | 24 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `paper_sample_size_score` | 24 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `recent_strategy_health` | 24 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `regime_alignment` | 24 | 0.7 | 0.7 | 0.7 | 0.0 | no |
| `risk_state` | 24 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `signal_strength` | 24 | 0.6 | 0.8 | 0.6917 | 0.010362 | yes |
| `slippage_risk` | 24 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `system_health` | 24 | 0.3636 | 0.7273 | 0.5303 | 0.008384 | yes |

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
- `REPLAY_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE`
- `NEAR_MISS_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE`
- `FIXTURE_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE`
- `CALIBRATION_NEVER_RECOMMENDED_WITHOUT_OUTCOMES`
