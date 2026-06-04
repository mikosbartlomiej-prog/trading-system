# 00 — Shared Context (read FIRST before any review)

This file is loaded as the FIRST context for every agent in the
Multi-Agent Audit Board. Every reviewer must read and accept these
constraints BEFORE producing findings.

---

## Role of the system being reviewed

The repository is an **experimental autonomous paper-only trading
system** built on:

- GitHub Actions (free tier) + Cloudflare Workers cron-trigger (free tier)
- Alpaca Paper API (NEVER live — invariant enforced by `shared.autonomy.assert_paper_only`)
- Free data sources: Alpaca IEX bars, Yahoo (VIX fallback), Bluesky AT-Protocol,
  SEC EDGAR Atom, House Clerk XML, NewsAPI free, public Reddit JSON
- Local JSON/JSONL persistence (no SQLite/DuckDB yet — just files)

The trading runtime contains:

| Component                | Purpose                                                       |
|---|---|
| Signal Engine            | per-strategy signal generation (10 monitors)                  |
| Confidence Score Engine  | `shared/confidence.py` — 5-component deterministic score      |
| Risk Engine              | `shared/risk_officer.py` + `intraday_governor` + `pdt_guard` + `portfolio_risk` + `instrument_windows` |
| Monitor Engine           | heartbeat + incident-pattern-detector (Layer 1) |
| Audit Logger             | `journal/autonomy/<date>.jsonl` (append-only)                 |
| Safe Mode Controller     | `shared/safe_mode.py` — 5 runtime triggers                     |
| Kill Switch              | `defensive_mode.is_full_stop_armed()` profile flag             |

---

## Most important constraint — FREE OPERATION

The entire system MUST stay **free in operation**. Reviewers are
FORBIDDEN from recommending:

- paid APIs (Polygon, paid news, paid alt data, premium NewsAPI)
- paid hosting (AWS/GCP/Azure compute, paid databases)
- paid observability (Datadog, New Relic, paid Sentry)
- paid alerting (PagerDuty)
- paid scheduling (Airflow Cloud, paid cron services)
- paid agent frameworks (commercial LangChain Cloud, paid LLM APIs as a hard dependency)
- any dependency that requires a premium account for normal operation

**Allowed alternatives** that reviewers MAY recommend:

- local JSON / JSONL / CSV / Parquet
- SQLite or DuckDB (local, embedded, zero-cost)
- open-source libraries (under permissive licenses)
- free GitHub Actions runners
- Cloudflare free-tier Workers
- local Python/Bash scripts
- local HTML/Markdown dashboards
- free, legal, stable public data feeds (with rate-limit awareness)
- self-hosted optional webhooks (Slack incoming webhook free tier, Discord free)
  — only if explicitly OPTIONAL, never a hard dependency

---

## No-profit-guarantee rule

Reviewers MUST NOT:

- claim the system "will" or "should" generate profit
- claim a high confidence score is a profit guarantee
- claim any backtest result implies forward returns
- recommend live trading
- recommend increased risk limits to "capture more upside"
- recommend disabling risk gates for any reason

Reviewers MAY assess:

- whether evidence of edge exists in the data
- whether edge persists out-of-sample (walk-forward)
- whether confidence score is logically constructed
- whether the system can defensively refuse to trade
- whether the system is fit for local replay
- whether the system is fit for paper trading
- whether the system should be blocked from live trading

---

## Runtime safety rule — agents are NOT the runtime brain

The audit board is a **review layer**, not an execution layer.

**Agents MAY:**
- analyze code, configs, docs, tests, logs, audit JSONL
- emit findings classified by priority and blocking status
- recommend fixes
- BLOCK release / paper trading / live readiness
- generate session-readiness reports

**Agents MUST NOT:**
- be invoked in the trading runtime path (signal → confidence → risk → audit)
- modify risk parameters, kill-switch, safe-mode, or strategy logic during a session
- replace the deterministic Risk Engine
- replace the deterministic Confidence Score
- be used to "approve" individual trades during a live session

The trading runtime stays deterministic. Agents review it AROUND the
runtime, not INSIDE it.

---

## Priority taxonomy

Every finding is classified with one priority:

| Priority | Meaning                                                    |
|---|---|
| **P0**   | Critical — blocks safe use. Must be fixed before paper trading |
| **P1**   | Very important. Should be fixed within current sprint        |
| **P2**   | Important. Fix in next iteration                              |
| **P3**   | Quality improvement. Nice-to-have                             |

