# LLM Advisory Output Quality Report (v3.31)

_Generated:_ `2026-06-16T13:11:17.186898+00:00`

## Aggregate verdict

- **Aggregate:** `USEFUL`
- **Agents total:** `10`
- **Pass:** `10`
- **LOW_QUALITY:** `0`
- **EMPTY:** `0`
- **Missing file:** `0`
- **Invariants clean (advisory_only + must_not_execute_orders):** `10/10`

## Per-agent table

| Agent | Verdict | Findings | Risks | Next-actions | Limitations | Advisory-only | Must-not-execute | Provider status |
|---|---|---:|---:|---:|---:|---|---|---|
| `ALLOCATOR_PLAN_CRITIC` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |
| `DAILY_BRIEF` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |
| `EQUITY_RECONCILIATION_CRITIC` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |
| `FINAL_ARBITER` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |
| `INCIDENT_REVIEW` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |
| `NO_SIGNAL_DIAGNOSTIC` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |
| `RISK_REVIEW` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |
| `SHADOW_CANDIDATE_REVIEW` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |
| `STRATEGY_REVIEW` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |
| `TRIGGER_WATCHLIST_REVIEW` | `USEFUL` | 3 | 2 | 2 | 235 | `True` | `True` | `PROVIDER_NOT_INVOKED` |

## Per-agent rationale

### `ALLOCATOR_PLAN_CRITIC`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

### `DAILY_BRIEF`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

### `EQUITY_RECONCILIATION_CRITIC`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

### `FINAL_ARBITER`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

### `INCIDENT_REVIEW`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

### `NO_SIGNAL_DIAGNOSTIC`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

### `RISK_REVIEW`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

### `SHADOW_CANDIDATE_REVIEW`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

### `STRATEGY_REVIEW`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

### `TRIGGER_WATCHLIST_REVIEW`
- all v3.30 thresholds met: findings=3, risks=2, next_actions=2, limitations_len=235

---

### Standing markers
- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER`
- `LLM_ADVISORY_ONLY`

> This reporter is read-only. It never calls the broker, never places orders, never flips any flag, and never auto-clears safe_mode. Deterministic gates remain final.
