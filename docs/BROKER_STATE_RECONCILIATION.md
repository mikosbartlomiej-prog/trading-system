# Broker-State Reconciliation (v3.23)

`shared/position_reconciliation_status.py` is the formal classifier
that disambiguates local-state-only inferences from broker-verified
truth.

## Status enum (closed)

| Status | Meaning |
| --- | --- |
| `VERIFIED_OPEN` | Local + broker/API both confirm OPEN. |
| `VERIFIED_CLOSED` | Local + broker/API both confirm CLOSED. |
| `STALE_LOCAL_OPEN` | Local says OPEN but no broker evidence. |
| `STALE_LOCAL_CLOSED` | Local says CLOSED but no broker evidence. |
| `BROKER_SIDE_CLOSED` | Bracket SL/TP child fired at broker outside our control. |
| `ORPHAN_BROKER_POSITION` | Broker shows OPEN but local has no record. |
| `LOCAL_BROKER_CONFLICT` | Local and broker disagree (legacy compatibility). |
| `DASHBOARD_VERIFIED_POSITION` | Operator manually confirmed OPEN on dashboard. |
| `DASHBOARD_VERIFIED_NOT_OPEN` | Operator manually confirmed NOT open on dashboard. |
| `API_UNAVAILABLE_OPERATOR_DASHBOARD_PROVIDED` | No API creds; using operator dashboard input. |
| `UNKNOWN_REQUIRES_API_VERIFICATION` | Need API. |
| `BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN` | AMD-style anomaly: dashboard says not_open, no local safe_close. |
| `STALE_LOCAL_TIME_EXPIRED_BUT_DASHBOARD_OPEN` | ETHUSD-style: local exit loop spinning, dashboard says still open. |
| `STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN` | AVAXUSD-style: local says closed, dashboard says open. |
| `STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN_DUST` | SOL/LTC dust variant. |
| `VERIFIED_CLOSED_FROM_AUDIT_SAFE_CLOSE` | Audit has safe_close + dashboard confirms not_open. |

## Invariants

- `NEVER_CLOSES_POSITIONS = True`
- `NEVER_MODIFIES_POSITIONS = True`
- `NEVER_PLACES_ORDERS = True`
- `NEVER_LOWERS_RISK = True`

## Operator-provided dashboard snapshot

`learning-loop/position_reconciliation/operator_dashboard_snapshot.json`
captures the operator's manual dashboard verification with explicit
`source: OPERATOR_DASHBOARD_MANUAL` so the classifier never silently
treats it as a full Alpaca API response.

## Tests

`tests/test_position_reconciliation_dashboard_conflict_v3230.py`
exercises every status branch including the 2026-06-08 scenarios
(AMD anomaly, ETHUSD stale-time-expired, AVAXUSD/SOLUSD/LTCUSD
stale-closed conflicts).
