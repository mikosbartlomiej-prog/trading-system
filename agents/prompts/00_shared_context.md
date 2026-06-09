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

## v3.23 coverage (added 2026-06-08)

v3.23 repairs broker-state reconciliation + trade reconstruction
after the 2026-06-08 incident where state.json::cumulative.total_trades
was 0 despite 7 confirmed safe_close events for the 2026-06-04
equity positions and dashboard showed ETH/AVAX/SOL/LTC open while
local state was widely stale.

When reviewing, also check:

- `shared/position_reconciliation_status.py` — formal 16-status enum
  classifier. READ-ONLY. Distinguishes VERIFIED_OPEN vs STALE_LOCAL
  vs DASHBOARD_VERIFIED vs BROKER_SIDE_CLOSED.
- `shared/trade_reconstruction.py` — FIFO lot matcher with explicit
  TRADE_CLOSED_WITH_PNL / TRADE_CLOSED_PRICE_MISSING /
  TRADE_BROKER_SIDE_CLOSE_INFERRED / TRADE_PARTIAL_CLOSE /
  TRADE_UNMATCHED_OPEN / TRADE_UNMATCHED_CLOSE statuses.
  CRITICAL: NEVER_INVENTS_PRICES; missing fill prices yield
  TRADE_CLOSED_PRICE_MISSING, not fake P&L.
- `shared/crypto_precision.py` — classifies Alpaca 403 responses
  into CLOSE_BLOCKED_BY_PRECISION_ROUNDING etc. `round_qty_down()`
  NEVER rounds up. Repeated-failure deduper caps retries at 3.
- `shared/drawdown_attribution.py` — disambiguates drawdown source
  (REALIZED / UNREALIZED / BASELINE_STALE / UNKNOWN). NEVER resets
  baseline automatically. NEVER lowers drawdown threshold.
- `shared/silent_strategy_classification.py` — funnel-based status
  (NO_SIGNALS / SIGNALS_BUT_NO_ORDERS / ORDERS_BUT_NO_FILLS /
  FILLS_BUT_NO_RECONSTRUCTED_TRADES / RECONSTRUCTION_FAILED /
  ACTIVE_BUT_ANALYZER_STALE / TRULY_SILENT). CRITICAL:
  RECONSTRUCTION_FAILURE_BLOCKS_AUTO_DISABLE — a strategy with
  fills + closes but reconstruction = 0 must NOT be auto-disabled.
- `learning-loop/position_reconciliation/operator_dashboard_snapshot.json`
  is sanitized manual input from the operator; reviewers must
  treat it as `source=OPERATOR_DASHBOARD_MANUAL` and NOT as full
  Alpaca API truth.

### Final Arbiter v3.23 escalation triggers (P0)

The Final Arbiter MUST block escalation and set primary verdict to
NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when:

- analyzer still reports `cumulative_trades = 0` despite safe_close
  events present in audit JSONL
- local state conflicts with dashboard and no v3.23 reconciliation
  status is emitted
- AMD-style positions (no safe_close + dashboard NOT_open) are
  treated as VERIFIED_OPEN
- ETHUSD close loop emits 403 precision errors without classification
  via `crypto_precision.classify_precision_error`
- a strategy is marked auto-disabled despite `block_auto_disable=True`
  from `silent_strategy_classification`
- drawdown_guard threshold is lowered automatically
- starting_equity baseline is reset automatically (operator-only
  action)
- trade reconstruction returns fake P&L when fill prices are missing
  (must be `TRADE_CLOSED_PRICE_MISSING`, not invented number)

---

## v3.23.2 coverage (added 2026-06-08)

v3.23.2 extends v3.23.1 by reconstructing the 7 remaining
2026-06-04 equity trades (CRWD / NOW / QQQ / SPY / GLD / PANW / ORCL)
from operator-provided Order History, AND investigates the
safe-close audit gap exposed by v3.23.1's AMD reconciliation
(market sell_to_close via Alpaca `access_key` with NO matching
`safe_close` event in local audit JSONL).

When reviewing, also check:

- `learning-loop/position_reconciliation/manual_order_history_remaining_2026-06-04.json`
  — placeholder structure for 7 symbols. Every entry uses
  `data_quality = REQUIRES_OPERATOR_EXTRACTION` and every fill
  price is `null` until the operator transcribes the Order History
  rows. NEVER invents prices. The reconstruction helper
  `shared/trade_reconstruction.py::trade_from_manual_order_history`
  returns `TRADE_CLOSED_PRICE_MISSING` on missing fields — fake
  P&L is forbidden.
- `docs/OPERATOR_ORDER_HISTORY_EXTRACTION_CHECKLIST.md` — what the
  operator must transcribe per symbol. Does NOT ask for credentials,
  screenshots, or raw API dumps. Sanitized table values only.
- `shared/drawdown_attribution.py` extended with four new statuses:
  `DRAWDOWN_ATTRIBUTION_COMPLETE`, `DRAWDOWN_ATTRIBUTION_PARTIAL`,
  `DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY`,
  `DRAWDOWN_ATTRIBUTION_CONFLICT`. The helper
  `compute_partial_attribution()` returns `PARTIAL` while AMD is
  known and 7 symbols are unknown, `CONFLICT` when known realized
  P/L diverges from the observed drawdown by >30% or >$100. Baseline
  is NEVER reset automatically.
- `shared/audit_bypass_detector.py` — static classifier for every
  Python file that could submit sell/close orders. Six
  classifications: `SAFE_CLOSE_WRAPPED`, `AUDIT_EQUIVALENT_WRAPPED`,
  `READ_ONLY`, `ORDER_SUBMITTER_BYPASS`, `LEGACY_DANGEROUS`,
  `UNKNOWN_REQUIRES_REVIEW`. Three test-asserted invariants:
  `NO_DIRECT_MARKET_SELL_WITHOUT_AUDIT`,
  `NO_SELL_TO_CLOSE_WITHOUT_SAFE_CLOSE_OR_EQUIVALENT_AUDIT`,
  `ACCESS_KEY_ORDER_PATH_MUST_EMIT_AUDIT`. Allow-list contains the
  three legitimate sell submitters: `shared/alpaca_orders.py`,
  `options-monitor/monitor.py`, `shared/broker_paper_adapter.py`.
  v3.23.2 scan flags `scripts/emergency_close_20260602.py` and
  `scripts/emergency_close_20260603.py` as `LEGACY_DANGEROUS`.
- `shared/amd_close_source_search.py` — static, READ-ONLY search for
  evidence of the AMD close source in local logs. Self-reference
  filter excludes `learning-loop/position_reconciliation/`, `docs/`,
  and the search module itself (those mention the order_id but are
  not evidence). Two classifications: `AMD_CLOSE_SOURCE_IDENTIFIED`,
  `AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY`.
  v3.23.2 result is the latter — no local STRONG matches; followup
  requires GitHub Actions run logs OR Alpaca order-history API.
- `learning-loop/position_reconciliation/audit_bypass_investigation_latest.json`
  — committed real-repo scan output. `risk_level=HIGH`,
  `invariant_satisfied=False`, flagged 2 legacy scripts.
- `learning-loop/position_reconciliation/amd_close_source_search_latest.json`
  — committed search output. `classification` is the unknown enum,
  `confirmed_path = null`.

### Final Arbiter v3.23.2 escalation triggers (P0)

In addition to all v3.23 triggers, the Final Arbiter MUST block
escalation and set primary verdict to NEEDS_FIXES with secondary
NOT_SAFE_FOR_LIVE_TRADING when:

- a `MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT`
  finding remains unresolved (audit gap not closed)
- placeholder JSON entries are silently mutated to `COMPLETE` with
  invented fill prices (data_quality enum is not honored)
- a file outside `ALLOW_LIST` is classified `ORDER_SUBMITTER_BYPASS`
  or `LEGACY_DANGEROUS` and is left active in cron/workflow paths
- `compute_partial_attribution` is misused to fabricate
  `DRAWDOWN_ATTRIBUTION_COMPLETE` when ≥1 symbol is unknown
- the AMD close source is set to a `STRONG` confirmed path
  without an actual STRONG match in the real-repo scan
- baseline `state.json::cumulative.starting_equity` is reset
  silently to absorb the unattributed -$5,304 residual
- placeholder data flips `data_quality` to a non-placeholder enum
  without operator-supplied values
- legacy `emergency_close_*` scripts are re-introduced without
  being rewritten to call `safe_close()` or write an audit event

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts.

---

## v3.23.3 coverage (added 2026-06-08)

v3.23.3 quarantines the 2 legacy direct-order scripts surfaced by
v3.23.2's static scan and adds a forensic GitHub Actions
investigation report for the AMD 2026-06-05 close audit gap.

When reviewing, also check:

- `scripts/quarantined_legacy_order_scripts/` — the dedicated
  quarantine directory. Holds `emergency_close_20260602.py.disabled`
  and `emergency_close_20260603.py.disabled` plus a README that
  documents the rules (DO NOT RUN, DO NOT RESTORE, only call
  `safe_close()`). The `.py.disabled` extension makes the files inert
  to Python's runner and import system.
