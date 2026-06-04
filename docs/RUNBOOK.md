# Operations Runbook — Trading System

**Version:** v3.10 (2026-05-27)
**Mode:** Paper-only Alpaca · Autonomous · Intraday-first · Free-tier
**Audience:** Operator (single user). Day-to-day operations + incident handling.

---

## What this system is

A fully autonomous, paper-only intraday trading system on Alpaca. Designed to:

- Maximize expected edge / profit within controlled risk
- Operate without manual approvals
- Stay free to run (GitHub Actions, Alpaca Paper, free data sources only)
- Survive transient failures (Anthropic LLM down, GitHub Actions cron-skip,
  Alpaca API outages, market closures) without paralyzing trading

What it is NOT:
- A live-trading system (paper-only invariant enforced by `assert_paper_only`)
- A passive defensive system that requires human approval for trades
- A system that promises profit (use backtest realistic mode for hypothesis
  selection, not as gain forecast)

---

## Risk taxonomy (BLOCK / DEFER / DOWNSIZE / ALLOW / ALERT_ONLY)

v3.10 introduces a unified 5-class risk verdict (`shared/risk_classification.py`)
that ALL risk gates return. The system is intraday-first: only the most critical
failures BLOCK a trade. Most uncertainty downsizes or alerts.

| Verdict | Meaning | Caller action |
|---|---|---|
| **BLOCK** | Critical risk control missing | Never place order. Examples: paper-only invariant violated, account_blocked=true, off-whitelist symbol, buying_power < size, daily drawdown HALT (-12%). |
| **DEFER** | Transient unavailability; retry next cron | Don't place order now. Examples: Alpaca account fetch failed, market closed for intraday signal. |
| **DOWNSIZE** | Partial uncertainty but edge alive | Multiply intended size by `size_multiplier` (0.1-2.0) and proceed. Examples: snapshot partial (positions fetch failed), strong news signal + partial market confirmation. |
| **ALERT_ONLY** | Interesting but unconfirmed | Send email for operator visibility; do NOT place order. Examples: weak news signal + no confirmation, freshness past intraday window. |
| **ALLOW** | All checks passed | Place order at normal size. |

**Emergency exits BYPASS all checks.** Position management must always be able
to dispose risk: SL hit, PROFIT_LOCK, RED_DAY_AFTER_GREEN, REGIME mismatch,
NEAR_DTH option, governor force-close → all proceed immediately regardless of
gate state.

**Severity ordering:** when multiple gates produce verdicts, the worst wins
(BLOCK > DEFER > DOWNSIZE > ALERT_ONLY > ALLOW). Multiple DOWNSIZE verdicts
multiply their size factors (e.g. 0.5 × 0.5 = 0.25 final size).

---

## Daily operating cycle

| Time UTC | Trigger | Component | What happens |
|---|---|---|---|
| 04:00 | cron daily-learning | analyzer.py + LLM Senior PM (P0_essential 4/day) | Generate allocation plan for today + adapt state.json based on yesterday's trades. Output: `learning-loop/allocations/<date>.json` |
| 05:30 / 06:30 | watchdog daily-learning-watchdog | re-trigger daily-learning if 04:00 missed | |
| 13:30 | market open | — | NYSE/NASDAQ open. session-only monitors begin |
| 13:35 | cron morning-allocator | execute_allocation_plan.py | (1) v3.10 plan revalidation against live Alpaca positions; (2) execute_orders via shared/allocator.py → safe_close for SELL/EXIT/REDUCE, place_stock_bracket for BUYs with GTC OCO |
| 13:30-20:00 | every 5 min | price/options/options-exit/exit/autonomous-remediation/incident-detector | Trading session monitors |
| any time | every 5 min 24/7 | crypto/defense/twitter/incident-detector | News + sentiment + crypto + Layer 1 anomaly watcher |
| 20:00 | market close | — | Stocks/options orders DAY-TIF cancelled by Alpaca. GTC bracket children survive (v3.9.6) |
| 21:00+ | every 15 min | autonomous-remediation | Detects missing exits, duplicate exits, stale orders → applies CANCEL_STALE_ORDERS keep_one or RECREATE_EXIT_PLAN via place_oco_exit |

---

## Kill-switches

| Switch | Trigger | Effect |
|---|---|---|
| `assert_paper_only(endpoint)` | non-paper Alpaca URL | Raises PaperOnlyViolation; system refuses to operate |
| `daily_drawdown_guard` | daily P&L ≤ -12% equity | BLOCK all new entries until next session; exits remain autonomous |
| `IntradayProfitGovernor RED_DAY_AFTER_GREEN` | Peak ≥$1k then giveback ≥146% | max_gross_target → 0.25; blocks new intraday entries; closes options first |
| `IntradayProfitGovernor PROFIT_LOCK` | Peak ≥$1k then giveback ≥50% | Harvests winners ≥+8% via MARKET sell |
| `INCIDENT_AUTO_DISABLE=true` env | Layer 1 detector P02/P03/P12 CRITICAL | Flips `config/capital_deployment.json::auto_execute_rebalance=false` (operator-reversible) |
| `REMEDIATION_DISABLE_RECREATE=true` env | manual operator | Disables RECREATE_EXIT_PLAN action |
| safe_close pre-flight 404 | position already closed | Skips MARKET sell (eliminates naked short class) |
| Layer 2 lint test CI gate | new code adds `requests.post(/v2/orders, side='sell'|'buy')` outside ALLOWED_FILES | PR fails CI before merge |

**To stop all new entries (emergency manual):**
```bash
# Set capital_deployment.auto_execute_rebalance = false
# Existing positions managed by exit-monitor + governor; no new BUYs
```

---

## Daily loss & giveback protection