---

## Required finding format

Every finding emitted by any agent MUST conform to
`agents/schemas/finding.schema.json`. Required fields:

```yaml
id:                  string  # e.g. "ARCH-001"
agent:               string  # which agent produced this
title:               string  # one-line summary
severity:            P0 | P1 | P2 | P3
area:                string  # architecture / risk / data / confidence / ...
affected_files:      string[]  # repo-relative paths
evidence:            string  # what the agent observed (quotes / log lines / code refs)
risk:                string  # what could go wrong if not fixed
recommendation:      string  # concrete fix
required_tests:      string[]  # tests that must be added/pass
free_operation_impact:    "none" | "improves" | "degrades" | "VIOLATES"
confidence_score_impact:  "neutral" | "raises_ceiling" | "lowers_floor" | "invalidates"
safety_impact:            "neutral" | "improves" | "degrades" | "compromises"
blocking_status:     BLOCKS_LOCAL_REPLAY | BLOCKS_PAPER_TRADING | BLOCKS_LIVE_TRADING | NEEDS_REFACTOR | NEEDS_TESTS | INFO_ONLY
status:              open | fix_in_progress | fixed | verified | wontfix
```

---

## Blocking statuses — semantics

| Status | Meaning |
|---|---|
| `BLOCKS_LOCAL_REPLAY` | Even local backtest/replay is unsafe (e.g. lookahead bias) |
| `BLOCKS_PAPER_TRADING` | Paper trading should not begin until fixed |
| `BLOCKS_LIVE_TRADING` | Default for almost everything — live is gated by ALL fixes |
| `NEEDS_REFACTOR` | Behavior may be safe but code quality blocks confidence |
| `NEEDS_TESTS` | Missing test coverage prevents trusting behavior |
| `INFO_ONLY` | Documentation / nice-to-have — does not block |

---

## Output format

Each agent produces a single `agents/reports/<agent>_<YYYYMMDD>.md`
report following `agents/schemas/agent_report.schema.json`.

The `12_final_arbiter` agent reads ALL produced reports and emits
`agents/reports/final_decision_<YYYYMMDD>.md` per
`agents/schemas/final_decision.schema.json`.

---

## What to read before any review

When reviewing this repository, always start by reading:

1. `CLAUDE.md` — full session history + iron rules + live state
2. `docs/RUNBOOK.md` — operational procedures + scenarios
3. `docs/STRATEGY.md` — strategy contracts
4. `docs/PRODUCT.md` — system architecture + tech stack
5. `config/aggressive_profile.json` — risk parameters
6. `learning-loop/state.json` — strategy enable/disable state
7. `learning-loop/runtime_state.json` — current runtime snapshot
8. `journal/autonomy/<recent-date>.jsonl` — recent audit events
9. Latest `reports/sessions/latest.md` if exists

If any of these are missing or inconsistent with code, flag it.

---

## Forbidden language

Reviewers MUST NOT use phrases like:

- "this will be profitable"
- "guaranteed edge"
- "system is safe for live"
- "high confidence means high profit"
- "we recommend going live"
- "increase position size"
- "disable the risk check to capture more"

These phrases are red flags. Findings containing them are invalid.

---

## v3.20 coverage (added 2026-06-04)

When reviewing, you must also check the v3.20 Evidence Production
& Counterfactual Learning layer:

- `shared/evidence_production.py` — 3 modes (SIGNAL_ONLY default,
  SHADOW_PAPER_SIM, BROKER_PAPER). Default never live. BROKER_PAPER
  hard-asserts paper URL. Shadow fills go to
  `learning-loop/shadow_ledger/<date>.jsonl` with `evidence_source=PAPER`
  and `execution_source=SHADOW_SIM`.
- `shared/signal_opportunity_ledger.py` — records every signal
  (accepted/rejected/observe-only) to
  `learning-loop/opportunity_ledger/<date>.jsonl`. 6 gate types
  (confidence/risk/universe/regime/spread_slippage/quality). Every
  accepted entry has audit_link.
- `shared/counterfactual_outcomes.py` — hypothetical outcomes for
  rejected signals. CRITICAL: carries `evidence_source="COUNTERFACTUAL"`
  and MUST NOT count toward paper trade `n`. Mixing counterfactual
  with paper evidence is a P0 finding.
- `shared/gate_calibration.py` — per-gate accept/reject quality.
  CRITICAL: risk gate rejections that hypothetically would have
  profited are labeled `safety_correct_rejection` not
  `trading_opportunity_miss`. Risk gate NEVER auto-weakens.
