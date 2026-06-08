# Audit Bypass Investigation — v3.23.2

**Generated:** 2026-06-08
**Risk level:** HIGH
**Status:** suspected paths identified; AMD-specific source not yet
confirmed; operator follow-up required.

## What happened

On 2026-06-05 17:35:45-04:00 (21:35:45 UTC) the Alpaca paper account
received a **market sell_to_close** for AMD (34 shares @ $485.02 →
realized -$437.07). The Order History row tags the close with
`submitter_source = access_key`, meaning some component using our
Alpaca API key submitted the order.

But `journal/autonomy/2026-06-04.jsonl` and
`journal/autonomy/2026-06-05.jsonl` contain **zero** matching
`safe_close` events for AMD. This is the
`MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT` finding —
some code path bypassed `shared/alpaca_orders.py::safe_close()`
and wrote no audit row.

## AMD close evidence (from operator-provided sanitized Order History)

| Field | Value |
| --- | --- |
| symbol | AMD |
| close order_id | `7f3ac850-49aa-4ccb-b075-c0ecb56c5871` |
| close type | market |
| close side | sell_to_close |
| close qty | 34 |
| close avg fill price | $485.02 |
| close filled at | 2026-06-05T17:35:45-04:00 |
| submitter_source | `access_key` |
| safe_close audit row in local JSONL | **NO** |

## Why it is a problem

- Every close path is supposed to go through
  `shared/alpaca_orders.py::safe_close()`, which writes an audit row
  before submitting the order.
- A close that bypasses that path:
  - cannot be attributed by the analyzer (cumulative_trades stays 0
    even when real trades execute),
  - cannot be reviewed in `journal/autonomy/<date>.jsonl`,
  - cannot trigger the existing `safe_close` guards (held_for_orders,
    cancel-brackets-first, etc.).

## Suspected paths (from static scan)

Two legacy emergency-close scripts contain direct
`requests.post(/v2/orders, side="sell", type="market")` calls
without going through `safe_close()` or writing an audit row:

- `scripts/emergency_close_20260602.py`
- `scripts/emergency_close_20260603.py`

These are flagged as `LEGACY_DANGEROUS` by `shared/audit_bypass_detector.py`.
They were one-shot operator-issued scripts written before
`safe_close()` was the single-entry exit path. They remain in the
repo and could in principle have been invoked manually on
2026-06-05.

## Confirmed path

**None yet.** The local logs (`journal/autonomy/`, `learning-loop/`,
allocator execution.json) do NOT contain evidence attributing the AMD
close to either suspected script. The `shared/amd_close_source_search.py`
module returned classification
`AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY`
after filtering out self-referential matches in the v3.23.1
reconciliation reports.

## Static scan summary

`shared/audit_bypass_detector.py` scanned all `.py` files under
the allow-listed scan dirs (`shared/`, `scripts/`, `learning-loop/`,
and the 8 monitor directories). Result:

| Classification | Count |
| --- | --- |
| `SAFE_CLOSE_WRAPPED` | 1 (`shared/alpaca_orders.py`) |
| `READ_ONLY` | 31 |
| `LEGACY_DANGEROUS` | **2** (the two `emergency_close_*` scripts above) |
| `UNKNOWN_REQUIRES_REVIEW` | 127 |
| `ORDER_SUBMITTER_BYPASS` | 0 |
| `AUDIT_EQUIVALENT_WRAPPED` | 0 |
| Total scanned | 161 |

- `invariant_satisfied`: **False** (2 flagged files outside the allow-list)
- Allow-list (`shared/alpaca_orders.py`, `options-monitor/monitor.py`,
  `shared/broker_paper_adapter.py`) contains the legitimate exception paths.

## Required fixes (operator-driven; no code path will be auto-modified)

1. **`INVESTIGATE_AMD_CLOSE_SOURCE_IN_GITHUB_ACTIONS`** — search
   GitHub Actions run logs on 2026-06-05 around 21:30 UTC for a run
   that triggered `scripts/emergency_close_*.py`. If found, that is
   the confirmed path.
2. **`PULL_ALPACA_API_ORDER_HISTORY_FOR_AMD_2026_06_05`** — fetch
   the actual close order's `extended_hours`, `time_in_force`, and
   any `client_order_id` from the Alpaca paper API. The
   `client_order_id` prefix tells us which script submitted (e.g.
   `exit-profit-lock-amd-*` → `emergency_close_20260603.py`,
   `exit-emergency-*` → other script).
3. **`DISABLE_OR_WRAP_DIRECT_ORDER_SCRIPT`** — operator must either
   - delete the two `emergency_close_*` scripts (they are one-shot,
     dated, no longer needed), OR
   - rewrite them to call `shared/alpaca_orders.py::safe_close()` only.
   This is not auto-applied — operator decision.
4. **`KEEP_DRAWDOWN_GUARD_ACTIVE`** — guard correctly halts new
   entries at -3.0%. No change.
