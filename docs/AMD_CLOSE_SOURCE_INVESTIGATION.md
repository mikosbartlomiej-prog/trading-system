# AMD Close Source — GitHub Actions Investigation Report (v3.23.3)

**Generated:** 2026-06-08
**Investigation type:** READ-ONLY GitHub Actions forensics
**Final classification:** `AMD_CLOSE_SOURCE_NOT_FOUND_IN_GITHUB_ACTIONS`
**Confirmed source:** **None** — see "next required action" below

## Target

| Field | Value |
| --- | --- |
| Symbol | AMD |
| Alpaca order_id | `7f3ac850-49aa-4ccb-b075-c0ecb56c5871` |
| Side | sell_to_close |
| Type | market |
| Qty | 34 |
| Avg fill price | $485.02 |
| Filled at (UTC) | 2026-06-05T21:35:45Z |
| Filled at (local) | 2026-06-05T17:35:45-04:00 |
| `submitter_source` | `access_key` |

## Method

1. Listed all GitHub Actions workflow runs in window
   2026-06-05T20:00:00Z .. 2026-06-05T23:00:00Z using
   `gh run list --limit 200 --json
   databaseId,name,event,headSha,status,conclusion,createdAt,updatedAt`.
   Returned **200** runs.
2. Computed which runs were **active** at exactly 21:35:45Z (the
   submission moment), defined as `createdAt <= 21:35:45 <= updatedAt`.
   Result: **ZERO**.
3. Pulled `gh run view <id> --log` for **19 candidate runs** —
   the closest temporal neighbours plus every Exit Monitor /
   Emergency Close / Autonomous Remediation / Morning Allocator in
   the window.
4. Grepped each log for: `AMD | 7f3ac850 | emergency_close_2026060 |
   sell_to_close | safe_close | access_key | 485.02 | 21:35:45 |
   17:35:45`.
5. Classified matches: STRONG = order_id literal OR exact `$485.02`
   within 80 chars of `AMD` OR explicit
   `python scripts/emergency_close_2026060X.py` invocation. WEAK =
   `AMD` + sell-related token on same line.

## Findings

### Strong matches: 0

No log line contains the order_id, the explicit fill price near AMD,
or an explicit invocation of either legacy emergency-close script
near the submission moment.

### Weak matches: 2 (both false positives)

| Run ID | Workflow | Time | Match | Verdict |
|---|---|---|---|---|
| 27040363147 | Price Monitor — Momentum Breakout | 21:11:48Z | "AMD" in LONG TICKERS scan list | informational — generates BUY only, never SELL |
| 27041804005 | Emergency Close — autonomous position closer | 21:46:45Z | matched `emergency_close_20260603.py — Already processed — skipping` | wrong symbol (not AMD), wrong time (+11 min) |

### Temporal-window evidence (decisive)

The order arrived in a **4 minute 16 second gap** between scheduled
cron waves:

| Event | UTC time |
| --- | --- |
| Previous wave ended (Defense Monitor run 27041158283) | 2026-06-05T21:31:29Z |
| **AMD order submitted** | **2026-06-05T21:35:45Z** |
| Next wave started (6 workflows incl. Exit Monitor) | 2026-06-05T21:35:52Z |

The order arrived **7 seconds before** the next wave even began.

### Post-submission corroboration

- Exit Monitor 21:48:05Z: `HOLD=4 placed=0 skipped_closed=0` — AMD is
  no longer in the local positions snapshot, consistent with the
  close having happened externally.
- Morning Allocator: 13:00Z run placed 0 orders; 16:15Z run had
  8 failed BUYs, 0 SELLs, no AMD.

## Conclusion

The AMD market sell_to_close was **NOT triggered by a GitHub Actions
workflow run**. Local GH Actions log evidence is exhaustive for the
investigation window and shows no causal path.

## Candidate non-workflow sources (unverified)

The `submitter_source = access_key` Alpaca attribution applies to
**any** REST call made with the paper API key. Without a
`client_order_id` from the Alpaca order itself, three explanations
remain consistent with the evidence:

1. **`DIRECT_ALPACA_MCP_CALL_FROM_INTERACTIVE_CLAUDE_SESSION`** — an
   interactive Claude session at the time using the Alpaca MCP tool
   (which uses the same key path).
2. **`CLOUDFLARE_WORKER_OR_ROUTINE_TRIGGERED_OUTSIDE_GH_ACTIONS`** —
   a Cloudflare Worker / Claude Routine invoked outside the GH
   Actions runner.
3. **`MANUAL_OPERATOR_ACTION_VIA_ALPACA_DASHBOARD_OR_API`** — an
   operator action via the paper dashboard or a manual curl.

The 2 quarantined legacy scripts
(`scripts/quarantined_legacy_order_scripts/emergency_close_20260602.py.disabled`,
`emergency_close_20260603.py.disabled`) **could have** been the
source if invoked locally on an operator machine (they leave no GH
Actions log). However: no `safe_close` audit row exists for AMD on
2026-06-04 / 2026-06-05, and the v3.23.2 static search also returned
zero strong matches for the order_id in local logs.

