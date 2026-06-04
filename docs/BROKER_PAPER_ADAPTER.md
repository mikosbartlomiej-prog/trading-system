# Broker Paper Adapter (v3.21.0)

**Module:** `shared/broker_paper_adapter.py`
**Tests:** `tests/test_broker_paper_adapter_v3210.py`
**Status:** PAPER ONLY, fail-closed, dry-run by default.

## Purpose

`shared/alpaca_orders.py` already targets the paper API and enforces
`assert_paper_only`. The audit board nonetheless flagged a structural
risk: any new caller might re-implement paper-only guards
inconsistently. This module is the single hardened wrapper that all
NEW experimental call sites must go through.

It does NOT replace `shared/alpaca_orders.py`. Existing flows
(allocator, exit-monitor, options-exit) continue unchanged.

## Invariants

```
ADAPTER_PAPER_ONLY           = True
ADAPTER_REQUIRES_IDEMPOTENCY = True
ADAPTER_FAIL_CLOSED          = True
```

The adapter:

- only accepts URLs that contain the paper host token;
- requires a non-empty `idempotency_key` keyword argument (missing →
  `TypeError`, empty → `BLOCKED`);
- treats every timeout, every network error, and every non-2xx broker
  response as `BLOCKED` — never falls through to `SUBMITTED`;
- writes an audit record for every outcome via `shared/audit.py`.

The adapter NEVER bypasses the risk engine. The optional `risk_check`
keyword takes a callable that returns `{"allow": bool, "reason": str}`;
any non-`allow` verdict short-circuits to `BLOCKED`.

## Operational gates (in order)

1. `idempotency_key` validation.
2. Kill-switch env (`ALLOW_BROKER_PAPER=true`).
3. Paper base URL validation (`ALPACA_PAPER_BASE_URL` must contain
   the paper host token).
4. Notional cap (`MAX_ORDER_NOTIONAL_USD = 100`).
5. Side / symbol presence.
6. Risk-check pass-through.
7. Credentials present → real path. Credentials missing →
   `SHADOW_FALLBACK`.
8. `dry_run=True` (default) → `DRY_RUN_OK`, no HTTP.
9. `dry_run=False` + credentials present → POST to paper API with
   5-second timeout, fail-closed on any error.

## Closed status enum

```
DISABLED         — kill-switch off
BLOCKED          — any guard refused
DRY_RUN_OK       — dry-run path, no HTTP
SUBMITTED        — real paper POST 2xx
SHADOW_FALLBACK  — credentials missing; shadow sim only
```

## Operator controls

| Env                       | Effect                                                              |
| ------------------------- | ------------------------------------------------------------------- |
| `ALLOW_BROKER_PAPER=true` | Enables the adapter. Default is OFF → every call returns `DISABLED`.|
| `ALPACA_PAPER_BASE_URL`   | Paper base URL. Must contain the paper host token.                  |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Paper credentials. When missing → SHADOW_FALLBACK.     |
| `AUDIT_TRADING_DIR`       | Audit override (used by tests).                                     |

## Notional cap

`MAX_ORDER_NOTIONAL_USD = 100` (USD). Hard cap, enforced before any
HTTP is constructed. Experimental-scale only; the adapter is not a
substitute for the allocator or the entry monitors.

## Test coverage (8 tests)

1. Live (non-paper) URL → `BLOCKED`.
2. Missing credentials → `SHADOW_FALLBACK`.
3. Risk-check `allow=False` → `BLOCKED`.
4. Every call writes an audit event with `actor=broker-paper-adapter`.
5a. Missing `idempotency_key` kwarg → `TypeError`.
5b. Empty `idempotency_key` → `BLOCKED`.
6. Patched `requests.post` raising → `BLOCKED` (timeout / network error).
7. `dry_run=True` → `DRY_RUN_OK` and `requests.post` is never called.
8. Invariants exposed (`ADAPTER_PAPER_ONLY`, `ADAPTER_REQUIRES_IDEMPOTENCY`,
   `ADAPTER_FAIL_CLOSED` all `True`) + notional cap ≤ 100 USD.

## Free-tier compliance

Pure stdlib + `requests` only on the dry-run-off branch. No paid APIs,
no LLM, no new dependencies. The dry-run default ensures the module
never makes a network call by accident.