- **Daily loss circuit-breaker:** -12% equity → block new entries
- **Weekly stop:** -25% equity → pause all monitors (operator review)
- **Monthly stop:** -40% equity → full stop, parameter reset
- **Intraday giveback (v3.5 governor):**
  - Peak ≥$1k: tracking armed
  - 30% giveback → WARN (email only)
  - 50% giveback → PROFIT_LOCK (harvest winners)
  - 146% giveback (peak →← red) → RED_DAY_AFTER_GREEN (defensive mode)

All giveback thresholds tunable via `config/aggressive_profile.json::intraday_profit_protection`.

---

## Disaster recovery

### Scenario 1: All positions auto-closed unexpectedly (2026-05-22 class)
**Symptom:** equity drops, positions=0, no manual action.
**Diagnose:** `tail journal/autonomy/<date>.jsonl | grep EMERGENCY_CLOSE`
**Mitigation in code (already shipped):** v3.9.6 GTC brackets + v3.9.9
emergency_engine invariant + v3.9.10 safe_close + Layer 2 lint test gate.
**Manual recovery:** wait for next 04:00 UTC daily-learning + 13:35 UTC allocator
(positions repopulate based on fresh plan).

### Scenario 2: Naked short on long-only symbol (2026-05-27 class)
**Symptom:** Alpaca shows position side=short on non-inverse ticker.
**Detect:** Layer 1 incident-pattern-detector P02 fires → `[INCIDENT-CRITICAL]` email.
**Mitigate (manual):** `mcp__claude_ai_Alpaca__close_position("<SYMBOL>")` or
Alpaca dashboard buy-to-cover.
**Prevention (shipped):** v3.10 safe_close skips sell when intent=sell + live=short;
allocator plan revalidation drops stale EXIT actions.

### Scenario 3: GitHub Actions cron-skip blackhole (≥3 monitors STALE)
**Symptom:** No emails for >30 min; expected workflows missing from gh run list.
**Detect:** Layer 1 P09 (`blackhole_hour`) fires when ≥3 monitors STALE.
**Mitigation:** entry-monitors-watchdog (cron */15) auto-retriggers via PAT.
**Manual recovery:** `gh workflow run <name>.yml` for affected workflows.

### Scenario 4: Anthropic LLM unavailable (3-day timeout pattern)
**Symptom:** daily-learning falls back to "deterministic only"; rationale.md
notes `LLM unavailable (skipped)`.
**Effect:** Deterministic adapter still runs (cooldown, size cut, hard_safety
pause). PR #10 macro fallback applies options_side_bias from SPY RSI.
**Tolerance:** Up to 7+ days of LLM unavailability does not paralyze trading.
After 7 days consider operator manual override of LLM-derived state.

### Scenario 6: Safe-mode triggered (v3.12.0 — 2026-05-30 class)
**Symptom:** No new BUY entries firing during market hours despite signals
in monitor logs. Email subject `[SAFE_MODE_ENTERED]`. risk_officer
returning REJECT with `safe_mode: SAFE_MODE ACTIVE (TRIGGER): reason`.
**Detect:**
- `cat learning-loop/runtime_state.json | jq .safe_mode` — `active: true`
- Trigger types: ACCOUNT_OUTAGE / AUDIT_GAP / STALE_DATA / CONFIDENCE_BROKEN / OPERATOR
**Behavior in safe_mode:**
- New entries BLOCKED by risk_officer
- size_multiplier 1.0 → 0.5 for any orders that do fire (exits etc.)
- confidence threshold raised by +0.10 (harder to qualify)
- Emergency closes (CLOSE_EMERGENCY / PROFIT_LOCK / GOVERNOR) BYPASS safe_mode
**Recovery:**
- ACCOUNT_OUTAGE: Alpaca status page; wait for /v2/account to recover; safe_mode auto-exits on next successful call
- AUDIT_GAP: check monitor crons firing; run `python3 scripts/incident_pattern_detector.py --dry-run` to verify pipeline writes audit events
- STALE_DATA: check `cat learning-loop/runtime_state.json | jq .heartbeat` for stale components; manually trigger affected monitor via `gh workflow run <name>.yml`
- OPERATOR-forced: clear `safe_mode.forced: false` in runtime_state.json
**Manual override:** edit `learning-loop/runtime_state.json::safe_mode.active = false` (NOT recommended without diagnosis)
**Prevention shipped (v3.12.0):** confidence module / safe_mode module / heartbeat module pin component health quantitatively; session report surfaces fresh state.

### Confidence gate (v3.12.0 — 2026-05-30)
**What it is:** every trade decision passing through `risk_officer.evaluate_trade`
can carry a `confidence_inputs` dict. If present, the 5-component score
(data_quality / signal_strength / regime_alignment / system_health /
risk_state) is computed; `total ≥ 0.65` → ALLOW, `≥ 0.50` → ALERT_ONLY,
`< 0.50` → BLOCK.
**Where to look:** `proposal["_confidence_report"]` after evaluate_trade
returns; or `journal/autonomy/<date>.jsonl` for `CONFIDENCE_BLOCK` /
`CONFIDENCE_ALERT` events.
**Tuning:** `config/aggressive_profile.json::confidence.weights` and
`.thresholds` override defaults. Weights are auto-normalized to sum 1.0.
**Doesn't replace risk engine:** risk_officer can still BLOCK a
high-confidence trade (e.g. PDT lock, buying-power insufficient).