- `shared/audit_bypass_detector.py` — extended with a new
  classification `QUARANTINED_LEGACY_DANGEROUS` (now in
  `ALL_CLASSIFICATIONS`), a new module-level boolean invariant
  `NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT = True`, a
  `QUARANTINE_DIR_MARKER` constant, and an extended
  `detect_bypasses()` that scans `.py.disabled` files, tracks them
  under a new `quarantined_files` key, and excludes them from
  `flagged_files`. Real-repo scan now returns
  `invariant_satisfied = True`, `flagged_files = []`,
  `quarantined_files = [2 paths]`.
- `learning-loop/position_reconciliation/audit_bypass_investigation_latest.json`
  refreshed: `version=v3.23.3`, `risk_level` downgraded
  `HIGH → MEDIUM`, `flagged_count=0`, `quarantined_count=2`,
  invariant satisfied. Quarantine metadata recorded.
- `docs/AMD_CLOSE_SOURCE_INVESTIGATION.md` +
  `learning-loop/position_reconciliation/amd_close_source_gh_actions_investigation_latest.json`
  — read-only GitHub Actions forensic report. Investigated 200
  workflow runs in 2026-06-05T20-23Z window via `gh CLI`.
  **Decisive finding:** at 2026-06-05T21:35:45Z (the exact AMD
  order submission moment) ZERO workflows were active. Previous
  cron wave ended 21:31:29Z; next wave started 21:35:52Z — leaving
  a 4m16s gap. The order arrived 7 seconds before any next-wave
  workflow began. Classification: `AMD_CLOSE_SOURCE_NOT_FOUND_IN_GITHUB_ACTIONS`.
  Confirmed source still **None** — operator must pull the
  Alpaca order's `client_order_id` via the API.

### Final Arbiter v3.23.3 escalation triggers (P0)

In addition to all v3.23 + v3.23.2 triggers, the Final Arbiter MUST
block escalation and set primary verdict to NEEDS_FIXES with
secondary NOT_SAFE_FOR_LIVE_TRADING when:

- any `scripts/*.py` (NOT under
  `scripts/quarantined_legacy_order_scripts/`) contains
  `requests.post(/v2/orders)` AND a sell-side literal AND is NOT in
  `audit_bypass_detector.ALLOW_LIST`
- either quarantined `.py.disabled` file is reverted back to `.py`,
  moved out of `scripts/quarantined_legacy_order_scripts/`, or
  imported from any active code path
- `scripts/quarantined_legacy_order_scripts/` or either
  `.py.disabled` file is added to the audit-bypass `ALLOW_LIST`
  (silently legitimising the bypass)
- the AMD close source is set to a confirmed value without an
  Alpaca order-history `client_order_id` retrieval (no GitHub
  Actions evidence is now decisive against any of the GH-Actions
  candidate classifications)
- `NO_ACTIVE_LEGACY_DANGEROUS_ORDER_SCRIPT` flips to False in a
  later sprint without an accompanying remediation plan
- `learning-loop/position_reconciliation/audit_bypass_investigation_latest.json`
  shows `flagged_count > 0` after a future scan run
- the README in `scripts/quarantined_legacy_order_scripts/` is
  deleted or rewritten to remove the rules

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts.

---

## v3.25.0 coverage (added 2026-06-09)

v3.25 ships the crypto position-sizing / laddering / cooldown / exit
guards plus a deterministic unlock-readiness gate, in response to the
v3.24 reattribution that placed the bulk of the -$5,741 drawdown on
the SOLUSD + LTCUSD realized close cycle on 2026-06-06.

When reviewing, also check:

- `docs/CRYPTO_SOL_LTC_POSITION_SIZING_INCIDENT.md` +
  `learning-loop/position_reconciliation/crypto_sol_ltc_sizing_incident_latest.json`
  — root-cause investigation. Confirmed: laddering uncapped, per-symbol
  dollar cap missing, pending-order pre-check missing. Some details
  marked `CRYPTO_ROOT_CAUSE_REQUIRES_MORE_LOGS`.
- `shared/crypto_exposure_policy.py` — hard per-symbol +
  aggregate caps, laddering limit, cooldown, recent-loss cooldown,
  pending-order pre-check, drawdown-guard hard block. Defaults
  conservative (10% aggregate / 3% per symbol / 2 meaningful
  symbols / 1 buy per symbol per day / 240 min cooldown / 72 h
  recent-loss cooldown / $500 loss threshold). Wired into
  `place_crypto_order` via `_crypto_exposure_policy_gate`,
  fail-CLOSED for BUY.
- `shared/crypto_exit_policy.py` — closed enum of allowed exit
  reasons + narrower `MARKET_EXIT_ALLOWED_REASONS`. Dust exits
  require operator approval. Precision rounding NEVER rounds up.
  Repeated close attempts within 10 min are deduped.
- `shared/trading_unlock_readiness.py` — verdict ladder
  `TRADING_UNLOCK_BLOCKED` → `SIGNAL_SHADOW_UNLOCK_READY` →
  `BROKER_PAPER_CANARY_NOT_READY` → `BROKER_PAPER_CANARY_READY` →
  `LIVE_TRADING_NOT_SUPPORTED`. Maximum verdict in v3.25 is
  `SIGNAL_SHADOW_UNLOCK_READY`. Live trading is permanently marked
  unsupported.
- `docs/TRADING_UNLOCK_READINESS.md` — operator-facing guide.
- New tests pin: SOL/LTC 60% combined exposure blocked; repeated
  5-min buys blocked; per-symbol 3% cap; aggregate 10% cap; market
  exit requires risk reason; dust exit requires operator approval;
  precision never rounds up; broker paper requires evidence.

### Final Arbiter v3.25.0 escalation triggers (P0)

In addition to all v3.23.x + v3.24 triggers, the Final Arbiter MUST
block escalation and set primary verdict to NEEDS_FIXES with
secondary NOT_SAFE_FOR_LIVE_TRADING when:

- crypto **aggregate exposure cap is missing** or weakened past the
  v3.25 default (10% gross)
- crypto **per-symbol cap is missing** or weakened past the v3.25
  default (3% per symbol)
- repeated crypto buys can happen **every 5 minutes** (cooldown
  weakened below the v3.25 default 240 min)
- an **existing meaningful position does not block** a new buy of
  the same symbol
- a **pending order does not block** a duplicate buy of the same
  symbol
- the **drawdown guard does not block** new crypto buys when active
- a **recent realized crypto loss does not trigger cooldown** under
  default thresholds
- a **market exit lacks a structured reason** from `ALLOWED_EXIT_REASONS`
- **dust is auto-closed** without operator decision
- `evaluate_unlock_readiness` returns `BROKER_PAPER_CANARY_READY`
  **without** the four evidence thresholds met AND explicit operator
  approval
- `EDGE_GATE_ENABLED` is flipped to True
- `ALLOW_BROKER_PAPER` is enabled
- baseline `state.json::cumulative.starting_equity` is reset silently
- live trading is enabled in any form

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts.

---

## v3.26.0 coverage (added 2026-06-09)

v3.26 ships the signal/shadow evidence-collection scaffolding. The
unlock verdict ladder is unchanged; v3.26 only adds the operator
playbook + preflight + counters + dry-run collector + JSON Schema
that the v3.25 `trading_unlock_readiness` gate consumes.

When reviewing, also check:

- `shared/signal_shadow_preflight.py` — single-call preflight that
  emits 14 named confirmation tokens or a blocker list. Returns
  `SIGNAL_SHADOW_PREFLIGHT_PASS` only when every broker-execution
  flag is off, the audit-bypass invariant is True, the quarantined
  scripts remain `.py.disabled`, and the unlock verdict is
  `SIGNAL_SHADOW_UNLOCK_READY` or higher.
- `shared/shadow_evidence_counters.py` — monotonic counter store
  under `learning-loop/shadow_evidence/evidence_counters_latest.json`.
  `save_counters()` refuses to write if any of
  `broker_order_submitted_ever`, `live_trading_enabled`,
  `broker_paper_enabled` is True.
- `learning-loop/shadow_evidence/schema.json` — shadow decision JSON
  Schema. `broker_order_submitted` and `broker_execution_enabled`
  are pinned to `enum: [false]`; any future caller attempting to
  flip them must fail JSON validation.
- `scripts/run_signal_shadow_evidence_collection.py` — dry-run
  collector. Refuses to proceed if `ALLOW_BROKER_PAPER`,
  `EDGE_GATE_ENABLED`, `BROKER_EXECUTION_ENABLED`, `LIVE_TRADING`,
  `LIVE_ENABLED`, `GO_LIVE`, or `LIVE_TRADING_ENABLED` is truthy.
  Does NOT import `shared/alpaca_orders.py`.
- `docs/SIGNAL_SHADOW_EVIDENCE_COLLECTION_RUNBOOK.md` +
  `docs/SHADOW_EVIDENCE_PROGRESS.md` — operator-facing playbook +
  current progress.

### Final Arbiter v3.26.0 escalation triggers (P0)

In addition to all v3.23.x / v3.24 / v3.25 triggers, the Final
Arbiter MUST block escalation and set primary verdict to
NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when:

- the `shared/signal_shadow_preflight.py::run_preflight()` verdict
  is `SIGNAL_SHADOW_PREFLIGHT_BLOCKED` and a downstream operation
  ignores it
- `scripts/run_signal_shadow_evidence_collection.py` is modified to
  import a function from `shared/alpaca_orders.py` (or any other
  module that submits orders)
