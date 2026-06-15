# Shadow candidate queue (v3.26.0)

**Generated:** `2026-06-15T14:33:28.847123+00:00`
**As of:** `2026-06-15T14:33:28.846126+00:00`
**Total rows:** 0
**Active risk blockers:** none

Each row is a candidate. Status remains `WAITING_FOR_REAL_MARKET_TRIGGER` until a real-market event satisfies the trigger condition. This queue NEVER auto-promotes a row.

## Candidate rows

| Strategy | Variant | Symbol | Asset | Reason | Trigger | Confidence Exp. | Risk Blockers | Mode | Status |
|---|---|---|---|---|---|---|---|---|---|
| (no candidates yet — empty queue is expected) | | | | | | | | | |

## Safety contract

- Every row mode = `SHADOW_ONLY`.
- Every row status = `WAITING_FOR_REAL_MARKET_TRIGGER`.
- This queue NEVER places orders.
- This queue NEVER auto-promotes a row.
- This queue NEVER inflates shadow eligibility counters.
- This script NEVER imports `alpaca_orders`.
- This script NEVER makes network calls.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `SHADOW_CANDIDATE_NEVER_AUTO_PROMOTED`
- `SHADOW_CANDIDATE_NEVER_PLACES_ORDERS`
- `QUEUE_NEVER_INFLATES_SHADOW_ELIGIBILITY`
