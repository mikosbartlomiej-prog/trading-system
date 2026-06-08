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

---

## v3.23.3.3 addendum — operator Positions / View All verification (2026-06-08)

Operator explicitly checked the Alpaca paper Positions / View All
panel. The 2026-06-04 equity batch (AMD, CRWD, NOW, QQQ, SPY, GLD,
PANW, ORCL) is **not open** on the dashboard. The 4 crypto
positions remain open: ETHUSD + AVAXUSD as meaningful holdings,
SOLUSD + LTCUSD as dust.

This **confirms** the v3.23.1 inference that the 8 equity
positions are no longer open (they appeared as "previously inferred
equity positions rejected" in the v3.23.1 reconciliation). It does
**not** resolve which submitter closed AMD — the v3.23.3.1 finding
`AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT`
stands.

Verbatim transcribed values + risk-impact narrative:
[`docs/AMD_CLOSE_SOURCE_INVESTIGATION.md`](AMD_CLOSE_SOURCE_INVESTIGATION.md).

Updated machine-readable snapshot:
[`learning-loop/position_reconciliation/operator_dashboard_snapshot.json`](../learning-loop/position_reconciliation/operator_dashboard_snapshot.json)
gained a `v3233_3_positions_view_verification_2026_06_08` block
with exact qty / market value / avg entry / cost basis values
(source: `OPERATOR_DASHBOARD_POSITIONS_VIEW_MANUAL`). The original
v3.23.1 session-start block is preserved for history.

---

## v3.24.0 addendum — full order-history drawdown reattribution (2026-06-08)

Operator provided the broader Alpaca paper Order History export.
This **invalidates** the v3.23.x interim hypothesis that the
remaining 7 equity trades carried ~-$5,304 of the drawdown.

Reattribution facts (from
`learning-loop/position_reconciliation/latest.json::v324_followups`):

- Full 8-symbol equity batch realized P/L: **-$236.74**
  (close to flat; not the primary drawdown source).
- SOLUSD sell_to_close on 2026-06-06: 451.353798 units @ $60.07,
  sell amount $27,112.92, reconstructed cost basis of sold lots
  ~$29,964.07, realized P/L approx **-$2,851.15**.
- LTCUSD sell_to_close on 2026-06-06: 675.170322 units @ $40.32,
  sell amount $27,221.13, reconstructed cost basis ~$29,964.03,
  realized P/L approx **-$2,742.90**.
- Combined SOLUSD + LTCUSD realized loss: approx **-$5,594.06**.
- Reported drawdown: -$5,741. Explained ~-$5,830.80
  (equity -$236.74 + crypto -$5,594.06). Small residual
  ~-$147 (or +$89 over-explained depending on baseline anchor).

Status tokens added:
- `EQUITY_BATCH_RECONSTRUCTED_FROM_ORDER_HISTORY`
- `EQUITY_BATCH_NOT_PRIMARY_DRAWDOWN_SOURCE`
- `CRYPTO_SOL_LTC_REALIZED_LOSS_CONFIRMED`
- `DRAWDOWN_REATTRIBUTED_TO_CRYPTO_CLOSE_CYCLE`
- `DRAWDOWN_ATTRIBUTION_NEAR_COMPLETE_WITH_SMALL_RESIDUAL`
- `RESIDUAL_DRAWDOWN_REQUIRES_ACCOUNT_EQUITY_TIMING_RECONCILIATION`

Primary new operator action item:
`INVESTIGATE_CRYPTO_POSITION_SIZING_AND_EXIT_POLICY_SOL_LTC_2026_06_06`
— each of SOL and LTC carried ~$29,964 cost basis at the closed-lot
batch, ~30% of $100k paper equity each (~60% combined), well above
the v2.0 per-ticker cap (40%). This points to repeated buy-side
laddering without a hard aggregate-crypto-exposure cap. Full
question list lives in
`learning-loop/position_reconciliation/latest.json::v324_followups.risk_findings`.

AMD reconciliation is unchanged: P/L -$437.07, source still
`AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT`.

---

## v3.25.0 addendum — crypto exposure / exit / unlock readiness (2026-06-09)

v3.25 adds three new shared modules and one investigation report:

- `docs/CRYPTO_SOL_LTC_POSITION_SIZING_INCIDENT.md` — partial
  root cause identified (laddering uncapped, per-symbol dollar cap
  missing, pending-order pre-check missing, recent-loss cooldown
  missing). Some details remain `CRYPTO_ROOT_CAUSE_REQUIRES_MORE_LOGS`.
- `shared/crypto_exposure_policy.py` — hard guards wired into
  `shared/alpaca_orders.py::place_crypto_order` via the new
  `_crypto_exposure_policy_gate`. Defense-in-depth on top of the
  existing `portfolio_risk` and `intraday_governor` gates. Fail-CLOSED
  for crypto buys.
- `shared/crypto_exit_policy.py` — every market crypto exit must
  carry a risk-side reason; dust exits require operator decision;
  precision rounding never rounds up; repeated close attempts within
  10 min are deduped.
- `shared/trading_unlock_readiness.py` — deterministic readiness
  verdict. Maximum permissible verdict in v3.25 is
  `SIGNAL_SHADOW_UNLOCK_READY`. Broker paper stays blocked.

Audit-bypass invariant `NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT`
remains `True`. AMD close source still
`AMD_CLOSE_SOURCE_REQUIRES_ALPACA_API_ORDER_DETAILS_OR_EXPORT`.
