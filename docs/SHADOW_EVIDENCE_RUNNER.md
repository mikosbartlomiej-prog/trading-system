# Shadow Evidence Runner (v3.21.0 — ETAP 2)

`scripts/run_shadow_evidence_cycle.py` is the deterministic daily
runner that turns the v3.20 evidence-production primitives into a
single CLI. It is **paper-only**, **non-auto-apply**, and **never
bypasses the risk engine**.

This module is reviewed by the Multi-Agent Audit Board and is
governed by Strategy Quality Gate. It is the answer to audit board
cross-cutting theme **STRAT-003** ("strategy validation deficit"):
before `EDGE_GATE_ENABLED` can ever flip, we need a continuous
deterministic stream of per-gate paper evidence. This runner produces
that stream.

---

## Invariants

Asserted at startup and re-asserted inside `run_cycle()`:

| Invariant | Meaning |
|---|---|
| `LIVE_MODE_NOT_SUPPORTED = True` | The CLI rejects `--mode live`. No live URL appears in source. |
| `RUNNER_NEVER_BYPASSES_GATES = True` | Every shadow fill must pass the same risk officer used by paper trading. |
| `RUNNER_NEVER_PLACES_BROKER_ORDERS = True` | The runner contains zero HTTP. `--mode broker` is delegated to `evidence_production` (which carries its own `assert_paper_only`). |

The CLI carries no live-trading code paths whatsoever. There is no
`LIVE` / `LIVE_APPROVED` / `LIVE_ENABLED` status anywhere.

---

## CLI

```text
python -m scripts.run_shadow_evidence_cycle \
    --mode {signal_only,shadow,broker} \
    [--dry-run]
```

- `--mode signal_only` (default): observe-only. Opportunity ledger
  entries are written; shadow ledger is NOT written.
- `--mode shadow`: write shadow ledger entries for gate-accepted
  signals via `evidence_production.estimate_shadow_fill`.
- `--mode broker`: delegate to `evidence_production.produce_evidence`,
  which routes to the existing paper-only broker path. The runner
  itself stays HTTP-free.

`--dry-run` skips all on-disk writes (opportunity ledger, shadow
ledger, report). Stdout still receives the JSON summary so the
operator can audit the proposed writes.

---

## Pipeline

1. Load `config/aggressive_profile.json` + `learning-loop/state.json`.
2. Load active (non-allocator) strategies from `state.json::strategies`.
3. Load the freshest `learning-loop/universe_ranking_*.json` if any.
4. Read `runtime_state.json::pre_open_plan` if any.
5. Kill-switch check (`shared/defensive_mode.py`) — exit early
   when armed.
6. Safe-mode check (`shared/safe_mode.py::gate_new_entry`) — record
   opportunities but defer shadow fills when active.
7. For each active strategy:
   - Build a SHADOW observation signal from the ranking (no new
     strategy logic).
   - Run gate stack:
     `confidence → quality → universe → regime → risk_engine`.
   - Always append a record to the
     `signal_opportunity_ledger` (every observed signal — accepted or
     rejected).
   - If every gate `PASS`-es and the mode allows, call
     `evidence_production.produce_evidence`.
   - Register the signal id for counterfactual outcome tracking
     (metadata only — actual computation is deferred to
     `counterfactual_outcomes`).
8. Render the daily report at
   `docs/shadow_evidence_cycle_LATEST.md`.

---

## What the runner does NOT do

- Does NOT flip `EDGE_GATE_ENABLED`.
- Does NOT promote any quarantined variant.
- Does NOT mutate strategies or thresholds.
- Does NOT call any LLM.
- Does NOT add paid services.
- Does NOT introduce a live-trading mode.
- Does NOT mix BACKTEST / REPLAY / COUNTERFACTUAL records with
  BROKER_PAPER records — the source separation is enforced upstream
  by `shared/evidence_source.py`.

---

## Files written

| Path | Owner | When |
|---|---|---|
| `learning-loop/opportunity_ledger/<date>.jsonl` | `signal_opportunity_ledger` | Every observed signal |
| `learning-loop/shadow_ledger/<date>.jsonl` | `evidence_production` | Only in `--mode shadow` for gate-accepted signals |
| `docs/shadow_evidence_cycle_LATEST.md` | `run_shadow_evidence_cycle.py` | Once per run |

The workflow `scripts/workflow-templates/shadow-evidence-cycle.yml`
adds these three paths to its narrow `git add` block. The workflow
basename is allow-listed in `scripts/audit_workflows.py`.

---

## Operational notes

- Default workflow cron is `30 22 * * 1-5`, which is AFTER
  `paper-experiment-update.yml` (22:00 UTC) so the freshest paper
  experiments are visible to the cycle.
- `workflow_dispatch` exposes `mode` and `dry_run` inputs.
- The workflow YAML hard-locks `EVIDENCE_PRODUCTION_MODE=SIGNAL_ONLY`
  in `env:`. Operator must explicitly choose `shadow` or `broker` via
  `workflow_dispatch` for actual shadow writes — a re-paste cannot
  silently enable them.

---

## v3.22 note (2026-06-15) — strategy registry + market-data diagnostics

v3.22 expanded the shadow opportunity generator's strategy registry
beyond the original four. The new registry covers the full
production-monitor set (`price`, `crypto`, `options`, `defense`,
`geo`, `twitter`, `reddit`, `politician`) so the shadow runner can
fan out evidence collection across every strategy the live monitors
would have fired.

The shadow runner also gained market-data diagnostics: each per-cycle
report now carries `market_data_diagnostics.symbols_skipped_stale`
and `symbols_skipped_provider_error` so an operator can tell at a
glance whether a thin evidence day is a strategy problem or a data
problem.

Hard-safety invariants are unchanged:

- `EVIDENCE_PRODUCTION_MODE=SIGNAL_ONLY` is the default and the only
  mode the cron picks. `shadow` and `broker` modes remain
  operator-driven.
- The runner NEVER imports `alpaca_orders` (asserted by
  `tests/test_shadow_universe_expansion_v3300.py`).
- `evidence_runner_no_live_mode` still holds — `--mode live` is
  rejected by argparse.
