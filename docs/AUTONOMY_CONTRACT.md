# Autonomy Contract — trading lifecycle

> **Last updated:** 2026-05-30 (v3.13.0). Adds: v3.12.0 confidence gate
> + safe_mode + heartbeat as runtime layers. Adds: Multi-Agent Audit
> Board (`agents/`) as REVIEW-ONLY layer explicitly outside the
> runtime decision path.

This is the formal contract that the trading system makes with the
operator. **There is no human approval step anywhere in the trading
lifecycle.** Every signal, every position, every error ends in a
deterministic decision, audited and (where possible) reversible.

## Invariants

1. **Paper trading only, forever.** `shared/autonomy.py::assert_paper_only`
   is the only allowed broker endpoint check. The only string it accepts
   is `https://paper-api.alpaca.markets`. Any other value raises
   `PaperOnlyViolation` and the autonomous flow STOPS.

2. **No FORBIDDEN states.** These strings (or any case-insensitive variant)
   may not appear in trading code paths:
   - APPROVAL_NEEDED
   - WAITING_FOR_HUMAN
   - MANUAL_CONFIRM_REQUIRED
   - PENDING_USER_APPROVAL
   - "please approve" / "awaiting operator"

   `tests/architecture_vnext/test_autonomy.py::TestRepoForbiddenScan`
   fails if any code outside `docs/`, `tests/architecture_vnext/`,
   `CLAUDE.md`, or `shared/autonomy.py` itself emits these.

3. **Every decision is one of these closed types** (see `DECISION_TYPES`
   in `shared/autonomy.py`):

   | Decision type | When it fires |
   |---|---|
   | `APPROVE_ENTRY` | Signal passed all gates; order placed |
   | `REJECT_ENTRY` | Signal failed a gate; no order, audit only |
   | `HOLD_POSITION` | Position checked, no action |
   | `CLOSE_POSITION` | TP/SL/trailing decided to close |
   | `PAUSE_STRATEGY` | Risk/failure rule fires |
   | `RESUME_STRATEGY` | Cooldown + health + risk-resolved checks pass |
   | `BLOCK_NEW_ENTRIES` | Aggregate block from health/risk |
   | `CLEANUP_STALE_ORDERS` | Stale order maintenance |
   | `RECREATE_EXIT_PLAN` | Position without exit found |
   | `EMERGENCY_CLOSE` | Hard loss / DTE / no exit / defensive mode |
   | `PANIC_CLOSE_OPTIONS` | Aggregate options risk BLOCKED |
   | `PATCH_APPROVE` / `PATCH_REJECT` / `PATCH_AUTO_MERGE` / `PATCH_ROLLBACK` | Code autonomy events |
   | `SAFE_MODE_ENTERED` / `SAFE_MODE_EXITED` | v3.12.0 — runtime safe_mode transitions |
   | `CONFIDENCE_BLOCK` / `CONFIDENCE_ALERT` | v3.12.0 — confidence gate decisions |

4. **Every decision is audited.** `shared/audit.py::write_audit_event`
   writes one JSONL row per decision under `journal/autonomy/`
   (trading) or `learning-loop/code-autonomy/history/` (code).

## Trading lifecycle (no approval anywhere) — v3.12.0+

```
Signal source (monitor)
    │
    ▼
[Gate 1] instrument_windows.can_trade_now → defer (REJECT_ENTRY) or pass
    │
    ▼
[Gate 2] portfolio_risk → reject (REJECT_ENTRY) or pass
    │
    ▼
[Gate 3] safe_mode.gate_new_entry → reject if active (v3.12.0)
    │
    ▼
[Gate 4] confidence.compute_confidence → BLOCK if total < 0.50 (v3.12.0)
    │     (5 components: data_quality / signal_strength /
    │      regime_alignment / system_health / risk_state)
    ▼
[Gate 5] risk_officer.evaluate_trade → reject or APPROVE
    │     (enforces ALL prior gate decisions + own checks)
    ▼
[Gate 6] pdt_guard.evaluate_order → defer / block / allow
    │
    ▼
[Order] Alpaca paper REST via safe_close (for SELL) or place_*_bracket (for BUY)
    │     v3.11.3: safe_close cancels OCO brackets BEFORE close (else 403)
    ▼
[Audit] make_decision + write_audit_event(kind="trading")
```

