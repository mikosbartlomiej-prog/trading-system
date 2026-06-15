# Shadow Eligibility Distribution Status

- **Version**: `v3.25.0`
- **Generated**: `2026-06-15T11:47:29.598335+00:00`
- **Cutoff (post-v3.24)**: `2026-06-15T11:35:05+00:00`
- **Rows evaluated**: 20
- **ELIGIBLE rows**: 0 (0.0%)

## Decision distribution

| Token | Count |
|---|---:|
| `ELIGIBLE` | 0 |
| `NOT_ELIGIBLE_NO_CONFIDENCE` | 0 |
| `NOT_ELIGIBLE_CONFIDENCE_LOW` | 0 |
| `NOT_ELIGIBLE_RISK_BLOCK` | 0 |
| `NOT_ELIGIBLE_NO_SIGNAL` | 0 |
| `NOT_ELIGIBLE_DRAWDOWN_GUARD` | 0 |
| `NOT_ELIGIBLE_DATA_FAILURE` | 0 |
| `NOT_ELIGIBLE_CANARY_DEFERRED` | 0 |
| `NOT_ELIGIBLE_OBSERVE_ONLY` | 20 |
| `NOT_ELIGIBLE_UNKNOWN` | 0 |

## Sample reasons per token

- **NOT_ELIGIBLE_OBSERVE_ONLY**:
  - `row is observe_only; diagnostic only, never shadowed`
  - `row is observe_only; diagnostic only, never shadowed`
  - `row is observe_only; diagnostic only, never shadowed`

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT_BY_REPORTER`
- `PURE_LOCAL_FILE_OPERATIONS`
- `NEAR_MISS_IS_NOT_TRADE_EVIDENCE`
- `SHADOW_IS_NOT_BROKER_PAPER`
- `LLM_ADVISORY_ONLY`

