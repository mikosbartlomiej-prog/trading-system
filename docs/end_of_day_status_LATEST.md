# End-of-Day System Status — Shadow Evidence Flow

Generated: 2026-06-15T11:30:00Z (Claude v3.24 FINAL-PHASE — runtime emit path enforcement + confidence-bearing rows activation)
HEAD: `e0c5eb1b77aa580a2e4309053bb1cfd46d2dd80e`

## TL;DR

The system is in `SHADOW_ONLY`, **NOT live-ready**. v3.24 enforces the
runtime emit path (`emit_signal_opportunity`) as the sole entry point
for ledger rows, bans direct `record_opportunity` calls outside an
allowlisted helper, ships the production confidence input builder
(`shared/confidence_input_builder.py`), shadow eligibility evaluator
(`shared/shadow_eligibility.py`), near-miss tracker, evidence quality
scorer, and runtime diagnostics.

v3.24 does NOT flip any safety flag, does NOT enable trading, does NOT
place any order. EDGE_GATE_ENABLED remains `false`. ALLOW_BROKER_PAPER
remains `false` (default). LLM stays advisory only. Canary stays
preflight-only.

## 1. Repo status

- **Branch:** `main`
- **HEAD:** `e0c5eb1b77aa580a2e4309053bb1cfd46d2dd80e`
- **Working tree:** v3.24 staged for commit
- **Worktrees:** single — `main` only

## 2. System status flags (canonical, hard-pinned)

| Flag                          | Value     | Notes                                  |
| ----------------------------- | --------- | -------------------------------------- |
| `EDGE_GATE_ENABLED`           | **false** | Hard-pinned. v3.24 does not flip this. |
| `ALLOW_BROKER_PAPER`          | **false** | Hard-pinned default.                   |
| `LIVE_TRADING_UNSUPPORTED`    | **true**  | CLI rejects `--mode live`.             |
| `NO_ORDER_PLACEMENT`          | **true**  | Reporters never call any order path.   |
| `BROKER_PAPER_CANARY_BLOCKED` | **true**  | Unlock gate has not flipped.           |

This LATEST refresh is a documentation pass. It does **NOT** flip any
flag, mutate any state file, or place any order.

## 3. v3.24 — what shipped today

- **Phase 2 (CORE-ENFORCEMENT)** — runtime emit path becomes mandatory.
  - `shared/confidence_input_builder.py` — production builder for the
    12-slot `ConfidenceInputs` envelope. Fail-soft defaults, per-slot
    reasons, completeness fraction, builder version stamp. Does NOT
    import `alpaca_orders`. Does NOT make network calls.
  - `shared/signal_emitter.py` persists `confidence_score` on every
    `emit_signal_opportunity` call.
  - Direct `record_opportunity` call sites outside `signal_emitter` are
    banned by lint test (`tests/test_no_direct_record_opportunity_v3240.py`).
    Legitimate diagnostic site in `scripts/run_shadow_evidence_cycle.py`
    is explicitly tagged `LEGACY_DIRECT_LEDGER_ALLOWED`.
- **Phase 3A (RUNTIME-DIAGNOSTICS)** — observability tokens.
  - `shared/monitor_runtime_diag.py` — frozen `DIAG_TOKENS` enum,
    fail-soft `record_diag(monitor, token, detail)`, JSONL writer to
    `learning-loop/monitor_runtime_diag/<date>.jsonl`.
  - `scripts/build_monitor_runtime_diagnostics_report.py` — 7-day rollup
    reporter (`docs/MONITOR_RUNTIME_DIAGNOSTICS.md`,
    `learning-loop/monitor_runtime_diag_status_latest.json`).
- **Phase 3B (STRATEGY-RECONCILE + GATE-DISTRIBUTION + NEAR-MISS)** —
  classification + blocker visibility.
  - `scripts/reconcile_strategy_sources.py` — 5-source ETAP 5
    reconciler, 9-status classification, safe auto-conversions only.
  - `scripts/gate_distribution_report.py` — blocker distribution across
    the 7-day ledger; surfaces top-N blockers + `shadow_eligible_count`.
  - `shared/near_miss_tracker.py` + `scripts/build_near_miss_report.py`
    — flags strategies that almost cleared every gate but did not.