### Scenario 5a: Bracket interlock blocks protective close (2026-05-29 class)
**Symptom:** Governor enters DEFEND_DAY or RED_DAY_AFTER_GREEN, but `safe_close`
returns Alpaca 403 `insufficient qty available; held_for_orders=N`. Positions
held behind their own bracket OCO children — protection armed but cannot fire.
**Detect:** Layer 1 P13 `bracket_interlock_blocked_close` fires when ≥3 such
events in 30 min → `[INCIDENT-CRITICAL]` email.
**Mitigation in code (shipped v3.11.3 — 2026-05-30):** `safe_close` now calls
`_cancel_open_orders_for_symbol(symbol)` BEFORE placing the protective close.
GET /v2/orders?symbols=X&status=open&nested=true → DELETE each matching bracket
parent (cascades to OCO legs). Default ON for all callers; opt-out via
`cancel_brackets_first=False` (only the entry path needs that — it has no
brackets yet). Fail-soft: cancel failure does NOT block close attempt; Alpaca
403 surfaces in audit reason.
**Manual recovery if P13 fires post-v3.11.3:** check Alpaca status page; the
cancel DELETE call may itself be failing (broker outage, network, or
DELETE-permission revoked). As emergency fallback for stuck positions use
`mcp__claude_ai_Alpaca__close_position("<SYMBOL>")` (DELETE /v2/positions
endpoint atomically cancels child orders + market-closes).

### Scenario 5: Alpaca API outage
**Symptom:** monitors log `account_fetch_failed`; safe_close logs `404` for everything.
**Effect:** v3.10 risk_officer returns DEFER (not fail-open) → monitors retry
next cron. Exits queued via emergency_close survive in DAY/GTC TIF.
**Recovery:** automatic when Alpaca returns.

---

## External cron driver (v3.11.2 — 2026-05-29) ✅ DEPLOYED

**Status:** 🟢 ACTIVE since 2026-05-29 ~06:45 UTC.

**Problem solved:** GitHub Actions schedule cron-skip cascade — production
delivery rate observed at **2.8-12%** vs 99% expected (crypto-monitor:
8 schedule runs/24h vs 288 expected). Effect: 5 days ZERO trade events
(audit JSONL 2026-05-23 → 2026-05-27 all empty; only 6 events on 28 May).
Watchdog itself dropped at 8% → couldn't save anything.

**Solution:** `cloudflare-workers/cron-trigger/` — Cloudflare Worker
firing Cloudflare cron triggers (99.99% SLA, free tier) and calling
GitHub API `workflow_dispatch` endpoint for each monitor. GH schedule
cron stays as fallback; concurrency `cancel-in-progress: true` prevents
duplicates.

**Production verification 2026-05-29 06:55 UTC:**
- 45 `workflow_dispatch` runs in last 30 min (vs 1 GH schedule)
- 6× per hot monitor (every 5 min × 5 ticks observed)
- All 6 hot monitors (crypto, defense, twitter, exit, options-exit,
  incident-detector) firing as designed
- 4 medium-freq monitors (geo, reddit, monitor-health, watchdog)
  firing 2× in 30 min (every 15 min)
- **43× MORE monitor activity** vs pre-deploy baseline

**Triggers configured (Cloudflare dashboard):**
- `*/5 * * * *` — hot 24/7 monitors + session-only when market open
- `*/15 * * * *` — medium-freq monitors
- `45 13 * * 1-5` — morning-allocator backup (weekday 13:45 UTC)

**Setup time:** ~10 min one-time. Full guide: `cloudflare-workers/cron-trigger/README.md`.

**Cost:** Free tier — ~2,100 GH API calls/day = 2.1% of 100k Cloudflare
quota. Zero paid services. PAT rotation aligned with WORKFLOW_PAT cycle
(90 days, next: 2026-08-11).

**Health check:**
```bash
# 1. Verify recent Worker firing (last 30 min should have ~6 dispatch per monitor)
gh run list --limit 50 --json createdAt,event,name 2>/dev/null | \
  python3 -c "
import json,sys
from datetime import datetime, timezone, timedelta
from collections import Counter
rs = json.load(sys.stdin)
cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
recent = [r for r in rs if datetime.fromisoformat(r['createdAt'].replace('Z','+00:00')) > cutoff]
events = Counter(r['event'] for r in recent)
print(f'Last 30min: {len(recent)} runs, {dict(events)}')
"

# 2. Worker health endpoint (returns config + market hours status)
curl -s https://cron-trigger.<your-subdomain>.workers.dev/health
```

**Troubleshooting:**

| Symptom | Likely cause | Recovery |
|---|---|---|
| Zero `workflow_dispatch` in 30 min | Worker stopped firing | Cloudflare dashboard → Workers → cron-trigger → check Logs |
| Worker logs "401 Bad credentials" | PAT expired/revoked | Generate new Classic PAT (scopes: `repo`, `workflow`); update Cloudflare env var `GITHUB_PAT` |
| Worker logs "404 workflow not found" | Workflow file renamed/deleted | Edit `worker.js` arrays HOT_24_7/MEDIUM_FREQ; redeploy |
| Many duplicate runs | Cron triggers fired twice within concurrency window | Should auto-cancel via `cancel-in-progress: true`; if not, check workflow YAML concurrency block |

**Fallback strategy:** If Cloudflare Worker fails entirely (99.99% SLA
means ~88 min/year downtime), GH schedule cron remains as path. System
degrades to pre-2026-05-29 rate (5-12%) but doesn't stop entirely.
Manual recovery: `gh workflow run <name>.yml`.

## Free-tier dependencies (no paid services)

| Component | Source | Cost | Fallback |
|---|---|---|---|
| Trading API | Alpaca Paper | Free | — |
| Market data | Alpaca IEX bars | Free | Yahoo public chart (VIX) |
| News | NewsAPI free + Finnhub free (OPTIONAL) | Free | Multiple RSS feeds, House Clerk XML |
| Social | Bluesky AT-Protocol | Free | — |
| Reddit | Public .json endpoints via Cloudflare Worker | Free | — |
| Insider | SEC EDGAR + House Clerk XML (free official) | Free | Capitol Trades (when up) |
| LLM | Anthropic Routines | 15/day budget | Deterministic adapter (always available) |
| CI/Runtime | GitHub Actions | Free public repo | Cloudflare Worker (planned for hot monitors) |
| Email | Gmail SMTP | Free | — |
| Audit | JSONL append-only in repo | Free | git history |

