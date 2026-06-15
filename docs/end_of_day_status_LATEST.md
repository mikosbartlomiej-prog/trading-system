# End-of-Day System Status — Shadow Evidence Flow

Generated: 2026-06-15T11:52:45Z (Claude v3.25 FINAL-PHASE — production confidence verification + conditional shadow accumulation)
HEAD: `30dcf4e48a644122938d7dc089ee0293f1dc76c4`

## TL;DR

The system is in `SHADOW_ONLY`, **NOT live-ready**. v3.25 verifies that
v3.24's runtime-emit enforcement actually populated production rows with
confidence fields, refreshes the gate-distribution / strategy-reconcile /
near-miss / evidence-quality reporters, and provisions a dry-run shadow
accumulation harness + conditional outcome scheduling — all gated on
real eligibility, no fabrication.

v3.25 does NOT flip any safety flag, does NOT enable trading, does NOT
place any order, does NOT lower thresholds, does NOT add paid services,
does NOT introduce LLM into the runtime path. EDGE_GATE_ENABLED remains
`false`. ALLOW_BROKER_PAPER remains `false` (default). LLM stays advisory
only. Canary stays preflight-only.

## 1. Repo status

- **Branch:** `main`
- **HEAD:** `30dcf4e48a644122938d7dc089ee0293f1dc76c4`
- **Working tree:** v3.25 staged for commit
- **Worktrees:** single — `main` only

## 2. System status flags (canonical, hard-pinned)

| Flag                          | Value     | Notes                                  |
| ----------------------------- | --------- | -------------------------------------- |
| `EDGE_GATE_ENABLED`           | **false** | Hard-pinned. v3.25 does not flip this. |
| `ALLOW_BROKER_PAPER`          | **false** | Hard-pinned default.                   |
| `LIVE_TRADING_UNSUPPORTED`    | **true**  | CLI rejects `--mode live`.             |
| `NO_ORDER_PLACEMENT`          | **true**  | Reporters never call any order path.   |
| `BROKER_PAPER_CANARY_BLOCKED` | **true**  | Unlock gate has not flipped.           |

This LATEST refresh is a documentation pass. It does **NOT** flip any
flag, mutate any state file, or place any order.

## 3. v3.25 — what shipped today

- **Phase 2 (PRODUCTION-AUDIT)** — verify v3.24's emit-path enforcement
  actually populated rows with confidence fields.
  - `scripts/build_post_v324_audit_report.py` — scans all ledger files
    for rows after the v3.24 cutoff (`2026-06-15T11:35:05+00:00`),
    classifies each row as entry-capable vs observe-only, and reports
    the percentage with `confidence_score` populated.
  - **Finding:** 20 post-v3.24 rows scanned; all 20 carry the
    `OBSERVE_ONLY_SKIP` sentinel under `raw_signal.confidence_status`,
    so the top-level `confidence_score` field is intentionally NULL
    (observe-only by design). There are currently 0 entry-capable rows
    in the post-v3.24 window. Once entry-capable signals fire, the v3.24
    enforcement path will populate `confidence_score` on them. No
    backfilling of pre-v3.24 rows.
- **Phase 3A (MONITOR-RUNTIME-DIAG-SYNTHESIZED-VIEW)** — the native
  `monitor_runtime_diag/` directory is empty (writers wired but no
  invocations have completed during the window). The reporter falls
  back to a synthesized view derived from the 7-day ledger and shows
  `crypto-monitor` ACTIVE (16,358 rows) and all 9 other monitors STALE
  (0 rows). No fabrication.
- **Phase 3B (SHADOW-ELIGIBILITY-DISTRIBUTION + CONDITIONAL
  ACCUMULATION + CONDITIONAL OUTCOME SCHEDULING)** — entirely gated on
  real eligibility.
  - `scripts/build_shadow_eligibility_distribution_report.py` — token
    distribution across the 20 post-v3.24 rows: 0 ELIGIBLE / 20
    NOT_ELIGIBLE_OBSERVE_ONLY. No shadow fills created.
  - `scripts/run_shadow_accumulation_dry_run.py` — dry-run wrapper. No
    eligible rows, no shadow fills created. The script refuses to
    fabricate fills.
  - `scripts/schedule_outcomes_for_eligible_rows.py` — conditional
    outcome scheduler. 0 fills loaded → 0 outcomes scheduled with reason
    `no_shadow_fills_in_ledger_today`.
- **Phase 3C (STRATEGY-RECONCILE + NEAR-MISS + EVIDENCE-QUALITY
  REFRESH)** — re-runs of the v3.24 reporters on the current window.
  - **Strategy reconcile:** 30 strategies tracked. 2 ACTIVE_RUNTIME_SOURCE
    (crypto-momentum, crypto-oversold-bounce), 1 ACTIVE_SHADOW_SOURCE
    (momentum-long-loose), 16 ACTIVE_MONITOR_UNREGISTERED (wired but not
    registered), the rest UNKNOWN / DISABLED.
  - **Near-miss:** scanned 7-day window for strategies that almost
    cleared every gate but did not. No new auto-applies.
  - **Evidence quality:** refreshed quality scoring across the 7-day
    ledger window.

## 4. Real-market evidence — current count

| Counter | Value | Source |
|---|---|---|
| `real_market_opportunities_count` | **0** | `learning-loop/shadow_evidence/workflow_health_latest.json` |
| `halt_path_records_count` | 15 | same |
| `scaffold_no_market_data_records_count` | 5 | same |
| `completed_shadow_outcomes_count` | 0 | same |
| `first_real_market_record_seen` | false | `first_real_market_record_status.json` |

Largest current blocker (from `learning-loop/gate_distribution_latest.json`):
**`confidence_decision=NULL` (100% of 16,238 rows)** — pre-v3.24 rows
remain NULL by design (no rewrites). Post-v3.24 entry-capable rows will
populate `confidence_decision`; currently 0 entry-capable rows in the
window.

Secondary blockers in the same window:

- `risk_decision=REJECT` — 10,516 / 16,238 rows (64.8%)
- `risk_decision=NO_SIGNAL` — 5,424 / 16,238 rows (33.4%)
- `risk_decision=HALTED_BY_DRAWDOWN_GUARD` — 169 / 16,238 rows (1.0%)

## 5. Monitor emission status (latest reporter output)

Generated by `scripts/build_monitor_emission_status.py`. The crypto
pipeline remains the only producing channel; all equity / options / news
monitors are wired but not firing under the current regime. v3.25 does
not alter the regime or thresholds.

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

1. Watch for the first entry-capable post-v3.24 ledger rows; verify the
   `confidence_score` field populates non-NULL on those rows.
2. Investigate the 9 STALE monitors (all but crypto-monitor) — wired
   but no diagnostic tokens emitted. May indicate scheduled crons have
   not fired, or `record_diag()` calls are missing from monitor paths.
3. Investigate the high `risk_decision=REJECT` share (64.8%) — surface
   the top reject reasons for operator review.
4. Do NOT flip `EDGE_GATE_ENABLED`, do NOT set `ALLOW_BROKER_PAPER=true`,
   do NOT fabricate ledger entries, do NOT count near-miss as trade
   evidence, do NOT lower thresholds automatically.

---

_This document is observability-only. It does not change runtime
behavior, place any order, or modify safety flags._
