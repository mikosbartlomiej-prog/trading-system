# Allocator BP / over-allocation pre-check

**Module:** `shared/allocator_bp_guard.py`
**Wired into:** `shared/allocator.py::AccountAwareAllocator.execute_orders`
**Audit decision_type:** `V322_BP_GUARD`
**Incident:** 2026-06-07 ETAP 3

---

## Why

**2026-06-05:** 8 BUYs were ALL rejected by Alpaca with
`HTTP 403 insufficient buying power`. Root cause: 2026-06-04 placed 8 BUYs
that consumed nearly all of the account's buying power; the next session
the allocator re-emitted fresh BUYs without checking that BP had not yet
been replenished by exits or settlements. Each call walked into the same
broker rejection.

The legacy `risk_officer.evaluate_trade` check kicked in per-order, but
it lacks the **cumulative** view across a batch of BUYs that the allocator
queues in one execute_orders call. Risk-officer would let the FIRST BUY
through (it sees BP ≥ that single size_usd) and then 7 successive BUYs
each silently bounced on the broker side.

This module is the **batch-level pre-flight** that walks the BUY notionals
once, drops the tail that wouldn't fit, and records every dropped order
in the audit JSONL.

---

## Contract

```
check_buying_power_pre_execution(
    orders,
    account_status,
    open_positions,
    *,
    pending_gtc_notional=0.0,
    max_gross_exposure=None,
    emit_audit=True,
) -> dict
```

### Inputs

| Argument | Type | Source |
|---|---|---|
| `orders` | `list[dict]` | Allocator plan orders (mixed BUY/REDUCE/EXIT/HOLD/SELL). |
| `account_status` | `dict | None` | `shared.risk_guards.get_account_status()`. |
| `open_positions` | `list[dict]` | `shared.risk_guards.get_open_positions()`. |
| `pending_gtc_notional` | `float` | Dollar value of GTC orders still resting at Alpaca. Default 0. |
| `max_gross_exposure` | `float | None` | If supplied, clamped DOWN to the profile (never raised). |
| `emit_audit` | `bool` | Disables JSONL emit for tests. |

### Output

```python
{
    "allowed_orders":           [...],   # passed through (preserve order)
    "deferred_orders":          [...],   # mutated: status=deferred_bp, deferred_reason=...
    "total_requested_notional": float,
    "total_available_bp":       float,
    "total_open_exposure":      float,   # positions + pending GTC
    "exposure_cap_usd":         float,   # equity × max_gross_exposure
    "max_gross_exposure":       float,   # the multiplier actually applied
    "reason":                   str,
    "warning":                  str | None,
    "guard_invariants":         {"BP_GUARD_NEVER_RAISES_LIMITS": True, ...},
    "n_buys_input":             int,
    "n_buys_allowed":           int,
    "n_buys_deferred":          int,
    "n_non_buy_passthrough":    int,
}
```

### Deferred reasons

| Reason | Meaning |
|---|---|
| `INSUFFICIENT_BP_PROJECTED` | Cumulative BUY notional + this order > `account.buying_power`. |
| `EXPOSURE_CAP` | Open exposure + pending GTC + this order > `equity × max_gross_exposure`. |

---

## Invariants (test-asserted)

These two module-level constants are checked in
`tests/test_allocator_bp_guard_v3220.py::TestInvariants`. They encode the
contract that this module is a **safety filter**, never an attack surface
that loosens limits.

```python
BP_GUARD_NEVER_RAISES_LIMITS = True
BP_GUARD_FAIL_SOFT_ON_DATA_UNAVAILABLE = True
```

1. **NEVER RAISES LIMITS** — even if a caller passes `max_gross_exposure=5.0`,
   the value is clamped DOWN to whatever's in
   `config/aggressive_profile.json::capital.max_gross_exposure`
   (currently 1.50). Tests confirm this.

2. **FAIL-SOFT** — if `account_status` is `None`, empty, or carries
   `buying_power=0` / `equity=0`, ALL orders pass through and the caller
   gets `warning="BP_DATA_UNAVAILABLE"`. The downstream risk_officer +
   portfolio_risk gates are still in the path; the BP guard is the first
   line of defense, not the only one.

Other guarantees baked into the implementation:

- Non-BUY orders (`EXIT`, `REDUCE`, `HOLD`, `SELL`) are **never deferred**.
  They free capital — deferring them would aggravate, not improve, BP usage.
- Zero-notional or negative-notional BUYs are passed through.
- Garbage input (string `buying_power`, missing `market_value`, malformed
  `delta`) never raises — the guard treats malformed numbers as 0 and
  proceeds.

---

## Audit event

Every call emits exactly one JSONL line via `shared.audit.write_audit_event`
into `journal/autonomy/<UTC-date>.jsonl`:

```json
{
  "decision_type":            "V322_BP_GUARD",
  "decision":                 "ENFORCE" | "ALLOW_ALL" | "PASS_THROUGH_FAIL_SOFT",
  "reason":                   "deferred 3 BUY(s): INSUFFICIENT_BP_PROJECTED",
  "actor":                    "allocator-bp-guard",
  "warning":                  null | "BP_DATA_UNAVAILABLE",
  "total_requested_notional": 80000.0,
  "total_available_bp":       50000.0,
  "total_open_exposure":      0.0,
  "exposure_cap_usd":         300000.0,
  "max_gross_exposure":       1.5,
  "n_allowed":                5,
  "n_deferred":               3,
  "deferred_symbols":         ["SYM5", "SYM6", "SYM7"],
  "deferred_reasons":         ["INSUFFICIENT_BP_PROJECTED", "INSUFFICIENT_BP_PROJECTED", "INSUFFICIENT_BP_PROJECTED"]
}
```

The audit emit itself is fail-soft. If JSONL append fails (disk full,
permission denied), the gate decision still applies — the only loss is
visibility, not safety.

---

## Wiring point

`shared/allocator.py::execute_orders`, immediately AFTER the EXIT-first
sort and BEFORE the `_execute_one` loop. Deferred orders are written into
`execution.json` results with `status="deferred_bp"` so the operator can
see exactly which BUYs were dropped and why.

The final trace line now reports four buckets:

```
execution complete: 5 placed, 0 skipped, 0 failed, 3 deferred_bp
```

---

## Required test scenarios (incident spec)

All defined in `tests/test_allocator_bp_guard_v3220.py`:

- 8 BUYs totaling $80k vs BP $50k → 5 allowed, 3 deferred.
- BP unavailable → all allowed with `warning="BP_DATA_UNAVAILABLE"`.
- Exposure cap respects existing exposure.
- Pending GTC orders count toward exposure.
- Fail-soft never raises (garbage orders / account / positions).
- Deferred orders carry `INSUFFICIENT_BP_PROJECTED` reason.
- Caller cannot raise `max_gross_exposure` above profile.
- Non-BUY orders always pass through.
- Audit JSONL is written with `decision_type=V322_BP_GUARD`.
- Fail-soft pass-through still emits an audit line with
  `decision=PASS_THROUGH_FAIL_SOFT`.

---

## What this module does NOT do

- It does not size, price, or sign orders — only DEFER vs ALLOW.
- It does not call Alpaca. Only reads in-process `account_status` /
  `positions` that the caller already fetched.
- It does not replace `risk_officer.evaluate_trade` — per-order checks
  (whitelist, SL, R:R, concentration, daily drawdown, VIX, PDT) still
  fire afterwards in the `_execute_one` path.
- It does not raise BP or exposure ceilings — only ratchets caller
  requests DOWN toward the profile setting.
- It does not auto-close positions, fabricate trades, or add LLM calls
  to the runtime trading path.
