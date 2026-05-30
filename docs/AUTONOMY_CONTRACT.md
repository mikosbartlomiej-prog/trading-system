# Autonomy Contract — trading lifecycle

> **Last updated:** 2026-05-30 (v3.13.0). Adds: v3.12.0 confidence gate
> + safe_mode + heartbeat as runtime layers. Adds: Multi-Agent Audit
> Board (`agents/`) as REVIEW-ONLY layer explicitly outside the
> runtime decision path.

This is the formal contract that the trading system makes with the
operator. **There is no human approval step anywhere in the trading
lifecycle.** Every signal, every position, every error ends in a
deterministic decision, audited and (where possible) reversible.

## Invariants

1. **Paper trading only, forever.** `shared/autonomy.py::assert_paper_only`
   is the only allowed broker endpoint check. The only string it accepts
   is `https://paper-api.alpaca.markets`. Any other value raises
   `PaperOnlyViolation` and the autonomous flow STOPS.

2. **No FORBIDDEN states.** These strings (or any case-insensitive variant)
   may not appear in trading code paths:
   - APPROVAL_NEEDED
   - WAITING_FOR_HUMAN
   - MANUAL_CONFIRM_REQUIRED
   - PENDING_USER_APPROVAL
   - "please approve" / "awaiting operator"

   `tests/architecture_vnext/test_autonomy.py::TestRepoForbiddenScan`
   fails if any code outside `docs/`, `tests/architecture_vnext/`,
   `CLAUDE.md`, or `shared/autonomy.py` itself emits these.

3. **Every decision is one of these closed types** (see `DECISION_TYPES`
   in `shared/autonomy.py`):

   | Decision type | When it fires |
   |---|---|
   | `APPROVE_ENTRY` | Signal passed all gates; order placed |
   | `REJECT_ENTRY` | Signal failed a gate; no order, audit only |
   | `HOLD_POSITION` | Position checked, no action |
   | `CLOSE_POSITION` | TP/SL/trailing decided to close |
   | `PAUSE_STRATEGY` | Risk/failure rule fires |
   | `RESUME_STRATEGY` | Cooldown + health + risk-resolved checks pass |
   | `BLOCK_NEW_ENTRIES` | Aggregate block from health/risk |
   | `CLEANUP_STALE_ORDERS` | Stale order maintenance |
   | `RECREATE_EXIT_PLAN` | Position without exit found |
   | `EMERGENCY_CLOSE` | Hard loss / DTE / no exit / defensive mode |
   | `PANIC_CLOSE_OPTIONS` | Aggregate options risk BLOCKED |
   | `PATCH_APPROVE` / `PATCH_REJECT` / `PATCH_AUTO_MERGE` / `PATCH_ROLLBACK` | Code autonomy events |
   | `SAFE_MODE_ENTERED` / `SAFE_MODE_EXITED` | v3.12.0 — runtime safe_mode transitions |
   | `CONFIDENCE_BLOCK` / `CONFIDENCE_ALERT` | v3.12.0 — confidence gate decisions |

4. **Every decision is audited.** `shared/audit.py::write_audit_event`
   writes one JSONL row per decision under `journal/autonomy/`
   (trading) or `learning-loop/code-autonomy/history/` (code).

## Trading lifecycle (no approval anywhere) — v3.12.0+

```
Signal source (monitor)
    │
    ▼
[Gate 1] instrument_windows.can_trade_now → defer (REJECT_ENTRY) or pass
    │
    ▼
[Gate 2] portfolio_risk → reject (REJECT_ENTRY) or pass
    │
    ▼
[Gate 3] safe_mode.gate_new_entry → reject if active (v3.12.0)
    │
    ▼
[Gate 4] confidence.compute_confidence → BLOCK if total < 0.50 (v3.12.0)
    │     (5 components: data_quality / signal_strength /
    │      regime_alignment / system_health / risk_state)
    ▼
[Gate 5] risk_officer.evaluate_trade → reject or APPROVE
    │     (enforces ALL prior gate decisions + own checks)
    ▼
[Gate 6] pdt_guard.evaluate_order → defer / block / allow
    │
    ▼
[Order] Alpaca paper REST via safe_close (for SELL) or place_*_bracket (for BUY)
    │     v3.11.3: safe_close cancels OCO brackets BEFORE close (else 403)
    ▼
[Audit] make_decision + write_audit_event(kind="trading")
```

**Hard invariants:**
- High confidence CANNOT override risk_officer REJECT (verified by test)
- safe_mode active BLOCKS new entries (emergency closes always bypass)
- Every gate writes to `journal/autonomy/<date>.jsonl` audit JSONL

