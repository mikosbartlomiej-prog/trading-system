# Operator Dashboard

> v3.19.0 (2026-06-04) — daily situational overview for the paper trading
> operator. Read-only by contract.

## What it shows

`scripts/daily_operator_dashboard.py` writes two files:

- `docs/operator_dashboard_LATEST.md` — human-readable markdown
- `docs/operator_dashboard_LATEST.json` — machine-readable mirror

Both contain 13 sections answering the questions you actually have
before each paper session:

1. **System health summary** — heartbeat ratio, safe_mode state, last incident
2. **Heartbeat 11/11** — per-component liveness from
   `learning-loop/runtime_state.json::heartbeat`
3. **Paper workflow status** — whether
   `scripts/workflow-templates/paper-experiment-update.yml` exists +
   whether the deployed `.github/workflows/` copy is live
4. **Paper trades collected** — count and per-strategy breakdown of records
   in `learning-loop/paper_experiments/*.jsonl`
5. **Strategies with most evidence** — top by `n_closed`
6. **Weakest strategies** — lowest PF + WR + `last_20_win_rate` flag
7. **Confidence buckets actually-working** — aggregate per-bucket WR + netP&L
8. **Best instruments to observe** — read from
   `docs/universe_ranking_LATEST.md` when present, otherwise from
   `config/market_universes.json::US_LARGE` or `config/watchlists.json`
9. **Can `EDGE_GATE_ENABLED` flip?** — delegates to
   `shared.strategy_quality_gate.edge_gate_decision`
10. **Why not?** — explicit list of blockers
11. **Active P0/P1 backlog items** — scans
    `learning-loop/heuristic_proposals.md` for open `- [ ]` items tagged
    `P0` or `P1`
12. **Is system still free?** — checks `docs/FREE_TIER_LIMITS.md` presence
    and scans `config/*.json` for paid-host hints
13. **Is live trading disabled?** — verifies `shared.autonomy.PAPER_BASE_URL`,
    `assert_paper_only` refusing live URLs, and absence of any `LIVE_*`
    strategy status

## How to read it

Each section either reports data or is marked
`unavailable — <reason>`. A section being unavailable does NOT block any
other section. A safe default is: until you see at least
**n_closed ≥ 50** in every enabled strategy with PF ≥ 1.3 and WR ≥ 50%,
`EDGE_GATE_ENABLED` cannot flip true. Section 10 (blockers) lists exactly
why not.

Routine cadence:

- Run the script once after each paper session has closed (~22:00 UTC)
- Re-run before next-day market open (~13:00 UTC) to see overnight
  audit/incident changes
- If a paper trading workflow is configured, the workflow can run the
  script and commit `docs/operator_dashboard_LATEST.{md,json}` so the
  operator just opens GitHub and reads the markdown

## When to act on findings

| Section | Trigger | Action |
|---------|---------|--------|
| 1 | Safe mode active OR last_incident == SAFE_MODE_ENTERED | Stop new entries until trigger cleared |
| 2 | Heartbeat < 100% (any stale component) | Investigate the stale monitor; do not auto-enable strategies on top of stale data |
| 3 | TEMPLATE_READY_NOT_DEPLOYED | Operator paste workflow into `.github/workflows/` |
| 4 | empty == true | Wait for trades to accumulate; do not flip EDGE_GATE |
| 5 | A strategy has high `n_closed` but PF < 1.0 | Pause via `learning-loop/state.json::strategies.<name>.enabled` |
| 6 | `recent_degradation == true` | Auto-disable per strategy_quality_gate v3.18 logic |
| 7 | Bucket WR drops below 50% on ≥ 10 trades | Re-calibrate confidence thresholds in `config/aggressive_profile.json::confidence` |
| 8 | Universe ranking file missing | Operator runs the universe ranker (separate workflow) |
| 9 | `allow_flip == false` for > 7 days | Review section 10 blockers — typically need more paper evidence |
| 10 | Any unresolved P0/P1 line | Address first before adding new features |
| 11 | P0 count > 0 | Backlog is the priority queue — drain it before scope expansion |
| 12 | `is_free == false` | Stop and audit; system contract is $0/month |
| 13 | `live_disabled == false` | This is a P0 incident. Open an issue immediately. |

## Why no live trading recommendation

The audit-board final decision 2026-06-02 (v3.14.0 cycle) is
`APPROVE_PAPER_TRADING_WITH_WARNINGS + NOT_SAFE_FOR_LIVE_TRADING`. That
decision cannot be over-ridden by a dashboard. Therefore this report
NEVER says "ready for live". The most positive language it allows is
"all paper criteria currently satisfy quality-gate thresholds — operator
MAY consider extending observation window".

Section 13 actively re-verifies the paper-only invariant on every run.
If the invariant slips, section 13 reports `live_disabled == false`,
which the operator should treat as a P0 incident requiring immediate
investigation.

## Free local operation

The script:

- reads only local files (`learning-loop/`, `config/`, `journal/`,
  `docs/`, `agents/reports/`)
- does NOT call Alpaca, Bluesky, Anthropic, OpenAI, GitHub, or any
  paid SaaS
- can be run on a laptop in a Python 3.11 venv with **zero** paid keys
- imports work via `sys.path.insert(_REPO_ROOT)` — no `pip install`
  beyond stdlib

This is intentional. Section 12 verifies it every run.

## CLI usage

```
# Write both files into docs/
python3 scripts/daily_operator_dashboard.py

# Print markdown to stdout without writing anything
python3 scripts/daily_operator_dashboard.py --no-write

# Custom output directory
python3 scripts/daily_operator_dashboard.py --out-dir /tmp/dash
```

Exit code 0 on success. Exit code 1 if data collection itself fails
(should be impossible — every section is fail-soft and emits an
`unavailable` payload instead of raising).

## Related modules

- `shared/heartbeat.py` — `health_snapshot()`, `EXPECTED_COMPONENTS`
- `shared/safe_mode.py` — `read_state()`
- `shared/paper_experiment.py` — `compute_strategy_metrics`
- `shared/strategy_quality_gate.py` — `classify_strategy`,
  `edge_gate_decision`
- `shared/universe_selector.py` — `get_universe`
- `shared/autonomy.py` — `PAPER_BASE_URL`, `assert_paper_only`
- `backtest/strategy_registry.py` — list of strategies in scope
- `learning-loop/heuristic_proposals.md` — P0/P1 backlog source
- `docs/FREE_TIER_LIMITS.md` — free-operation contract
