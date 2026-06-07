# Order Rejection Audit (v3.22)

`shared/order_rejection_audit.py` replaces the bare
`"Alpaca rejected order (see stdout)"` line that previously appeared
in `learning-loop/allocations/<date>.execution.json` whenever a BUY
order failed at the broker.

## Categories

| Category | Trigger |
| --- | --- |
| `INSUFFICIENT_BUYING_POWER` | 403 + BP hint OR 403 with no text |
| `MARKET_CLOSED` | "market closed" / "outside trading hours" |
| `PDT_BLOCK` | "pattern day trader" / "pdt" |
| `RISK_BLOCK` | "wash trade" / "halted" / "not tradable" |
| `INVALID_ORDER` | 4xx without other match |
| `DUPLICATE_ORDER` | 409 OR duplicate client_order_id |
| `BROKER_UNAVAILABLE` | 5xx |
| `UNKNOWN_BROKER_REJECTION` | nothing matched (raw exception preserved) |

## Structured fields written to execution.json

`result["rejection_category"]`, `result["http_status"]`,
`result["alpaca_message"]`, `result["order_notional"]`,
`result["order_qty"]`, plus the human-readable
`result["reason"] = "Alpaca rejected: <CATEGORY> — <message>"`.

## Audit event

`V322_ORDER_REJECTION` appended to `journal/autonomy/<date>.jsonl`
with the full payload (symbol, side, notional, BP at attempt,
strategy, raw exception).

## What this does NOT do

- Does NOT place orders.
- Does NOT mutate strategy state.
- Does NOT auto-close positions.
- Does NOT raise risk limits.
- Does NOT clear LLM override locks.

## Tests

`tests/test_order_rejection_audit_v3220.py` covers all 8 categories
plus the allocator wire-in static check (legacy "see stdout" line
must be gone).
