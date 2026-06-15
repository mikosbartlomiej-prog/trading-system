# Confidence Reality Check (v3.23.0)

**Generated:** `2026-06-15T11:28:34.556860+00:00`
**As of:** `2026-06-15T11:28:34.440442+00:00`
**Git HEAD:** `a8186d5f70f66f77b86d337f936541bea06c544b`
**Calibrated yet:** `False`

## Population over last 7 days

| Metric | Value |
|---|---|
| Total ledger rows (7d) | `16338` |
| Rows with `confidence_score` non-null | `0` (`0.0%`) |
| Rows with `confidence_components` non-empty | `0` (`0.0%`) |

## Score distribution

| Bucket | Count |
|---|---|
| `0.0-0.5` | 0 |
| `0.5-0.65` | 0 |
| `0.65-0.80` | 0 |
| `0.80+` | 0 |
| `null` | 16338 |

## Verdict distribution

| Verdict | Count |
|---|---|
| `unknown` | 16338 |

## Components currently producing default 0.5 only

- `data_quality`
- `signal_strength`
- `regime_alignment`
- `system_health`
- `risk_state`
- `sample_size`
- `track_record`
- `calibration`

## Components with observed variance

- (none)

## Low-sample strategies (trades_lifetime < 10)

Total: `11`

- `alloc-exit`
- `alloc-reduce`
- `allocator-rebalance`
- `crypto-breakdown`
- `crypto-momentum`
- `crypto-oversold-bounce`
- `geo-defense`
- `geo-gold`
- `geo-xom`
- `options-momentum`
- `overbought-short`

## Calibration status

- `calibration_dir_exists`: `False`
- `calibrated_yet`: `False`

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
