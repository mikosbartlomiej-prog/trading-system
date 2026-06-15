# Post-v3.24 Production Audit (v3.25.0)

Generated: 2026-06-15T11:45:15.557405+00:00
Cutoff: `2026-06-15T11:35:05+00:00`

## Verdict

**NO_BUT_CRON_HASNT_FIRED_YET**

## Row counts

- Total rows audited: 20
- Entry-capable: 0
- Observe-only: 20

## Confidence presence

- confidence_score populated: 0 (0.0%)
- confidence_components non-empty: 0 (0.0%)
- confidence_default_reasons populated: 0
- confidence_input_completeness avg: n/a

## Entry-capable confidence-bearing slice

- with numeric score: 0
- with ERROR status: 0
- bearing (score or ERROR): 0
- silent-null (v3.24 contract violation): 0

## Distributions

### confidence_status
- OBSERVE_ONLY_SKIP: 20

### confidence_decision
- NULL: 20

### by source_monitor
- crypto-monitor: 20

### by strategy_id
- crypto-momentum: 20

### by risk_decision
- UNKNOWN: 20

## Evidence quality

- avg score: 10.0 (20 rows scored)

---

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT_BY_REPORTER`
- `PURE_LOCAL_FILE_OPERATIONS`
- `NEAR_MISS_IS_NOT_TRADE_EVIDENCE`
- `SHADOW_IS_NOT_BROKER_PAPER`
- `LLM_ADVISORY_ONLY`