- the v3.26 collector ever returns `SHADOW_COLLECTION_PROCEEDING`
  while `ALLOW_BROKER_PAPER` / `EDGE_GATE_ENABLED` /
  `BROKER_EXECUTION_ENABLED` / `LIVE_TRADING` are truthy
- any shadow record persisted under
  `learning-loop/shadow_evidence/records_YYYY-MM-DD.jsonl` carries
  `broker_order_submitted=true` or `broker_execution_enabled=true`
- the `learning-loop/shadow_evidence/schema.json` is weakened to
  allow `broker_order_submitted=true` or
  `broker_execution_enabled=true`
- the counter file is mutated to inflate
  `normal_non_halt_opportunities_count` or
  `completed_shadow_outcomes_count` without matching evidence
  records
- the v3.25 `trading_unlock_readiness` thresholds (50 normal / 20
  outcomes / 0 audit bypass / 0 exposure breach) are weakened
- `EDGE_GATE_ENABLED` is flipped to True
- `ALLOW_BROKER_PAPER` is enabled
- baseline `state.json::cumulative.starting_equity` is reset
- live trading is enabled in any form

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts.

---

## v3.27.0 coverage (added 2026-06-09)

v3.27 automates the v3.26 signal/shadow evidence pipeline. The
verdict ladder is unchanged; v3.27 adds the missing real-market
data path so the v3.25 `trading_unlock_readiness` gate can
eventually advance toward `BROKER_PAPER_CANARY_READY` purely from
automated evidence — no manual collector runs.

When reviewing, also check:

- `shared/market_data_provider.py` — read-only Alpaca-data fetcher
  (`data.alpaca.markets`). Never imports `shared/alpaca_orders.py`.
  Returns `MarketSnapshot` with the 4-value `data_quality` enum
  (`REAL_MARKET_DATA` / `NO_MARKET_DATA` / `STALE_MARKET_DATA` /
  `PROVIDER_ERROR`). Fail-soft on missing creds / network errors —
  never fabricates price.
- `shared/shadow_opportunity_generator.py` — wraps the pure
  `backtest/strategies.py::*_signal_at` functions. Emits a record
  ONLY when the snapshot is `REAL_MARKET_DATA` AND daily bars are
  present. Applies the v3.25 crypto exposure policy + drawdown
  guard as `would_block` reasons (never blocks the broker — it
  just records that an order WOULD be blocked).
- `shared/shadow_outcome_resolver.py` + `scripts/resolve_shadow_outcomes.py`
  — sidecar outcome writer. Records are append-only to
  `learning-loop/shadow_evidence/outcomes_YYYY-MM-DD.jsonl`. Marks
  every outcome `SHADOW_OUTCOME` with
  `is_broker_realized_pnl=false`. Skips scaffold + halt-path
  records by `evidence_quality` filter.
- `scripts/update_shadow_evidence_progress.py` — rewrites the
  auto-progress section of `docs/SHADOW_EVIDENCE_PROGRESS.md`
  between markers `<!-- v3.27 auto-progress-start -->` and
  `<!-- v3.27 auto-progress-end -->` from live counters.
- `.github/workflows/signal-shadow-evidence.yml` — automation
  driver. Cron `35 13-19 * * 1-5`. Hard-pins all 7 broker-execution
  env flags `false` at workflow `env` level. Path allow-list at
  commit time enforces only
  `learning-loop/shadow_evidence/**`, `docs/SHADOW_EVIDENCE_PROGRESS.md`,
  `learning-loop/position_reconciliation/latest.json`.
- `scripts/audit_workflows.py::CONTENTS_WRITE_ALLOWLIST` — extended
  to include `signal-shadow-evidence.yml`.
- `shared/trading_unlock_readiness.py` — `UnlockReadinessInputs`
  gained `real_market_opportunities_count`; `_broker_paper_blockers`
  now reads it; `evaluate_from_current_repo_state` loads live
  counters from disk.

### v3.27 status tokens (added)

- `AUTOMATED_SHADOW_EVIDENCE_PIPELINE_READY`
- `REAL_MARKET_DATA_COLLECTION_AUTOMATED`
- `OUTCOME_RESOLUTION_AUTOMATED`

### Final Arbiter v3.27.0 escalation triggers (P0)

In addition to all v3.23.x / v3.24 / v3.25 / v3.26 triggers, the
Final Arbiter MUST block escalation and set primary verdict to
NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when:

- the v3.27 collector or resolver acquires an import of
  `shared/alpaca_orders.py`
- any record in `learning-loop/shadow_evidence/records_YYYY-MM-DD.jsonl`
  carries `broker_order_submitted=true` or `broker_execution_enabled=true`
- the `signal-shadow-evidence.yml` workflow drops an env hard-pin
  for ALLOW_BROKER_PAPER / EDGE_GATE_ENABLED / BROKER_EXECUTION_ENABLED
  / LIVE_TRADING / LIVE_ENABLED / GO_LIVE / LIVE_TRADING_ENABLED
- the workflow path allow-list is widened beyond
  `learning-loop/shadow_evidence/**`, `docs/SHADOW_EVIDENCE_PROGRESS.md`,
  and `learning-loop/position_reconciliation/latest.json`
- `signal-shadow-evidence.yml` is removed from
  `scripts/audit_workflows.py::CONTENTS_WRITE_ALLOWLIST`
- `real_market_opportunities_count` is incremented from a code path
  that does NOT also write a `REAL_MARKET_DATA` record to the day's
  JSONL
- a SHADOW outcome record is misrepresented as `is_broker_realized_pnl=true`
- the v3.25 thresholds (50 real opportunities / 20 outcomes / 0
  audit-bypass / 0 exposure breach) are weakened
- `EDGE_GATE_ENABLED` is flipped True
- `ALLOW_BROKER_PAPER` is enabled
- baseline `state.json::cumulative.starting_equity` is silently reset
- live trading is enabled in any form

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts.

---

## v3.27.1 coverage (added 2026-06-09)

v3.27.1 layers a deterministic **automated-pipeline healthcheck** on
top of the v3.27.0 cron driver, so an operator (or the audit board)
can answer a single question — *"is the automated shadow workflow
making progress toward the v3.25 50/20 thresholds, or is it stuck?"*
— from one health artifact.

When reviewing, also check:

- `shared/market_data_provider.py` — extended with **9 granular
  diagnostic tokens** (`ALL_STATUS_TOKENS` frozenset) that replace
  the v3.27.0 `HALT_PATH_ONLY` catch-all:
  `MARKET_DATA_CREDENTIALS_MISSING`, `MARKET_DATA_AUTH_FAILED`,
  `MARKET_DATA_PROVIDER_ERROR`, `MARKET_DATA_EMPTY_RESPONSE`,
  `MARKET_CLOSED_OR_NO_BARS`, `MARKET_DATA_STALE`,
  `INSUFFICIENT_BARS_FOR_SIGNAL`,
  `REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL`,
  `REAL_MARKET_SIGNAL_RECORDS_EMITTED`. Every quote return path
  attaches one token to the `MarketSnapshot.status_token` field; the
  9 modes are mutually exclusive. New helper
  `fetch_daily_bars_diagnostic(symbol)` returns
  `(bars, status_token)` and distinguishes the four failure modes
  the v3.27.0 `fetch_daily_bars` silently coalesced to `None`.
- `scripts/run_signal_shadow_evidence_collection.py` — extended with
  `per_symbol_diagnostics` aggregation. Every symbol the collector
  considers appears in the summary with `{symbol, status_token,
  reason}` so the audit board can see *which* symbols hit each
  failure mode in the most recent cron tick.
- `scripts/evaluate_automated_shadow_progress.py` — **NEW**
  pure-function verdict evaluator. Reads
  `evidence_counters_latest.json` + the most recent
  `workflow_health_latest.json` + caller-passed workflow-run /
  collector / resolver / secrets statuses; emits one of 6 verdicts:
  `AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET`,
  `AUTOMATED_PIPELINE_HEALTHY_COLLECTING_REAL_MARKET_DATA`,
  `AUTOMATED_PIPELINE_BLOCKED_NO_SECRETS`,
  `AUTOMATED_PIPELINE_BLOCKED_PROVIDER_ERROR`,
  `AUTOMATED_PIPELINE_BLOCKED_WORKFLOW_FAILURE`,
  `AUTOMATED_PIPELINE_BLOCKED_SCHEMA_OR_COUNTER_ERROR`. Standing
  markers `BROKER_PAPER_CANARY_STILL_BLOCKED` and
  `LIVE_TRADING_UNSUPPORTED` are returned with every verdict —
  there is NO verdict that unblocks broker paper or live trading.
  The script refuses (exit 1) if any of
  `ALLOW_BROKER_PAPER` / `EDGE_GATE_ENABLED` /
  `BROKER_EXECUTION_ENABLED` / `LIVE_TRADING` / `LIVE_ENABLED` /
  `GO_LIVE` / `LIVE_TRADING_ENABLED` is truthy. NEVER imports the
  broker-orders module.
- `learning-loop/shadow_evidence/workflow_health_latest.json` —
  **NEW** auto-refreshed health artifact. Contains: verdict,
  rationale lines, standing markers, last workflow run id /
  conclusion, last collector / resolver statuses, secrets status,
  diagnostic_token_counts, counters_snapshot, safety block.
