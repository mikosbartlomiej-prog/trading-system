# Quarantined Legacy Direct-Order Scripts

**DO NOT RUN. DO NOT RESTORE AS `.py`. DO NOT IMPORT.**

This directory holds disabled copies of legacy emergency-close
scripts that contained a direct `requests.post(/v2/orders, side="sell",
type="market")` path **without** going through
`shared/alpaca_orders.py::safe_close()` and **without** emitting an
audit event.

These scripts are the root cause of the v3.23.1 finding
`MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT` — they
were the most plausible (but unconfirmed) source of the AMD market
`sell_to_close` at 2026-06-05T21:35:45Z that produced no local
`safe_close` event.

## What is here

| File | Status |
| --- | --- |
| `emergency_close_20260602.py.disabled` | quarantined 2026-06-08 (v3.23.3) |
| `emergency_close_20260603.py.disabled` | quarantined 2026-06-08 (v3.23.3) |

The `.py.disabled` extension makes them non-executable as Python
modules. Python's import system, `python3 <path>` runner, and the
`audit_bypass_detector` all treat them as inert reference material.

## Why quarantined, not deleted

Operators and the Final Arbiter must still be able to inspect the
exact code that produced the v3.23.1 audit gap when reviewing
incidents. Deleting these files would erase evidence; keeping them as
`.py` would leave a footgun. `.py.disabled` strikes the balance:
visible but inert.

## Rules

1. **DO NOT** rename either file back to `.py`.
2. **DO NOT** copy their content into a new active script.
3. **DO NOT** move them out of this directory.
4. **DO NOT** add this directory or its files to any allow-list as
   "active legitimate sell submitters" — the only legitimate sell
   submitters in this codebase are:
   - `shared/alpaca_orders.py` (single-entry `safe_close()`)
   - `options-monitor/monitor.py` (BUY only — entry path)
   - `shared/broker_paper_adapter.py` (hardened paper-only adapter)
5. **DO NOT** invoke them from any GitHub Actions workflow, shell
   wrapper, cron job, or systemd unit.
6. If you genuinely need an emergency close in the future, call
   `shared/alpaca_orders.py::safe_close()`. That function:
   - cancels open OCO brackets first,
   - validates the side/qty,
   - emits an audit event to `journal/autonomy/<date>.jsonl`,
   - records the `decision_id` for cross-reference.

## Static-detector behavior

`shared/audit_bypass_detector.py` (v3.23.3+) classifies any file in
this directory — and any `.py.disabled` file anywhere in scanned
trees — as `QUARANTINED_LEGACY_DANGEROUS`. These do **not** count
toward the `flagged_files` list and do **not** flip
`invariant_satisfied` to False.

If anyone reintroduces a `.py` direct-order script outside the
allow-list, the detector will flag it as `ORDER_SUBMITTER_BYPASS` or
`LEGACY_DANGEROUS` and the invariant
`NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT` (test-asserted in
`tests/test_legacy_direct_order_quarantine_v3233.py`) will fail.

## Reference

- v3.23.1: AMD reconciliation surfaced the audit gap
  (`docs/AUDIT_BYPASS_INVESTIGATION.md`).
- v3.23.2: static detector + AMD close-source search
  (`shared/audit_bypass_detector.py`, `shared/amd_close_source_search.py`).
- v3.23.3: this quarantine + GH Actions investigation
  (`docs/AMD_CLOSE_SOURCE_INVESTIGATION.md`).

The AMD close source remains formally unknown. The GH Actions
investigation found ZERO workflow runs active at the exact submission
moment (4m16s gap between scheduled waves). Confirmation of the
actual submitter requires pulling the order's `client_order_id` from
the Alpaca paper API.
