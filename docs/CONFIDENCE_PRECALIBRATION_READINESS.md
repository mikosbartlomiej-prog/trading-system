# Confidence Pre-Calibration Readiness (v3.27.0)

**Generated:** `2026-11-05T12:40:30.054975+00:00`
**As of:** `2026-11-05T12:40:29.775131+00:00`
**Git HEAD:** `a456a22a55ac304f04db6218092dafad98dfe315`
**Window:** last 7 days
**Rows total:** `18506`
**Positive rows (non-null confidence_score):** `120`

## v3.27 Source separation

**Verdict (v3.27):** `NOT_READY_NO_OUTCOMES`

120 production positive row(s) present BUT no outcomes attached yet. Calibration remains explicitly NOT recommended until outcomes are collected via the shadow-outcome cycle.

| Source | Count | Counts as production? |
|---|---|---|
| PRODUCTION_POSITIVE_ROWS | `120` | yes |
| REPLAY_POSITIVE_ROWS     | `0` | NO (review-only) |
| NEAR_MISS_ROWS           | `28678` | NO (advisory) |
| FIXTURE_ONLY_ROWS        | `0` | NO (test artefacts) |
| OUTCOMES_AVAILABLE       | `False` | gate for calibration |

> Calibration is **NEVER** recommended without real outcomes.
> Replay rows, near-miss rows, and fixture rows are surfaced for
> operator situational awareness only — they never count as
> production positives.

## Verdict (v3.26, retained for back-compat)

**`NEEDS_COMPONENT_VARIANCE`**

2/8 components show meaningful variance; need >= 4.

## Confidence-score distribution

| Stat | Value |
|---|---|
| `count` | 120 |
| `min` | 0.1081 |
| `median` | 0.4596 |
| `p95` | 0.5483 |
| `max` | 0.5483 |
| `mean` | 0.327 |

## Builder completeness

| Stat | Value |
|---|---|
| `count` | 0 |
| `min` | None |
| `median` | None |
| `mean` | None |

## Per-component variance

Total components observed: `12`
Varying components: `2`
Default-only components: `10`

| Component | Samples | Min | Max | Mean | Variance | Varying |
|---|---|---|---|---|---|---|
| `anomaly_penalty` | 120 | 0.2 | 1.0 | 0.5996 | 0.113004 | yes |
| `data_quality` | 120 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `edge_evidence` | 120 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `event_risk_penalty` | 120 | 1.0 | 1.0 | 1.0 | 0.0 | no |
| `liquidity_quality` | 120 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `paper_sample_size_score` | 120 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `recent_strategy_health` | 120 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `regime_alignment` | 120 | 0.7 | 0.7 | 0.7 | 0.0 | no |
| `risk_state` | 120 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `signal_strength` | 120 | 0.6 | 0.6 | 0.6 | 0.0 | no |
| `slippage_risk` | 120 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `system_health` | 120 | 0.0 | 0.6364 | 0.4311 | 0.014653 | yes |

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