- `docs/AUTOMATED_SHADOW_WORKFLOW_HEALTH.md` — **NEW** human-view
  mirror of the JSON. Generated by the evaluator. Path is in the
  `signal-shadow-evidence.yml` allow-list.
- `.github/workflows/signal-shadow-evidence.yml` — extended with an
  `Evaluate automated pipeline health` step (calls the new
  evaluator with `--workflow-run-id`, `--workflow-run-conclusion`,
  `--collector-status`, `--resolver-status`,
  `--secrets-status SECRETS_AVAILABLE`). Commit allow-list
  extended to include
  `docs/AUTOMATED_SHADOW_WORKFLOW_HEALTH.md`. Hard-pinned
  broker-execution env flags are unchanged.

### v3.27.1 status tokens (added)

- 6 verdicts of the new evaluator (see list above).
- 9 diagnostic status tokens in `ALL_STATUS_TOKENS`.

### Final Arbiter v3.27.1 escalation triggers (P0)

In addition to all v3.23.x / v3.24 / v3.25 / v3.26 / v3.27.0
triggers, the Final Arbiter MUST block escalation and set primary
verdict to NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when:

- the v3.27.1 evaluator drops the
  `BROKER_PAPER_CANARY_STILL_BLOCKED` or `LIVE_TRADING_UNSUPPORTED`
  standing markers from its emitted `workflow_health_latest.json`
- `evaluate_automated_shadow_progress.py` returns a verdict
  outside its enum, or returns ANY verdict while a
  broker-execution env flag is truthy (the script must refuse first)
- `evaluate_automated_shadow_progress.py` acquires an import of
  the broker-orders module
- `workflow_health_latest.json` records a verdict of
  `AUTOMATED_PIPELINE_HEALTHY_COLLECTING_REAL_MARKET_DATA` while
  `real_market_opportunities_count == 0` (verdict / counter
  mismatch)
- the collector emits a `per_symbol_diagnostics` entry whose
  `status_token` is not in `ALL_STATUS_TOKENS` (introduction of an
  unaudited diagnostic mode)
- `MARKET_DATA_AUTH_FAILED` count is >0 for more than 2
  consecutive successful workflow runs without an operator-visible
  alert (silent auth outage — credentials may have been rotated
  away)
- the `signal-shadow-evidence.yml` workflow drops the
  `Evaluate automated pipeline health` step
- the v3.27.1 evaluator's refusal list shrinks (any of the 7 env
  flags removed from the truthy-refusal check)

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts. The v3.27.1 verdict
`AUTOMATED_PIPELINE_HEALTHY_COLLECTING_REAL_MARKET_DATA` does NOT
unblock the canary — the canary remains gated on the v3.25
50 real opportunities / 20 outcomes / explicit operator approval.

---

## v3.27.2 coverage (added 2026-06-09)

v3.27.1 answered *"is this tick healthy?"* — v3.27.2 answers
*"are we making PROGRESS across multiple ticks, or is the
pipeline silently stuck?"* by stacking a multi-run progress
monitor on top of the per-tick evaluator.

When reviewing, also check:

- `scripts/monitor_automated_shadow_progress.py` — **NEW**
  multi-run progress monitor. Appends the latest
  `workflow_health_latest.json` to
  `learning-loop/shadow_evidence/workflow_health_history.jsonl`
  (append-only, idempotent on
  `(workflow_run_id, generated_at_iso)`); reads the rolling
  history; applies an 8-status rule matrix
  (`ALL_PROGRESS_STATUSES`): `AUTOMATED_EVIDENCE_PROGRESSING`,
  `AUTOMATED_EVIDENCE_HEALTHY_BUT_NO_SIGNALS_YET`,
  `AUTOMATED_EVIDENCE_STUCK_NO_MARKET_DATA`,
  `AUTOMATED_EVIDENCE_STUCK_INSUFFICIENT_BARS`,
  `AUTOMATED_EVIDENCE_STUCK_AUTH`,
  `AUTOMATED_EVIDENCE_STUCK_PROVIDER_ERROR`,
  `AUTOMATED_EVIDENCE_STUCK_GENERATOR_TOO_RESTRICTIVE`,
  `AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS`. Standing markers
  `BROKER_PAPER_CANARY_STILL_BLOCKED` and
  `LIVE_TRADING_UNSUPPORTED` are returned with every status —
  no status unblocks broker paper or live trading. Refuses
  (exit 1) on any truthy broker-execution env flag. NEVER
  imports the broker-orders module.
- `learning-loop/shadow_evidence/workflow_health_history.jsonl` —
  **NEW** rolling append-only history of every workflow health
  snapshot. Records `{appended_at_iso, workflow_run_id,
  workflow_conclusion, collector_status, resolver_status,
  verdict, diagnostic_token_counts, counters_snapshot,
  standing_markers, safety}`. Idempotent on
  `(workflow_run_id, generated_at_iso)`. The monitor never
  rewrites this file — only appends.
- `learning-loop/shadow_evidence/first_real_market_record_status.json` —
  **NEW** operator-visible flag artifact. Tells the operator
  whether ANY shadow record with
  `evidence_quality == REAL_MARKET_DATA` exists on disk. Stays
  `false` until a real-market record actually lands; scaffold
  / halt-path records do NOT flip it. Includes
  `current_waiting_reason` (the progress status),
  `diagnostic_dominant_token`, `runs_observed`,
  `successful_runs_observed`, and `next_expected_automation_window`
  for at-a-glance debug.
- `scripts/run_signal_shadow_evidence_collection.py` — extended
  with `SHADOW_MARKET_DATA_LOOKBACK_DAYS` env override (default
  `40`). The collector pins a `max(22, ...)` floor in source so
  the env override CANNOT weaken the 22-bar ATR safety floor.
  A test (`tests/test_shadow_lookback_v3272.py::test_collector_clamp_uses_max_22`)
  fails CI if the floor is removed.
- `.github/workflows/signal-shadow-evidence.yml` — extended with
  a `Monitor multi-run automated evidence progress (v3.27.2)`
  step that runs after the evaluator. The commit allow-list
  (existing umbrella `learning-loop/shadow_evidence/*` pattern)
  already covers the new history JSONL and status JSON; no
  allow-list widening is needed.

### v3.27.2 status tokens (added)

- 8 progress statuses of the new monitor (see list above).

### v3.27.2 deferred (deliberate non-change)

- `OBSERVATION_RECORD` / `NO_TRADE_OBSERVATION` second record
  type is **deferred to v3.28**. Introducing a new
  `evidence_quality` enum value touches the v3.27.0/v3.27.1
  record contracts + the readiness gate semantics. The
  conservative path — wait until repeated
  `STUCK_GENERATOR_TOO_RESTRICTIVE` verdicts demonstrate
  concrete demand — keeps v3.27.2 a zero-schema-risk delivery.

### Final Arbiter v3.27.2 escalation triggers (P0)

In addition to all v3.23.x / v3.24 / v3.25 / v3.26 / v3.27.0 /
v3.27.1 triggers, the Final Arbiter MUST block escalation and set
primary verdict to NEEDS_FIXES with secondary
NOT_SAFE_FOR_LIVE_TRADING when:

- the v3.27.2 monitor drops the
  `BROKER_PAPER_CANARY_STILL_BLOCKED` or
  `LIVE_TRADING_UNSUPPORTED` standing markers
- the v3.27.2 monitor acquires an import of the broker-orders
  module
- the monitor returns a progress status outside
  `ALL_PROGRESS_STATUSES`, or returns ANY status while a
  broker-execution env flag is truthy (the monitor must refuse
  first with exit 1)
- `workflow_health_history.jsonl` is rewritten in place (the
  contract is append-only) — verified by stat / size monotonicity
- `first_real_market_record_status.json::first_real_market_record_seen`
  flips `true` without a matching shadow record carrying
  `evidence_quality == REAL_MARKET_DATA` on disk
- `first_real_market_record_status.json::safety.broker_paper_canary_still_blocked`
  is ever serialised as `false`
- the workflow drops the
  `Monitor multi-run automated evidence progress (v3.27.2)` step
- the `SHADOW_MARKET_DATA_LOOKBACK_DAYS` clamp's 22-bar floor is
  removed from the collector source
- the monitor's refusal list shrinks (any of the 7 env flags
  removed from the truthy-refusal check)
- the spec calls a no-signal verdict a failure with fewer than
  3 consecutive `REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL`-dominant
  runs (the 3-run threshold is part of the conservative
  contract — weakening it would amount to opportunistic
  signal-fabrication pressure on the operator)

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts. The v3.27.2 status
`AUTOMATED_EVIDENCE_PROGRESSING` does NOT unblock the canary —
the canary remains gated on the v3.25 50 real opportunities /
20 outcomes / explicit operator approval, AND the v3.27.1 standing
markers MUST be present in every monitor invocation.

---

## v3.27.3 coverage (added 2026-06-09)