Position management runs in `exit-monitor` + `options-exit-monitor` +
`autonomous-remediation.yml`:

```
For each open position:
    if TP / SL / trailing / regime mismatch → CLOSE_POSITION
    else if emergency criteria → EMERGENCY_CLOSE (via emergency_engine)
    else if no exit plan → RECREATE_EXIT_PLAN (via remediation)
    else → HOLD_POSITION
```

No step asks the operator. The decisions are deterministic and audited.

## Emergency-close autonomy

`shared/emergency_engine.py::scan_emergency_conditions` returns a
deterministic list of positions matching:

- position loss ≤ HARD_LOSS_PCT (default -15%)
- option DTE ≤ NEAR_DTE_DAYS (default 5) AND loss ≤ DEEP_OPTION_LOSS_PCT (default -40%)
- position has no valid exit plan (no open opposite-side order)
- duplicate exit orders
- stale exit order > STALE_ORDER_HOURS (default 24h)
- defensive_mode_active in state

`execute_emergency_close` follows the canonical Alpaca paper flow:
1. Cancel any conflicting open orders on the symbol
2. DELETE /v2/positions/{symbol}
3. (No MARKET fallback — that gets HIGH_RISK rejected if proposed.)

Per-symbol rate limit: `MAX_EMERGENCY_ATTEMPTS_PER_DAY` (default 3).

## Options autonomy

| Outcome | When |
|---|---|
| `APPROVE_ENTRY` (order placed) | OPTIONS_ENABLED=true + all gates pass + liquidity OK + portfolio premium-at-risk OK |
| `REJECT_ENTRY` (audit email) | Any of the above fail |
| `EMERGENCY_CLOSE` | DTE ≤ 5 + deep loss, OR loss ≤ -15%, OR no exit plan |
| `PANIC_CLOSE_OPTIONS` | Aggregate options safety BLOCKED |

Subject line is now `[OPTIONS REJECTED]` (was `[OPTIONS APPROVAL NEEDED]`
— removed because the system never asks the operator).

## Strategy pause/resume autonomy

`shared/remediation.py::list_actions` + `validation.validate_adaptation`:

- **Auto-pause** allowed any time on:
  - 5+ consecutive losses
  - repeated API failures
  - state validation errors
  - excessive drawdown
- **Auto-resume** requires:
  - cooldown expired (default 24h)
  - `resume_min_health_ok_consecutive` consecutive OK health checks
  - the underlying risk condition resolved
  - bounded by `config/autonomy_bounds.json::strategy_enabled`

## Optional manual overrides (documentation only)

The system supports optional operator tools. These are **never required**
in the trading lifecycle; they exist for debug / manual investigation:

- `scripts/panic_close_options.py` (dry-run by default)
- `scripts/emergency_close_*.py` (historical, kept for audit)
- Cron `workflow_dispatch` triggers (manual one-off runs)

Crucially: the autonomy layer does NOT wait for these. If
`AUTONOMOUS_PANIC_CLOSE_OPTIONS=true` is set, the same script proceeds
without an operator-supplied `CONFIRM_PANIC_CLOSE_OPTIONS`.

## What the operator *can* do

- Read audit JSONL: `journal/autonomy/YYYY-MM-DD.jsonl`
- Disable individual workflows in GitHub Actions UI
- Set `OPTIONS_ENABLED=false` to kill new options entries
- Set `LLM_ENABLED=false` to kill LLM features (defaults to false anyway)
- Change `RISK_PROFILE` (tighter caps apply to all autonomy)
- Trigger optional one-off scripts above

## What the operator *cannot* do

The contract guarantees that the operator's input is **not needed** for
the system to keep operating safely. There is no inbox in which a
"please approve" mail can pile up.

---

## Multi-Agent Audit Board separation (v3.13.0)

The `agents/` directory contains 11 prompt-based area reviewers + Final
Arbiter. They are **REVIEW-ONLY** and explicitly OUTSIDE this autonomy
contract's decision path:

```
[ THIS AUTONOMY CONTRACT — runtime, deterministic, NO LLMs ]
  signal → safe_mode → confidence → risk → decision → audit → execution

[ AUDIT BOARD — offline, prompt-based, may use LLM ]
  reads:  code, configs, audit JSONL, reports, tests
  emits:  findings, blockers, final decision
  cannot: trade, modify risk, modify safe_mode, modify kill_switch
```

The Audit Board is invoked manually by the operator (or in CI as a
weekly gate). Its decisions are recommendations, not commands. The
runtime decision path is unaffected by Audit Board verdicts during
a session.

See `docs/AGENTS_DOCUMENTATION.md` and `agents/README.md` for details.
