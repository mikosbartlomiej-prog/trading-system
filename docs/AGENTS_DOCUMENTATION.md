# Agents Documentation

> **Last updated:** 2026-05-30 (v3.13.0). Now covers **THREE classes of agents**:
> (1) deterministic CI gates in `tools/`, (2) Multi-Agent Audit Board in
> `agents/` (review-only), (3) per-domain LLM Curators in `*-monitor/`
> (signal-filter only, fail-soft).

Comprehensive guide to the autonomous agents that run inside the
trading-system repo. Three distinct classes of agents live here:

| Class | Where | Job | When it runs | Output |
|---|---|---|---|---|
| **Deterministic CI tools** | `tools/` | Static + dynamic auditors enforcing invariants | every push/PR + daily | `reports/{system-consistency,strategy-coherence,e2e}/latest.{json,md}` |
| **Multi-Agent Audit Board** | `agents/` | Prompt-based offline review (design/code/risk/etc.) | manual: before paper-start + weekly | `agents/reports/*_<DATE>.md` |
| **Per-domain LLM Curators** | `crypto-monitor/`, `reddit-monitor/`, `politician-monitor/` | Signal-quality filter (NOT decision) | per cron tick (when budget permits) | Curator picks merged into monitor signal flow with fail-soft path |

---

## Class 1 — Deterministic CI tools

Three agents in `tools/<name>_agent/`:

| Agent | Job | When it runs | Output |
|---|---|---|---|
| **System Consistency Agent** | Static auditor — enforces 8 system invariants (76 checks) | every push/PR + daily 06:15 UTC | `reports/system-consistency/latest.{json,md}` |
| **Strategy Coherence Agent** | Strategy-contract invariants (75 checks) | every push/PR + daily | `reports/strategy-coherence/latest.{json,md}` |
| **E2E System Test Agent** | Dynamic harness — runs end-to-end with fake clients (40 capabilities) | every push/PR + daily 06:45 UTC | `reports/e2e/latest.{json,md}` |