v3.27.x added autonomous shadow-evidence visibility. v3.27.3 closes an
**operational** issue introduced as a side-effect of that growth:
`shared/notify.py`'s `_CRITICAL_MARKERS` ships `[INCIDENT-CRITICAL]`
through the SMTP fast-path, and the `scripts/incident_pattern_detector.py`
cron firing every 5 min could (and did) deliver hundreds of identical
`[INCIDENT-CRITICAL]` emails per hour during an incident loop. v3.27.3
layers a deterministic flood guard in front of the SMTP path so the
**first unique critical incident still reaches the operator
immediately**, while duplicates within a configurable cooldown are
routed to a digest. Every decision is appended to an audit JSONL — no
critical event is ever silently dropped.

When reviewing, also check:

- `shared/notification_flood_guard.py` — **NEW** pure-function flood
  guard. Public surface: `normalize_subject`, `incident_fingerprint`,
  `should_send_immediate`, `apply_verdict`, `evaluate_and_record`,
  `load_flood_state`, `save_flood_state`, `record_notification_decision`.
  Six verdicts (`ALL_FLOOD_VERDICTS`):
  `FLOOD_SEND_FIRST` / `FLOOD_SEND_ESCALATION` / `FLOOD_DIGEST` /
  `FLOOD_BLOCK_HOURLY_CAP` / `FLOOD_BLOCK_DAILY_CAP` /
  `FLOOD_BYPASS_DISABLED`. NEVER submits orders. NEVER imports the
  broker-orders module. NEVER deletes existing audit or digest files.
  NEVER silently drops a critical event — even capped events are
  appended to the digest JSONL. Subject + body previews stored in the
  audit JSONL redact any 16+ char uppercase-alphanumeric token
  (Alpaca-key shape).
- `shared/notify.py::send_email` — extended with `_consult_flood_guard`
  helper. Insertion point is AFTER the v3.13 classifier resolves to
  `send` — so `off` / `suppress` / `digest` short-circuits are
  preserved. The flood guard only gates flood-guarded prefixes
  (default: `[INCIDENT-CRITICAL]`); all other subjects fall through
  to SMTP. Sending verdicts (`FLOOD_SEND_FIRST` /
  `FLOOD_SEND_ESCALATION` / `FLOOD_BYPASS_DISABLED`) proceed to SMTP.
  Digest verdicts also call the standard `_append_to_digest` so the
  operator can still see digested events through the existing digest
  pipeline.
- `scripts/send_incident_digest.py` — **NEW** daily digest aggregator.
  Reads the v3.13 digest JSONL + the v3.27.3 audit JSONL, groups by
  fingerprint, renders ONE email
  (`[INCIDENT-DIGEST] YYYY-MM-DD — N unique, M immediate, K digested`).
  Sends AT MOST ONE email per invocation regardless of input size.
  Refuses (exit 1) on any truthy broker-execution env flag. NEVER
  imports the broker-orders module. Modes: default = send today's
  digest; `--only-if-events` = quiet exit when nothing to send;
  `--print-only` = render to stdout without sending; `--date YYYY-MM-DD`
  = aggregate a specific date.
- `docs/NOTIFICATION_POLICY.md` — **NEW** comprehensive doc covering
  the layered routing (NOTIFY_MODE → v3.13 classifier → flood guard),
  the six flood-guard verdicts, fingerprinting algorithm, env knobs,
  always-send markers, on-disk artefacts, operator persona tuning,
  hard safety invariants, and test coverage.
- `tests/test_notify_policy_v3131.py::_reload_notify` — extended to
  isolate the flood-guard state directory (`NOTIFY_FLOOD_STATE_DIR` +
  `NOTIFY_DIGEST_DIR`) per call so the legacy v3.13 baseline does not
  collide with on-repo state files written by production runs.

### v3.27.3 status tokens (added)

- 6 flood-guard verdicts (`FLOOD_SEND_FIRST` / `FLOOD_SEND_ESCALATION`
  / `FLOOD_DIGEST` / `FLOOD_BLOCK_HOURLY_CAP` / `FLOOD_BLOCK_DAILY_CAP`
  / `FLOOD_BYPASS_DISABLED`).

### v3.27.3 default policy

| Knob | Default | Purpose |
|---|---|---|
| `NOTIFY_FLOOD_GUARD_ENABLED` | `true` | Master switch. `false` still writes audit JSONL but bypasses gating. |
| `INCIDENT_CRITICAL_IMMEDIATE_FIRST` | `true` | First occurrence sends immediately. |
| `INCIDENT_CRITICAL_COOLDOWN_MINUTES` | `60` | Duplicates within window → digest. |
| `INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_HOUR` | `3` | Hourly safety cap. |
| `INCIDENT_CRITICAL_MAX_IMMEDIATE_PER_DAY` | `10` | Daily safety cap. |
| `NOTIFY_ALWAYS_SEND_MARKERS` | `[KILL-SWITCH,[FAIL` | Bypass cooldown + caps. |
| `NOTIFY_ALWAYS_DIGEST_MARKERS` | (empty) | Force-digest list. |

### Final Arbiter v3.27.3 escalation triggers (P0)

In addition to all v3.23.x / v3.24 / v3.25 / v3.26 / v3.27.0 /
v3.27.1 / v3.27.2 triggers, the Final Arbiter MUST block escalation
and set primary verdict to NEEDS_FIXES with secondary
NOT_SAFE_FOR_LIVE_TRADING when:

- the v3.27.3 flood guard returns a verdict outside
  `ALL_FLOOD_VERDICTS`
- `shared/notification_flood_guard.py` acquires an import of the
  broker-orders module
- `scripts/send_incident_digest.py` acquires an import of the
  broker-orders module
- the digest script sends more than one email per invocation
- a `FLOOD_DIGEST` / `FLOOD_BLOCK_*` verdict is emitted without a
  corresponding append to the digest JSONL (silent drop)
- the audit JSONL is rewritten in place (the contract is append-only)
  — verified by stat / size monotonicity
- the always-send default list shrinks (any of `[KILL-SWITCH*`,
  `[FAIL*` removed from default routing)
- the `_consult_flood_guard` wire-in is moved BEFORE the v3.13
  classifier (the classifier is the authoritative first gate)
- the digest script's refusal list shrinks (any of the 7 broker
  env flags removed from the truthy-refusal check)
- audit JSONL preview fields contain a 20+ char uppercase-alphanumeric
  run (potential secret leak — the redactor was bypassed)

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts. v3.27.3 changes notification ROUTING only;
no trading behaviour, broker state, or readiness gate is touched.

---

## v3.28 coverage (added 2026-06-09)

v3.27.x layered automated shadow-evidence visibility + notification
flood guard. v3.28 adds the missing layer: a **cloud-run LLM advisory
mesh** that can review, challenge, recommend, propose-veto, and
propose-config-change across the whole trading process — without
direct execution authority and without requiring the operator's
computer to be open. LLM provider calls happen inside GitHub Actions
using API keys stored as GitHub Secrets.

When reviewing, also check:

- `docs/LLM_AUTHORITY_MODEL.md` — **NEW** canonical authority enum.
  Six levels: `L0_OBSERVE_ONLY`, `L1_EXPLAIN_ONLY`,
  `L2_RECOMMEND_ONLY`, `L3_VETO_RECOMMEND_ONLY`,
  `L4_PROPOSE_CONFIG_CHANGE_ONLY`, `L5_EXECUTE_FORBIDDEN`. L5 is a
  **sentinel** — `ASSIGNABLE_LEVELS` excludes it and
  `assert_assignable_authority` raises `ValueError` on assignment.
  Default ceiling for every agent is `L3_VETO_RECOMMEND_ONLY`; the
  single risk-proposal agent gets `L4_PROPOSE_CONFIG_CHANGE_ONLY`.
- `learning-loop/llm_advisory/schema.json` — **NEW** JSON Schema with
  pinned safety enums: `advisory_only=[true]`, `may_execute=[false]`,
  `may_modify_risk=[false]`, `may_unlock_broker_paper=[false]`,
  `broker_order_submitted=[false]`, `broker_execution_enabled=[false]`,
  `affects_readiness_gate=[false]`. Authority enum excludes
  `L5_EXECUTE_FORBIDDEN`. Every row's `forbidden_actions_confirmed`
  list must include all ten capability tokens.
- `shared/llm_agent_budget.py` — **NEW** governor: defaults
  `LLM_AGENTS_ENABLED=false`, daily 20 calls, per-run 5 calls,
  $1.00/day cost cap, fail-soft. Six statuses. State in
  `learning-loop/llm_advisory/llm_budget_state.json`. NEVER imports
  the broker-orders module.
- `shared/llm_provider_client.py` — **NEW** Anthropic / OpenAI /
  offline_mock abstraction. Default `offline_mock` makes no network
  calls. Six statuses. Keys read at call time, never persisted.
  Response text redacted for secret-shaped tokens.
- `shared/llm_advisory_registry.py` — **NEW** 11-agent canonical
  registry. Every agent's `forbidden_actions` list includes all
  ten capability tokens; constructor asserts. L5 sentinel raises.
- `shared/llm_pre_order_advisory.py` — **NEW**. Verdict enum does
  NOT include `EXECUTE`. `is_blocking()` returns True only when
  verdict=`ADVISORY_VETO_RECOMMENDED` AND
  `LLM_PRE_ORDER_VETO_HONORED=true`.
- `shared/llm_risk_change_proposal.py` — **NEW**. Constructor
  enforces `auto_apply=False`, `requires_operator_approval=True`,
  `advisory_only=True`. `applies_to_risk_config()` is a hard
  `return False`.
