# Confidence Pre-Calibration Readiness (v3.27.0)

**Generated:** `2026-10-25T09:18:55.306867+00:00`
**As of:** `2026-10-25T09:18:55.068894+00:00`
**Git HEAD:** `65dcabededad8a49b667115d3f1642ee62d6901c`
**Window:** last 7 days
**Rows total:** `18242`
**Positive rows (non-null confidence_score):** `62`

## v3.27 Source separation

**Verdict (v3.27):** `NOT_READY_NO_OUTCOMES`

62 production positive row(s) present BUT no outcomes attached yet. Calibration remains explicitly NOT recommended until outcomes are collected via the shadow-outcome cycle.

| Source | Count | Counts as production? |
|---|---|---|
| PRODUCTION_POSITIVE_ROWS | `62` | yes |
| REPLAY_POSITIVE_ROWS     | `0` | NO (review-only) |
| NEAR_MISS_ROWS           | `22960` | NO (advisory) |
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
| `count` | 62 |
| `min` | 0.0976 |
| `median` | 0.4725 |
| `p95` | 0.6214 |
| `max` | 0.6316 |
| `mean` | 0.3625 |

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
| `anomaly_penalty` | 62 | 0.2 | 1.0 | 0.6371 | 0.12606 | yes |
| `data_quality` | 62 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `edge_evidence` | 62 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `event_risk_penalty` | 62 | 1.0 | 1.0 | 1.0 | 0.0 | no |
| `liquidity_quality` | 62 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `paper_sample_size_score` | 62 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `recent_strategy_health` | 62 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `regime_alignment` | 62 | 0.7 | 0.7 | 0.7 | 0.0 | no |
| `risk_state` | 62 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `signal_strength` | 62 | 0.348 | 1.0 | 0.6125 | 0.030038 | yes |
| `slippage_risk` | 62 | 0.5 | 0.5 | 0.5 | 0.0 | no |
| `system_health` | 62 | 0.3636 | 0.8182 | 0.5103 | 0.008225 | yes |

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
