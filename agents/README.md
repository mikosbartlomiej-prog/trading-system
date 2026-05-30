# Multi-Agent Audit Board

> A review and quality-gate system for the experimental autonomous
> paper trading runtime. **Agents review the system — they are NOT
> the runtime trading brain.**

---

## What this is

The Audit Board is a set of 11 area-specialist prompt-based reviewers
plus one Final Arbiter. They produce structured, auditable findings
about the codebase, design, risk gates, confidence score, data quality,
documentation, security, runtime safety, testing, simplicity, and
**free in operation** status — every recommendation must keep the
system $0 / month.

The board exists OUTSIDE the deterministic trading loop:

```
[ runtime, deterministic, NO LLMs ]
  signal → confidence → risk → decision → audit → execution

[ audit board, prompt-based, may use LLM offline ]
  reads:  code, configs, audit JSONL, reports, tests
  emits:  findings, blockers, final decision
  cannot: trade, modify risk, modify safe_mode, modify kill-switch
```

This separation is structural — the Audit Board has no import paths
into `shared/` order placement, no write access to risk parameters,
no ability to call Alpaca.

---

## What this is NOT

- **NOT a runtime trading brain.** Agents cannot make per-trade decisions.
- **NOT a replacement for `shared/risk_officer.py`.** The deterministic
  risk engine remains the sole authority during a session.
- **NOT a replacement for `shared/confidence.py`.** The deterministic
  multi-component confidence score remains the per-decision quality gate.
- **NOT a profit estimator.** Agents do not predict returns.
- **NOT a live-trading approver.** Live trading is permanently blocked
  by `shared/autonomy.assert_paper_only` invariant. Agents cannot
  override it.

---

## When to use the Audit Board

| Trigger | What to review |
|---|---|
| Before paper-trading start | All 11 agents + Final Arbiter |
| After major code change in `shared/` | architecture + risk + simplicity |
| After new strategy added | strategy + confidence + data_quality + tests |
| After incident (P02/P03/P12 from incident-pattern-detector) | runtime_safety + risk + final_arbiter |
| Weekly cadence | All 11 + Final Arbiter (cron suggested) |
| Before bumping any limit in `aggressive_profile.json` | risk + simplicity |
| Before adding new dependency | free_operations + security |

---

## When NOT to use the Audit Board

- During a live trading session (live is permanently forbidden anyway)
- As a per-trade approver in runtime
- To "approve" higher leverage
- As justification for skipping deterministic gates

---

## The 12 agents

| # | Agent | Area | Output prefix |
|---|---|---|---|
| 00 | `00_shared_context.md` | Common rules (read first) | — |
| 01 | `01_architecture_reviewer.md` | Module layering, flow, bypass detection | `ARCH-XXX` |
| 02 | `02_trading_strategy_reviewer.md` | Market hypothesis, edge, costs | `STRAT-XXX` |
| 03 | `03_risk_reviewer.md` | Risk engine completeness + invariants | `RISK-XXX` |
| 04 | `04_data_quality_bias_reviewer.md` | Data quality, lookahead, leakage | `DATA-XXX` |
| 05 | `05_confidence_score_reviewer.md` | Confidence score honesty | `CONF-XXX` |
| 06 | `06_runtime_safety_reviewer.md` | Heartbeat, safe_mode, kill_switch | `RUNTIME-XXX` |
| 07 | `07_testing_e2e_reviewer.md` | Unit + integration + E2E coverage | `TEST-XXX` |
| 08 | `08_documentation_runbook_reviewer.md` | Docs match code | `DOC-XXX` |
| 09 | `09_simplicity_refactoring_reviewer.md` | No overengineering | `SIMPL-XXX` |
| 10 | `10_security_secrets_reviewer.md` | Secrets, paper-only invariant | `SEC-XXX` |
| 11 | `11_free_operations_reviewer.md` | $0 / month operational | `FREE-XXX` |
| 12 | `12_final_arbiter.md` | Aggregates all 11 + binding decision | `ARB-XXX` |

---

## How to run a review (manually, locally)

The audit board uses prompt-based reviewers. You can:

### Option A — Local LLM (Claude Code session, Codex, etc.)

1. Open a session in this repo with your preferred LLM tool.
2. Run `python3 agents/run_agent_board.py --init <YYYYMMDD>` to scaffold
   the report templates.
3. For each agent, load the corresponding prompt:
   - `cat agents/prompts/00_shared_context.md`
   - `cat agents/prompts/<NN>_<area>.md`
4. Instruct the LLM to follow the prompt and produce a report at
   `agents/reports/<NN>_<area>_<YYYYMMDD>.md` conforming to
   `agents/schemas/agent_report.schema.json`.
5. After all 11 area agents finished, run the Final Arbiter prompt
   (`12_final_arbiter.md`).
6. Validate everything with `python3 agents/run_agent_board.py --validate <YYYYMMDD>`.

### Option B — Manual human review

1. Read each prompt in order.
2. Manually inspect the code and fill in the report template.
3. Use the same `--init` and `--validate` runner commands.

### Option C — Hybrid (recommended)

- Use LLM for first-pass scan
- Have a human verify P0 / P1 findings
- Final Arbiter is always human-verified before any decision is acted on

---

## How to interpret findings

Each finding has these required fields (see `schemas/finding.schema.json`):

- `severity`: P0 / P1 / P2 / P3
- `blocking_status`: BLOCKS_LOCAL_REPLAY / BLOCKS_PAPER_TRADING /
  BLOCKS_LIVE_TRADING / NEEDS_REFACTOR / NEEDS_TESTS / INFO_ONLY