**Hard invariants:**
- High confidence CANNOT override risk_officer REJECT (verified by test)
- safe_mode active BLOCKS new entries (emergency closes always bypass)
- Every gate writes to `journal/autonomy/<date>.jsonl` audit JSONL

Position management runs in `exit-monitor` + `options-exit-monitor` +
`autonomous-remediation.yml`:

```
For each open position:
    if TP / SL / trailing / regime mismatch → CLOSE_POSITION
    else if emergency criteria → EMERGENCY_CLOSE (via emergency_engine)
    else if no exit plan → RECREATE_EXIT_PLAN (via remediation)
    else → HOLD_POSITION
```

No step asks the operator. The decisions are deterministic and audited.

## Emergency-close autonomy

`shared/emergency_engine.py::scan_emergency_conditions` returns a
deterministic list of positions matching:

- position loss ≤ HARD_LOSS_PCT (default -15%)
- option DTE ≤ NEAR_DTE_DAYS (default 5) AND loss ≤ DEEP_OPTION_LOSS_PCT (default -40%)
- position has no valid exit plan (no open opposite-side order)
- duplicate exit orders
- stale exit order > STALE_ORDER_HOURS (default 24h)
- defensive_mode_active in state

`execute_emergency_close` follows the canonical Alpaca paper flow:
1. Cancel any conflicting open orders on the symbol
2. DELETE /v2/positions/{symbol}
3. (No MARKET fallback — that gets HIGH_RISK rejected if proposed.)

Per-symbol rate limit: `MAX_EMERGENCY_ATTEMPTS_PER_DAY` (default 3).

## Options autonomy

| Outcome | When |
|---|---|
| `APPROVE_ENTRY` (order placed) | OPTIONS_ENABLED=true + all gates pass + liquidity OK + portfolio premium-at-risk OK |
| `REJECT_ENTRY` (audit email) | Any of the above fail |
| `EMERGENCY_CLOSE` | DTE ≤ 5 + deep loss, OR loss ≤ -15%, OR no exit plan |
| `PANIC_CLOSE_OPTIONS` | Aggregate options safety BLOCKED |

Subject line is now `[OPTIONS REJECTED]` (was `[OPTIONS APPROVAL NEEDED]`
— removed because the system never asks the operator).

## Strategy pause/resume autonomy

`shared/remediation.py::list_actions` + `validation.validate_adaptation`:

- **Auto-pause** allowed any time on:
  - 5+ consecutive losses
  - repeated API failures
  - state validation errors
  - excessive drawdown
- **Auto-resume** requires:
  - cooldown expired (default 24h)
  - `resume_min_health_ok_consecutive` consecutive OK health checks
  - the underlying risk condition resolved
  - bounded by `config/autonomy_bounds.json::strategy_enabled`

## Optional manual overrides (documentation only)

The system supports optional operator tools. These are **never required**
in the trading lifecycle; they exist for debug / manual investigation:

- `scripts/panic_close_options.py` (dry-run by default)
- `scripts/emergency_close_*.py` (historical, kept for audit)
- Cron `workflow_dispatch` triggers (manual one-off runs)

Crucially: the autonomy layer does NOT wait for these. If
`AUTONOMOUS_PANIC_CLOSE_OPTIONS=true` is set, the same script proceeds
without an operator-supplied `CONFIRM_PANIC_CLOSE_OPTIONS`.

## What the operator *can* do

- Read audit JSONL: `journal/autonomy/YYYY-MM-DD.jsonl`
- Disable individual workflows in GitHub Actions UI
- Set `OPTIONS_ENABLED=false` to kill new options entries
- Set `LLM_ENABLED=false` to kill LLM features (defaults to false anyway)
- Change `RISK_PROFILE` (tighter caps apply to all autonomy)
- Trigger optional one-off scripts above

## What the operator *cannot* do

The contract guarantees that the operator's input is **not needed** for
the system to keep operating safely. There is no inbox in which a
"please approve" mail can pile up.

---

## Multi-Agent Audit Board separation (v3.13.0)