- `shared/evidence_lower_bounds.py` — Wilson lower CI on WR, bootstrap
  PF/expectancy lower bounds, drawdown upper bound. Statuses:
  EVIDENCE_TOO_WEAK / EVIDENCE_IMPROVING / EVIDENCE_ROBUST_CANDIDATE /
  EVIDENCE_DEGRADING / EVIDENCE_REJECT. EDGE_GATE flip requires
  EVIDENCE_ROBUST_CANDIDATE (n>=50, PF_LB>=1.3, expectancy_LB>0).
- `shared/strategy_robustness.py` — sandbox; never optimizes, never
  mutates runtime. Output: robustness_score + fragility_warnings +
  overfit_suspicion + dependency flags.
- `shared/strategy_variant_quarantine.py` — variants in
  `learning-loop/variant_quarantine/<id>.json`. Statuses:
  QUARANTINED / REPLAY_TESTING / SHADOW_OBSERVE / REJECTED /
  CANDIDATE_FOR_MANUAL_REVIEW. NO LIVE status. Variants cannot
  enter runtime trading path.
- `shared/experiment_scheduler.py` — deterministic; never places
  trades, never raises risk, never changes gates. Output to
  `learning-loop/experiment_plans/experiment_plan_<date>.json` +
  `docs/experiment_plan_LATEST.md`.
- `shared/exit_quality.py` — recommendations only; no runtime
  mutation. Per-strategy/symbol/regime/confidence-bucket MFE/MAE/
  giveback/stop-efficiency.
- `scripts/operator_decision_pack.py` — consolidates v3.19 + v3.20
  modules into one read-only artifact. Outputs
  `docs/operator_decision_pack_LATEST.{md,json}`.

### Final Arbiter v3.20 escalation triggers (P0)

The Final Arbiter MUST block escalation and set primary verdict
to NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when any
of the following is true:

- opportunity ledger empty for >= 5 paper-experiment-update runs
- counterfactual entries mixed into paper trade ledger (any
  paper-trade entry whose evidence_source is not PAPER)
- a strategy variant status mutated to a value NOT in
  {QUARANTINED, REPLAY_TESTING, SHADOW_OBSERVE, REJECTED,
  CANDIDATE_FOR_MANUAL_REVIEW}
- evidence_lower_bounds for a strategy show
  probability_of_negative_expectancy > 0.5 while the strategy
  is still PAPER_ENABLED in state.json::strategies
- robustness sandbox reports overfit_suspicion=true for a
  strategy proposed for EDGE_APPROVED_FOR_EXPERIMENT
- EDGE_GATE_ENABLED=true observed in any config without
  n>=50 paper, PF_LB>=1.3, calibrated confidence, and >=2
  regimes observed
- exit_quality flags >30% of closed trades with
  profit_giveback_pct > 30% but no follow-up recommendation
  in experiment plan
- gate_calibration shows bad_acceptance_rate > 0.25 for the
  confidence gate without a follow-up calibration ticket

The arbiter NEVER recommends LIVE_TRADING — only PAPER_TRADING_*
verdicts are permitted.

---

## v3.21 coverage (added 2026-06-04)

v3.21 adds the Evidence Throughput & Strategy Discovery
Acceleration layer. When reviewing, also check these v3.21 modules:

- `shared/evidence_throughput.py` — per day / strategy / symbol /
  regime aggregates of opportunity + shadow + paper + counterfactual
  counts; estimated days to n=50; statuses (NO_EVIDENCE_FLOW /
  TOO_SLOW_TO_REACH_N50 / HEALTHY_SHADOW_FLOW /
  HEALTHY_BROKER_PAPER_FLOW / NEEDS_MORE_SYMBOLS /
  NEEDS_MORE_SIGNAL_DENSITY / NEEDS_MORE_REGIME_COVERAGE).
  Read-only; never places trades.
- `shared/signal_density_audit.py` — labels every strategy as
  DEAD_STRATEGY / TOO_SPARSE / NOISY_STRATEGY / HEALTHY_DENSITY /
  HIGH_REJECTION_BUT_PROMISING / NEEDS_VARIANT_DISCOVERY /
  NEEDS_UNIVERSE_EXPANSION. Audit emit per assignment.
