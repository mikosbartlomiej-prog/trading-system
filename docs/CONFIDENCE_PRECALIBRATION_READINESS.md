> INCIDENT ACTIVE: `AVAX` (and 4 more) in BROKER_REPAIR_REQUIRED state.
>
> Blocked symbols: `AVAX`, `AVAXUSD`, `ETH`, `ETHUSD`, `LTCUSD`
> Discovery layer remains active for analysis but trading is BLOCKED until manual repair.
> Status: DISCOVERY_ACTIVE_BUT_TRADING_BLOCKED_BY_P13
> See: [docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md](docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md)

# Confidence Pre-Calibration Readiness (v3.27.0)

**Generated:** `2026-06-16T09:40:08.009215+00:00`
**As of:** `2026-06-16T09:40:07.204131+00:00`
**Git HEAD:** `5d493ee95ba682d032a8c55b16cb9b0f321c2280`
**Window:** last 7 days
**Rows total:** `16128`
**Positive rows (non-null confidence_score):** `0`

## v3.27 Source separation

**Verdict (v3.27):** `READY_FOR_COMPONENT_VARIANCE_REVIEW`

0 replay row(s) and 12332 near-miss row(s) available for component-variance review. NO production positive rows yet — calibration MUST NOT be attempted; operator may proceed only to variance review.

| Source | Count | Counts as production? |
|---|---|---|
| PRODUCTION_POSITIVE_ROWS | `0` | yes |
| REPLAY_POSITIVE_ROWS     | `0` | NO (review-only) |
| NEAR_MISS_ROWS           | `12332` | NO (advisory) |
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
