# Broker-Paper Canary Executor — Design (v3.29.1, NOT IMPLEMENTED)

## Status

**Design only.** v3.29.1 ships NO executor code. This document
defines what the future safe canary executor MUST satisfy before
any code lands.

## Hard rules

The future canary executor MUST:

1. Place **at most 1 order per UTC day**.
2. Cap notional at **$25 per order**.
3. Trade **US equity only** — crypto and options are forbidden.
4. Use the **deterministic safe-order wrapper**
   (`shared/alpaca_orders.py::safe_close` is the reference pattern;
   the canary entry path requires its sibling).
5. Run the full deterministic pre-order gate stack BEFORE placing
   any order:
   - VIX guard
   - drawdown guard
   - per-ticker concentration cap
   - daily drawdown circuit breaker
   - PDT guard
   - risk_officer evaluator
6. **LLM may veto-recommend only.** `LLM_PRE_ORDER_VETO_HONORED`
   must remain `false` until separately audited + operator-approved.
7. Post-trade reconciliation MUST run within 60 seconds and write
   an audit entry to `journal/autonomy/<date>.jsonl` with
   `decision_type=BROKER_PAPER_CANARY_ORDER`.
8. **Auto-disable on first error** — any non-200 from Alpaca, any
   exception, any reconciliation mismatch flips the canary OFF
   for the rest of the UTC day.
9. **Auto-disable on LLM quality regression** — if any post-order
   LLM advisory run returns a `quality_status` other than
   `LLM_ADVISORY_QUALITY_ACCEPTABLE`, the canary flips OFF.
10. **Auto-disable on reconciliation mismatch** — any difference
    between the submitted order and the broker's fill report
    flips the canary OFF.
11. **Live trading forbidden.** The executor must use the paper
    Alpaca endpoint (`paper-api.alpaca.markets`). The 7
    broker-execution env flags must remain hard-pinned `false`
    except for one new dedicated flag (see "What's new" below).
12. **Operator approval required.** The new flag must default
    `false` and must be set by the operator in a separate audited
    PR.

## What's new (the safe enable switch v3.29 did NOT ship)

A single new repo flag would gate the canary execution path:

```
configs/broker_paper_canary.json::canary_execution_flag_present = true
```

This flag is read by both `shared/broker_paper_canary_unlock.py`
and the future executor. It does NOT replace
`OPERATOR_APPROVED_BROKER_PAPER_CANARY` — both are required.

## Implementation checklist (when prioritised)

1. New file `shared/broker_paper_canary_executor.py` with
   `try_place_canary_order(symbol, side, notional_usd)`.
2. Wire the deterministic gate stack at the top of the function.
3. Call `place_stock_bracket` ONLY when every gate passes.
4. Post-trade reconciler runs synchronously after fill.
5. Auto-disable writes `OPERATOR_APPROVED_BROKER_PAPER_CANARY=false`
   automatically on any error (the variable can be re-set by the
   operator).
6. Audit entry mandatory for every decision (allow, defer, block,
   fill, reconcile-mismatch).
7. New tests:
   - one order/day cap enforced
   - $25 max notional enforced
   - crypto/options refused at function entry
   - LLM veto-recommend does NOT block (until
     `LLM_PRE_ORDER_VETO_HONORED=true`)
   - any deterministic gate fail → no order placed
   - reconciliation mismatch flips canary off
   - any 5xx → flips canary off
   - LLM quality regression flips canary off
   - live env flags refuse function entry

## What v3.29.1 SHIPS instead

- Read-only canary unlock evaluator with 11 statuses + 6 stages.
- LLM strategy alignment gate.
- Quality truth source + history.
- Real-market evidence acceleration analyzer.

## v3.30 update (2026-06-09) — pre-executor skeleton landed

v3.30 ships the *pre-executor* in **preflight-only** mode. This is
NOT the executor described above (no order placement yet). It is a
deterministic gate-evaluation skeleton that satisfies hard rules #1
through #6 of this document and exposes the new
`canary_executor_mode = "preflight_only"` knob.

What landed:

- [shared/broker_paper_canary_preflight.py](../shared/broker_paper_canary_preflight.py) —
  pure read-only preflight; NEVER imports the broker-orders module;
  NEVER calls submit_order / place_order / safe_close.
- [scripts/run_broker_paper_canary.py](../scripts/run_broker_paper_canary.py) —
  CLI runner. Default `--preflight-only --dry-run`. Maximum verdict
  in v3.30 is `CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED`.
- [configs/broker_paper_canary.json](../configs/broker_paper_canary.json)
  flipped `canary_execution_flag_present` from `false` to `true`,
  added `canary_executor_mode = "preflight_only"`, kept
  `canary_order_placement_implemented = false`.
- [shared/broker_paper_canary_unlock.py](../shared/broker_paper_canary_unlock.py)
  reads the two new fields and emits a new terminal status —
  `BROKER_PAPER_CANARY_UNLOCK_READY_PRE_EXECUTOR_ONLY` — when all 21
  hard gates pass but the executor is still preflight-only.

What is still NOT shipped (this remains the v3.31+ checklist):

- An actual `try_place_canary_order` implementation.
- The wired call to `place_stock_bracket` (still bounded by limits).
- Post-trade reconciliation invocation.
- Auto-disable cascade.

The next audited PR may:

1. Implement `try_place_canary_order` in
   `shared/broker_paper_canary_executor.py` per items 1–7 above.
2. Flip `canary_order_placement_implemented` to `true` in the config.
3. Flip `canary_executor_mode` to `"full_executor"`.
4. Add tests covering each hard rule.

When all three are done, the unlock evaluator advances to the
existing `BROKER_PAPER_CANARY_UNLOCK_READY` terminal. Operator
approval (`OPERATOR_APPROVED_BROKER_PAPER_CANARY=true`) plus
`BROKER_PAPER_CANARY_EXECUTION_ENABLED=true` plus `CANARY_DRY_RUN=false`
are still required at runtime for any order to actually fly.

## Standing markers (apply to this design AND any future executor)

- `LLM_STRATEGY_ALIGNMENT_ENFORCED`
- `LLM_ADVISORY_ONLY_CONFIRMED`
- `LLM_OUTPUT_DOES_NOT_COUNT_AS_REAL_MARKET_EVIDENCE`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING`
- `LIVE_TRADING_UNSUPPORTED`
- `DETERMINISTIC_GATES_REMAIN_FINAL`
- `CANARY_PRE_EXECUTOR_PREFLIGHT_ONLY`
- `NO_ORDER_PLACEMENT_IN_V330`