**Finnhub** is OPTIONAL (not required for any critical path). Free tier returns
0 for `^VIX` since 2024 → Yahoo fallback used in `shared/risk_guards.py`.
price-monitor logs WARN if Finnhub key missing but proceeds.

---

## Health-check command set

Run these to verify system state:

```bash
# Working tree + remote sync
git fetch --prune && git status

# Today's incident detector hits
cat learning-loop/incidents/$(date -u +%Y-%m-%d).md 2>/dev/null || echo "no incidents today"

# Today's audit JSONL summary
wc -l journal/autonomy/$(date -u +%Y-%m-%d).jsonl 2>/dev/null

# Recent workflow runs (need gh CLI)
gh run list --limit 20

# Pre-trade snapshot status (Python in repo root)
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'shared')
from pretrade_snapshot import get_snapshot, classify_snapshot_for_intraday
s = get_snapshot(force_refresh=True)
print(s.to_summary())
d = classify_snapshot_for_intraday(s)
print(f'verdict={d.verdict.value} reason={d.reason}')
"

# Backtest sanity (realistic mode, walk-forward)
.venv/bin/python3 -m backtest.run \
    --strategy momentum-long --tickers AAPL --days 60 \
    --mode both --walk-forward 3

# All audit agents
python3 scripts/system_consistency_agent.py --no-files --format markdown | grep -E "Overall|Score"
python3 scripts/strategy_coherence_agent.py --no-files --format markdown | grep -E "Overall|Score"
python3 scripts/e2e_system_test_agent.py --all --no-network --no-files --format markdown | grep "Overall"
```

---

## Manual operator actions (rare)

System is autonomous by design. Operator interventions:

