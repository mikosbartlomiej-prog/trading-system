# End-of-Day System Status — Shadow Evidence Flow

**Generated:** 2026-06-04 EoD (Claude Opus, after v3.21.0 + activation push)

## TL;DR

The system is in `SHADOW_EVIDENCE_FLOW_READY`. The workflow runs cron-driven
at 22:30 UTC weekdays in `signal_only` mode (hard-locked). **No real,
broker-paper, or shadow orders are being placed during the active session
— this is the expected paper/shadow-only contract**, not a bug.

The only operational gap is a **wiring gap**: monitors (price, options,
crypto, defense, twitter, reddit, geo, politician) do not yet call
`signal_opportunity_ledger.record_opportunity()`. That refactor is the
next iteration's scope. Until then, `signals_seen=0` is the honest
NO_EVIDENCE_FLOW state.

## 1. Repo status

- **Branch:** `main`
- **HEAD:** `5c52b20f` (origin/main in sync after pull)
- **Working tree:** clean (84 Cowork sidecar `* 2.*` files removed locally;
  all were untracked)
- **Worktrees:** single — `main` only (no stale worktrees)
- **Local branches:** single — `main` only (no stale post-merge branches)

## 2. Active workflows

| Workflow | Cron | Mode lock | Status |
| --- | --- | --- | --- |
| `shadow-evidence-cycle.yml` | `30 22 * * 1-5` (22:30 UTC) | `EVIDENCE_PRODUCTION_MODE=SIGNAL_ONLY` at workflow env level | Active |
| `paper-experiment-update.yml` | `0 22 * * 1-5` | "NEVER changes EDGE_GATE_ENABLED" docstring | Active |
| `pre-open-planner.yml` | `0 13 * * 1-5` | Read-only (daily bar fetch) | Active |

Workflow dispatch choices for `shadow-evidence-cycle`: `{signal_only,
shadow, broker}` — **no `live` choice exists**.

## 3. Sanity command results (just executed)

| Command | Result |
| --- | --- |
| `python3 -m scripts.run_shadow_evidence_cycle --dry-run --mode signal_only` | ✅ `mode=signal_only`, `strategies_seen=7`, `signals_seen=0` |
| `python3 -m scripts.run_shadow_evidence_cycle --dry-run --mode shadow` | ✅ `mode=shadow`, `signals_seen=0`, no fills |
| `python3 -m scripts.run_shadow_evidence_cycle --dry-run --mode live` | ✅ rejected by argparse |

## 4. Report status (just executed)

| Report | Output | Status |
| --- | --- | --- |
| `evidence_throughput_report.py` | `strategies analyzed: 0` | Fail-soft on empty ledger ✅ |
| `signal_density_report.py` | `records: 0` | Fail-soft on empty ledger ✅ |
| `operator_decision_pack.py` | `edge_gate_flip_now: False` | All invariants True ✅ |

## 5. Order placement diagnosis

**Operator question: "System nie zakłada zleceń mimo że sesja trwa — bug?"**

Technical answer: **NO, this is the contracted paper/shadow-only state.**

| Defense layer | Setting | Effect |
| --- | --- | --- |
| `EDGE_GATE_ENABLED` | default `false` (not in env) | EDGE_GATE flip blocked; no edge-promoted strategy can trigger |
| `ALPACA_LIVE_*` | not set | No live broker credentials wired |
| `ALLOW_BROKER_PAPER` | not set | Broker paper adapter returns DISABLED status |
| `EVIDENCE_PRODUCTION_MODE` | workflow env-locked `SIGNAL_ONLY` | Even cron run won't fill |
| `DEFAULT_DRY_RUN` (broker adapter) | True | Every call without explicit `dry_run=False` is a no-op |
| Argparse `--mode` choices | `{signal_only, shadow, broker}` | `--mode live` rejected at parser |
| `assert_paper_only(PAPER_BASE_URL)` | enforced | Any non-paper URL raises |
| `test_no_direct_sell_post_outside_safe_close` | AST lint | CI gate against naked sell POSTs |

So:

1. **Real/live orders not placed → GOOD / EXPECTED.** Multiple defenses
   in place; argparse + URL assert + AST lint all confirm.