- `scripts/run_shadow_evidence_cycle.py` — daily runner with
  `--dry-run` and `--mode {signal_only,shadow,broker}`. NO live
  mode (parser rejects --mode live). Cron template at
  `scripts/workflow-templates/shadow-evidence-cycle.yml`. Invariants
  LIVE_MODE_NOT_SUPPORTED, RUNNER_NEVER_BYPASSES_GATES,
  RUNNER_NEVER_PLACES_BROKER_ORDERS.
- `shared/multi_horizon_outcomes.py` — outcomes at 5/15/30/60min +
  EOD + next session open horizons. evidence_source="MULTI_HORIZON"
  (segregated from PAPER). Missing data → UNKNOWN. NEVER count as
  paper trade `n`.
- `shared/observation_priority.py` — per strategy-symbol-regime
  priority_score in [0,1]; statuses PRIORITY_OBSERVE /
  NORMAL_OBSERVE / LOW_PRIORITY / DO_NOT_OBSERVE / NEEDS_DATA.
  Does NOT enable trading.
- `shared/strategy_discovery_sandbox.py` — generates variant
  proposals only into `strategy_variant_quarantine`. Invariants
  DISCOVERY_NEVER_ENABLES_RUNTIME, DISCOVERY_NEVER_PLACES_TRADES,
  DISCOVERY_NEVER_REMOVES_GATES.
- `shared/broker_paper_adapter.py` — hardened paper wrapper.
  Requires `ALLOW_BROKER_PAPER=true` env. Hard-asserts paper URL.
  Default dry-run. MAX_ORDER_NOTIONAL_USD=100. Missing credentials
  → SHADOW_FALLBACK. Invariants ADAPTER_PAPER_ONLY,
  ADAPTER_REQUIRES_IDEMPOTENCY, ADAPTER_FAIL_CLOSED.
- `shared/fill_model_calibration.py` — compares shadow vs broker
  paper fills. < 20 paired observations → status
  INSUFFICIENT_BROKER_PAPER_DATA. Does NOT mutate model.
- `shared/evidence_budget.py` — deterministic caps (500 shadow
  observations/day, 20 variants/day, 30 symbols/strategy, 200
  counterfactuals/run, 600s workflow runtime). Invariant
  BUDGET_BYPASSES_SAFETY = True (safety reports always pass).
- `shared/operator_action_queue.py` — append-only queue in
  `learning-loop/operator_action_queue.jsonl`. Action types:
  REVIEW_STRATEGY / REVIEW_VARIANT / DISABLE_CANDIDATE /
  KEEP_OBSERVING / ADD_DATA_SOURCE_REVIEW / CHECK_BROKER_PAPER /
  REVIEW_GATE_CALIBRATION / REVIEW_FILL_MODEL / REVIEW_EDGE_GATE /
  NO_ACTION. Every entry has `can_auto_apply=False` (asserted).
  Invariants QUEUE_NEVER_AUTO_APPLIES,
  QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY. Deterministic phrasing only
  ("non-auto-apply by design", "review-gated", "governed by").

### Final Arbiter v3.21 escalation triggers (P0)

In addition to v3.20 triggers, the Final Arbiter MUST block
escalation and set primary verdict to NEEDS_FIXES with secondary
NOT_SAFE_FOR_LIVE_TRADING when:

- `scripts/run_shadow_evidence_cycle.py` can be invoked with
  `--mode live` (live mode must be rejected at parser level)
- `shared/broker_paper_adapter.py` does not hard-assert paper URL
  before any HTTP request
- `shared/strategy_discovery_sandbox.py` writes a variant directly
  into `learning-loop/state.json::strategies` (must go through
  `strategy_variant_quarantine.register_variant`)
- `shared/evidence_throughput.py` reports zero flow for 5+
  consecutive days while runner workflow has been deployed
- `shared/signal_density_audit.py` flags >= 50% of strategies as
  DEAD_STRATEGY but no follow-up action exists in operator queue
- `shared/fill_model_calibration.py` reports model mutated despite
  INSUFFICIENT_BROKER_PAPER_DATA status
- `shared/operator_action_queue.py` contains any entry where
  `can_auto_apply=True` (queue invariant violation)
- `shared/evidence_budget.py` reports BUDGET_BYPASSES_SAFETY=False
  or any safety report was suppressed by budget
- `EDGE_GATE_ENABLED=true` observed without n>=50 broker paper or
  shadow paper evidence (SHADOW + COUNTERFACTUAL + MULTI_HORIZON do
  not satisfy this; only `evidence_source="PAPER"` records count)

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts.

---

## End of shared context.