5. **`KEEP_EDGE_GATE_DISABLED`** — `EDGE_GATE_ENABLED=false` stays.
6. **`DO_NOT_ENABLE_BROKER_PAPER`** — `ALLOW_BROKER_PAPER` stays unset.

## Remaining unknowns

- Was the AMD close actually placed by one of the
  `emergency_close_*` scripts, or by some other access_key holder
  (operator-issued curl, manual dashboard action,
  not-yet-found one-shot script)?
- Did either `emergency_close_*` script even run on 2026-06-05?
  (No run logs in `learning-loop/incidents/2026-06-05.md` or other
  local files; GH Actions runs must be checked.)
- Are there other access_key paths that bypass `safe_close()`?
  (Static scan suggests no for production code, but legacy scripts
  remain a risk.)

## Invariants

- `NO_DIRECT_MARKET_SELL_WITHOUT_AUDIT`
- `NO_SELL_TO_CLOSE_WITHOUT_SAFE_CLOSE_OR_EQUIVALENT_AUDIT`
- `ACCESS_KEY_ORDER_PATH_MUST_EMIT_AUDIT`

Each is a module-level constant in `shared/audit_bypass_detector.py`
and is test-asserted. They are currently **not satisfied** while
the 2 legacy scripts are still present and not allow-listed.

## What this report does NOT do

- Does NOT auto-delete the legacy scripts.
- Does NOT auto-allow-list them (would silently hide the bypass).
- Does NOT submit orders, modify positions, or close ETH/AVAX.
- Does NOT lower drawdown_guard, reset equity baseline, or clear
  the LLM override lock.
- Does NOT mutate `state.json` or `runtime_state.json`.

Machine-readable output:
`learning-loop/position_reconciliation/audit_bypass_investigation_latest.json`.

---

## v3.23.3 update — 2026-06-08

**Quarantine action completed.** Both flagged scripts have been
moved out of the active `scripts/` directory:

| Original path | Quarantined to |
| --- | --- |
| `scripts/emergency_close_20260602.py` | `scripts/quarantined_legacy_order_scripts/emergency_close_20260602.py.disabled` |
| `scripts/emergency_close_20260603.py` | `scripts/quarantined_legacy_order_scripts/emergency_close_20260603.py.disabled` |

The new directory `scripts/quarantined_legacy_order_scripts/`
carries a README that explicitly forbids restoring either file as
`.py`, copying their content into a new active script, or
allow-listing the directory.

**Static-detector status** (after re-scan):

| Metric | Before (v3.23.2) | After (v3.23.3) |
| --- | --- | --- |
| `flagged_files` count | 2 | **0** |
| `quarantined_files` count | n/a | 2 |
| `invariant_satisfied` | False | **True** |
| `risk_level` | HIGH | MEDIUM |

`shared/audit_bypass_detector.py` gained:
- new classification `QUARANTINED_LEGACY_DANGEROUS`,
- new module-level invariant
  `NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT = True`,
- a `QUARANTINE_DIR_MARKER` constant,
- `detect_bypasses()` now scans `.py.disabled` and reports them
  separately under `quarantined_files`.

**GH Actions investigation result** (see
`docs/AMD_CLOSE_SOURCE_INVESTIGATION.md`): no workflow run was
active at 2026-06-05T21:35:45Z (4m16s gap between cron waves). The
AMD close cannot have come from a GitHub Actions runner.
Classification: `AMD_CLOSE_SOURCE_NOT_FOUND_IN_GITHUB_ACTIONS`.

**Remaining unknowns:**
- The AMD close source is still formally unknown. Operator must
  pull the `client_order_id` via the Alpaca paper API to discriminate
  among: direct MCP call from an interactive Claude session, a
  Cloudflare Worker / Routine, or a manual operator action via the
  dashboard.

**What changed in invariant set:**
- `NO_DIRECT_MARKET_SELL_WITHOUT_AUDIT` — still True (test-asserted).
- `NO_SELL_TO_CLOSE_WITHOUT_SAFE_CLOSE_OR_EQUIVALENT_AUDIT` — still True.
- `ACCESS_KEY_ORDER_PATH_MUST_EMIT_AUDIT` — still True.
- `NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT` — **new in v3.23.3,
  test-asserted**, currently True.

---

## v3.23.3.2 follow-up — operator orders-view verification

Operator verified the Alpaca paper dashboard Orders view: **no
hanging / open orders** are present. All visible orders are filled
or canceled. No pending AMD TP / SL or stale AMD open order is
visible.

Status token added:
- `OPERATOR_VERIFIED_NO_OPEN_ORDERS_ALL_FILLED_OR_CANCELED`

Position-state verification was NOT performed in this check, so
`OPERATOR_VERIFIED_NO_OPEN_POSITIONS` is intentionally NOT added.

Impact:
- Operational risk surface from orphan brackets / stale open
  orders is currently zero per dashboard.
- AMD audit-gap status is **unchanged**: source still unresolved,
  next action still `AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT`.
- Audit-bypass invariant `NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT`
  remains True (quarantine intact).