They are **complementary** — the consistency agent catches structural
regressions (a live URL added, a risk gate removed, a missing module).
The strategy-coherence agent catches strategy-contract drift (sizing
mismatch between docs and code, missing regime gate, etc.). The E2E
agent catches behavioural regressions (a guard that silently returns
OK when it should REJECT, a fake Alpaca that fills when it shouldn't).

### CLI

```bash
python3 scripts/system_consistency_agent.py
python3 scripts/strategy_coherence_agent.py
python3 scripts/e2e_system_test_agent.py --all --no-network --report-only
```

Current scores (v3.13.0): **100/100 + 100/100 + PASS**.

---

## Class 2 — Multi-Agent Audit Board (v3.13.0, NEW)

Located in `agents/`. 11 area-specialist prompt-based reviewers + Final
Arbiter. Used for design / code / risk / data / confidence / runtime
safety / testing / docs / simplicity / security / free-ops review.

**CRITICAL DISTINCTION:** Audit Board is **REVIEW-ONLY**. It cannot:
- trade
- modify risk parameters
- modify safe_mode / kill_switch
- run inside the deterministic decision loop
- recommend live trading

```
[ RUNTIME — deterministic, NO LLMs ]
  signal → confidence → risk → decision → audit → execution

[ AUDIT BOARD — prompt-based, may use LLM offline ]
  reads:  code, configs, audit JSONL, reports, tests
  emits:  findings, blockers, final decision
  CANNOT: trade, modify risk, modify safe_mode
```

### 12 prompts

| # | Agent | Prefix |
|---|---|---|
| 00 | Shared context (read first) | — |
| 01 | Architecture | `ARCH-XXX` |
| 02 | Trading strategy | `STRAT-XXX` |
| 03 | Risk | `RISK-XXX` |
| 04 | Data quality & bias | `DATA-XXX` |
| 05 | Confidence score | `CONF-XXX` |
| 06 | Runtime safety | `RUNTIME-XXX` |
| 07 | Testing & E2E | `TEST-XXX` |
| 08 | Documentation & runbook | `DOC-XXX` |
| 09 | Simplicity & refactoring | `SIMPL-XXX` |
| 10 | Security & secrets | `SEC-XXX` |
| 11 | Free operations | `FREE-XXX` |
| 12 | Final Arbiter | `ARB-XXX` |

### 3 JSON schemas

- `agents/schemas/finding.schema.json` — finding shape
- `agents/schemas/agent_report.schema.json` — per-agent report
- `agents/schemas/final_decision.schema.json` — Final Arbiter
  (`live_trading_readiness` HARDCODED `"blocked"`; `agents_consumed`
  `minItems=11`)

### CLI

```bash
python3 agents/run_agent_board.py list
python3 agents/run_agent_board.py validate-structure
python3 agents/run_agent_board.py check-forbidden
python3 agents/run_agent_board.py init <YYYY-MM-DD>
python3 agents/run_agent_board.py validate-reports <YYYY-MM-DD>
```

Zero LLM calls, zero network. See `agents/README.md` for usage details.

### Tests

`tests/test_audit_board_v3130.py` — **28 tests** verifying prompt
structure, schema validity, runner behavior, forbidden-phrase scan.

---

## Class 3 — Per-domain LLM Curators (signal-filter only)

Located in `*-monitor/llm_curator.py` files. Each is a **signal-quality
filter** wired via `routine_budget` (15/day Anthropic cap). **FAIL-SOFT** —
when LLM unavailable, monitor proceeds with heuristic fallback.

| Curator | Domain | File |
|---|---|---|
| **Crypto Signal Curator** | Validates crypto-monitor picks | `crypto-monitor/llm_curator.py` |
| **Reddit Signal Curator** | Validates reddit-monitor picks | `reddit-monitor/llm_curator.py` |
| **Capitol Trader Curator** | Validates politician-monitor PTRs | `politician-monitor/llm_curator.py` |
| **Senior PM** + **Challenger** | Learning-loop 3-round dialog (daily) | `learning-loop/llm_client.py` |

**Constraint:** Curators only FILTER what monitors emit — they do NOT
add their own signals. They cannot override risk_officer, cannot ignore
confidence threshold, cannot recommend live trading.

---

---

## 1. System Consistency Agent

### 1.1 What it does

Walks the working tree and verifies 8 system invariants:

1. paper-only (no live endpoints anywhere)
2. fully autonomous trading (no human-approval wording in trading code)
3. bounded autonomous code changes (validator self-modify forbidden)
4. deterministic execution (LLM cannot bypass risk gates)
5. free-first (no paid deps, LLM default off)
6. risk-managed (portfolio_risk module + wiring)
7. auditable (Decision dataclass + audit JSONL)
8. coherent (workflows + docs ↔ code parity)

Each invariant is broken into one or more checks (74 total across 15
categories). Every check returns PASS / WARN / FAIL / SKIP with
optional Evidence rows pointing at `file:line:snippet`.

### 1.2 Location

```
tools/system_consistency_agent/
├── __init__.py                 — exports run() + run_cli()
├── main.py                     — orchestrator + CLI
├── models.py                   — Finding / CategoryResult / AuditReport
├── utils.py                    — file walking, git_sha, regex grep
├── report.py                   — JSON + Markdown renderers
└── checks/
    ├── paper_only.py              (weight 15)
    ├── autonomy_trading.py        (12)
    ├── deterministic_execution.py (12)
    ├── portfolio_risk.py          (10)
    ├── code_autonomy.py           (10)
    ├── options_safety.py          (8)
    ├── state_policy.py            (7)
    ├── emergency_remediation.py   (7)
    ├── workflows.py               (6)
    ├── security.py                (5)
    ├── documentation.py           (5)
    ├── signal_confirmation.py     (5)
    ├── learning_loop.py           (4)
    ├── auditability.py            (4)
    └── free_tier.py               (3)
```

Total weight: 113. Score normalised 0–100.

Thin CLI: `scripts/system_consistency_agent.py`.
CI: `.github/workflows/system-consistency-audit.yml`.

### 1.3 How to run

```bash
# Full audit — Markdown + JSON files in reports/system-consistency/
python3 scripts/system_consistency_agent.py

# JSON only, stdout, no files
python3 scripts/system_consistency_agent.py --json --no-files

# One category
python3 scripts/system_consistency_agent.py --category paper_only

# Strict: WARN escalates exit code to 1
python3 scripts/system_consistency_agent.py --strict

# Non-blocking: FAIL exits 1 instead of 2
python3 scripts/system_consistency_agent.py --non-blocking
```

Exit codes:
- `0` — PASS or WARN
- `1` — WARN with `--strict`, or FAIL with `--non-blocking`
- `2` — FAIL or BLOCKED

### 1.4 What each category enforces (cheat sheet)

| Category | Key checks |
|---|---|
| `paper_only` | No `api.alpaca.markets/` in code (only `paper-api.`). No `LIVE_TRADING=true`. `assert_paper_only` wired in emergency_engine + remediation. ALPACA_BASE_URL points at paper. |
| `trading_autonomy` | No "approval needed" / "waiting for human" / "manual confirm" in trading code paths. `DECISION_TYPES` enum present. OPTIONS_ENABLED gate exists. panic_close_options has autonomous mode. emergency_engine auto-selects targets. |
| `deterministic_execution` | `alpaca_orders.py` invokes `_portfolio_risk_gate` + `risk_officer`. `signal_confirmation.py` exists. LLM client has kill switch. analyzer chains `validate_adaptation` after `safe_apply_overrides`. |
| `portfolio_risk` | Module + `compute_exposure` + `evaluate_portfolio_risk` + `CORRELATED_BUCKETS` (7 buckets) + 3 profiles (SAFE_FREE/BALANCED_PAPER/AGGRESSIVE_PAPER). Wired into stock + crypto + options paths. |
| `code_autonomy` | `patch_validator` present + self-modify forbidden + blocks live + blocks test-skip. `code_autonomy.py` exists with run_once/evaluate/apply/revert. `autonomy_bounds.json` with daily cap. autonomous-code-loop.yml runs audit + secret-scan + tests before merge. |
| `options_safety` | OPTIONS_ENABLED default False. liquidity check (spread/bid/ask). panic-close autonomous mode. options-exit dedup. |
| `state_policy` | `assert_can_write_state` + `StateWriteForbidden`. ALLOWED_ACTORS has daily-learning/daily-report/weekly-retro/manual-maintenance. `validate_state` + size_multiplier bounds. exit-monitor + reddit-monitor workflows do NOT commit state.json. |
| `emergency_remediation` | `scan_emergency_conditions` + `execute_emergency_close` + `EmergencyTarget` + MAX_ATTEMPTS_PER_DAY. 6 emergency conditions covered. Remediation actions (CANCEL_STALE_ORDERS / RECREATE_EXIT_PLAN / BLOCK_NEW_ENTRIES / PANIC_CLOSE_OPTIONS) + cooldown. |
| `workflows` | Schedule workflows have `concurrency:`. git commit/push has `contents: write`. autonomous-code-loop / autonomous-remediation / security-audit workflows exist. |
| `security` | audit_workflows.py + secret_scan_light.py exist. Both run clean. `mask()` helper present. |
| `documentation` | All 6 key docs exist + invariants confirmed in wording. |
| `signal_confirmation` | Module + API (confirm_price_volume / dedupe / cooldown / freshness). Wiring into 4 news monitors (defense/geo/twitter/reddit) — currently WARN, backlog. |
| `learning_loop` | sample-size constants + step bounds + `last_validated_at` once-per-day. analyzer.py wires validate_adaptation. |
| `auditability` | `shared/audit.py` + Decision dataclass with all 18 required fields. emergency_engine + remediation + code_autonomy all write audit events. |
| `free_tier` | LLM_ENABLED default False. docs/FREE_TIER_LIMITS.md present. No paid SaaS in requirements.txt. alpaca_orders has no LLM imports. |

### 1.5 Output format

JSON (`reports/system-consistency/latest.json`):

```json
{
  "overall_status": "PASS|WARN|FAIL|BLOCKED",
  "score": 99.13,
  "generated_at": "2026-05-14T...",
  "repo_sha": "fb5c36c50cc1a906...",
  "summary": {"pass": 72, "warn": 2, "fail": 0, "skip": 0},
  "categories": {
    "paper_only": {"weight": 15, "score": 15.0, "status": "PASS", ...},
    ...
  },
  "findings": [
    {
      "id": "PAPER_ONLY_NO_LIVE_ENDPOINT",
      "category": "paper_only",
      "severity": "PASS",
      "status": "PASS",
      "message": "No live Alpaca endpoint references in code paths.",
      "principle": "PAPER_TRADING_ONLY",
      "evidence": [],
      "recommendation": "",
      "blocking": false
    },
    ...
  ]
}
```

Markdown (`latest.md`) is generated from the same data — top of file has
"Overall / Score / Principle scorecard" cards, then sections for
Blocking failures / Non-blocking / Warnings / Per-category scorecard /
Recommended fixes.

### 1.6 Adding a new check

1. Create `tools/system_consistency_agent/checks/<category>.py` (or
   extend an existing one).
2. Implement `run(root: Path) -> list[Finding]`. Each Finding takes
   `id`, `category`, `severity`, `status`, `message`, `principle`
   (uppercase rule ID), optional `evidence`, `recommendation`,
   `blocking` (bool).
3. If a new category, register in `checks/__init__.py::CATEGORY_MODULES`
   with a weight.
4. Add a fixture-based test in
   `tests/architecture_vnext/test_system_consistency_agent.py`
   (create a temp FakeRepo with the violating file, call the check,
   assert FAIL).

Example minimal check:

```python
# tools/system_consistency_agent/checks/my_category.py
from pathlib import Path
from ..models import Finding

CATEGORY = "my_category"
PRINCIPLE = "MY_PRINCIPLE"

def run(root: Path) -> list[Finding]:
    out = []
    p = root / "shared" / "my_module.py"
    out.append(Finding(
        id="MY_CHECK_PRESENT",
        category=CATEGORY, severity="PASS" if p.exists() else "FAIL",
        status="PASS" if p.exists() else "FAIL",
        message="my_module.py present" if p.exists() else "missing",
        principle=PRINCIPLE,
        blocking=not p.exists(),
    ))
    return out
```

### 1.7 What it does NOT do

- Run tests (use `tools/e2e_system_test_agent/` for that)
- Touch the working tree (read-only)
- Hit the network or use any API keys
- Run LLMs

### 1.8 First-run result on this repo

`99.1/100, overall WARN, 8/8 principles PASS`.

Two backlog warnings:
- `SIGCONF_MONITORS_WIRED` — 4 news monitors (defense/geo/twitter/
  reddit) don't yet invoke `signal_confirmation.confirm_event_signal()`
  in pre-emit path. (Each alert still passes through
  `alpaca_orders → portfolio_risk → risk_officer` before order
  placement.)
- `OPTIONS_EXIT_DEDUP` — options-exit-monitor dedup pattern is correct
  in code but not statically detectable by the simple regex.

---

## 2. E2E System Test Agent

### 2.1 What it does

Hermetic end-to-end test harness for the trading system. **No real
orders. No real network. No real secrets. No LLM dependency.**

Three responsibilities:

1. **Discovery** — walks the repo, identifies monitors / shared
   modules / workflows / scripts / learning-loop / tests, and
   cross-references against a fixed 40-capability map
   (`tools/e2e_system_test_agent/coverage_model.py`).
2. **Inventory** — classifies every existing test as
   unit / integration / e2e / weak (a test with no `assert`).
3. **Run + report** — executes the test suites under a global
   no-network guard and produces JSON + Markdown reports with
   functional-coverage table.

### 2.2 Location

```
tools/e2e_system_test_agent/
├── __init__.py
├── main.py                  — orchestrator + CLI
├── discovery.py             — scans monitors / shared / workflows / tests
├── inventory.py             — classifies tests
├── coverage_model.py        — 40-capability fixed map
├── runners.py               — subprocess unittest invocations
├── report.py                — JSON + Markdown renderers
├── scenarios/               — reserved for future scenario builders
└── fixtures/
    ├── __init__.py
    ├── fake_alpaca.py
    ├── fake_market_data.py
    ├── fake_news.py
    ├── fake_social.py
    ├── fake_llm.py
    ├── fake_notify.py
    ├── fake_clock.py
    └── fake_state.py

scripts/e2e_system_test_agent.py  — thin CLI wrapper

tests/e2e/
├── conftest.py                          — no-network + safe-env + fixtures
├── test_no_network_guard_e2e.py
├── test_entry_lifecycle_e2e.py
├── test_news_social_lifecycle_e2e.py
├── test_options_lifecycle_e2e.py
├── test_emergency_remediation_e2e.py
├── test_learning_loop_e2e.py
├── test_code_autonomy_e2e.py
└── test_system_failure_modes_e2e.py
```

CI: `.github/workflows/e2e-system-tests.yml`.

### 2.3 How to run

```bash
# Full pipeline (discover + inventory + run E2E + report)
python3 scripts/e2e_system_test_agent.py

# Discovery + inventory only (no tests)
python3 scripts/e2e_system_test_agent.py --discover

# Run only the E2E suite
python3 scripts/e2e_system_test_agent.py --run-e2e

# Hard-lock network (sets NO_NETWORK=1)
python3 scripts/e2e_system_test_agent.py --no-network

# Markdown only on stdout, no files
python3 scripts/e2e_system_test_agent.py --format markdown --no-files

# Re-render existing latest.json
python3 scripts/e2e_system_test_agent.py --report-only

# Run tests directly via unittest (bypassing the agent)
python3 -m unittest discover -s tests/e2e -p "test_*.py" -v
```

Exit codes:
- `0` — PASS / WARN
- `2` — FAIL or BLOCKED

### 2.4 No-network / no-real-orders guard

`tests/e2e/conftest.py` is imported by every E2E test. On import:

1. **`requests.Session.request`** is replaced with a `NetworkBlocked`
   raiser; only `localhost` / `127.0.0.1` is allowed.
2. **`socket.socket.connect`** wraps the same way.
3. **Env scrub** — `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` /
   `FINNHUB_API_KEY` / `GMAIL_*` are removed from `os.environ` so the
   real `shared/alpaca_orders.py` would fail-loud if it ever ran.
4. **Safe defaults set** — `LLM_ENABLED=false`, `OPTIONS_ENABLED=true`,
   `RISK_PROFILE=BALANCED_PAPER`, `NO_NETWORK=1`,
   `USE_RISK_OFFICER=true`.

Confirmed by `test_no_network_guard_e2e.py::TestNoNetworkGuard`:
intentional `requests.get("https://api.alpaca.markets/...")` raises
`NetworkBlocked` before any HTTP I/O happens.

### 2.5 Fake clients

| Fake | What it stands in for | Key scenarios |
|---|---|---|
| `FakeAlpacaClient` | `/v2/account`, `/v2/positions`, `/v2/orders` (POST/GET), DELETE position, option chain, quote, paper-only verify | normal fill, no fill, API failure (`fail_mode='timeout'/'429'/'500'`), insufficient buying power, market closed, duplicate order |
| `FakeMarketData` | bars, latest quote, VIX, stale-symbol marker, market-open flag | fresh, stale, missing |
| `FakeNewsFeed` | News items dict with symbol/headline/source/published_at | fresh/stale/duplicate |
| `FakeSocialFeed` | Reddit spike + Bluesky post fixtures | spike, low-cred, high-cred |
| `FakeLLM` | LLM client | `disabled`/`timeout`/`invalid_json`/`hallucinated`/`valid` (scriptable) |
| `FakeNotify` | Email sender | captures in-memory, `assert_no_secret_leak()` method |
| `FakeClock` | Deterministic time | market hours, weekend, expiry date |
| `FakeState` | state.json | policy-enforced writes (raises `PermissionError` for unauthorized actor) |

Every fake is import-safe (no I/O at import time), side-effect-free,
and uses pure Python (no external deps beyond `requests` which is
already in the repo).

### 2.6 Coverage model

`tools/e2e_system_test_agent/coverage_model.py::CAPABILITIES` lists 40
capabilities grouped by area:

- **entry** (7): price/crypto/defense/geo/twitter/reddit/options monitors
- **exit** (5): exit_monitor / options_exit_monitor / emergency_close /
  panic_close_options / stale_order_cleanup
- **infra** (15): portfolio_risk / risk_officer / risk_guards /
  signal_confirmation / state_policy / state_schema / emergency_engine /
  remediation / audit / alpaca_orders / instrument_windows /
  peak_tracker / runtime_config / notify / autonomy
- **learning** (3): analyzer / adapter / learning_validation
- **code_autonomy** (2): patch_validator / code_autonomy
- **health** (4): trading_health / system_consistency / secret_scan /
  audit_workflows
- **workflows** (4): scheduled_monitors / autonomous_remediation_workflow /
  autonomous_code_loop_workflow / e2e_workflow

Each entry has a `module_path` (the implementation) and
`expected_tests` (the tests that should cover it). The report
cross-references and emits one of:

- `PASS` — module exists + unit + e2e present
- `PARTIAL` — module exists + unit only (no e2e yet)
- `UNCOVERED` — module exists but no tests
- `MISSING_MODULE` — module doesn't exist

### 2.7 Output format

JSON (`reports/e2e/latest.json`):

```json
{
  "overall_status": "PASS|WARN|FAIL",
  "generated_at": "...",
  "network_blocked": true,
  "summary": {"capabilities_total": 40,
              "capabilities_pass": 28,
              "capabilities_partial": 9,
              "capabilities_uncovered": 3,
              "capabilities_missing": 0},
  "test_inventory": {"total": 347,
                      "by_classification": {"unit": 281, "e2e": 65, "weak": 1, "integration": 0},
                      "without_asserts": 1},
  "test_runs": [
    {"suite": "tests/architecture_vnext", "ran": 155, "ok": true, ...},
    {"suite": "tests/e2e", "ran": 65, "ok": true, ...}
  ],
  "coverage": [
    {"capability": "price_monitor", "area": "entry", "status": "PASS", ...},
    ...
  ],
  "discovery": {"monitors": [...], "shared_modules": [...], ...}
}
```

Markdown is rendered from the same data with a functional-coverage
table.

### 2.8 Writing a new E2E scenario

1. Create `tests/e2e/test_<scenario>_e2e.py`. Import the conftest:

```python
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import conftest  # registers network blocker + safe env

from tools.e2e_system_test_agent.fixtures import (
    FakeAlpacaClient, FakeMarketData, FakeLLM, FakeNotify,
)
```

2. Use fakes — never real `requests.get` or real Alpaca client.

```python
def test_my_scenario(self):
    cli = FakeAlpacaClient(auto_fill=True)
    cli.set_quote("AAPL", bid=175.0, ask=175.10)
    order = cli.submit_order(symbol="AAPL", qty=10, side="buy",
                             type="limit", limit_price=175.10,
                             client_order_id="my-scenario-1")
    self.assertEqual(order["status"], "filled")
```

3. If you add a new capability, register it in `coverage_model.py`.

### 2.9 What the agent does NOT do

- Run backtests with live data (use `python -m backtest.run` for that)
- Hit external APIs
- Send emails
- Modify state.json or commit anything
- Substitute for `tools/system_consistency_agent/` — they're
  complementary

### 2.10 First-run result on this repo

`Overall: PASS, score N/A (status-based), 220 tests green` (155
architecture_vnext + 65 e2e). Functional coverage: 28/40 fully covered,
9 partial (unit-only), 3 uncovered (`exit_monitor`,
`scheduled_monitors`, `e2e_workflow`).

---

## 3. Workflow-step LLM personas (NOT separate agents)

These are configured by `learning-loop/routine-prompts.md` and live
inside Claude routines on claude.ai. They are NOT runnable from the
repo — they're invoked by the daily-learning + weekly-retro workflows
via Cloudflare Workers that wrap the Routines API.

They are documented here so future readers understand the full agent
landscape:

| Persona | Routine | When invoked | Output consumed by |
|---|---|---|---|
| **Senior PM** | `Learning Loop Strategist` | daily 21:00 UTC + weekly Sunday 22:00 UTC | `learning-loop/analyzer.py` → `safe_apply_overrides` → `validate_adaptation` |
| **Challenger** | `Learning Loop Challenger` | between Senior PM round 1 and round 3 | `learning-loop/analyzer.py::_apply_challenger_filter` (drops REJECTED proposals if revise fails) |
| **Reddit Curator** | `Reddit Signal Curator` | every reddit-monitor cron | `reddit-monitor/llm_curator.py::filter_signals_via_curator` |
| **Crypto Curator** | `Crypto Signal Curator` | every crypto-monitor cron | `crypto-monitor/llm_curator.py::filter_signals_via_curator` |
| **Options Handler** | `Options Handler` (legacy) | DEPRECATED | superseded by `AUTO_EXECUTE_OPTIONS=true` direct Alpaca REST path |

Crucially: **none of these can place an order on their own.** Their
output is always routed through `shared/alpaca_orders.py` which runs
the full deterministic gate stack (instrument_windows → portfolio_risk
→ risk_officer → broker). LLM output is metadata + ranking, never
authorisation.

If LLM_ENABLED=false (the default), all five personas no-op and the
system trades on its deterministic baseline (adapter heuristics +
hard-coded thresholds). The system is paper-only and trades safely
even when every LLM is offline.

### 3.1 Deterministic gate that all signals pass through

```
Signal source (any monitor)
      │
      ▼
[Gate 1] instrument_windows.can_trade_now()
      │
      ▼
[Gate 2] shared/alpaca_orders._portfolio_risk_gate()
      │   (portfolio_risk.evaluate_portfolio_risk)
      │
      ▼
[Gate 3] shared/risk_officer.evaluate_trade()
      │
      ▼
Alpaca REST /v2/orders (PAPER ONLY)
      │
      ▼
shared/notify.notify_*  +  journal/trades-*.md
```

Every gate is deterministic Python. LLM never sits on this path.

### 3.2 Risk-officer (deterministic, NOT an LLM)

`shared/risk_officer.py::evaluate_trade(proposal) -> {decision, ...}`.
Replaces the old agent-based `.claude/agents/risk-officer.md`.
Synchronous, runs the 9 hard checks (whitelist / size cap / SL exists /
R:R / per-ticker concentration / daily drawdown / VIX HALT) + 4 soft
warnings, returns the canonical APPROVE/REJECT envelope.

Opt-out via `USE_RISK_OFFICER=false` (used by backtests). Never
disabled in production.

---

## 4. Cross-agent invariants

Both agents (and every LLM persona) operate under these invariants:

1. **Paper-only forever.** `shared/autonomy.py::assert_paper_only` is
   the single source of truth; any non-paper URL raises
   `PaperOnlyViolation`.
2. **No human approval anywhere in trading lifecycle.** Verified by
   `system_consistency_agent` (static repo scan) and
   `e2e_system_test_agent` (dynamic test).
3. **No real orders in tests.** Verified by `e2e_system_test_agent` —
   `conftest.py` blocks network + scrubs secrets.
4. **No paid deps.** Verified by `system_consistency_agent::free_tier`
   (greps requirements.txt for known paid SaaS markers) and
   `patch_validator` (blocks new dependency additions in patches).
5. **No LLM bypass of risk gates.** Verified at every layer:
   `safe_apply_overrides` (whitelist) → `state_schema.validate_state`
   (clamp + drop) → `validation.validate_adaptation` (sample size).
6. **No autonomous code change to safety contract.**
   `patch_validator.py` is in its own `FORBIDDEN_PATHS` — the validator
   cannot be modified by the code-autonomy loop.

If any of these invariants fail, the responsible agent will surface a
BLOCKED / FAIL status and CI will block merge.

---

## 5. Operator quick reference

```bash
# Check if system is structurally healthy (consistency)
python3 scripts/system_consistency_agent.py

# Check if system can trade right now (real Alpaca + state)
python3 scripts/trading_health.py

# Check if E2E tests are green
python3 scripts/e2e_system_test_agent.py

# Manual autonomous remediation cycle (dry-run safe)
python3 scripts/autonomous_remediation.py --dry-run

# Validate a patch before merge
python3 scripts/autonomous_code_review.py path/to/patch.diff

# Panic close all options (dry-run by default)
python3 scripts/panic_close_options.py
# Real: CONFIRM_PANIC_CLOSE_OPTIONS=true ...
# Auto: AUTONOMOUS_PANIC_CLOSE_OPTIONS=true ... (no human in loop)
```

The two CI agents run automatically every push/PR + daily. Operator
intervention is OPTIONAL — the system handles its own consistency and
testing without needing the operator to remember to run anything.

## v3.30 addendum — LLM authority is still advisory only

v3.30 ships the canary pre-executor (preflight-only) and observation
records. None of this changes the LLM authority model:

- LLM agents remain bounded by L0–L4 with `L5_EXECUTE_FORBIDDEN` as
  the sentinel.
- LLM agents cannot place orders, cannot flip broker flags, cannot
  force the canary unlock, cannot mutate risk gates, cannot count
  their own output as real-market evidence.
- LLM output never increments
  `real_market_opportunities_count`.
- Observation records (`record_type=NO_TRADE_OBSERVATION`) are
  diagnostic only and never count toward the unlock gate.
- The canary pre-executor stops at
  `CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED` — no
  order is placed in v3.30.

The audit-board arbiter's regression triggers for these invariants
are pinned in `agents/prompts/00_shared_context.md` under "v3.30
coverage."