The `agents/` directory contains 11 prompt-based area reviewers + Final
Arbiter. They are **REVIEW-ONLY** and explicitly OUTSIDE this autonomy
contract's decision path:

```
[ THIS AUTONOMY CONTRACT — runtime, deterministic, NO LLMs ]
  signal → safe_mode → confidence → risk → decision → audit → execution

[ AUDIT BOARD — offline, prompt-based, may use LLM ]
  reads:  code, configs, audit JSONL, reports, tests
  emits:  findings, blockers, final decision
  cannot: trade, modify risk, modify safe_mode, modify kill_switch
```

The Audit Board is invoked manually by the operator (or in CI as a
weekly gate). Its decisions are recommendations, not commands. The
runtime decision path is unaffected by Audit Board verdicts during
a session.

See `docs/AGENTS_DOCUMENTATION.md` and `agents/README.md` for details.

---

## v3.20 — Evidence Production layer (added 2026-06-04)

v3.20 adds a deterministic, free, paper-only evidence production
and counterfactual learning layer. The layer is **strictly outside
the runtime trading decision path** — runtime trading still goes
through the same gates (confidence + risk_officer + safe_mode +
kill_switch + portfolio_risk + risk_classification). v3.20 modules
either record observations or compute diagnostics; none of them can
mutate runtime state, place trades, raise risk limits, weaken gates,
or flip `EDGE_GATE_ENABLED`.

### Modules and invariants

| Module | What it does | Cannot do |
| --- | --- | --- |
| `shared/evidence_production.py` | 3 modes (SIGNAL_ONLY default, SHADOW_PAPER_SIM, BROKER_PAPER) for collecting fill-attempt records | Place live trades; default mode never trades; BROKER_PAPER hard-asserts paper URL |
| `shared/signal_opportunity_ledger.py` | Records EVERY signal (accept/reject/observe-only) with full gate breakdown | Place trades; modify gates |
| `shared/counterfactual_outcomes.py` | Computes hypothetical outcomes for rejected signals (24h/48h horizons) | Count toward paper trade `n`; outcome carries `evidence_source="COUNTERFACTUAL"` |
| `shared/gate_calibration.py` | Per-gate accept/reject quality, missed opportunity, protection value | Auto-weaken risk gate; risk-gate rejections labeled `safety_correct_rejection` |
| `shared/evidence_lower_bounds.py` | Wilson lower CI on WR, bootstrap PF/expectancy lower bounds, drawdown upper bound | Promote a strategy on mean alone; promotion requires `EVIDENCE_ROBUST_CANDIDATE` (n>=50 + PF_LB>=1.3 + expectancy_LB>0) |
| `shared/strategy_robustness.py` | Parameter sweeps, ablations, slippage sensitivity, drop-one tests | Optimize automatically; mutate runtime; `SANDBOX_NEVER_OPTIMIZES = SANDBOX_NEVER_MUTATES_RUNTIME = True` |
| `shared/strategy_variant_quarantine.py` | Variant registry in `learning-loop/variant_quarantine/<id>.json` | Have LIVE status; enter runtime trading path; auto-promote |
| `shared/experiment_scheduler.py` | Deterministic plan for next-cycle observations | Place trades; raise risk; change gates (`SCHEDULER_NEVER_PLACES_TRADES = SCHEDULER_NEVER_RAISES_RISK = SCHEDULER_NEVER_CHANGES_GATES = True`) |
| `shared/exit_quality.py` | Per-strategy/symbol/regime/confidence-bucket MFE/MAE/giveback/stop-efficiency analysis | Mutate exit rules; only emits recommendations |
| `scripts/operator_decision_pack.py` | One read-only consolidated artifact (`docs/operator_decision_pack_LATEST.{md,json}`) | Place trades; mutate state; recommend live trading |

### Evidence-source segregation rule

`shared/evidence_source.py::EvidenceSource` enum has three values:
`BACKTEST`, `REPLAY`, `PAPER`. v3.20 adds the string constant
`"COUNTERFACTUAL"` for counterfactual outcomes (does NOT modify the
enum, to avoid mixing into existing flows). The rule is invariant:

- A strategy cannot be promoted to `EDGE_APPROVED_FOR_EXPERIMENT`
  using BACKTEST, REPLAY, or COUNTERFACTUAL evidence.