- **Phase 3C (ELIGIBILITY + SIMULATION + EVIDENCE-QUALITY)** —
  shadow-only acceptance.
  - `shared/shadow_eligibility.py` — 10-value
    `ShadowEligibilityDecision` enum. Threshold: `confidence_score >=
    0.50 AND risk in {APPROVE, DETECTED} AND canary in {DRY_RUN_OK,
    READY_BUT_DEFERRED}`. Never imports `alpaca_orders`.
  - `shared/evidence_quality.py` + reporter — scores each shadow row on
    a quality label (HIGH / MEDIUM / LOW / REJECTED).

## 4. Real-market evidence — current count

| Counter | Value | Source |
|---|---|---|
| `real_market_opportunities_count` | **0** | `learning-loop/shadow_evidence/workflow_health_latest.json` |
| `halt_path_records_count` | 15 | same |
| `scaffold_no_market_data_records_count` | 5 | same |
| `completed_shadow_outcomes_count` | 0 | same |
| `first_real_market_record_seen` | false | `first_real_market_record_status.json` |

Largest current blocker (from `learning-loop/gate_distribution_latest.json`):
**`confidence_decision=NULL` (100% of 16,238 rows)** — emit path did not
run on those rows, monitor missed back-fill, or downstream consumer did
not persist the field. v3.24's enforcement closes this for all NEW rows
written post-deploy; pre-deploy rows remain NULL by design (no rewrites).

Secondary blockers in the same window:

- `risk_decision=REJECT` — 10,516 / 16,238 rows (64.8%)
- `risk_decision=NO_SIGNAL` — 5,424 / 16,238 rows (33.4%)
- `risk_decision=HALTED_BY_DRAWDOWN_GUARD` — 169 / 16,238 rows (1.0%)

## 5. Monitor emission status (latest reporter output)

Generated by `scripts/build_monitor_emission_status.py`. The crypto
pipeline remains the only producing channel; all equity / options / news
monitors are wired but not firing under the current regime.

Full report: `docs/MONITOR_EMISSION_STATUS.md`.

## 6. Active workflows (hard-pinned safety env)

| Workflow                              | Cron                  | Mode lock                              |
| ------------------------------------- | --------------------- | -------------------------------------- |
| `signal-shadow-evidence.yml` v3.27    | `35 13-19 * * 1-5`    | `--with-market-data`, observability-only |
| `shadow-evidence-cycle.yml` v3.21     | `30 22 * * 1-5`       | `--mode signal_only`                   |
| `paper-experiment-update.yml` v3.18   | `0 22 * * 1-5`        | "NEVER changes EDGE_GATE_ENABLED"      |
| `real-market-evidence-accelerator`    | `0 22 * * 1-5`        | hard-pins 7 broker/live flags = false  |

All 4 workflows hard-pin the canonical safety flags = `false`. Zero drift.

## 7. Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

## 8. Recommendation for next session

1. Watch the first 24h of post-v3.24 ledger rows to confirm
   `confidence_decision` field populates non-NULL on freshly-emitted
   rows (pre-deploy rows remain NULL by design).
2. Wire `scripts/check_heartbeat_freshness.py` +
   `scripts/check_evidence_throughput_sla.py` into a cron workflow
   (currently invoked only ad-hoc).
3. Investigate the high `risk_decision=REJECT` share (64.8%) — is the
   risk gate over-rejecting, or are signals genuinely thin in this
   regime?
4. Do NOT flip `EDGE_GATE_ENABLED`, do NOT set `ALLOW_BROKER_PAPER=true`,
   do NOT fabricate ledger entries, do NOT count near-miss as trade
   evidence.

---

_This document is observability-only. It does not change runtime
behavior, place any order, or modify safety flags._
