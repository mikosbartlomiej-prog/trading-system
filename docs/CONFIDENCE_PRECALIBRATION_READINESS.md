# Confidence Pre-Calibration Readiness (v3.27.0)

**Generated:** `2026-08-06T07:16:33.345171+00:00`
**As of:** `2026-08-06T07:16:33.044018+00:00`
**Git HEAD:** `717b0a1e883e455077187d6e4385ad43ce1d72cd`
**Window:** last 7 days
**Rows total:** `18651`
**Positive rows (non-null confidence_score):** `173`

## v3.27 Source separation

**Verdict (v3.27):** `NOT_READY_NO_OUTCOMES`

173 production positive row(s) present BUT no outcomes attached yet. Calibration remains explicitly NOT recommended until outcomes are collected via the shadow-outcome cycle.

| Source | Count | Counts as production? |
|---|---|---|
| PRODUCTION_POSITIVE_ROWS | `173` | yes |
| REPLAY_POSITIVE_ROWS     | `0` | NO (review-only) |
| NEAR_MISS_ROWS           | `26710` | NO (advisory) |
| FIXTURE_ONLY_ROWS        | `0` | NO (test artefacts) |
| OUTCOMES_AVAILABLE       | `False` | gate for calibration |

> Calibration is **NEVER** recommended without real outcomes.
> Replay rows, near-miss rows, and fixture rows are surfaced for
> operator situational awareness only — they never count as
> production positives.

## Verdict (v3.26, retained for back-compat)

**`NEEDS_COMPONENT_VARIANCE`**

3/8 components show meaningful variance; need >= 4.

## Confidence-score distribution

| Stat | Value |
|---|---|
| `count` | 173 |
| `min` | 0.101 |
| `median` | 0.571 |
| `p95` | 0.6316 |
| `max` | 0.6392 |
| `mean` | 0.48 |

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
| `anomaly_penalty` | 173 | 0.2 | 1.0 | 0.8243 | 0.101965 | yes |
| `data_quality` | 173 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `edge_evidence` | 173 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `event_risk_penalty` | 173 | 1.0 | 1.0 | 1.0 | 0.0 | no |
| `liquidity_quality` | 173 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `paper_sample_size_score` | 173 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `recent_strategy_health` | 173 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `regime_alignment` | 173 | 0.7 | 0.7 | 0.7 | 0.0 | no |
| `risk_state` | 173 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `signal_strength` | 173 | 0.428 | 1.0 | 0.727 | 0.019744 | yes |
| `slippage_risk` | 173 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `system_health` | 173 | 0.0 | 0.7273 | 0.5039 | 0.012922 | yes |

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