- Only PAPER evidence (broker paper or shadow-sim with mode
  `SHADOW_PAPER_SIM`) counts toward `n >= 50`.
- Mixing any other evidence source into a paper trade record is a P0
  finding for the Audit Board (`agents/prompts/00_shared_context.md`
  Final Arbiter v3.20 escalation triggers).

### EDGE_GATE_ENABLED flip criteria (unchanged from v3.11)

`EDGE_GATE_ENABLED` may flip from default `false` to `true` ONLY when
**all** of these hold:

1. `n >= 50` paper trades closed for the strategy
2. Profit factor lower bound (bootstrap 5th percentile) `>= 1.3`
3. Expectancy lower bound `> 0`
4. Win rate Wilson lower bound `>= 0.40` (strategy-specific)
5. Confidence calibration buckets monotonic (per
   `shared/confidence_calibration.py`)
6. At least 2 distinct regimes observed
7. No `overfit_suspicion` flag from `shared/strategy_robustness.py`
8. No `EVIDENCE_DEGRADING` status from `shared/evidence_lower_bounds.py`
9. Operator review of `docs/operator_decision_pack_LATEST.md` and
   audit-board verdict `APPROVE_PAPER_TRADING_WITH_WARNINGS` or
   stronger

If any criterion fails, `EDGE_GATE_ENABLED` stays `false`. The
flip is operator-driven, not automatic.

### v3.20 invariants the contract enforces

- `live_trading_disabled = True` (assert_paper_only at every entry)
- `edge_gate_enabled = False` by default
- `no_promises_of_profit = True` (no docstring/markdown text promises
  edge or profit)
- `evidence_sources_segregated = True` (enforced by EvidenceSource
  enum + counterfactual marker)
- `agents_review_only = True` (audit board outputs reports, never
  mutates state)
- `no_paid_services = True` (deep E2E test scans for paid imports)

---

## v3.21 — Evidence Throughput & Strategy Discovery (added 2026-06-04)

v3.21 adds 9 new modules + 1 daily runner. The layer is strictly
outside the runtime trading decision path. None of these modules can
mutate runtime state, place trades, raise risk limits, weaken gates,
or flip `EDGE_GATE_ENABLED`.

### Modules and invariants

| Module | What it does | Cannot do |
| --- | --- | --- |
| `shared/evidence_throughput.py` | Per day/strategy/symbol/regime aggregate of opportunity + shadow + paper + counterfactual counts; estimated days to n=50 | Place trades; mutate runtime |
| `shared/signal_density_audit.py` | Per-strategy density status (DEAD/TOO_SPARSE/NOISY/HEALTHY_DENSITY/HIGH_REJECTION_BUT_PROMISING/NEEDS_VARIANT_DISCOVERY/NEEDS_UNIVERSE_EXPANSION) | Auto-disable a strategy; mutate state.json |
| `scripts/run_shadow_evidence_cycle.py` | Daily runner; modes `signal_only` (default) / `shadow` / `broker`; `--mode live` is rejected by argparse | Place real broker orders in shadow mode; bypass gates; bypass risk engine |
| `shared/multi_horizon_outcomes.py` | Outcomes at 5/15/30/60min + EOD + next session open | Count toward paper trade `n`; uses evidence_source="MULTI_HORIZON" segregated from PAPER |
| `shared/observation_priority.py` | Per strategy-symbol-regime priority score and status | Enable trading; no alpaca_orders import |
| `shared/strategy_discovery_sandbox.py` | Variant proposals only into `strategy_variant_quarantine` | Enable runtime; place trades; remove gates (3 invariant flags asserted) |
| `shared/broker_paper_adapter.py` | Hardened paper wrapper; requires `ALLOW_BROKER_PAPER=true`; dry-run default; MAX_ORDER_NOTIONAL_USD=100; idempotency_key required; fail-closed | Use live URL; raise notional cap; skip audit; submit without idempotency_key |
| `shared/fill_model_calibration.py` | Shadow vs broker paper fill comparison; < 20 paired observations → INSUFFICIENT_BROKER_PAPER_DATA | Mutate model on insufficient data; pretend calibration occurred |
| `shared/evidence_budget.py` | Deterministic caps (500 obs/day, 20 variants/day, 30 symbols/strategy, 200 counterfactuals/run, 600s runtime) | Suppress safety reports (BUDGET_BYPASSES_SAFETY=True) |
| `shared/operator_action_queue.py` | Action queue with deterministic phrasing | Auto-apply (QUEUE_NEVER_AUTO_APPLIES=True); risky actions are non-auto-apply by design |

