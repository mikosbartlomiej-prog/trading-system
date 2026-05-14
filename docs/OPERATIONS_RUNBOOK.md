# Operations runbook

Everything an operator needs day-to-day. **The trading lifecycle requires
no operator approval** — see `docs/AUTONOMY_CONTRACT.md`.

## Quick reference

| I want to … | Run this |
|---|---|
| Check if the system can trade right now | `python scripts/trading_health.py` |
| See today's autonomous decisions | `cat journal/autonomy/$(date -u +%F).jsonl` |
| See today's code-autonomy decisions | `cat learning-loop/code-autonomy/history/$(date -u +%F).md` |
| Manually run autonomous remediation | `python scripts/autonomous_remediation.py` |
| Review a candidate patch | `python scripts/autonomous_code_review.py path/to/patch.diff` |
| Audit workflows for issues | `python scripts/audit_workflows.py` |
| Scan for accidental secret leaks | `python scripts/secret_scan_light.py` |
| Run all vNext tests | `python -m unittest discover -s tests/architecture_vnext` |
| Run system consistency audit | `python scripts/system_consistency_agent.py` |
| Audit one category only | `python scripts/system_consistency_agent.py --category paper_only` |
| Strict audit (WARN→exit 1) | `python scripts/system_consistency_agent.py --strict` |
| See what options would be closed (dry-run) | `python scripts/panic_close_options.py` |
| Trigger autonomous panic-close (paper) | `AUTONOMOUS_PANIC_CLOSE_OPTIONS=true python scripts/panic_close_options.py` |
| Disable LLM globally | `export LLM_ENABLED=false` (or unset — that's the default) |
| Disable options entries | `export OPTIONS_ENABLED=false` (default) |
| Disable autonomous code loop | GitHub Actions → autonomous-code-loop → Disable workflow |
| Block all new entries (emergency) | Toggle health to BLOCKED OR set every strategy `enabled=false` in `state.json` |
| Switch to safer risk profile | `export RISK_PROFILE=SAFE_FREE` |
| Trigger daily learning manually | GitHub Actions → daily-learning → Run workflow |

## Daily checklist (operator, ~5 min)

1. Inbox: scan for `[BLOCKED]`, `[OPTIONS APPROVAL NEEDED]`, daily summary
2. `scripts/trading_health.py` — confirm severity ≤ WARN
3. Alpaca dashboard — eyeball positions vs CLAUDE.md "Open positions"
4. If state.json has `validator reject:` lines → review rationale.md

## Severity ladder

| Severity | Meaning | Exit code | Action |
|---|---|---:|---|
| OK | All checks green | 0 | None |
| WARN | Minor inconsistency | 0 | Monitor in next run |
| DEGRADED | Partial outage | 2 | Investigate but trading continues |
| BLOCKED | Cannot trade safely | 3 | Stop manual interventions; fix Alpaca auth / state corruption |

## Common scenarios

### "I want to disable trading immediately"

The system is paper-only — there's no risk of real money loss. But to
quiet it down:

```bash
# Disable LLM (already off by default but be explicit)
gh secret set LLM_ENABLED -b "false"

# Disable options entries
gh secret set OPTIONS_ENABLED -b "false"

# Tighten the risk profile
gh secret set RISK_PROFILE -b "SAFE_FREE"
```

Or disable individual workflows in GitHub Actions UI.

### "LLM is misbehaving / hallucinating"

LLM cannot bypass deterministic gates. Worst case it proposes overrides
that get clamped/rejected by the schema + validator. Still, to silence:

```bash
gh secret set LLM_ENABLED -b "false"
```

The learning loop continues with deterministic adapter output. Daily
narrative and weekly retro stop producing LLM-augmented content but
the per-strategy size adjustments still happen.

### "Options panic close"

```bash
# Dry-run (always safe — prints what WOULD happen)
python scripts/panic_close_options.py

# Real submission (paper only — there is no live path)
CONFIRM_PANIC_CLOSE_OPTIONS=true python scripts/panic_close_options.py
```

The script:
- Skips contracts that already have an open SELL order
- Prices at ask × 0.95 (aggressive seller, still LIMIT — never MARKET)
- Tags each order with `client_order_id=panic-close-<sym>-<ts>` so the
  learning loop can attribute it correctly

### "How do I know if a workflow's state writes are violating policy?"

Run `scripts/audit_workflows.py`. Anything not on
`CONTENTS_WRITE_ALLOWLIST` that declares `contents: write` will be flagged.

The current allow-list is the source of truth — to add a new writer:

1. Add the workflow filename to `CONTENTS_WRITE_ALLOWLIST` in
   `scripts/audit_workflows.py`
2. Set `STATE_WRITE_ACTOR` env to one of:
   - `daily-learning`, `weekly-retro`, `daily-report`, or
     `manual-maintenance`
3. Use `shared/state_policy.assert_can_write_state(actor, reason)`
   in the Python code that writes the file

### "I need to verify a state.json change"

```bash
python -c "
import sys; sys.path.insert(0, 'shared')
from state_schema import validate_state
import json
state = json.load(open('learning-loop/state.json'))
sanitized, errors = validate_state(state)
print('errors:', errors)
print('strategies:', list(sanitized['strategies'].keys()))
"
```

### "Backtest a strategy with realistic slippage"

```bash
python -m backtest.run --strategy momentum-long --tickers AAPL MSFT NVDA --days 180
```

For the realistic path with slippage / gap / costs, use
`backtest.realism.replay_with_realism()` programmatically. Example:

```python
from backtest.realism import RealismConfig, replay_with_realism
from backtest.data import fetch_daily_bars
from backtest.strategies import momentum_long_signal_at

bars = fetch_daily_bars("NVDA", days=180)
result = replay_with_realism(
    bars, momentum_long_signal_at, ticker="NVDA",
    config=RealismConfig(slippage_bps=10, gap_penalty_pct=0.01,
                        missed_run_pct=0.05, cost_per_trade_usd=1.0),
)
print(result["summary"])  # profit_factor, max_drawdown_pct, etc.
```

### "Workflow file edit blocked by OAuth proxy"

GitHub workflow files require a `workflow` scope PAT. Edit
`scripts/workflow-templates/*.yml` instead — the `sync-workflows.yml`
workflow propagates changes automatically.

## Migration plan (future, not in this PR)

The 21-workflow fan-out is structurally fine but verbose. Eventual
consolidation into dispatchers:

- `entry-dispatcher.yml` — price + crypto + defense + geo + twitter + reddit
- `exit-dispatcher.yml` — exit-monitor + options-exit-monitor
- `daily-report.yml` — daily-learning + weekly-retro + state schema
- `health.yml` — monitor-health + trading-health + security-audit

For now we keep the per-monitor workflows; consolidation is a larger
PR that needs separate review.

## Inspecting autonomous decisions

All trading and code decisions write JSONL audit rows. Each row contains
`decision_type`, `reason`, `actor`, `affected_symbols`, `risk_metrics`,
`code_before_sha` / `code_after_sha` (for code events), and
`rollback_action` where reversible.

```bash
# Today's trading decisions (one decision per line, JSON)
cat journal/autonomy/$(date -u +%F).jsonl | jq '.decision_type + " " + .decision + " — " + .reason'

# Today's code-autonomy decisions
cat learning-loop/code-autonomy/history/$(date -u +%F).md

# Filter only EMERGENCY_CLOSE
cat journal/autonomy/$(date -u +%F).jsonl | jq 'select(.decision_type == "EMERGENCY_CLOSE")'

# Last 7 days, code patches that were merged
python3 -c "
import sys; sys.path.insert(0, 'shared')
from audit import read_range
for r in read_range(7, kind='code'):
    if r.get('decision_type') == 'PATCH_AUTO_MERGE':
        print(r['timestamp'], r['code_after_sha'][:8], r['reason'])
"
```

## Rolling back an autonomous code change

Every auto-merge records the pre-merge SHA in `code_before_sha`. To
revert a specific commit:

```bash
# Find the commit
grep -r "PATCH_AUTO_MERGE" learning-loop/code-autonomy/history/ | tail -5

# Revert
git revert --no-edit <code_after_sha>
git push origin main
```

The autonomous loop also revert-on-its-own: if post-merge health stays
DEGRADED for 3 consecutive cron ticks, `code_autonomy.revert_commit()`
fires automatically and writes a `PATCH_ROLLBACK` audit row.

## End-to-end system testing

`tools/e2e_system_test_agent/` is a hermetic test harness with fake
Alpaca / fake LLM / fake news / fake notify / fake state. No real
orders, no real network, no real secrets.

```bash
# Full run
python3 scripts/e2e_system_test_agent.py

# Just E2E suite
python3 scripts/e2e_system_test_agent.py --run-e2e

# Discovery + inventory only
python3 scripts/e2e_system_test_agent.py --discover
```

Outputs land in `reports/e2e/latest.{json,md}`. Coverage table shows
which of the 39 mapped capabilities are PASS / PARTIAL / UNCOVERED /
MISSING_MODULE. Exit code 0 on PASS/WARN, 2 on FAIL.

Full guide: `docs/E2E_SYSTEM_TEST_AGENT.md`.

CI: `.github/workflows/e2e-system-tests.yml` (push/PR/daily 06:45 UTC).

## System consistency audit

The agent in `tools/system_consistency_agent/` enforces the 8 system
principles. Run it locally before pushing big changes:

```bash
python3 scripts/system_consistency_agent.py
```

Exit codes:
- `0` — PASS / WARN (or `1` with `--strict` on WARN)
- `2` — FAIL or BLOCKED (or `1` with `--non-blocking` on FAIL)

What to do at each status:

- `BLOCKED` — stop. Read the "Blocking failures" section in
  `reports/system-consistency/latest.md`. Common: live endpoint added,
  risk gate removed, secret leaked, core module missing.
- `FAIL` — backlog; safe to keep trading, but a regression crept in.
- `WARN` — backlog only.
- `PASS` — green.

Full guide: `docs/SYSTEM_CONSISTENCY_AGENT.md`.

The same agent runs in CI as `.github/workflows/system-consistency-audit.yml`
on every push, PR, and daily 06:15 UTC. Artifacts are uploaded as
`system-consistency-report` (30-day retention).

## How to disable the autonomous code loop

```
GitHub → Actions → autonomous-code-loop.yml → "..." → Disable workflow
```

The trading lifecycle is unaffected — it does NOT depend on the code
loop. The code loop only edits non-trading-path code (validator's
allowlist).

## How to disable new trading entries

Four options, increasing scope:

1. Single strategy: edit `learning-loop/state.json::strategies.<name>.enabled = false`. Daily-learning is allowed to write state.
2. Single asset class: `config/instrument_windows.json::asset_classes.<class>.enabled = false`.
3. All entries via global block: `scripts/autonomous_remediation.py` flips BLOCK if health is BLOCKED. Force this by setting `ALPACA_API_KEY=""` — auth check fails, BLOCKED rolls down.
4. Stop the workflow: disable individual entry monitors in GitHub Actions UI.

## On-call escalation

- Alpaca down: nothing to do (paper). Wait for restore.
- GitHub Actions down: nothing to do. Manual closes via Alpaca UI.
- Anthropic 429: LLM_ENABLED=false stops the noise; system trades on
  deterministic baseline.
- Cloudflare Workers down: monitors fall back to direct alpaca_orders
  path (after this PR).
- Local state corruption: revert `learning-loop/state.json` via git;
  next daily-learning rebuilds.
