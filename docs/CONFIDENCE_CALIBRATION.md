# Confidence Calibration Contract — v3.19.0

**Created:** 2026-06-04 (ETAP 4 of v3.19.0)
**Module:** `shared/confidence_calibration.py`
**CLI:** `scripts/confidence_calibration_report.py`
**Reports:** `docs/confidence_calibration_LATEST.md`,
`learning-loop/confidence_calibration_LATEST.json`

---

## Why this exists

`shared/confidence.py` (shipped in v3.18.0) produces a 0..1 confidence
score for each trade signal, blended from twelve component scoring
functions. The risk engine uses that score as a gate input.

A score is only useful if it is *calibrated* — that is, trades scored
0.80 actually win more often (or earn more per trade) than trades
scored 0.55. If the high bucket performs no better than the mid
bucket, the score is overstating the signal and the gate threshold
becomes a placebo.

This module answers the question:

> *Are the confidence scores produced by the system actually
> predictive of trade outcomes?*

It NEVER calls the broker. It NEVER calls a paid API. It NEVER
auto-raises the confidence threshold. It writes local reports.

---

## Bucket structure

Six closed buckets — lower-inclusive, with the last bucket inclusive
of `1.0`:

| Bucket       | Range          |
|--------------|----------------|
| `very_low`   | `[0.00, 0.40)` |
| `low`        | `[0.40, 0.50)` |
| `mid`        | `[0.50, 0.65)` |
| `high`       | `[0.65, 0.75)` |
| `very_high`  | `[0.75, 0.85)` |
| `extreme`    | `[0.85, 1.00]` |

The boundaries match the thresholds the risk engine currently uses
(`BLOCK < 0.50`, `ALERT_ONLY 0.50–0.65`, `ALLOW ≥ 0.65`).

```python
from shared.confidence_calibration import bucket_for
bucket_for(0.42)  # "low"
bucket_for(0.85)  # "extreme"
bucket_for(1.00)  # "extreme" (last bucket is inclusive of upper bound)
```

---

## Per-bucket metrics

For each bucket the module computes:

| Field                       | Meaning                                                  |
|-----------------------------|----------------------------------------------------------|
| `n`                         | Number of closed trades in the bucket                    |
| `win_rate`                  | Fraction with `net_pnl > 0`                              |
| `expectancy`                | `WR · avg_win + (1−WR) · avg_loss`                        |
| `profit_factor`             | gross wins ÷ gross losses                                |
| `avg_drawdown_after_entry`  | Average per-trade adverse excursion (proxy when missing) |
| `false_positive_rate`       | Fraction of losing trades that fired in this bucket      |

Buckets with `n < 5` are flagged `sparse` and excluded from
monotonicity comparisons by default.

---

## Calibration = monotonicity

A score is **calibrated** when, for every pair of buckets `(lo, hi)`
with `hi > lo`, ALL three hold:

- `WR(hi) ≥ WR(lo)`
- `expectancy(hi) ≥ expectancy(lo)`
- `false_positive_rate(hi) ≤ false_positive_rate(lo)`

Buckets with `n < min_n_per_bucket` (default **10**) do not count
toward the check — without enough samples the comparison is noise.

The function returns `(is_calibrated, rationale)`:

```python
from shared.confidence_calibration import is_calibrated, compute_calibration_metrics

calibration = compute_calibration_metrics(records, source="PAPER")
ok, why = is_calibrated(calibration, min_n_per_bucket=10)
```

---

## Why uncalibrated does NOT auto-raise thresholds

This is an explicit design choice.

1. **Confidence calibration depends on small samples.** Auto-tuning
   the threshold off a small `n_per_bucket` would react to noise.
2. **The Strategy Quality Gate is the right place for evidence-based
   decisions.** Calibration is one input to that gate, not its own
   independent control surface.
3. **Operator review remains the final say.** When the report says
   `Calibrated: NO`, an operator decides whether to (a) collect more
   data, (b) tighten the threshold, or (c) review the scoring
   functions.

There is no auto-disable, no auto-pause, no automatic adjustment.

---

## Overstatement and underuse

`detect_overstatement(calibration)` returns the high buckets
(`high`, `very_high`, `extreme`) that look bad:

- `WR < 50%`, OR
- `expectancy ≤ 0`, OR
- A LOWER bucket has a higher win rate.

These are the buckets where the score is making confident claims that
fail in practice. The most likely cause is overfit weighting in the
scoring functions, but it could also be an underlying signal that has
gone stale.

`detect_underuse(calibration)` returns the low buckets
(`very_low`, `low`, `mid`) that look surprisingly good:

- `WR ≥ 55%` AND `expectancy > 0`.

A low bucket with strong outcomes is information left on the table —
the scoring function should be rating those trades higher.

Both lists are surfaced in the report.

---

## Drift detection

`calibration_drift(prev, curr)` returns a weighted L1 distance
between two calibration snapshots:

```
drift = Σ_bucket weight_bucket · |curr.WR − prev.WR|
```

Higher buckets get more weight (the `extreme` bucket weight is 1.75
vs `very_low` 0.50). A drift of 0 means the calibrations are
identical.

Operators inspect drift to spot when the scoring function changes
behaviour without an obvious code change (regime shift, data quality
event, etc.).

---

## How the Strategy Quality Gate uses calibration

The Strategy Quality Gate reads the latest calibration JSON as a
*context input*. Specifically:

- An uncalibrated score lowers operator confidence in
  `EDGE_APPROVED_FOR_EXPERIMENT` decisions.
- Overstating buckets surface as a warning alongside risk metrics.
- Underused buckets are notes for future scoring-function tuning.

The Gate itself does not flip thresholds. It surfaces the calibration
state in its report and lets the operator decide.

---

## Free local operation

All artefacts are local files:

```
docs/confidence_calibration_LATEST.md
learning-loop/confidence_calibration_LATEST.json
journal/autonomy/<UTC-date>.jsonl  (one "confidence_calibration" event per run)
```

`python3 scripts/confidence_calibration_report.py` regenerates the
two reports. No paid API is called. No external monitoring service is
involved.

---

## Audit emission

Every report run emits one JSONL line under
`journal/autonomy/<UTC-date>.jsonl` with `kind="confidence_calibration"`.
Fields:

```json
{
  "kind": "confidence_calibration",
  "timestamp": "2026-06-04T12:34:56+00:00",
  "actor": "confidence-calibration",
  "window_days": 180,
  "calibrated": false,
  "rationale": "bucket high WR 42% < bucket mid WR 58%",
  "overstating_buckets": ["high"],
  "underused_buckets": ["mid"],
  "n_total": 87
}
```

The audit module's narrower `DECISION_TYPES` set does not include
calibration findings (they are not autonomous trading decisions), so
this module writes its JSONL line directly using the same daily file
convention. Fail-soft: any I/O error is swallowed.

---

## Change history

| Version | Date       | What                                                                 |
|---------|------------|----------------------------------------------------------------------|
| 3.19.0  | 2026-06-04 | ETAP 4 — Confidence Calibration module + reports + audit emission.   |