- `free_operation_impact`: none / improves / degrades / **VIOLATES**
- `confidence_score_impact`: neutral / raises_ceiling / lowers_floor /
  **invalidates**
- `safety_impact`: neutral / improves / degrades / **compromises**

**Auto-reject** any finding with:
- `free_operation_impact == "VIOLATES"` whose recommendation requires a paid service
- `severity == "P0"` with `recommendation` that increases risk limits
- any finding that recommends live trading

---

## How to interpret the Final Decision

| Final Arbiter decision | What you may do |
|---|---|
| `APPROVE_LOCAL_REPLAY` | Backtest / replay OK. Paper not yet approved. |
| `APPROVE_PAPER_TRADING_WITH_WARNINGS` | Paper OK — warnings logged but not blockers. |
| `BLOCK_PAPER_TRADING` | Stop / do not start paper trading. Fix P0s first. |
| `NEEDS_REFACTOR` | Code-quality blockers (not necessarily unsafe). Fix before paper. |
| `NEEDS_MORE_TESTS` | Coverage blockers. Add tests before paper. |
| `NOT_SAFE_FOR_LIVE_TRADING` | Always-on permanent verdict. |
| `BLOCK_ALL_TRADING_MODES` | Critical: even local replay unsafe. Hard stop. |

The Final Arbiter's decision is binding. It cannot be overridden without
re-running the relevant agents AND addressing the cited findings.

---

## Blocking statuses — semantics

- **BLOCKS_LOCAL_REPLAY** — Local backtest is unsafe (e.g. lookahead bias).
  Replay output cannot be trusted. Highest priority.
- **BLOCKS_PAPER_TRADING** — Paper trading would have undefined / unsafe
  behavior. Trading must not start until fixed.
- **BLOCKS_LIVE_TRADING** — Permanently blocks live. Default for ALL
  findings; lifted only by paper trading proven safe over months + manual
  operator + multiple safety properties verified.
- **NEEDS_REFACTOR** — Behavior may be safe, but the code is too complex
  / fragile to audit confidently. Fix before depending on it.
- **NEEDS_TESTS** — Behavior may be correct, but uncovered by tests.
  Fix before depending on it.
- **INFO_ONLY** — Documentation/cosmetic. Does not block.

---

## How to add a new agent

1. Pick the next number (13, 14, ...) and area name.
2. Create `agents/prompts/<NN>_<area>.md` following the format of any
   existing agent. Required sections:
   - Role
   - Scope of responsibility
   - What you MUST look for
   - What you MUST NOT do
   - Checklist
   - Blocking criteria
   - Acceptance criteria
   - Confidence-score impact
   - Output format
   - Required tests
   - Free-operation requirement
3. Add the agent name to the enums in
   `agents/schemas/finding.schema.json::agent` and
   `agents/schemas/agent_report.schema.json::agent_name`.
4. Update `agents/run_agent_board.py::AGENT_NAMES` to include it.
5. Update this README's agent table.
6. Update `agents/schemas/final_decision.schema.json::agents_consumed`
   `minItems` to the new count.
7. Add tests in `tests/test_audit_board.py` to assert the new prompt
   contains all required sections.

---

## How to keep free operation

The Free Operations Reviewer (agent 11) enforces this, but every agent
must self-restrict:

- Do not recommend paid SaaS.
- Do not recommend cloud DBs.
- Do not recommend commercial frameworks.
- Do not recommend dependencies requiring credit cards for normal use.
- If you would recommend a paid tool, propose a free alternative or
  state that the requirement should be deferred.

The runner `agents/run_agent_board.py` does NOT make any external
network calls. The entire pipeline runs locally.

---

## How to avoid false profit guarantees

The Shared Context (`00_shared_context.md`) explicitly forbids:

- "this will be profitable"
- "guaranteed edge"
- "high confidence means high profit"
- "system is safe for live"

Findings containing such phrases are auto-rejected by the validation
step in `agents/run_agent_board.py`.

---

## File structure

```
agents/
├── README.md                       (this file)
├── prompts/
│   ├── 00_shared_context.md        (READ FIRST)
│   ├── 01_architecture_reviewer.md
│   ├── 02_trading_strategy_reviewer.md
│   ├── 03_risk_reviewer.md
│   ├── 04_data_quality_bias_reviewer.md
│   ├── 05_confidence_score_reviewer.md
│   ├── 06_runtime_safety_reviewer.md
│   ├── 07_testing_e2e_reviewer.md
│   ├── 08_documentation_runbook_reviewer.md
│   ├── 09_simplicity_refactoring_reviewer.md
│   ├── 10_security_secrets_reviewer.md
│   ├── 11_free_operations_reviewer.md
│   └── 12_final_arbiter.md
├── schemas/
│   ├── finding.schema.json
│   ├── agent_report.schema.json
│   └── final_decision.schema.json
├── reports/                        (created by --init; gitignored except templates)
│   └── templates/
└── run_agent_board.py              (local runner, no LLM calls)
```

---

## Related (but distinct) — deterministic audit agents

Confusingly, the repo also has `tools/<name>_agent/` directories:
- `tools/system_consistency_agent/` — deterministic Python checks (75+ rules)
- `tools/strategy_coherence_agent/` — deterministic strategy invariants
- `tools/e2e_system_test_agent/` — deterministic E2E test orchestrator

Those are **deterministic Python checks** that run in CI as quality
gates. They are NOT the Multi-Agent Audit Board.

The Audit Board (this directory) is **prompt-based offline review** —
broader scope, deeper analysis, human-in-the-loop.

Both layers complement each other:
- `tools/*_agent` = automated CI gates (run every push)
- `agents/` = human/LLM review board (run before paper-start + weekly)