## Next required action (operator)

**`PULL_ALPACA_API_ORDER_HISTORY_FOR_AMD_2026_06_05_CLIENT_ORDER_ID`**

The Alpaca paper API order-history endpoint exposes the order's
`client_order_id`. Known prefix conventions:

| Prefix | Likely submitter |
| --- | --- |
| `exit-profit-lock-amd-*` | `emergency_close_20260603.py.disabled` (if it ran locally) |
| `exit-emergency-*` | exit-monitor (would also have written `safe_close` — inconsistent here) |
| `safe-close-*` | `shared/alpaca_orders.py::safe_close()` (would have left an audit row — inconsistent) |
| `mcp-*` or no prefix / UUID | Alpaca MCP direct call OR Alpaca dashboard manual close |

The operator can pull the prefix without operator-side credentials
leaving the local machine by curl'ing
`https://paper-api.alpaca.markets/v2/orders/7f3ac850-49aa-4ccb-b075-c0ecb56c5871`
with the existing `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` env vars.

## What this report does NOT do

- Does NOT place orders, modify positions, change stop-losses.
- Does NOT call the live endpoint.
- Does NOT enable `EDGE_GATE_ENABLED` or `ALLOW_BROKER_PAPER`.
- Does NOT reset `state.json::cumulative.starting_equity`.
- Does NOT lower the drawdown guard.
- Does NOT delete or hide any audit log.
- Does NOT fabricate `client_order_id` or fill data.
- Does NOT clear the LLM override lock.

Machine-readable output:
`learning-loop/position_reconciliation/amd_close_source_gh_actions_investigation_latest.json`.

---

## Operator UI verification — 2026-06-08 EOD (v3.23.3.1)

Operator re-opened the Alpaca paper dashboard Order History view and
confirmed the AMD close order row is **still visible** (NOT deleted).
The row was transcribed verbatim from the UI table:

| Field | Value |
| --- | --- |
| ID | `7f3ac850-49aa-4ccb-b075-c0ecb56c5871` |
| Asset | AMD |
| Order Type | Market |
| Type | market |
| Side | sell |
| Position Intent | sell_to_close |
| Qty | 34.00 |
| Filled Qty | 34.00 |
| Currency | USD |
| Avg Fill Price | 485.02 |
| Total Amount | 16,490.68 |
| Status | filled |
| Source | `access_key` |
| Submitted At | Jun 05, 2026, 05:35:44 PM (local 17:35:44-04:00) |
| Filled At | Jun 05, 2026, 05:35:45 PM (local 17:35:45-04:00) |
| Expires At | Jun 05, 2026, 10:00:00 PM (local 22:00:00-04:00) |

**Critical:** the UI table does **NOT** expose `client_order_id`.
The operator confirmed visually that the column is absent from the
dashboard's default Order History view.

### Status tokens (added 2026-06-08 EOD)

- `AMD_ORDER_ROW_VISIBLE_IN_ALPACA_UI` — the close row remains on
  the Alpaca paper dashboard, evidence is NOT lost.
- `CLIENT_ORDER_ID_NOT_VISIBLE_IN_UI_TABLE` — the discriminating
  field is absent from the dashboard's default columns.
- `AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT` —
  the source remains unresolved; the gap can only be closed by
  one of the two paths below.

### Conclusion (refined)

The AMD close remains **confirmed** as `market sell_to_close` via
`access_key`. Realized P/L is unchanged at **-$437.07** (buy
$16,927.75 − sell $16,490.68 = -$437.07). The submitter remains
**unknown** because the field that would discriminate among the
candidate sources (`client_order_id`) is not visible in the UI
table.

### Narrowed next-required action

The previous broad action
`PULL_ALPACA_API_ORDER_HISTORY_FOR_AMD_2026_06_05_CLIENT_ORDER_ID`
is now narrowed to ONE of:

1. **Alpaca read-only API order-details lookup** for the exact
   order_id:
   `GET https://paper-api.alpaca.markets/v2/orders/7f3ac850-49aa-4ccb-b075-c0ecb56c5871`
   using existing paper `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY`.
   The JSON response includes `client_order_id`.
2. **Alpaca CSV / activity export** that includes the
   `client_order_id` column (some export views expose more columns
   than the live table).

Either path resolves the source. Both are READ-ONLY operations
against the paper endpoint.

### What this verification does NOT do

- Does NOT change AMD's realized P/L (still -$437.07).
- Does NOT mark AMD evidence as lost (row is preserved on the
  dashboard).
- Does NOT infer or invent a `client_order_id`.
- Does NOT alter AMD's status as "manually verified from Alpaca UI /
  operator transcription".
- Does NOT place, modify, or close any position.
- Does NOT enable live trading or broker_paper.
- Does NOT reset the equity baseline.
- Does NOT lower the drawdown guard.