2. **Broker paper orders not placed → EXPECTED.** Requires
   `ALLOW_BROKER_PAPER=true` AND `dry_run=False` AND paper credentials —
   none of which are set.
3. **Shadow fills not created → EXPECTED.** Runner saw 0 signals during
   today's cycle (`signals_seen=0`). Without signals, there's nothing
   to simulate filling.
4. **Opportunity ledger empty → WIRING GAP** (not a runtime bug). No
   monitor module (`price-monitor/monitor.py`, `options-monitor/monitor.py`,
   `crypto-monitor/monitor.py`, etc.) currently imports or calls
   `signal_opportunity_ledger.record_opportunity()`. The v3.20 ledger
   module was shipped before the monitor refactor. The shadow runner
   observes the strategy registry but does not invoke each strategy's
   signal generator (this is a design choice — runner does not
   duplicate monitor logic).

**Safe?** Yes. **Bug?** Not in runtime behavior. The wiring gap is a
known next-iteration item.

## 6. When does "0 signals" become a real problem?

- After 1-2 full cron cycles (≈ 2 weekdays) with still
  `current_daily_signal_rate=0`, the wiring gap should be investigated.
- Possible remediation paths:
  1. Add `signal_opportunity_ledger.record_opportunity(...)` calls in
     each monitor's signal-detection branch (mechanical refactor, ~5
     line-changes per monitor × 8 monitors).
  2. Add a `--invoke-strategies` flag to `run_shadow_evidence_cycle.py`
     that walks the registry and calls each strategy's
     `generate_signal()` directly (more intrusive — would duplicate
     monitor logic).
  3. Hybrid: instrument a shared `_emit_signal()` helper that monitors
     already call, and route through `record_opportunity()` there.

  **Recommendation:** Path #3 (single helper-level instrumentation)
  when prioritized.

## 7. Ledger status

| Ledger | Path | Files | Last write |
| --- | --- | --- | --- |
| Opportunity | `learning-loop/opportunity_ledger/` | 0 | never |
| Shadow | `learning-loop/shadow_ledger/` | 0 | never |
| Paper experiments | `learning-loop/paper_experiments/` | 0 | never |
| `current_daily_signal_rate` | — | **0** | — |
| `current_shadow_fill_rate` | — | **0** | — |
| `current_rejected_signal_rate` | — | **0** | — |
| `current_counterfactual_outcome_rate` | — | **0** | — |
| `estimated_days_to_n50` | — | ∞ (cannot extrapolate from 0) | — |

**Bottleneck:** monitor → opportunity ledger wiring (8 monitor modules
do not call `record_opportunity()`).

## 8. Safety invariants

| Setting | Required | Actual |
| --- | --- | --- |
| `EDGE_GATE_ENABLED` | False | False (default) ✅ |
| `ALLOW_BROKER_PAPER` | not "true" | unset ✅ |
| `LIVE_TRADING` | False | not set, blocked by `assert_paper_only` ✅ |
| Risk engine | final say | `risk_officer.evaluate_trade` enforced ✅ |
| Safe mode | functional | `shared/safe_mode.py` present, FSM intact ✅ |
| Kill-switch | functional | `shared/autonomy.py` invariants enforced ✅ |
| Paid services | none | scanned ✅ |

## 9. Recommendation for the next working day

**Choice: `WAIT_FOR_NEXT_CRON` for one more day, then
`INVESTIGATE_MONITOR_TO_OPPORTUNITY_LEDGER_WIRING` if still 0.**

Steps for the operator (or next Claude session):

1. Tomorrow 22:30 UTC: shadow-evidence-cycle.yml fires automatically.
2. Tomorrow 23:00 UTC: re-run `python3 scripts/operator_decision_pack.py`
   to check `current_daily_signal_rate`.
3. If still 0 after the first scheduled cron, prioritize the monitor
   → opportunity ledger wiring (Path #3 from §6 above).
4. **Do NOT** flip `EDGE_GATE_ENABLED=true`. Do NOT set
   `ALLOW_BROKER_PAPER=true`. Do NOT fabricate ledger entries.

---

*This document is read-only operational summary. It does not change
runtime behavior. Generated by the EoD hygiene pass on 2026-06-04.*