- `scripts/run_llm_advisory_mesh.py` — **NEW** cloud-callable
  runner. Default returns `LLM_ADVISORY_MESH_SKIPPED_DISABLED`.
  Refuses (exit 1) on any truthy broker-execution env flag.
  Validates every emitted row against the schema before writing.
- `.github/workflows/llm-advisory-mesh.yml` — **NEW**
  `workflow_dispatch` only by default; scheduled cron only when
  repo variable `LLM_AGENTS_SCHEDULED=true`. All 7 broker flags
  pinned `false`. No broker secrets. Tight commit allow-list.

### v3.28 status tokens (added)

- 6 budget statuses, 6 provider statuses, 7 advisory verdicts,
  4 mesh runner statuses, 5 cross-cutting markers
  (`LLM_CLOUD_ADVISORY_MESH_ADDED`, `LLM_AUTHORITY_MODEL_ADDED`,
  `LLM_ORDER_EXECUTION_DIRECT_CONTROL_FORBIDDEN`,
  `LLM_RISK_GATE_DIRECT_MUTATION_FORBIDDEN`,
  `DETERMINISTIC_GATES_REMAIN_FINAL`,
  `LLM_OUTPUT_NEVER_COUNTS_AS_REAL_MARKET_EVIDENCE`).

### Final Arbiter v3.28 escalation triggers (P0)

In addition to all v3.23.x through v3.27.x triggers, the Final
Arbiter MUST block escalation and set primary verdict to
NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when:

- any v3.28 module acquires an import of the broker-orders module
- the `L5_EXECUTE_FORBIDDEN` sentinel appears in a serialized
  advisory row
- any advisory row carries `advisory_only=false`,
  `may_execute=true`, `may_modify_risk=true`,
  `may_unlock_broker_paper=true`, `broker_order_submitted=true`,
  `broker_execution_enabled=true`, or `affects_readiness_gate=true`
- `llm_pre_order_advisory.is_blocking()` returns `True` for any
  verdict OTHER than `ADVISORY_VETO_RECOMMENDED`
- `llm_pre_order_advisory.is_blocking()` returns `True` for
  `ADVISORY_VETO_RECOMMENDED` while `LLM_PRE_ORDER_VETO_HONORED`
  is unset / false
- any `RiskChangeProposal` is serialized with `auto_apply=true`
- the v3.28 workflow YAML drops the 7 broker-flag hard-pins or
  adds broker secrets to its `env:` block
- the v3.28 workflow's commit path allow-list widens beyond the
  three approved paths
- the `LLM_AGENTS_ENABLED` env default flips from `false` to `true`
  anywhere in the workflow
- the advisory schema's pinned enums on the seven safety-critical
  fields are loosened
- the budget governor's `LLM_AGENTS_ENABLED=false` default flips
  to `true` in source
- the offline-mock provider acquires a network-call path

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts. v3.28 changes LLM advisory ROUTING and
authority — no trading behaviour, broker state, readiness gate, or
real-market-evidence counters are touched.

---

## v3.28.2 coverage (added 2026-06-09)

v3.28 shipped the cloud LLM advisory mesh disabled-by-default with
provider support for Anthropic / OpenAI / offline_mock. v3.28.2 adds
a **free-first activation path via Gemini** so the operator can
enable the mesh without paying for an LLM API. The operator's
computer does not need to stay open — activation, set-vars, trigger,
and validation all happen via `gh` CLI / GitHub Actions.

When reviewing, also check:

- `shared/llm_provider_client.py` — extended with `FREE_PROVIDERS`
  / `PAID_PROVIDERS` sets, **`LLM_FREE_ONLY=true` policy gate**
  (default), and a **Gemini provider branch** (default model
  `gemini-2.5-flash-lite`). Gemini 400/404 routed to new
  `LLM_PROVIDER_MODEL_ERROR`. Response parser handles Gemini's
  `candidates[0].content.parts[0].text` shape.
- `scripts/run_llm_advisory_mesh.py` — gained a free-only gate
  AFTER master-enable but BEFORE the key check. Paid provider +
  `LLM_FREE_ONLY=true` returns
  `LLM_ADVISORY_MESH_SKIPPED_PROVIDER_BLOCKED_BY_FREE_ONLY`.
  Summary always carries `selected_provider` + `llm_free_only`.
- `.github/workflows/llm-advisory-mesh.yml` — gained
  `GEMINI_API_KEY` secret env, `GEMINI_MODEL` repo var (default
  `gemini-2.5-flash-lite`), `LLM_FREE_ONLY` repo var (default
  `'true'`). All 7 broker-execution env flags remain hard-pinned
  `false`. No broker secrets added.
- `scripts/activate_llm_advisory_mesh.py` — **NEW** activation
  helper. Modes: `--check-only` (default), `--set-vars`,
  `--trigger`. Uses `gh secret list --json name` to detect secret
  NAMES only — NEVER reads or prints values. NEVER imports the
  broker-orders module. Exits 0 when blocked.
- `learning-loop/llm_advisory/activation_status_latest.json` +
  `docs/LLM_ADVISORY_ACTIVATION_STATUS.md` — **NEW** auto-generated
  artefacts. Contain `secret_names_seen` (NAMES only — no values),
  `selected_provider`, `llm_free_only`, `schedule_enabled`,
  status fields, blockers, next-action.

### v3.28.2 status tokens (added)

- 2 provider statuses: `LLM_PROVIDER_BLOCKED_BY_FREE_ONLY`,
  `LLM_PROVIDER_MODEL_ERROR`.
- 1 runner status:
  `LLM_ADVISORY_MESH_SKIPPED_PROVIDER_BLOCKED_BY_FREE_ONLY`.
- 9 activation statuses (`LLM_ACTIVATION_*`).
- 8 cross-cutting markers: `FREE_ONLY_POLICY_ENABLED`,
  `PAID_PROVIDER_BLOCKED_BY_FREE_ONLY`, `FREE_PROVIDER_ALLOWED`,
  `OFFLINE_MOCK_STILL_DEFAULT`, `GEMINI_PROVIDER_AVAILABLE`,
  `API_KEYS_NOT_EXPOSED`, `SCHEDULE_LEFT_DISABLED_BY_DEFAULT`,
  `DETERMINISTIC_GATES_REMAIN_FINAL`.

### Operator opt-in (v3.28.2 flow)

1. Add `GEMINI_API_KEY` as GitHub Secret (operator does this).
2. `python3 scripts/activate_llm_advisory_mesh.py --check-only`
   → verifies readiness.
3. `python3 scripts/activate_llm_advisory_mesh.py --set-vars
   --provider gemini --enable-schedule false` → sets four repo
   variables.
4. `python3 scripts/activate_llm_advisory_mesh.py --trigger` →
   fires workflow_dispatch.

### Final Arbiter v3.28.2 escalation triggers (P0)

In addition to all v3.23.x through v3.28 triggers, the Final
Arbiter MUST block escalation and set primary verdict to
NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when:

- `LLM_FREE_ONLY` default flips from `true` to `false` in source
  or in the workflow YAML
- the v3.28.2 free-only policy gate is bypassed (paid provider
  reaches network with `LLM_FREE_ONLY=true`)
- `GEMINI_API_KEY` (or any other provider key) is printed or
  persisted in any committed artifact
- the activation helper sets a GitHub Secret (it must only set
  non-secret variables)
- the activation helper imports the broker-orders module
- the v3.28.2 workflow YAML adds broker secrets / broker host /
  Alpaca order paths
- the workflow's `LLM_AGENTS_SCHEDULED` gate is removed
- the workflow's commit path allow-list widens beyond the three
  approved paths
- an advisory row produced via Gemini violates any of the seven
  pinned safety enums

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts. v3.28.2 adds a free LLM provider plus
activation helper — no trading behaviour, broker state, readiness
gate, or real-market-evidence counters are touched.

---

## v3.28.3 coverage (added 2026-06-09)

v3.28.2 activated Gemini and produced 5 schema-valid advisory rows
— but they were **generic placeholders** because the v3.28 runner
never actually called `call_provider()` per agent. v3.28.3 fixes
the root cause and adds a quality guard so future runs cannot
silently regress to placeholder output.

When reviewing, also check:

- `scripts/run_llm_advisory_mesh.py` — **per-agent prompts +
  real provider calls now wired**. Each of the 11 registered
  agents gets a distinct prompt template (`_AGENT_PROMPT_TEMPLATES`)
  plus a per-agent evidence slice (`_evidence_summary_for_agent`).
  The prompt footer requires the provider to return ONE JSON
  object with `recommendation` / `rationale` / `risks_identified`
  / `proposed_next_actions` / `confidence` / `veto_recommendation`.
  `_parse_provider_response_into_row_fields` handles direct JSON,
  ```json``` fences, embedded JSON, and falls back to prose-as-
  recommendation. Each emitted row carries a new
  `provider_status` field: `PROVIDER_USED`,
  `PROVIDER_SKIPPED_DISABLED`, `PROVIDER_FAILED_FAIL_SOFT`, or
  `PROVIDER_OUTPUT_INVALID_SCHEMA`. Mock provider still returns
  `PROVIDER_SKIPPED_DISABLED` (deterministic placeholder text);
  Gemini / Anthropic / OpenAI paths return `PROVIDER_USED` on
  success.
