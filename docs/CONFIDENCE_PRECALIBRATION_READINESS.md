# Confidence Pre-Calibration Readiness (v3.27.0)

**Generated:** `2026-06-15T15:18:00.575223+00:00`
**As of:** `2026-06-15T15:18:00.425232+00:00`
**Git HEAD:** `1b2a7b9825753d2e05fc7f218fafdc168709dce2`
**Window:** last 7 days
**Rows total:** `16508`
**Positive rows (non-null confidence_score):** `0`

## v3.27 Source separation

**Verdict (v3.27):** `READY_FOR_COMPONENT_VARIANCE_REVIEW`

29 replay row(s) and 4074 near-miss row(s) available for component-variance review. NO production positive rows yet — calibration MUST NOT be attempted; operator may proceed only to variance review.

| Source | Count | Counts as production? |
|---|---|---|
| PRODUCTION_POSITIVE_ROWS | `0` | yes |
| REPLAY_POSITIVE_ROWS     | `29` | NO (review-only) |
| NEAR_MISS_ROWS           | `4074` | NO (advisory) |
| FIXTURE_ONLY_ROWS        | `0` | NO (test artefacts) |
| OUTCOMES_AVAILABLE       | `False` | gate for calibration |

> Calibration is **NEVER** recommended without real outcomes.
> Replay rows, near-miss rows, and fixture rows are surfaced for
> operator situational awareness only — they never count as
> production positives.

## Verdict (v3.26, retained for back-compat)

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
- `REPLAY_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE`
- `NEAR_MISS_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE`
- `FIXTURE_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE`
- `CALIBRATION_NEVER_RECOMMENDED_WITHOUT_OUTCOMES`
