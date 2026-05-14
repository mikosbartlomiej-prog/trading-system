# System Consistency Agent

Deterministic auditor for the trading-system repo. Long-term guardian
of the eight system principles:

1. paper-only,
2. fully autonomous trading,
3. bounded autonomous code changes,
4. deterministic execution,
5. free-first,
6. risk-managed,
7. auditable,
8. coherent (workflows + docs ↔ code).

No LLM. No paid deps. Read-only against the working tree.

## Quick start

```bash
# Markdown + JSON to reports/system-consistency/
python3 scripts/system_consistency_agent.py

# JSON only (for CI parsing)
python3 scripts/system_consistency_agent.py --json --no-files

# Run a single category
python3 scripts/system_consistency_agent.py --category paper_only

# Strict mode — WARN escalates exit code to 1
python3 scripts/system_consistency_agent.py --strict

# Non-blocking — FAIL exits 1 instead of 2
python3 scripts/system_consistency_agent.py --non-blocking
```

## Reading the report

Default outputs:

- `reports/system-consistency/latest.json` — machine-readable
- `reports/system-consistency/latest.md` — human-readable
- `reports/system-consistency/YYYYMMDDTHHMMSSZ.{json,md}` — timestamped snapshot

Top of the report:

- **Overall**: `PASS` / `WARN` / `FAIL` / `BLOCKED`
- **Score**: weighted 0-100 (see "Scoring" below)
- **Repo SHA**: HEAD commit at audit time

Per-category scorecard table with PASS/WARN/FAIL/SKIP counts.

## Status meanings

| Status | Meaning | Exit code |
|---|---|---|
| `PASS` | All checks green | 0 |
| `WARN` | Non-blocking issues (backlog) | 0 (1 with --strict) |
| `FAIL` | At least one check failed but none are blocking | 2 (1 with --non-blocking) |
| `BLOCKED` | A blocking principle violated (live trading, removed risk gate, missing validator, leaked secret, …) | 2 |

`BLOCKED` overrides everything else — the trading system is structurally
unsafe until the blocking finding is fixed.

## Categories (15 total)

| Category | Weight | What it enforces |
|---|---:|---|
| `paper_only` | 15 | No live endpoint, paper-only guard wired, no `LIVE_TRADING=true` |
| `trading_autonomy` | 12 | No "approval needed" wording in trading code; decision enum present |
| `deterministic_execution` | 12 | Order path runs through `portfolio_risk` + `risk_officer`; LLM has kill switch |
| `portfolio_risk` | 10 | Module + API + 3 risk profiles + correlated buckets; wired into order path |
| `code_autonomy` | 10 | `patch_validator` exists, self-modify forbidden, blocks live + test-skip |
| `options_safety` | 8 | OPTIONS_ENABLED default false, liquidity gate, autonomous panic-close path |
| `state_policy` | 7 | Actor allowlist, validator, no state.json commits from monitors |
| `emergency_remediation` | 7 | Engine + actions + cooldown |
| `workflows` | 6 | concurrency on schedule workflows; git-write ↔ contents:write parity |
| `security` | 5 | secret scan clean, audit script clean |
| `documentation` | 5 | All key docs present + key invariants confirmed |
| `signal_confirmation` | 5 | Module + 4 news monitors wiring |
| `learning_loop` | 4 | Sample-size + step bounds + once-per-day |
| `auditability` | 4 | `shared/audit.py` + full Decision schema + writers wired |
| `free_tier` | 3 | LLM default off, no paid deps, no LLM import in execution |

Total weight = 113. Score is normalised to 0-100.

## Scoring

Each category contributes up to its `weight` points:

- All PASS in the category → full weight.
- Each non-blocking `FAIL` costs `weight × 60% / n` (n = number of findings).
- Each `WARN` costs `weight × 25% / n`.
- A blocking `FAIL` in a category → category score = 0.

Aggregate score = `sum(category_scores) / 113 × 100`.

## When CI fails

`.github/workflows/system-consistency-audit.yml` runs on every push, PR,
and daily 06:15 UTC. The job fails when:

- The agent exits non-zero (BLOCKED, or FAIL without `--non-blocking`).
- (With `--strict`: also WARN.)

The full report is uploaded as a CI artifact (`system-consistency-report`)
with 30-day retention.

## What to do at each status

### `BLOCKED`
Stop. Read the "Blocking failures" section. Common causes:

- Live endpoint accidentally introduced
- Risk gate removed from `shared/alpaca_orders.py`
- `patch_validator.py` modified to bypass itself
- Leaked secret pattern in code
- Missing core module (`portfolio_risk.py`, `emergency_engine.py`, …)

Fix the issue, run the agent locally to confirm, then commit.

### `FAIL`
Something non-critical is broken. Treat as backlog. The trading system
is still safe, but a regression has crept in.

### `WARN`
Backlog / nice-to-have. Common: news monitor not yet wired to
`signal_confirmation`, optional cleanup pattern missing.

### `PASS`
You're good.

## Adding a new check

1. Create `tools/system_consistency_agent/checks/<category>.py` (or extend an existing one).
2. Implement `run(root: Path) -> list[Finding]`.
3. Each Finding needs: `id`, `category`, `severity`, `status`, `message`, `principle`, optional `evidence`, `recommendation`, `blocking`.
4. If it's a new category, register it in `checks/__init__.py::CATEGORY_MODULES`.
5. Add a fixture-based test in `tests/architecture_vnext/test_system_consistency_agent.py`.

Example skeleton:

```python
from pathlib import Path
from ..models import Finding

CATEGORY = "my_category"
PRINCIPLE = "MY_PRINCIPLE"

def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    # ... your check ...
    findings.append(Finding(
        id="MY_CHECK_X",
        category=CATEGORY, severity="PASS", status="PASS",
        message="X is fine", principle=PRINCIPLE,
    ))
    return findings
```

## Architectural notes

- **Deterministic only**: no LLM, no network calls. Walks the working tree.
- **Read-only**: never writes to repo paths. Writes only to `--output-dir` (default `reports/system-consistency/`).
- **Modular**: each category is one file in `tools/system_consistency_agent/checks/`.
- **CI-friendly**: returns JSON for machines, Markdown for humans.

## Example output (current repo)

```
Overall: WARN (score 99.1/100)
Principle scorecard:
  paper-only ✅
  fully autonomous trading ✅
  bounded autonomous code changes ✅
  deterministic execution ✅
  free-first ✅
  risk-managed ✅
  auditable ✅
  coherent ✅

Warnings (2):
  - signal_confirmation: news monitors not yet wired (backlog)
  - options_safety: options-exit-monitor dedup pattern not statically detectable
```
