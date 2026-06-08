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

---

## v3.23.2 addendum — audit bypass investigation (2026-06-08)

After v3.23.1 surfaced `MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT`
for AMD, v3.23.2 adds tooling to investigate (without auto-fixing
or auto-deleting anything):

- `shared/audit_bypass_detector.py` — static classifier for every
  Python file that can submit a sell/close order. Six
  classifications: `SAFE_CLOSE_WRAPPED`, `AUDIT_EQUIVALENT_WRAPPED`,
  `READ_ONLY`, `ORDER_SUBMITTER_BYPASS`, `LEGACY_DANGEROUS`,
  `UNKNOWN_REQUIRES_REVIEW`. ALLOW_LIST contains the three
  legitimate sell submitters (`shared/alpaca_orders.py`,
  `options-monitor/monitor.py`, `shared/broker_paper_adapter.py`).
  Three test-asserted invariants: `NO_DIRECT_MARKET_SELL_WITHOUT_AUDIT`,
  `NO_SELL_TO_CLOSE_WITHOUT_SAFE_CLOSE_OR_EQUIVALENT_AUDIT`,
  `ACCESS_KEY_ORDER_PATH_MUST_EMIT_AUDIT`.
- `shared/amd_close_source_search.py` — static, READ-ONLY search
  for evidence of the AMD `7f3ac850-…` close order across
  `journal/`, `learning-loop/`, `scripts/`, `shared/`, `exit-monitor/`,
  `options-exit-monitor/`, `.github/`, `docs/`. Self-reference filter
  excludes v3.23.1 reconciliation reports.
- `learning-loop/position_reconciliation/audit_bypass_investigation_latest.json`
  — real-repo scan: 161 files scanned, **2 flagged**
  (`scripts/emergency_close_20260602.py`,
  `scripts/emergency_close_20260603.py`),
  `invariant_satisfied=False`, `risk_level=HIGH`.
- `learning-loop/position_reconciliation/amd_close_source_search_latest.json`
  — search result: 0 STRONG matches after self-reference filter.
  Classification: `AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY`.
  Confirmed close source remains unknown locally.
- `docs/AUDIT_BYPASS_INVESTIGATION.md` — operator-facing report
  documenting the AMD close evidence, suspected paths, confirmed
  path = None, and required follow-ups.

Operator action items (none auto-applied):

1. `INVESTIGATE_AMD_CLOSE_SOURCE_IN_GITHUB_ACTIONS` — check GH
   Actions run logs on 2026-06-05 around 21:30 UTC for invocation
   of either suspected script.
2. `PULL_ALPACA_API_ORDER_HISTORY_FOR_AMD_2026_06_05` — fetch the
   actual close order's `client_order_id` from the Alpaca paper API
   to identify which script (if any) submitted.
3. `DISABLE_OR_WRAP_DIRECT_ORDER_SCRIPT` — operator must either
   delete the 2 flagged legacy scripts OR rewrite them to call
   `safe_close()` only.

v3.23.2 does NOT auto-allow-list either script (that would silently
hide the bypass). The audit invariant stays `False` until operator
chooses one of the above remediation paths.


---

## v3.23.3 addendum — quarantine + GH Actions investigation (2026-06-08)

The 2 LEGACY_DANGEROUS scripts from v3.23.2
(`scripts/emergency_close_20260602.py`,
`scripts/emergency_close_20260603.py`) have been quarantined to
`scripts/quarantined_legacy_order_scripts/` as `.py.disabled`. They
cannot be invoked, imported, or used as a sell-submit path. A
README in that directory pins the rules.

`shared/audit_bypass_detector.py` was extended with:
- new classification `QUARANTINED_LEGACY_DANGEROUS`,
- new invariant `NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT = True`,
- `detect_bypasses()` now scans `.py.disabled` files, tracks them
  under a new `quarantined_files` key, and excludes them from
  `flagged_files`.

Post-quarantine real-repo scan returns
`invariant_satisfied = True`, `flagged_files = []`,
`quarantined_files = [2 paths]`. Risk level downgraded
**HIGH → MEDIUM** in
`learning-loop/position_reconciliation/audit_bypass_investigation_latest.json`.

The remaining MEDIUM is the still-unknown AMD close source. The
v3.23.3 GitHub Actions investigation
(`docs/AMD_CLOSE_SOURCE_INVESTIGATION.md`) examined 200 runs in the
2026-06-05T20-23Z window and confirmed ZERO workflow runs were
active at the exact submission moment (4m16s gap between cron
waves). Classification:
`AMD_CLOSE_SOURCE_NOT_FOUND_IN_GITHUB_ACTIONS`. Confirmed source
still **None**. Operator follow-up:
**`PULL_ALPACA_API_ORDER_HISTORY_FOR_AMD_2026_06_05_CLIENT_ORDER_ID`**.

v3.23.3 does NOT auto-allow-list either quarantined file (that
would silently legitimise the bypass). Operator may, as a future
decision, delete the quarantined files entirely once the AMD source
is confirmed — until then they remain as evidence.