### Evidence-source segregation rule (extended)

v3.21 introduces `evidence_source="MULTI_HORIZON"` as an additional
non-PAPER marker. Together with v3.20's COUNTERFACTUAL, the segregation
rules are:

- A strategy cannot be promoted to `EDGE_APPROVED_FOR_EXPERIMENT`
  using BACKTEST, REPLAY, COUNTERFACTUAL, or MULTI_HORIZON evidence.
- Only records with `evidence_source="PAPER"` (broker paper or
  shadow-sim under `SHADOW_PAPER_SIM`) count toward `n >= 50`.
- Mixing any other source into a paper trade record is a P0 finding.

### EDGE_GATE_ENABLED flip criteria (extended with v3.21 checks)

In addition to v3.20 criteria, v3.21 adds verification gates:

1. v3.20 list (1-9) unchanged
2. Signal density audit must show the strategy in
   HEALTHY_DENSITY or HIGH_REJECTION_BUT_PROMISING status
3. Evidence throughput must show HEALTHY_SHADOW_FLOW or
   HEALTHY_BROKER_PAPER_FLOW with `estimated_days_to_n50` already in
   the past
4. Fill model calibration must NOT be in
   INSUFFICIENT_BROKER_PAPER_DATA when BROKER_PAPER mode is used
5. Operator action queue must have a `REVIEW_EDGE_GATE` action that
   has been processed (reviewed via Multi-Agent Audit Board)

Even with all criteria met, the flip remains operator-driven, not
automatic.

### v3.21 invariants the contract enforces

- `evidence_runner_no_live_mode = True` (argparse rejects `--mode live`)
- `broker_paper_paper_only = True` (hard URL assert at adapter level)
- `discovery_quarantine_only = True` (no runtime variant writes)
- `multi_horizon_segregated = True` (separate evidence_source marker)
- `operator_queue_never_auto_applies = True` (per-entry can_auto_apply)
- `budget_bypasses_safety = True` (safety reports never throttled)
- `fill_model_no_silent_mutation = True` (insufficient → no model change)


---

## v3.22.0 invariants (2026-06-15)

v3.22 wires the signal-production spine end-to-end. It does NOT
flip any broker flag and it does NOT generate evidence by itself.
The invariants below are enforced by `tests/test_*_v3220.py`.

### Signal pipeline invariants

1. **`confidence_inputs` mandatory for entry.**
   Every `entry_capable=True` `SignalEvent` MUST carry a non-empty
   `confidence_inputs` dict. The emitter's validator blocks any
   entry-capable event with empty `confidence_inputs` and writes
   `status="BLOCKING_VALIDATION_ERROR"`. NO ledger row is produced
   for blocked events. (See
   `tests/test_entry_path_confidence_mandatory_v3220.py`.)

2. **`risk_inputs` mandatory for entry.** Same rule as
   `confidence_inputs` — entry-capable events without `risk_inputs`
   are blocked at validation.

3. **`pipeline` is a closed enum.** `monitor`, `shadow`, `paper`,
   `replay`, `backtest`. **`live` is intentionally absent** and the
   validator rejects it.

4. **`source_monitor` mandatory.** Every event must declare which
   monitor produced it. Used downstream for fault attribution.

5. **`evidence_source` mandatory.** One of `BACKTEST`, `REPLAY`,
   `PAPER`. The learning loop weights evidence by this field; a
   missing value is rejected.

### Canary preflight wired (no order placement)

6. **Canary preflight runs as a soft gate.** When a monitor proposes
   an entry, the v3.22 entry-gate stack
   (`shared/alpaca_orders.py::_v322_entry_gate_stack`) reads
   `learning-loop/broker_paper_canary/unlock_readiness_latest.json`
   and refuses the entry if `verdict` is not in
   `_V322_PREFLIGHT_OK_VERDICTS`. No order is placed because
   `ALLOW_BROKER_PAPER` remains `false` at the alpaca_orders level;
   the preflight rejection happens BEFORE that final gate. (See
   `tests/test_canary_preflight_wired_v3220.py`.)