1. **Approve auto-PR from Lane 2 LLM proposals** (GitHub UI squash-merge)
2. **Verify [INCIDENT-CRITICAL] emails** within 1h of receipt
3. **Quarterly PAT rotation** (`WORKFLOW_PAT` classic, 90-day expiry)
4. **Manual buy-to-cover** on rare naked SHORT (Layer 1 P02 flags it; system
   skips via safe_close but doesn't auto-cover)
5. **Cleanup `claude/*` branches** (~weekly): `git push origin --delete <branch>`

**Never** required:
- Approve individual trades
- Set sizing per symbol
- Decide regime
- Confirm exit plan

---

## Python invocation

```bash
.venv/bin/python3 <script>          # preferred (uses pinned deps)
python3 <script>                     # fallback (system Python; works for most)
python3 -m unittest discover tests   # full test suite (some Python-3.10+ deps; CI uses 3.11)
```

---

## Where to look first when something is wrong

| Symptom | Look here |
|---|---|
| No emails for >1h | `gh run list --limit 30` (check workflow health) |
| Unexpected position close | `journal/autonomy/<date>.jsonl` (decision history) |
| Allocator placed nothing | `learning-loop/allocations/<date>.execution.json` |
| Plan revalidation dropped orders | search `[allocator REVALIDATE]` email or stdout in workflow log |
| Naked short / weird position | Layer 1 incident-detector `learning-loop/incidents/<date>.md` |
| LLM unavailable for days | OK — deterministic adapter still runs; check P0 budget in `runtime_state.json::routine_budget` |
| Many monitors STALE | GitHub Actions cron-skip; entry-monitors-watchdog handles; manual `gh workflow run` for urgent |

---

## Glossary

- **Lane 1 (LLM)**: Daily-learning Senior PM proposals applied directly via state_overrides whitelist
- **Lane 2 (LLM)**: LLM-proposed heuristic added to `adapter.py` → opens GitHub PR for operator review
- **Lane 3 (LLM)**: LLM ideas added to `heuristic_proposals.md` backlog (manual implementation)
- **Layer 1 (deterministic)**: `incident_pattern_detector.py` cron */5 24/7 — 12 pattern checks
- **Layer 2 (architectural)**: `safe_close()` centralized SELL + AST lint test CI gate
- **Layer 3 (deterministic)**: Plan revalidation in `execute_allocation_plan.py`
- **Layer 4 (deterministic)**: `entry-monitors-watchdog.yml` matrix 12 monitors

---

*Last updated: 2026-05-27 (v3.10.1 — full audit + Phase C wiring complete in 5 monitors + P05/P11 stubs filled + E2E session test)*

## v3.10.1 changes (post-full-audit)

- **`shared/news_signal_gate.py`** — single helper for monitor wiring (DRY).
  Replaces 40-line copy-paste with 5-line `gate_news_signal(...)` call.
- **Phase C wiring complete** in 5 news monitors: defense (refactored to
  use helper), twitter (post-level gate in `classify_and_execute`),
  reddit (in `_emit_signal`), geo (in `execute_geo_signal`), politician
  (in `emit_djt_signal`). Each strategy has its own EventCache+CooldownTracker
  per `_shared_caches()` singleton.
- **Layer 1 incident-detector P05 + P11 stubs filled.**
  P05 now queries `GET /v2/orders?symbols=X&status=closed` per position and
  flags those whose recent fills lack any known client_order_id prefix.
  P11 self-manages `pdt_count_prev` baseline in
  `runtime_state.json::incident_detector_history`.
- **E2E session test** (`tests/architecture_vnext/test_full_session_e2e.py`):
  9 scenarios covering signal→risk→decision→audit flow + invariants
  (no naked short, no emergency for repairable, no-lookahead, DEFER not
  fail-open). 8/9 green (1 skipped on Python <3.10 due to PEP 604).

## Troubleshooting

### "E2E + Security Audit emails — both FAILED" (2026-05-27 EOD pattern)

**Symptom:** 4 emails (2× E2E, 2× Security Audit) arrive within minutes
of each other reporting `NameError` or similar in same unit test.

**Likely cause:** new code shipped that uses a name not imported in scope.
Caught by CI Python 3.11 but invisible to local Python 3.9 dev — entire
test class skipped because `shared/alpaca_orders.py` uses PEP 604
`dict | None` syntax (requires 3.10+) → module fails to load on 3.9 →
`@unittest.skipIf(sys.version_info < (3, 10), ...)` decorator skips
whole class → local `unittest` reports `OK (skipped=N)` which LOOKS
like pass but is actually N untested cases.

**First seen:** 2026-05-27 EOD — `safe_close()` in commit `ab7ff93`
v3.9.10 called `assert_paper_only(ALPACA_BASE_URL)` without importing it.
4 failure emails (E2E ×2 + Security Audit ×2). Fix in commit `63db126`:
lazy import inside function.

**Recovery procedure:**
1. `gh run view <RUN_ID> --log-failed` to find exact undefined name
2. Add lazy import inside the function (handles both `shared/`-on-path
   and module-style sys.path):
   ```python
   try:
       from autonomy import X
   except ImportError:
       from shared.autonomy import X  # type: ignore
   ```
3. Commit + push; next CI run (~5 min) should be green

**Prevention** (memory/feedback_test_environment_parity.md):
- Local `OK (skipped=N>0)` is NOT "tests green" — N = untested cases
- Upgrade local `.venv` to Python 3.11 to match CI (`pyenv install 3.11.x`)
- Function-call smoke beats AST lint: `python3 -c "from alpaca_orders
  import safe_close; print(safe_close.__doc__[:50])"` — proves module
  loads, not just parses
- After every push touching `shared/alpaca_orders.py` or other PEP-604
  modules, wait ~5 min and check `gh run list --limit 5 --status failure`
  BEFORE claiming "shipped clean"

### "Forensic Position Origin — FAILED" (pre-2026-05-27 behavior)

**Symptom:** Email `[Forensic Position Origin] failed` after operator
triggers `workflow_dispatch`.

**Post-2026-05-27 (commit `18d3617`):** script returns exit 0 ALWAYS.
If you see this email after that commit, indicates real infra failure
(Alpaca auth, network), not anomaly discovery.

**Pre-2026-05-27 (history):** script returned exit 2 when finding
UNKNOWN orders — that's expected discovery, not workflow failure.
Anomaly findings ARE reported via email body + audit JSONL; workflow
status should reflect only INFRA success (commit + push + script ran),
not whether findings happened.

---

## v3.11 EDGE-FIRST (2026-05-27)

Shift from "infrastructure ready" to "high-probability positive-EV". Each
new gate forces strategies to PROVE edge before consuming capital.

**Phase A — `learning-loop/edge_validator.py`** — backtest-gated `enabled=true`.
Strategy must show realistic-mode backtest pass (WR ≥ 50%, PF ≥ 1.3,
MDD < 20%, n ≥ 10) within last 30d to remain enabled. Default OFF
(`EDGE_GATE_DISABLED=true`) — operator opts in via env after backtesting
all enabled strategies. Operational tags (alloc-*) exempt.

**Phase B — auto-prune zombies.** After 21 days SILENT + 0 trades lifetime,
adapter automatically sets `enabled=False`. Override via
`hard_safety_override=true` per-strategy.

**Phase D — `shared/kelly_sizing.py`** — quarter-Kelly fraction sizing.
Strategy with 70% WR + 1.5 R:R → ~12.5% equity per position; 50% WR →
falls back to base size. Floor 0.10×base, ceiling 2.0×base. Requires
≥10 lifetime trades (else base).

**Phase E — regime-conditional enable.** Strategies declare
`compatible_regimes: ["RISK_ON", "NEUTRAL"]` in state.json. If current
regime not in list → auto-pause with `paused_by_regime=true` (auto-resume
when regime changes back). Backward compat: no field = all regimes allowed.

**Phase G — `shared/earnings_calendar.py`** — earnings ±1d blackout for
stocks (extends options-monitor pattern). Data: `config/earnings_calendar.json`
JSON file populated manually OR by LLM daily-learning. Fail-OPEN if missing.

**Phase H — execution window delay.** Morning-allocator cron 13:35 → **13:45 UTC**
(15 min after open) to avoid open-volatility + wide spreads. Full VWAP-style
tranching deferred.

**Phase I — fill-rate gated sizing.** Already exists since v3.X
(`heuristic_fill_rate_size_cut`); strategies with fill_rate < 50% over 5+
orders get `size_multiplier × cancel_factor`. Verified active in adapter.

### Deferred to v3.12 backlog (with justification)

- **Phase C — edge dashboard separate workflow** (~30 min) — value lower
  than D/E. Existing per-strategy metrics in `learning-loop/history/<date>.md`
  serve as dashboard for now.
- **Phase F — correlation cap** (~25 min implementation + N×N daily-bar
  fetch tax) — properly done requires correlation matrix cache built daily.
  Risk for v3.11 ship: heavy Alpaca API load. Current concentration_ok 40%
  per-ticker + bucket caps (65% per correlated bucket) partially cover.

### Migration plan to enforced edge gate

1. Operator runs backtests for each currently-enabled strategy:
   ```bash
   .venv/bin/python3 -m backtest.run --strategy momentum-long \
       --tickers AAPL MSFT NVDA --days 180 --mode both --walk-forward 3
   ```
   Results land in `backtest/results/`.
2. Check edge_validator verdict per strategy:
   ```bash
   .venv/bin/python3 -c "
   import sys; sys.path.insert(0, 'learning-loop')
   from edge_validator import validate_strategy_edge
   for s in ['momentum-long', 'crypto-momentum', 'options-momentum', ...]:
       ok, m, r = validate_strategy_edge(s); print(f'{s}: {ok} — {r}')
   "
   ```
3. When 100% of enabled strategies PASS, flip `EDGE_GATE_DISABLED=false`
   in `.github/workflows/daily-learning.yml::env`.
4. Next daily-learning will enforce; any strategy losing edge auto-disables.

---

*Last updated: 2026-05-30 EOD (v3.13.0 — Multi-Agent Audit Board added; v3.12.0 confidence + safe_mode + heartbeat + session reporter; v3.11.3 bracket-interlock fix + crypto-oversold-bounce + symbol attribution + zombie-LLM-lock + fill_rate-closed separation; previous v3.11.2 Cloudflare cron-trigger verified)*

---

## v3.12.0 / v3.13.0 quick reference (2026-05-30)

**Confidence gate** — `shared/confidence.py`: 5-component deterministic
score. ALLOW≥0.65 / ALERT_ONLY≥0.50 / BLOCK<0.50. Wired into
`risk_officer.evaluate_trade` (legacy callers warn-only). Cannot override
risk_officer REJECT. See "Confidence gate" section above and
`shared/confidence.py::compute_confidence`.

**Safe mode** — `shared/safe_mode.py`: runtime-operational state distinct
from `defensive_mode`. 5 triggers: ACCOUNT_OUTAGE / AUDIT_GAP /
STALE_DATA / CONFIDENCE_BROKEN / OPERATOR. Effects: blocks NEW entries,
halves size, raises confidence threshold +0.10. Emergency closes
(CLOSE_EMERGENCY/PROFIT_LOCK/GOVERNOR) ALWAYS bypass. See Scenario 6.

**Heartbeat** — `shared/heartbeat.py`: per-component liveness in
`runtime_state.json::heartbeat`. Feeds `confidence.system_health`.
Check with `cat learning-loop/runtime_state.json | jq .heartbeat`.

**Session report** — `python3 scripts/session_report.py [--no-write] [--date YYYY-MM-DD]`.
Writes `reports/sessions/<date>_<ts>.md` + `latest.md` symlink. Surfaces
risk flags 🔴/🟠/🟡 + account snapshot + governor state + safe_mode +
strategies + allocator + decisions breakdown + heartbeat + routine_budget +
incidents.

**Multi-Agent Audit Board** — `agents/`: 11 area-specialist prompt-based
reviewers + Final Arbiter for design/code/risk/etc. review. **REVIEW-ONLY
— never runtime brain.** Usage:
```bash
python3 agents/run_agent_board.py list
python3 agents/run_agent_board.py validate-structure
python3 agents/run_agent_board.py check-forbidden
python3 agents/run_agent_board.py init <YYYY-MM-DD>
python3 agents/run_agent_board.py validate-reports <YYYY-MM-DD>
```
See `agents/README.md`.

**Crypto oversold-bounce** — new strategy in `crypto-monitor`. Bypasses
predator-bracket when `RSI ≤ 30 + 24h-move ≥ -10% + 1-bar reversal +
≥50% vol`. Tagged `crypto-oversold-bounce-*` in audit. Solves 45-day
SILENT period from BTC/ETH deep oversold (RSI 20-27).

---

## Email notification policy (v3.13.1 — 2026-05-30)

`shared/notify.py::send_email` consults `NotificationPolicy` BEFORE any
SMTP call. Subjects are classified into 3 buckets:

### Always SENT immediately (CRITICAL — requires operator attention)
| Marker | Meaning |
|---|---|
| `[INCIDENT-CRITICAL]` | Layer 1 detector found P01-P13 critical pattern |
| `[SAFE_MODE_ENTERED]` | runtime trigger — investigate cause |
| `[INTRADAY-DEFEND]` | governor entered DEFEND_DAY (max_gross 0.50) |
| `[INTRADAY-RED-AFTER-GREEN]` | governor entered RED state (max_gross 0.25) |
| `[PROFIT-LOCK]` | governor armed PROFIT_LOCK, harvesting winners |
| `[POL-FILING]` | politician PTR alert — operator reads PDF |
| `[ROUTINE-BUDGET-LOW]` | Anthropic budget < 3 calls remaining |
| `[op-correction]` | scheduled operational correction (e.g. NOW cover) |
| `[allocator EXEC] N failed` | allocator orders failed (N > 0) |
| `[allocator REVALIDATE]` | stale orders dropped before execution |
| `[CONFIDENCE-BLOCK]` | confidence gate BLOCKed a trade |
| `[PDT-LOCKED]` | PDT lockout (daytrade_count ≥ 3) |
| `[KILL-SWITCH ...]` | any kill-switch activation |
| `[ERROR]` / `[FAIL ...]` | workflow / monitor failures |

### Sent to local DIGEST file (non-critical — batched)
Per-signal: `[BUY]` / `[SELL]` / `[EXIT]` / `[EXECUTED]` / `[OPTIONS REJECTED]` /
`[QUEUED]` / `[DEFERRED]`
State info: `[INTRADAY-WARN]` / `[PEAK-WARN]` / `[INCIDENT-WARN]` / `[PDT-OK/CAUTION/RESTRICTED]` /
`[SAFE_MODE_EXITED]` / `[CONFIDENCE-ALERT]`
Planning: `[allocator PLAN]` / `[learning-loop AUTO-PR]` / `[allocator EXEC] 0 failed`
Cron summaries with signals: `[<Monitor>] N signal(s), M sent` (N > 0)

Digest file: `learning-loop/notify_digest/<date>.jsonl` (one JSONL line per email).

### SUPPRESSED (never delivered)
Cron summaries with zero signals: `[<Monitor>] 0 signal(s), 0 sent`

### Modes (env `NOTIFY_MODE`)

```bash
# Default — CRITICAL sent, INFO digested, NOISE suppressed
NOTIFY_MODE=minimal

# Get every email (legacy v3.12 behavior — NOT recommended)
NOTIFY_MODE=verbose

# Suppress ALL emails (e.g. holiday silence)
NOTIFY_MODE=off
```

### Per-subject overrides

```bash
# Force-send a subject even in minimal mode (comma-separated substrings)
NOTIFY_FORCE_SEND="[allocator PLAN],[PDT-CAUTION]"

# Force-suppress a subject even if it's CRITICAL (use with extreme care)
NOTIFY_FORCE_SUPPRESS="[POL-FILING]"
```

### Daily digest email (optional)

`scripts/send_daily_digest.py` reads the digest JSONL and sends ONE
summary email with all batched items:

```bash
python3 scripts/send_daily_digest.py             # today UTC
python3 scripts/send_daily_digest.py --no-send   # preview only
python3 scripts/send_daily_digest.py --clear     # delete digest after send
```

To schedule daily at 21:00 UTC: add a workflow step (template not auto-shipped
to avoid implicit dependency). For manual: run after market close.

### Verify policy

```bash
# Smoke test — classifier output
python3 -c "
import sys; sys.path.insert(0,'shared'); import notify
print(notify._classify_subject('[INCIDENT-CRITICAL] xxx'))   # send
print(notify._classify_subject('[BUY] AAPL'))                # digest
print(notify._classify_subject('[Defense Monitor] 0 signal(s), 0 sent'))  # suppress
"
```

## v3.20 Evidence Production — operational quickstart (added 2026-06-04)

### Daily local report generation (no network required)

```bash
# Consolidated decision pack
python3 scripts/operator_decision_pack.py
# → docs/operator_decision_pack_LATEST.md
# → docs/operator_decision_pack_LATEST.json

# Per-module reports
python3 scripts/evidence_lower_bounds_report.py
python3 scripts/strategy_robustness_report.py
python3 scripts/counterfactual_report.py
python3 scripts/gate_calibration_report.py
python3 scripts/exit_quality_report.py
python3 scripts/experiment_scheduler_run.py
```

### Modes of evidence production (env: `EVIDENCE_PRODUCTION_MODE`)

| Mode | What it does | Where it writes |
| --- | --- | --- |
| `SIGNAL_ONLY` (default) | Records signal facts only, no fill | nothing on disk |
| `SHADOW_PAPER_SIM` | Local fill sim with conservative slippage/spread | `learning-loop/shadow_ledger/<date>.jsonl` |
| `BROKER_PAPER` | Opt-in only; hard-asserts paper URL; falls back to SHADOW if creds missing | broker + audit log |

### Validating v3.20 invariants

```bash
python3 -m unittest tests.test_deep_e2e_v3200            # 38 steps, no network
python3 -m unittest tests.test_operator_decision_pack_v3200
python3 -m unittest tests.test_audit_board_v3_20_appends_v3200
```

### EDGE_GATE_ENABLED — must remain FALSE without

The flip from `false` to `true` requires (per `docs/AUTONOMY_CONTRACT.md`
v3.20 section):

- `n >= 50` paper trades closed for the strategy
- bootstrap PF lower bound `>= 1.3`
- expectancy lower bound `> 0`
- Wilson WR lower bound `>= 0.40`
- confidence calibration monotonic
- ≥ 2 regimes observed
- no `overfit_suspicion` flag
- no `EVIDENCE_DEGRADING` status
- operator review of decision pack + audit board verdict

When any criterion fails, leave `EDGE_GATE_ENABLED=false`.

### Inspecting variant quarantine

```bash
ls learning-loop/variant_quarantine/            # registered variants
python3 -c "
import sys; sys.path.insert(0, 'shared')
from strategy_variant_quarantine import list_variants
for v in list_variants():
    print(v['id'], v['parent_strategy'], v['status'])
"
```

Variants NEVER enter the runtime trading path. Promotion to a runtime
strategy requires an explicit operator-issued review trigger.

## v3.21 Evidence Throughput & Strategy Discovery (added 2026-06-04)

### Daily shadow evidence cycle

```bash
# Dry-run (validates pipeline, no writes)
python3 scripts/run_shadow_evidence_cycle.py --dry-run

# Signal-only mode (records opportunity entries, no fills)
python3 scripts/run_shadow_evidence_cycle.py --mode signal_only

# Shadow mode (records shadow fills with conservative slippage)
python3 scripts/run_shadow_evidence_cycle.py --mode shadow

# Broker paper mode (requires ALLOW_BROKER_PAPER=true)
ALLOW_BROKER_PAPER=true \
    python3 scripts/run_shadow_evidence_cycle.py --mode broker
```

**Live mode does NOT exist** — `--mode live` is rejected by argparse.

### v3.21 module reports

```bash
python3 scripts/evidence_throughput_report.py
python3 scripts/signal_density_report.py
python3 scripts/multi_horizon_outcome_report.py
python3 scripts/observation_priority_report.py
python3 scripts/strategy_discovery_report.py
python3 scripts/fill_model_calibration_report.py
python3 scripts/operator_action_queue_render.py
```

### Validating v3.21 invariants

```bash
python3 -m unittest tests.test_deep_e2e_v3210            # 41 steps, no network
python3 -m unittest tests.test_audit_board_v3_21_appends_v3210
```

### Modes of shadow runner (env: `EVIDENCE_PRODUCTION_MODE`)

| Mode | What it does | Side effects |
| --- | --- | --- |
| `SIGNAL_ONLY` (default) | Records every signal to opportunity ledger | learning-loop/opportunity_ledger/ entries |
| `SHADOW_PAPER_SIM` | + simulates fills with 5bps slippage + 1bps spread | learning-loop/shadow_ledger/ entries |
| `BROKER_PAPER` | Opt-in via env; hard-asserts paper URL; falls back to SHADOW_PAPER_SIM if credentials missing | Alpaca paper API + audit JSONL |

### Strategy density labels (`shared/signal_density_audit.py`)

When reviewing `docs/signal_density_LATEST.md`:

- **DEAD_STRATEGY** — Zero signals in window. Candidate for disable
  (file an operator queue action; do not auto-disable).
- **TOO_SPARSE** — < 5 signals AND no fills. Watch list.
- **NOISY_STRATEGY** — High signal volume but low average confidence.
  Discovery sandbox may propose tighter-threshold variants.
- **HIGH_REJECTION_BUT_PROMISING** — Rejection ratio >= 70% but
  accepted minority has confidence >= 0.65. Risk gate doing its job.
- **NEEDS_VARIANT_DISCOVERY** — One-symbol or one-regime dependence.
  Discovery sandbox may propose universe / regime variants.
- **NEEDS_UNIVERSE_EXPANSION** — Healthy density but single-symbol
  concentration. Add ticker candidates to the universe.
- **HEALTHY_DENSITY** — Default healthy state.

### Broker paper adapter — operator checklist

Before flipping `ALLOW_BROKER_PAPER=true`:

1. Verify `ALPACA_PAPER_BASE_URL` env var contains
   `paper-api.alpaca.markets`. The adapter rejects any URL without
   the `paper` prefix.
2. Verify `MAX_ORDER_NOTIONAL_USD` in `shared/broker_paper_adapter.py`
   is still 100 (very small for paper experiments).
3. Verify `DEFAULT_DRY_RUN = True` — every caller must explicitly
   pass `dry_run=False`.
4. Verify `ADAPTER_REQUIRES_IDEMPOTENCY = True` — calls without
   `idempotency_key` are rejected.
5. Audit JSONL captures every attempt.
6. Without credentials, the adapter returns `SHADOW_FALLBACK` and
   defers to `evidence_production.estimate_shadow_fill`.

### Operator action queue

```bash
# Render the queue as Markdown
python3 scripts/operator_action_queue_render.py
# → docs/operator_action_queue_LATEST.md
```

Every queue entry has `can_auto_apply=False`. The queue is
informational; v3.21 modules emit actions, the operator reviews and
manually executes follow-ups (e.g., flipping a strategy enabled flag,
flipping `EDGE_GATE_ENABLED`, registering a variant for replay).

### EDGE_GATE_ENABLED — flip criteria extended in v3.21

In addition to the v3.20 criteria (n>=50, PF_LB>=1.3, expectancy_LB>0,
WR_LB>=0.40, calibrated, 2+ regimes, no overfit, no degradation),
v3.21 adds:

- signal_density_audit shows HEALTHY_DENSITY or
  HIGH_REJECTION_BUT_PROMISING
- evidence_throughput shows HEALTHY_SHADOW_FLOW or
  HEALTHY_BROKER_PAPER_FLOW
- fill_model_calibration not in INSUFFICIENT_BROKER_PAPER_DATA
  (if BROKER_PAPER mode is used)
- operator_action_queue contains a processed REVIEW_EDGE_GATE entry

When any criterion fails, leave `EDGE_GATE_ENABLED=false`.

## Shadow Evidence Flow — activated 2026-06-04

`scripts/workflow-templates/shadow-evidence-cycle.yml` has been
auto-synced to `.github/workflows/shadow-evidence-cycle.yml`.

### Workflow contract

- **Cron:** 22:30 UTC weekdays (Mon-Fri). Runs after
  `paper-experiment-update.yml` (22:00 UTC).
- **Default mode:** `signal_only` (no shadow fill writes).
- **Hard env lock:** `EVIDENCE_PRODUCTION_MODE: SIGNAL_ONLY` set at
  workflow level — re-pasting cannot accidentally flip to broker mode.
- **Manual modes:** `workflow_dispatch` with `mode: {signal_only,
  shadow, broker}` and `dry_run: {false, true}`. **No `live` choice
  exists.**
- **Permissions:** `contents: write` only — for committing ledgers +
  the rendered `docs/shadow_evidence_cycle_LATEST.md`.
- **Push retry:** 3 attempts with `git pull --rebase` between each
  to survive automerge race conditions.

### Operator triggers

```bash
# Manual dry-run via GitHub UI (Actions → Shadow Evidence Cycle):
#   mode=signal_only, dry_run=true   → no writes
#   mode=shadow,      dry_run=true   → no writes
#   mode=shadow,      dry_run=false  → writes shadow_ledger entries
#   mode=broker,      dry_run=false  → only when ALLOW_BROKER_PAPER=true secret is set

# Local equivalent:
python3 -m scripts.run_shadow_evidence_cycle --dry-run --mode signal_only
python3 -m scripts.run_shadow_evidence_cycle --mode signal_only
```

### Expected ledger growth

The runner writes to:

- `learning-loop/opportunity_ledger/<YYYY-MM-DD>.jsonl`
- `learning-loop/shadow_ledger/<YYYY-MM-DD>.jsonl` (shadow mode only)

Both directories are auto-created on first write. While
`signals_seen=0`, no directories are created — this is the correct
`NO_EVIDENCE_FLOW` state (the runner does not fabricate signals).

### Reading throughput

After the first 24 h with non-zero signal flow:

```bash
python3 scripts/evidence_throughput_report.py
python3 scripts/signal_density_report.py
python3 scripts/operator_decision_pack.py
```

The throughput report's `estimated_days_to_n50` per strategy tells
you whether the current pace can reach the EDGE_GATE n=50 threshold
in a reasonable window.

### What the operator does NOT do

- Do NOT set `EDGE_GATE_ENABLED=true` — the gate stays default-off.
- Do NOT add `ALLOW_BROKER_PAPER=true` without reading
  `docs/BROKER_PAPER_ADAPTER.md` first.
- Do NOT manually create files in
  `learning-loop/opportunity_ledger/` or
  `learning-loop/shadow_ledger/` — only the runner writes to them.
- Do NOT trigger the workflow with `mode=broker` unless paper-only
  credentials are configured.
