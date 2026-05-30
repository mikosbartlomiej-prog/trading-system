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

## Architecture (v3.13.0 — 2026-05-30)

**Five defense layers + Confidence + Safe-mode + Audit Board:**

### Runtime layers (deterministic, no LLM in critical path)

1. **Layer 1 — incident pattern detector** (`scripts/incident_pattern_detector.py`)
   Cron */5 24/7 (via Cloudflare). 13 known anomaly patterns (P01-P13, last
   added v3.11.3: `P13_bracket_interlock_blocked_close`). Zero LLM. Auto-disable opt-in.
2. **Layer 2 — centralized SELL + lint test gate** (`shared/alpaca_orders.py::safe_close`)
   Single entry point for all sell/exit/buy-to-cover. v3.11.3: now auto-cancels
   bracket OCO children BEFORE close (fixes 2026-05-29 incident where governor
   protective closes were blocked by `held_for_orders`). AST lint test
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
   pre-deploy → ~100% via Worker). Production verified at 45× pre-deploy
   monitor activity.

### Decision quality stack (v3.10 → v3.12 → v3.13)

- **v3.10 unified risk taxonomy** (`shared/risk_classification.py`):
  all risk gates return one of `BLOCK / DEFER / DOWNSIZE / ALLOW / ALERT_ONLY`
  with a `decision_id` for cross-component audit correlation.
- **v3.11 EDGE-FIRST** gates (default OFF, opt-in after backtests):
  `learning-loop/edge_validator.py` (WR≥50%, PF≥1.3, MDD<20%, n≥10),
  `shared/kelly_sizing.py` (quarter-Kelly), `shared/earnings_calendar.py`
  (±1d earnings blackout). v3.11.1 zombie-prune distinguishes
  pipeline_failure from no_edge.
- **v3.11.3 part 3 crypto-oversold-bounce** path in `crypto-monitor`:
  bypasses predator-bracket [3%, 15%] when `RSI ≤ 30 + 24h-move ≥ -10%
  + 1-bar reversal + ≥50% normal volume`. Solves 45-day SILENT period.
- **v3.12.0 unified confidence score** (`shared/confidence.py`):
  deterministic 5-component score (data_quality 0.20 / signal_strength 0.30
  / regime_alignment 0.20 / system_health 0.15 / risk_state 0.15).
  Thresholds `ALLOW≥0.65 / ALERT_ONLY≥0.50 / BLOCK<0.50`. Wired into
  `risk_officer.evaluate_trade` (backward-compat: legacy callers warn-only).
- **v3.12.0 safe_mode** (`shared/safe_mode.py`): runtime-operational state
  (different from `defensive_mode` which is risk-driven). 5 triggers:
  ACCOUNT_OUTAGE / AUDIT_GAP / STALE_DATA / CONFIDENCE_BROKEN / OPERATOR.
  Effects: blocks NEW entries, halves `size_multiplier`, raises confidence
  threshold +0.10. Emergency closes ALWAYS bypass.
- **v3.12.0 heartbeat** (`shared/heartbeat.py`): per-component liveness
  in `runtime_state.json::heartbeat`. Feeds `confidence.system_health`.
- **v3.12.0 session reporter** (`scripts/session_report.py`): local
  end-of-session markdown report with risk flags + state + decisions
  breakdown. Writes to `reports/sessions/<date>_<ts>.md`.

### Review layer (NOT runtime brain — offline only)

- **v3.13.0 Multi-Agent Audit Board** (`agents/`): 11 area-specialist
  prompt-based reviewers + Final Arbiter. Used for design / code / risk /
  data / confidence / runtime / testing / docs / simplicity / security /
  free-ops review. **Cannot trade, cannot modify risk params, cannot
  recommend live trading.** See `agents/README.md`.
- **Deterministic audit tools** (`tools/*_agent/`): CI gates that run
  every push — system_consistency (76 checks), strategy_coherence
  (75 checks), e2e_system_test (40 capabilities).

## Detailed docs

- **`docs/RUNBOOK.md`** — full operations runbook (kill-switches, daily loss,
  giveback protection, safe_mode, confidence gate, disaster recovery)
- **`docs/STRATEGY.md`** — strategy contract (sizing rules, regime detection,
  asset-class caps, crypto-oversold-bounce path)
- **`docs/PRODUCT.md`** — system architecture + tech stack (1500+ lines)
- **`docs/AUTONOMY_CONTRACT.md`** — formal autonomy contract + invariants
- **`docs/AGENTS_DOCUMENTATION.md`** — deterministic audit tools + Multi-Agent Audit Board
- **`docs/INCIDENT-2026-05-22-positions-closed.md`** — incident post-mortems
- **`agents/README.md`** — Multi-Agent Audit Board usage guide
- **`CLAUDE.md`** — full session history + iron rules + live state

## Repo layout

```
shared/                       Risk gates, order execution, classification, snapshots,
                              confidence/safe_mode/heartbeat (v3.12.0)
learning-loop/                Analyzer, adapter, validation, allocations, incidents
backtest/                     Strategies + replay + realism (idealized + realistic modes)
{price,crypto,options,options-exit,exit,defense,geo,twitter,reddit,politician}-monitor/
                              Per-source signal monitors (11 total)
scripts/                      Operator + autonomous scripts (incident detector, forensic,
                              allocator executor, session_report)
tools/{strategy_coherence,system_consistency,e2e_system_test}_agent/
                              Deterministic audit agents (CI gates)
agents/                       Multi-Agent Audit Board (review-only, v3.13.0):
                              11 area reviewers + Final Arbiter + schemas + runner
tests/                        Unit + e2e + architecture tests (380+ green in primary suites)
journal/autonomy/             Append-only audit JSONL per day
reports/                      Generated reports (sessions/, system-consistency/,
                              strategy-coherence/, e2e/)
docs/                         All documentation
config/                       JSON config (aggressive_profile, watchlists, etc.)
cloudflare-workers/           Free-tier Worker (cron-trigger Layer 5)
.claude/rules/                Whitelists + per-source rules
.github/workflows/            29+ cron-driven workflows
```

## Constraints (architectural — DO NOT change)

- Paper-only (`assert_paper_only` raises on non-paper URL)
- No paid services anywhere
- No manual approval as main safety
- No removal of risk gates (only refinement of classification)
- Aggressive intraday character preserved in `AGGRESSIVE_PAPER` profile
- High confidence CANNOT override `risk_officer` REJECT
- `safe_mode.active=true` BLOCKS new entries (emergency closes bypass)
- Audit Board agents are review-only — never in runtime decision path
- Live trading permanently blocked (structural invariant)

See `CLAUDE.md` for full Iron Rules + `docs/STRATEGY.md` for current
strategy contracts.