- `shared/llm_advisory_quality.py` — **NEW** quality guard. 7
  statuses (`ALL_QUALITY_STATUSES`): `ACCEPTABLE`,
  `GENERIC_PLACEHOLDER`, `PROVIDER_OUTPUT_NOT_USED`,
  `SCHEMA_INVALID`, `SECRET_LEAK_BLOCKED`, `UNSAFE_BLOCKED`,
  `INSUFFICIENT_SAMPLE`. Secret-pattern scan (`AIza*`, `sk-ant-*`,
  `sk-*`, 20+ char uppercase-alphanumeric) blocks the batch.
  Unsafe-phrase scan (`enable broker paper`, `submit_order`, etc.)
  blocks the batch. `BLOCKING_STATUSES` = {secret-leak, unsafe}
  — runner must not commit on those.
- `learning-loop/llm_advisory/quality_review_latest.json` +
  `docs/LLM_ADVISORY_QUALITY_REVIEW.md` — **NEW** auto-generated
  artefacts. Contain quality status, full report, rationale, and
  full safety block.
- `shared/llm_agent_budget.py::per_run_budget` — gained an
  override path. `LLM_AGENT_PER_RUN_BUDGET_OVERRIDE` env is
  honoured ONLY when `LLM_FREE_ONLY=true` AND
  `LLM_PROVIDER=gemini`, clamped to `[1, 11]`. Override is
  silently ignored otherwise so a misconfigured value can never
  amplify cost on a paid provider.
- `.github/workflows/llm-advisory-mesh.yml` — new
  `workflow_dispatch` input `per_run_budget_override` (string,
  empty default). Plumbed through env as
  `LLM_AGENT_PER_RUN_BUDGET_OVERRIDE`. Schedule still gated on
  `LLM_AGENTS_SCHEDULED == 'true'`. All 7 broker-execution env
  flags remain hard-pinned `false`. Commit allow-list extended
  with `docs/LLM_ADVISORY_QUALITY_REVIEW.md`.
- `learning-loop/llm_advisory/schema.json` — optional
  `provider_status` field added (enum: the four PROVIDER_*
  tokens). All v3.28 v3.28.2 pinned safety enums unchanged.

### v3.28.3 status tokens (added)

- 4 per-row provider statuses (`PROVIDER_USED`,
  `PROVIDER_SKIPPED_DISABLED`, `PROVIDER_FAILED_FAIL_SOFT`,
  `PROVIDER_OUTPUT_INVALID_SCHEMA`).
- 7 quality statuses (see above).

### Final Arbiter v3.28.3 escalation triggers (P0)

In addition to all v3.23.x through v3.28.2 triggers, the Final
Arbiter MUST block escalation and set primary verdict to
NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when:

- the runner regresses to the v3.28 hard-coded placeholder
  recommendation (i.e. removes the `call_provider()` wire-in)
- the per-agent prompt builder is bypassed and a single
  prompt is sent for every agent
- any advisory row contains a secret-shape token
  (`AIza*`, `sk-ant-*`, `sk-*`, 20+ char uppercase-alphanumeric)
  not redacted to `<REDACTED>` — the quality guard returns
  `LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED` and the runner
  MUST not commit
- any advisory row contains an unsafe-action phrase (the
  quality guard returns `LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED`
  and the runner MUST not commit)
- the per-run budget override is honoured outside the
  `gemini+free-only` configuration, or exceeds the `[1, 11]`
  clamp, or applies to the schedule (it must apply only to
  workflow-dispatch validation runs)
- the runner removes the `quality_status` /
  `quality_report` fields from its summary
- the runner removes the `provider_status` field from a row
- the schema's optional `provider_status` enum gains a value
  outside the four PROVIDER_* tokens
- the quality guard's `BLOCKING_STATUSES` set shrinks

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts. v3.28.3 calibrates LLM output quality
— no trading behaviour, broker state, readiness gate, or
real-market-evidence counters are touched. Schedule remains
disabled until quality is consistently `ACCEPTABLE` across N
runs; `LLM_PRE_ORDER_VETO_HONORED` remains `false`.

---

## v3.29 coverage (added 2026-06-09)

Three independent deliveries in one sprint: Gemini provider recovery
(Part A), LLM strategy alignment gate (Part B), broker-paper canary
unlock orchestrator (Part C).

When reviewing, also check:

### Part A — Gemini provider recovery

- `shared/gemini_model_selector.py` — **NEW**. `discover_models()`
  calls the Gemini `/v1beta/models` endpoint and returns text-capable
  models in score-sorted order; `select_model()` picks the
  configured-or-candidate-or-discovered winner; `classify_http_status()`
  maps HTTP codes to one of 7 failure categories
  (`GEMINI_MODEL_UNAVAILABLE`, `GEMINI_AUTH_FAILED`,
  `GEMINI_QUOTA_OR_RATE_LIMIT`, `GEMINI_PERMISSION_DENIED`,
  `GEMINI_ENDPOINT_ERROR`, `GEMINI_TIMEOUT`,
  `GEMINI_UNKNOWN_PROVIDER_FAILURE`). Discovery + selection statuses
  in `ALL_DISCOVERY_STATUSES`. Redacts secrets. NEVER imports the
  broker-orders module.
- `shared/llm_provider_client.py` — Gemini branch now calls the
  selector before constructing the URL; `ProviderResponse` gained 5
  safe diagnostic fields (`provider_http_status`,
  `provider_error_category`, `provider_endpoint_family`,
  `provider_retryable`, `provider_suggested_next_model`); 4xx/5xx
  failures populate them.
- `scripts/smoke_test_gemini_provider.py` — **NEW** one-call smoke
  test. 8 statuses (`GEMINI_SMOKE_OK`, plus 7 failure modes). Writes
  `learning-loop/llm_advisory/gemini_smoke_latest.json` +
  `docs/GEMINI_PROVIDER_STATUS.md`. NEVER logs the key. NEVER logs
  the full URL.
- `.github/workflows/llm-advisory-mesh.yml` — gained
  `workflow_dispatch` input `model_override` (threaded through env
  as the highest-priority `GEMINI_MODEL` source); default
  `GEMINI_MODEL` switched to `gemini-flash-latest` (alias is more
  durable than a dated name); new `Gemini smoke test (v3.29)` step
  short-circuits the full 11-agent mesh when the provider is
  unhealthy.

### Part B — LLM strategy alignment

- `shared/llm_strategy_alignment.py` — **NEW** gate. 7 statuses
  (`ALL_ALIGNMENT_STATUSES`):
  `LLM_STRATEGY_ALIGNMENT_PASS`,
  `..._FAIL_EXECUTION_AUTHORITY`,
  `..._FAIL_RISK_MUTATION`,
  `..._FAIL_READINESS_BYPASS`,
  `..._FAIL_FAKE_EVIDENCE`,
  `..._FAIL_UNSUPPORTED_LIVE`,
  `..._INSUFFICIENT_PROVIDER_QUALITY`.
  Scans every advisory row's `recommendation` /
  `rationale` / `risks_identified` / `proposed_next_actions` for
  unsafe phrase patterns + checks `may_execute` /
  `may_modify_risk` / `may_unlock_broker_paper` /
  `broker_order_submitted` / `broker_execution_enabled` /
  `affects_readiness_gate` are all false +
  `advisory_only=true`. Requires quality status =
  `LLM_ADVISORY_QUALITY_ACCEPTABLE` and at least one row carries
  `PROVIDER_USED` for PASS.

### Part C — Broker-paper canary unlock orchestrator

- `docs/BROKER_PAPER_CANARY_UNLOCK_CONTRACT.md` — **NEW** canonical
  contract. 6 stages (`STAGE_0_SHADOW_ONLY` through
  `STAGE_5_LIVE_UNSUPPORTED` — the last permanently unreachable).
  21 hard gates listed for `STAGE_2_BROKER_PAPER_CANARY_READY`.
- `shared/broker_paper_canary_unlock.py` — **NEW** read-only
  evaluator. 11 unlock statuses (`ALL_UNLOCK_STATUSES`). Aggregates
  evidence counters, workflow health, first-real-record,
  quality_review, strategy_alignment. Returns
  `BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH` even
  when every gate green (v3.29 ships no safe enable switch). NEVER
  flips a broker flag. NEVER imports the broker-orders module.
- `scripts/evaluate_broker_paper_canary_unlock.py` — **NEW**
  orchestrator. Default `--evaluate-only`. `--apply-enable` exists
  but in v3.29 always emits
  `BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH`
  because `configs/broker_paper_canary.json::canary_execution_flag_present`
  is `false`. Refuses (exit 1) on any truthy broker-execution env
  flag.
- `configs/broker_paper_canary.json` — **NEW** conservative limits
  (`max_orders_per_day: 1`, `max_notional_per_order_usd: 25`,
  `allowed_asset_classes: ["us_equity"]`, `crypto_enabled: false`,
  `options_enabled: false`, `live_trading_supported: false`,
  `canary_execution_flag_present: false`).