7. **Canary remains preflight-only.** `BROKER_EXECUTION_ENABLED`,
   `ALLOW_BROKER_PAPER`, `EDGE_GATE_ENABLED`, `LIVE_TRADING`,
   `LIVE_ENABLED`, `GO_LIVE`, `LIVE_TRADING_ENABLED`,
   `OPERATOR_APPROVED_BROKER_PAPER_CANARY` all stay `false`. No
   order is ever placed by the canary in v3.22.

### Safe-mode auto-triggers on P01/P02/P13

8. **Incident → safe_mode coupling.** `scripts/incident_pattern_detector.py`
   detects P01 (state corruption), P02 (workflow loss), and P13
   (broker invariant breach) and writes a `safe_mode_trigger`
   marker. The safe-mode runtime
   (`shared/safe_mode.py`) reads the marker on next monitor entry
   and gates all NEW entries with `SAFE_MODE_ACTIVE`. Existing
   emergency closes continue. (See
   `tests/test_safe_mode_incident_trigger_v3220.py`.)

### Hard-safety invariants (unchanged from v3.21)

- LLM stays advisory only.
- Canary stays preflight-only.
- Live remains unsupported.
- `EDGE_GATE_ENABLED = false` (hard-pinned).
- `ALLOW_BROKER_PAPER = false` (hard-pinned).
- `BROKER_EXECUTION_ENABLED = false` (hard-pinned).
- `LIVE_TRADING` and the four siblings remain `false`.
- No paid APIs added. No LLM calls on the runtime trading path.

### System status

- System is NOT live-ready.
- System has NOT yet proven edge.
- Aggressive trading requires real evidence. v3.22 wires the
  production layer but does NOT generate evidence by itself.
- Confidence score without data is not proof of edge.

## v3.23 — observability layer additions (2026-06-15)

v3.23 ships six reporters in `scripts/`. All are observability-only;
none of them places, modifies, or cancels any order, and none of them
imports `alpaca_orders`. They consume the existing v3.20 ledger, the
v3.22 diagnostic tokens, and the runtime state files, then write JSON +
Markdown artefacts.

### Reporters added

1. `build_real_market_evidence_status.py` (Agent 3A) — surfaces the
   real-market-only opportunity counter + dominant blocker class.
   Output: `docs/REAL_MARKET_EVIDENCE_STATUS.md`,
   `learning-loop/shadow_evidence/real_market_evidence_status_latest.json`.
2. `confidence_reality_check_report.py` (Agent 3A) — compares declared
   confidence against actual ledger outcomes; READ-only over the
   ledger.
3. `strategy_coverage_report.py` (Agent 3A) — per-strategy coverage
   summary across the active universe.
4. `shadow_simulator.py` (Agent 3B) — pure simulator over historical
   ledger rows. Never calls the broker; never opens a paper trade.
   Produces no broker side-effects.
5. `outcome_tracker.py` (Agent 3B) — tracks shadow-outcome rows that
   already exist in the ledger. NOT a paper trade.
6. `build_monitor_emission_status.py` (Agent 3C) — per-monitor runtime
   emission summary. Output: `docs/MONITOR_EMISSION_STATUS.md`,
   `learning-loop/shadow_evidence/monitor_emission_status_latest.json`.

### v3.23 hard-safety invariants (re-asserted, unchanged)

- `EDGE_GATE_ENABLED = false` (hard-pinned).
- `ALLOW_BROKER_PAPER = false` (hard-pinned default).
- `BROKER_EXECUTION_ENABLED = false`.
- `LIVE_TRADING_UNSUPPORTED`.
- `NO_ORDER_PLACEMENT` for every v3.23 reporter.
- Live trading remains unsupported. LLM stays advisory only. Canary
  stays preflight-only.

HEAD at v3.23 LATEST refresh: `4b15542f95fad53584a283fdc8f8b168426a94cd`
(v3.23 commit follows the consolidated push).
