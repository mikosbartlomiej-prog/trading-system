# Architecture vNext — deterministic, free, paper-only

This doc captures the architectural invariants introduced in the
2026-05-14 super-session. It complements (does not replace)
`docs/STRATEGY.md`, `docs/PRODUCT.md`, and `CLAUDE.md`.

**Current status:**
- 8/8 system principles PASS
- `tools/system_consistency_agent/`: 99.1/100 (WARN, 2 backlog warnings)
- `tools/e2e_system_test_agent/`: 220 tests green, 28/40 capabilities fully covered

For agent-level details: `docs/AGENTS_DOCUMENTATION.md`.

## Core invariants

1. **Paper trading only, forever.** No live broker URL anywhere in the
   repo. No `LIVE_TRADING` flag. The Alpaca base URL is hard-coded to
   `https://paper-api.alpaca.markets`.
2. **Free tier only.** No paid services, no SaaS databases, no upgraded
   plans. All dependencies are public APIs (Alpaca paper, NewsAPI free,
   Finnhub free, Yahoo public, Bluesky AT-Protocol, GitHub Actions,
   Cloudflare Workers free tier).
3. **Deterministic execution.** LLM is OFF by default. The system must
   place, reject, and close trades with `LLM_ENABLED=false`.
4. **Git is an audit log, not a runtime database.** Monitors do not
   commit state.json. The only writers are `daily-learning`,
   `weekly-retro`, `daily-report`, and `manual-maintenance`.
5. **Risk gates cannot be bypassed.** Every entry order passes through
   four gates in this order: trading window → portfolio_risk →
   risk_officer → broker. LLM is strictly additive — it can suggest
   rankings or write rationales, never short-circuit a gate.

## Module map

| Layer | Module | Purpose |
|---|---|---|
| Config | `shared/runtime_config.py` | `LLM_ENABLED`, `OPTIONS_ENABLED`, `RISK_PROFILE` flags + per-profile limits |
| State policy | `shared/state_policy.py` | Whitelist of allowed `STATE_WRITE_ACTOR` names; raises if a monitor tries to write |
| State schema | `shared/state_schema.py` | Validates state.json → drops hallucinated keys, clamps numeric overrides |
| Portfolio risk | `shared/portfolio_risk.py` | Per-symbol / correlated-bucket / gross / options-premium / cash caps |
| Signal confirm | `shared/signal_confirmation.py` | News/social must have price+volume confirmation, dedupe, cooldown, freshness |
| Learning validate | `learning-loop/validation.py` | Sample-size rules + step bounds + once-per-day enforcement |
| Health | `scripts/trading_health.py` | "Can the system trade right now?" — JSON + Markdown |
| Audit | `scripts/audit_workflows.py` | Static check: concurrency, permissions, git-write parity |
| Secret scan | `scripts/secret_scan_light.py` | Regex-based scan for accidental key leaks |
| Panic close | `scripts/panic_close_options.py` | Dry-run by default; closes all open options on opt-in |
| Realism | `backtest/realism.py` | Slippage, gap penalty, missed runs, profit factor, max DD |

## Order execution path (paper-only, deterministic)

```
Monitor (price/crypto/defense/geo/twitter/reddit/options)
  │
  ▼ build signal dict
shared/instrument_windows.can_trade_now()
  │   PASS                FAIL → log + defer
  ▼
shared/alpaca_orders._portfolio_risk_gate()         ← spec §D
  │   APPROVE             REJECT → log + skip
  ▼
shared/risk_officer.evaluate_trade()                 ← whitelist + R:R + drawdown + VIX
  │   APPROVE             REJECT → log + skip
  ▼
Alpaca REST /v2/orders (paper)
  │   200/201             4xx/5xx → log + email
  ▼
shared/notify.notify_*    journal/trades-YYYY-MM-DD.md
```

Every step is deterministic Python. LLM never sits on this path.

## LLM isolation

The learning loop is the ONLY place LLM is invoked. Even there:

1. `learning-loop/llm_client.py::USE_LLM` honours `LLM_ENABLED` first,
   falls back to legacy `USE_LLM_LEARNING`. Default is **false**.