- `.github/workflows/broker-paper-canary-unlock-evaluator.yml` —
  **NEW** daily read-only evaluator workflow.
  `workflow_dispatch` + schedule `30 21 * * 1-5` (after US market
  close). Hard-pins all 7 broker-execution env flags `false`.
  Commit allow-list tight: `learning-loop/broker_paper_canary/**` +
  `docs/BROKER_PAPER_CANARY_UNLOCK_STATUS.md` +
  `docs/BROKER_PAPER_CANARY_UNLOCK_CONTRACT.md` +
  `docs/LLM_STRATEGY_ALIGNMENT.md` +
  `learning-loop/llm_advisory/strategy_alignment_latest.json` +
  `learning-loop/position_reconciliation/latest.json`. NEVER
  includes broker secrets.

### v3.29 status tokens (added)

- 8 Gemini smoke statuses, 10 Gemini discovery statuses, 7 Gemini
  failure categories, 7 alignment statuses, 11 unlock statuses, 6
  unlock stages, 5 provider diagnostic fields.

### Final Arbiter v3.29 escalation triggers (P0)

In addition to all v3.23.x through v3.28.3 triggers, the Final
Arbiter MUST block escalation and set primary verdict to
NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when:

- any v3.29 module acquires an import of the broker-orders module
- the canary unlock evaluator flips any of
  `ALLOW_BROKER_PAPER` / `EDGE_GATE_ENABLED` /
  `BROKER_EXECUTION_ENABLED` / `LIVE_TRADING*` flags
- the canary unlock evaluator advances past
  `BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH`
  while
  `configs/broker_paper_canary.json::canary_execution_flag_present`
  is `false`
- the canary unlock evaluator returns `READY` without
  `OPERATOR_APPROVED_BROKER_PAPER_CANARY=true`
- the canary unlock evaluator returns `READY` while
  `LLM_STRATEGY_ALIGNMENT_PASS` is not present
- the canary unlock evaluator returns `READY` while
  `LLM_ADVISORY_QUALITY_ACCEPTABLE` is not present
- the canary config's `max_orders_per_day` exceeds 1,
  `max_notional_per_order_usd` exceeds 25,
  `crypto_enabled` flips true, `options_enabled` flips true, or
  any `auto_disable_on_*` flag is removed
- the smoke test acquires an import of the broker-orders module
- the smoke test logs the key, the full URL, or any secret-shape
  token
- the Gemini model selector silently picks an image / video / embed
  model
- the strategy alignment gate weakens its phrase blacklists (the
  test enumerates the expected categories)
- any live-trading env flag becomes assignable from a v3.29 file

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts. v3.29 introduces the canary readiness
proposal path — no order is placed, no broker flag is flipped, no
trading behaviour changes. Live trading remains permanently
unsupported.

---

## v3.29.1 coverage (added 2026-06-09)

v3.29 unlocked the canary readiness path but left two operational
holes: (a) the unlock evaluator could count stale/mock quality
artefacts as ACCEPTABLE, and (b) the operator had no visibility into
*why* real-market opportunity records were not landing. v3.29.1
closes both holes.

When reviewing, also check:

- `shared/broker_paper_canary_unlock.py` — extended with:
  - `_quality_row_passes_anti_mock()` — rejects ACCEPTABLE status
    when `rows_with_provider_used <= 0`, secret_leak_hits > 0,
    unsafe_phrase_hits > 0, OR all rows have empty risks AND
    empty next-actions AND zero confidence.
  - `_quality_source_mismatch_detected()` — detects (a) top-level
    `quality_status` ≠ `quality_report.status`, OR (b) latest
    artefact's `run_id` missing from `quality_history.jsonl`
    when history exists.
  - `_read_quality_history()` + `append_quality_history()` —
    append-only history with idempotent run_id dedup. Anti-mock
    check applied at append time → `accepted_for_unlock_counting`.
  - `_count_acceptable_quality_runs()` — counts distinct
    `accepted_for_unlock_counting=true` runs from history. Falls
    back to latest-only WITH anti-mock check.
  - New status
    `BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH`
    fires BEFORE the other quality gates.
- `scripts/run_llm_advisory_mesh.py` — appends every quality
  result to `quality_history.jsonl` via the new
  `_append_to_quality_history()`. Strengthened prompt footer
  (`_AGENT_PROMPT_FOOTER`) now requires:
  1. Recommendation must cite at least one evidence value.
  2. Rationale must cite evidence verbatim or say "insufficient
     evidence because <specific>".
  3. Risks must contain ≥1 item.
  4. Proposed_next_actions must contain ≥1 item.
  5. Confidence > 0 when any evidence is present.
  6. New required field `evidence_values_used` (dict).
  Parser extracts the new field; row builder + schema accept it.
- `shared/llm_advisory_quality.py` — two new statuses
  (`LLM_ADVISORY_QUALITY_EMPTY_ANALYSIS`,
  `LLM_ADVISORY_QUALITY_NO_EVIDENCE_VALUES_USED`). Empty-analysis
  takes precedence over generic placeholder. ACCEPTABLE requires
  at least one row populated `evidence_values_used`.
- `learning-loop/llm_advisory/schema.json` — adds optional
  `evidence_values_used` property (additionalProperties: true; no
  pinned safety enums affected).
- `shared/real_market_evidence_accelerator.py` — **NEW**
  read-only analyzer. 9 statuses
  (`REAL_MARKET_EVIDENCE_HEALTHY`,
  `..._BLOCKED_NO_BARS`,
  `..._BLOCKED_INSUFFICIENT_BARS`,
  `..._BLOCKED_AUTH_FAILED`,
  `..._BLOCKED_PROVIDER_ERROR`,
  `..._BLOCKED_GENERATOR_RESTRICTIVE`,
  `..._BLOCKED_OUTSIDE_SESSION`,
  `..._BLOCKED_INSUFFICIENT_RUNS`,
  `..._ACCELERATION_READY`). 8 `ALLOWED_ACTIONS` + 7
  `FORBIDDEN_ACTIONS`. NEVER mutates counters. NEVER imports
  the broker-orders module.
- `scripts/evaluate_real_market_evidence_acceleration.py` —
  **NEW** CLI wrapper. Refuses on any truthy broker-execution /
  live env flag.
- `.github/workflows/real-market-evidence-accelerator.yml` —
  **NEW** daily read-only workflow. Cron `0 22 * * 1-5`. All 7
  broker-execution env flags hard-pinned `false`. Commits only
  `learning-loop/shadow_evidence/acceleration_latest.json` +
  `docs/REAL_MARKET_EVIDENCE_ACCELERATION.md` +
  `docs/REAL_MARKET_OBSERVATION_RECORD_PROPOSAL.md` +
  `learning-loop/position_reconciliation/latest.json`.
- `docs/REAL_MARKET_OBSERVATION_RECORD_PROPOSAL.md` — **NEW**
  proposal doc. **Observation record schema change DEFERRED to
  v3.30.** v3.29.1 ships the accelerator + executor design only.
- `docs/BROKER_PAPER_CANARY_EXECUTOR_DESIGN.md` — **NEW**
  design-only doc. **No executor code in v3.29.1.** Spec for a
  future executor: 1 order/day, $25 cap, US equity only, safe
  order wrapper + post-trade reconciliation, auto-disable on
  first error / LLM quality regression / reconciliation
  mismatch.

### v3.29.1 status tokens (added)

- 1 new unlock status
  (`BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH`).
- 2 new quality statuses (`EMPTY_ANALYSIS`,
  `NO_EVIDENCE_VALUES_USED`).
- 9 new acceleration statuses (see above).
- 8 `ALLOWED_ACTIONS` + 7 `FORBIDDEN_ACTIONS` in the accelerator.

### Final Arbiter v3.29.1 escalation triggers (P0)

In addition to all v3.23.x through v3.29 triggers, the Final
Arbiter MUST block escalation and set primary verdict to
NEEDS_FIXES with secondary NOT_SAFE_FOR_LIVE_TRADING when:

- the unlock evaluator counts a `quality_review_latest.json` snapshot
  toward `n_acceptable_quality_runs` while its `quality_report`
  embedded status disagrees with the top-level `quality_status`
- the unlock evaluator counts a snapshot while
  `_quality_row_passes_anti_mock` would return False (rows_with_provider_used
  ≤ 0, secret_leak_hits > 0, unsafe_phrase_hits > 0, or all rows
  empty)
- the unlock evaluator counts a stale snapshot (run_id not in
  `quality_history.jsonl` when history exists)
- the strengthened prompt footer is reverted to its v3.28.3 form
- the quality guard's `EMPTY_ANALYSIS` precedence is reversed
  back behind `GENERIC_PLACEHOLDER`
- the accelerator acquires a counter-mutation pattern
- the accelerator suggests a forbidden action
  (`LOWER_SAFETY_THRESHOLDS_TO_CREATE_FAKE_SIGNALS`,
  `COUNT_NO_SIGNAL_AS_OPPORTUNITY`,
  `COUNT_SCAFFOLD_OR_HALT_AS_REAL_MARKET`,
  `USE_LLM_OUTPUT_AS_EVIDENCE`, etc.)
- a real-market observation record lands without first updating
  the v3.30 schema + readiness gate semantics
- any v3.29.1 module acquires an import of the broker-orders
  module

The arbiter still NEVER recommends LIVE_TRADING — only
PAPER_TRADING_* verdicts. v3.29.1 fixes quality gating
inconsistencies + adds the accelerator + ships executor design —
no orders placed, no broker flag flipped, no live trading.

---

## End of shared context
