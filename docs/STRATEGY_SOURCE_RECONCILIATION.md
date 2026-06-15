# Strategy Source Reconciliation (v3.24.0)

**Generated:** `2026-06-15T11:45:53.423591+00:00`
**As of:** `2026-06-15T11:45:53.284136+00:00`
**Git HEAD:** `d532e3504e88290707d9cfaa12d16046f00297ca`

## Source totals

| Source | Count |
|---|---|
| Shadow registry | 7 |
| state.json | 12 |
| backtest/strategies.py functions | 5 |
| backtest/strategy_registry.py entries | 0 |
| monitors with `"strategy"` literals | 22 |
| ledger last 7 days | 3 |
| **Union (rows below)** | 30 |

## Status distribution

| Status | Count |
|---|---|
| `ACTIVE_MONITOR_UNREGISTERED` | 16 |
| `ACTIVE_RUNTIME_SOURCE` | 2 |
| `ACTIVE_SHADOW_SOURCE` | 1 |
| `DEAD_ORPHAN` | 1 |
| `DISABLED_INTENTIONALLY` | 2 |
| `OBSERVE_ONLY` | 2 |
| `ZOMBIE_STATE_ONLY` | 6 |

## Auto-suggested safe conversions

| Strategy | From → To | Action |
|---|---|---|
| (none) | | |

## Operator flags (NOT auto-deleted)

| Strategy | Status | Note |
|---|---|---|
| `alloc-exit` | `ZOMBIE_STATE_ONLY` | operator review — flagged but NOT deleted from state.json |
| `alloc-reduce` | `ZOMBIE_STATE_ONLY` | operator review — flagged but NOT deleted from state.json |
| `allocator-rebalance` | `ZOMBIE_STATE_ONLY` | operator review — flagged but NOT deleted from state.json |
| `geo-energy` | `ZOMBIE_STATE_ONLY` | operator review — flagged but NOT deleted from state.json |
| `geo-gold` | `ZOMBIE_STATE_ONLY` | operator review — flagged but NOT deleted from state.json |
| `geo-xom` | `ZOMBIE_STATE_ONLY` | operator review — flagged but NOT deleted from state.json |
| `momentum-long` | `DEAD_ORPHAN` | operator review — flagged but NOT deleted from state.json |

## Per-strategy detail

| Strategy | Status | In Registry | In State | Backtest fn | Monitor | Ledger 7d | Observe-only | Has signal_at | Enabled | Suggested action |
|---|---|---|---|---|---|---|---|---|---|---|
| `alloc-exit` | `ZOMBIE_STATE_ONLY` | no | yes | no | no (-) | 0 | no | no | yes | operator review — flagged but NOT deleted. Consider removing from state.json or registering in shadow_opportunity_generator |
| `alloc-reduce` | `ZOMBIE_STATE_ONLY` | no | yes | no | no (-) | 0 | no | no | yes | operator review — flagged but NOT deleted. Consider removing from state.json or registering in shadow_opportunity_generator |
| `allocator-rebalance` | `ZOMBIE_STATE_ONLY` | no | yes | no | no (-) | 0 | no | no | yes | operator review — flagged but NOT deleted. Consider removing from state.json or registering in shadow_opportunity_generator |
| `crypto-breakdown` | `DISABLED_INTENTIONALLY` | no | yes | no | yes (crypto-monitor) | 86 | no | no | no | no action; intentional disable / pause respected |
| `crypto-momentum` | `ACTIVE_RUNTIME_SOURCE` | yes | yes | yes | yes (crypto-monitor) | 16202 | no | yes | yes | no action; live and recording ledger rows |
| `crypto-oversold-bounce` | `ACTIVE_RUNTIME_SOURCE` | yes | yes | yes | yes (crypto-monitor) | 70 | no | yes | yes | no action; live and recording ledger rows |
| `defense-long` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (defense-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `defense-short` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (defense-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `geo-defense` | `OBSERVE_ONLY` | yes | yes | no | no (-) | 0 | yes | no | yes | no action; observe-only registry entry |
| `geo-energy` | `ZOMBIE_STATE_ONLY` | no | yes | no | no (-) | 0 | no | no | yes | operator review — flagged but NOT deleted. Consider removing from state.json or registering in shadow_opportunity_generator |
| `geo-gold` | `ZOMBIE_STATE_ONLY` | no | yes | no | no (-) | 0 | no | no | yes | operator review — flagged but NOT deleted. Consider removing from state.json or registering in shadow_opportunity_generator |
| `geo-xom` | `ZOMBIE_STATE_ONLY` | no | yes | no | no (-) | 0 | no | no | yes | operator review — flagged but NOT deleted. Consider removing from state.json or registering in shadow_opportunity_generator |
| `momentum-long` | `DEAD_ORPHAN` | yes | no | yes | yes (price-monitor) | 0 | no | yes | yes | operator review — flagged but NOT deleted. Likely renamed strategy or stale audit prefix |
| `momentum-long-loose` | `ACTIVE_SHADOW_SOURCE` | yes | no | yes | no (-) | 0 | no | yes | yes | no action; shadow-only registry entry; verify no monitor traffic expected |
| `options-momentum` | `OBSERVE_ONLY` | yes | yes | no | yes (options-monitor) | 0 | yes | no | yes | no action; observe-only registry entry |
| `overbought-short` | `DISABLED_INTENTIONALLY` | yes | yes | yes | yes (price-monitor) | 0 | no | yes | no | no action; intentional disable / pause respected |
| `politician-djt-form4` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (politician-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `politician-stock-act` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (politician-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `position-manager` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (exit-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `reddit-sentiment` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (reddit-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-A-direct` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-B-escalation-defense` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-B-escalation-energy` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-C-deescalation-spy` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-C-deescalation-xle` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-D-macro-bear-gld` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-D-macro-bear-spy` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-D-macro-bull` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-news` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |
| `twitter-news-review` | `ACTIVE_MONITOR_UNREGISTERED` | no | no | no | yes (twitter-monitor) | 0 | no | no | yes | operator: add strategy to shadow_opportunity_generator registry OR confirm this is an admin-only client_order_id prefix (e.g. allocator tag) |

## Status enum

- `ACTIVE_RUNTIME_SOURCE`     — registry + monitor + recent ledger rows
- `ACTIVE_SHADOW_SOURCE`      — registry + signal_at fn; no monitor traffic
- `ACTIVE_MONITOR_UNREGISTERED` — monitor / ledger traffic; not in registry
- `OBSERVE_ONLY`              — registry observe_only=True OR no signal_at
- `BACKTEST_ONLY`             — backtest function only
- `ZOMBIE_STATE_ONLY`         — only state.json
- `ZOMBIE_REGISTRY_ONLY`      — only registry, no monitor / ledger / state
- `DEAD_ORPHAN`               — nowhere active
- `DISABLED_INTENTIONALLY`    — explicit enabled=false or paused_until future

## Safety contract

- This reconciler is READ-ONLY.
- It does NOT delete state.json entries.
- It does NOT mutate the shadow_opportunity_generator registry.
- It does NOT submit orders or call the broker.
- Operator must approve every conversion / deletion manually.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `STRATEGY_RECONCILIATION_IS_READ_ONLY`