2. LLM-proposed `state_overrides` pass through:
   - `safe_apply_overrides` — whitelist-enforced; drops unknown fields
   - `state_schema.validate_state` — schema check + clamps
   - `learning-loop/validation.py::validate_adaptation` — sample-size
     rules + step bounds + once-per-day rule
3. Even after all three layers, the override only affects
   `size_multiplier`, `enabled`, `side_bias`, `paused_until`, `notes` —
   it can never enable a non-whitelisted strategy or remove a risk gate.

If LLM is unreachable (no key, no Worker URL, 429s, timeouts), the
loop continues with the deterministic adapter output.

## State write policy

State.json is treated as a **slow-update audit snapshot**, not a
fast-update runtime cache. Allowed writers (read from
`STATE_WRITE_ACTOR` env):

- `daily-learning`
- `weekly-retro`
- `daily-report`
- `manual-maintenance`
- `test`, `local-dev`

Any other actor (`exit-monitor`, `reddit-monitor`, …) trying to write
state raises `StateWriteForbidden`. The workflows that previously
committed state on every tick (`exit-monitor.yml`, `reddit-monitor.yml`,
`crypto-monitor.yml` cleanup) have been switched to `contents: read`.

### Known follow-up

`shared/peak_tracker.py` stores intraday `daily_peak` + `trailing_state`
in `learning-loop/state.json`. Without commit, that state resets per
cron tick — trailing stops will be best-effort. Backlog: migrate
peak_tracker to `learning-loop/runtime_state.json` behind a separate
manual-maintenance workflow.

## Workflow simplification

- Every `schedule:`-triggered workflow now has:

  ```yaml
  concurrency:
    group: ${{ github.workflow }}
    cancel-in-progress: true
  ```

- Default permission is `contents: read`. Write is on an explicit
  allow-list (`scripts/audit_workflows.py::CONTENTS_WRITE_ALLOWLIST`).
- A new `.github/workflows/security-audit.yml` runs on every PR + push
  to main:
  - `scripts/audit_workflows.py`
  - `scripts/secret_scan_light.py`
  - `tests/architecture_vnext/test_*.py`

The 21-workflow fan-out is preserved (not consolidated to dispatchers
yet — that is bigger surgery). Future migration plan is in
`docs/OPERATIONS_RUNBOOK.md`.

## Options safety

- `OPTIONS_ENABLED=false` by default. `options-monitor` exits with a
  safe no-op when the flag is unset.
- Liquidity gate in `options-monitor/monitor.py::check_options_liquidity`:
  - bid + ask available
  - ask > bid (no crossed/locked)
  - spread ≤ `OPTIONS_SPREAD_PCT_MAX` (default 20%)
  - open_interest ≥ `OPTIONS_MIN_OPEN_INTEREST` (default 100) when
    populated
  - volume ≥ `OPTIONS_MIN_VOLUME` (default 10) when populated
- Portfolio gate enforces `max_options_premium_at_risk_pct` per profile.
- `scripts/panic_close_options.py` — dry-run by default; submits SELL
  LIMIT only with `CONFIRM_PANIC_CLOSE_OPTIONS=true`.

## News / social confirmation

`shared/signal_confirmation.py` provides:

- `confirm_price_volume(symbol, side, market_data, config)`
- `dedupe_event(event, EventCache)` with on-disk persistence
- `CooldownTracker(symbol, strategy, hours)`
- `article_fresh(published_at, max_age_hours)` — rejects stale and
  future-dated articles
- `confirm_event_signal(...)` — composite pipeline

Wiring into individual news/social monitors is the **next backlog
item** — the module is shipped, fully tested, and ready. Per the
implementation budget I prioritised:

1. Foundation modules + tests
2. Wire into `shared/alpaca_orders.py` (central choke point — covers
   all stock + crypto execution paths)
3. Wire into `options-monitor` (only path that bypassed alpaca_orders)
4. Workflow + script + docs hardening

That covers all order placement. News monitors still emit alerts; once
they call `confirm_event_signal` before forwarding to alpaca_orders,
the gate is end-to-end.
