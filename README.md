# trading-system

Fully autonomous, paper-only intraday trading system on Alpaca. Free-tier
operation (GitHub Actions + Alpaca Paper + free data sources). Designed to
maximize expected edge / profit within controlled risk **without manual
approvals**.

## What it is

- **Paper-only** (enforced by `assert_paper_only` invariant — system refuses to
  operate against any non-paper Alpaca endpoint)
- **Autonomous** — no manual approval required for any trade. Every decision
  is classified into one of 5 verdicts (BLOCK / DEFER / DOWNSIZE / ALLOW /
  ALERT_ONLY) and acted on automatically
- **Intraday-first** — optimized for fast cron-driven signal flow during US
  market hours; allocator runs 5 min after open
- **Free to run** — GitHub Actions, Alpaca Paper, Bluesky, SEC EDGAR, House
  Clerk XML, NewsAPI free, Yahoo public chart. No paid services anywhere
- **Defensive against transient failures** — survives Anthropic LLM outage,
  GitHub Actions cron-skip, Alpaca API outage, market closure

## What it is NOT

- A live-trading system (paper-only is structurally enforced)
- A system that requires human approval
- A system that promises profit

## Quick start (operator)

```bash
# Health check
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'shared')
from pretrade_snapshot import get_snapshot, classify_snapshot_for_intraday
s = get_snapshot(force_refresh=True)
print(s.to_summary())
"

# Recent workflow runs
gh run list --limit 20

# Today's incidents (Layer 1 detector findings)
cat learning-loop/incidents/$(date -u +%Y-%m-%d).md 2>/dev/null

# Today's audit decisions
tail -20 journal/autonomy/$(date -u +%Y-%m-%d).jsonl 2>/dev/null

# Backtest (realistic + walk-forward)
.venv/bin/python3 -m backtest.run \
    --strategy momentum-long --tickers AAPL MSFT --days 60 \
    --mode both --walk-forward 3
```

## Architecture (v3.11.2 — 2026-05-29)

**Five defense layers + EDGE-FIRST gates + reliable cron driver:**

1. **Layer 1 — incident pattern detector** (`scripts/incident_pattern_detector.py`)
   Cron */5 24/7 (via Cloudflare). 12 known anomaly patterns (geo-* prefixes
   added v3.11.1). Zero LLM. Auto-disable opt-in.
2. **Layer 2 — centralized SELL + lint test gate** (`shared/alpaca_orders.py::safe_close`)
   Single entry point for all sell/exit/buy-to-cover. AST lint test
   `test_no_naked_sell_v3910.py` FAILS CI if anyone adds direct `requests.post(
   /v2/orders, side='sell'|'buy')` outside ALLOWED_FILES.
3. **Layer 3 — plan staleness defense** (`_revalidate_plan_against_live` in
   `scripts/execute_allocation_plan.py`)
   Fetches live Alpaca positions before allocator exec; drops stale orders.
4. **Layer 4 — cron reliability** (`entry-monitors-watchdog.yml` matrix 12)
   PAT-based retrigger when GitHub Actions cron-skip happens.
5. **Layer 5 — EXTERNAL cron driver** (`cloudflare-workers/cron-trigger/`)
   Cloudflare Worker (free tier, 99.99% SLA) fires `*/5`, `*/15`, weekday
   `45 13 UTC` cron triggers calling GitHub `workflow_dispatch` API.
   **Bypasses GH Actions schedule cron-skip** (observed 2.8-12% delivery rate
   on 2026-05-29 → fixed to ~100% via Worker). Production verified at
   45× pre-deploy monitor activity.

Plus **v3.10 unified risk taxonomy** (`shared/risk_classification.py`):
all risk gates return one of `BLOCK / DEFER / DOWNSIZE / ALLOW / ALERT_ONLY`
with a `decision_id` for cross-component audit correlation.

Plus **v3.11 EDGE-FIRST** gates (default OFF, opt-in after backtests):
- `learning-loop/edge_validator.py` — strategy must pass realistic-mode
  backtest (WR ≥ 50%, PF ≥ 1.3, MDD < 20%, n ≥ 10) to remain `enabled=true`
- `shared/kelly_sizing.py` — quarter-Kelly position sizing
- `shared/earnings_calendar.py` — ±1d earnings blackout
- v3.11.1 zombie-prune: distinguish pipeline_failure (don't disable) from
  no_edge (auto-disable after 21d SILENT with ≥5 placement attempts)

## Detailed docs

- **`docs/RUNBOOK.md`** — full operations runbook (kill-switches, daily loss,
  giveback protection, disaster recovery, health checks)
- **`docs/STRATEGY.md`** — strategy contract (sizing rules, regime detection,
  asset-class caps)
- **`docs/PRODUCT.md`** — system architecture + tech stack (1500+ lines)
- **`docs/INCIDENT-2026-05-22-positions-closed.md`** — incident post-mortems
  + v3.9.6 / v3.9.9 / v3.9.10 fix explanations
- **`CLAUDE.md`** — full session history + iron rules + live state

## Repo layout

```
shared/                       Risk gates, order execution, classification, snapshots
learning-loop/                Analyzer, adapter, validation, allocations, incidents
backtest/                     Strategies + replay + realism (idealized + realistic modes)
{price,crypto,options,options-exit,exit,defense,geo,twitter,reddit,politician}-monitor/
                              Per-source signal monitors
scripts/                      Operator + autonomous scripts (incident detector, forensic,
                              allocator executor, agents)
tools/{strategy_coherence,system_consistency,e2e_system_test}_agent/
                              Audit agents (run locally or in CI)
tests/                        Unit + e2e + architecture tests (290+ green)
journal/autonomy/             Append-only audit JSONL per day
docs/                         All documentation
config/                       JSON config (aggressive_profile, watchlists, etc.)
.claude/rules/                Whitelists + per-source rules
.github/workflows/            29+ cron-driven workflows
```

## Constraints (architectural — DO NOT change)

- Paper-only (`assert_paper_only` raises on non-paper URL)
- No paid services anywhere
- No manual approval as main safety
- No removal of risk gates (only refinement of classification)
- Aggressive intraday character preserved in `AGGRESSIVE_PAPER` profile

See `CLAUDE.md` for full Iron Rules + `docs/STRATEGY.md` v3.10.
