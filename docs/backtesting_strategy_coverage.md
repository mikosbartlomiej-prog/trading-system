# Backtesting Strategy Coverage (v3.17.0 — 2026-06-04)

**Modules:**
- `backtest/run.py` (walk-forward + crypto-hourly + event-driven harness)
- `backtest/strategies.py` (signal functions — bar-driven)
- `backtest/crypto_data.py` (v3.16.0 hourly Alpaca v1beta3 fetcher)
- `backtest/event_data.py` + `event_replay.py` + `event_strategies.py` (v3.16.0 GDELT MVP)
- `backtest/strategy_registry.py` (registry with readiness levels)
- `backtest/realism.py` (slippage + gap)

**Audit-board feedback closed:** FB-005
**Drift guarded by:** `tests/test_strategy_registry_drift_v3170.py` — enforces
that every strategy in `learning-loop/state.json::strategies` has a REGISTRY
entry. Test runs in CI; flips red if operator adds/removes a strategy
without keeping registry honest.

## Honest coverage snapshot (post v3.16.0 + v3.17.0)

| Strategy | Live? | Readiness | Why |
|---|---|---|---|
| momentum-long | ✅ price-monitor | ✅ HAS_SIGNAL | Walk-forward ready |
| momentum-long-loose | research | ✅ HAS_SIGNAL | Research-only variant |
| overbought-short | disabled in state.json | ✅ HAS_SIGNAL | Backtested 2026-05-08 → -$2,065 / 11% WR; disabled live |
| crypto-momentum | ✅ crypto-monitor | ✅ HAS_SIGNAL (v3.16.0) | Hourly Alpaca v1beta3 harness shipped |
| crypto-oversold-bounce | ✅ crypto-monitor | ✅ HAS_SIGNAL (v3.16.0) | Same hourly harness |
| crypto-breakdown | disabled (structural) | n/a NOT_APPLICABLE | Alpaca paper crypto LONG-only |
| geo-defense | ✅ geo-monitor | ⚠ MVP_IN_PROGRESS (v3.16.0) | GDELT replay shipped; results ADVISORY until n≥50 |
| geo-energy | ✅ geo-monitor | ⚠ MVP_IN_PROGRESS (v3.16.0) | Same |
| geo-gold | ✅ geo-monitor | ⚠ MVP_IN_PROGRESS (v3.16.0) | Same |
| geo-xom | enabled tag but deprecated routine path | EVENT_DRIVEN | Defunct; shares classifier with geo-energy |
| options-momentum | ✅ options-monitor | ⚠ INTERFACE | Requires historical option chain (paid data; no free path). Operator decision deferred. |
| allocator-rebalance | ✅ morning-allocator | n/a NOT_APPLICABLE | Portfolio sim, not signal replay |
| alloc-exit / alloc-reduce | admin emission tags | n/a NOT_APPLICABLE | Administrative tags |

## What HAS_SIGNAL means

The strategy has a pure Python signal function in `backtest/strategies.py`
that takes `(idx, bars)` and returns a signal dict or None. The
walk-forward harness can replay it over any window of bars.

These strategies pass:
- no-lookahead test (`tests/architecture_vnext/test_backtest_no_lookahead.py`)
- realism test (`test_backtest_realism.py`)
- determinism (same bars → same trades)

## What INTERFACE means

Signal function name registered, but the function does not exist yet OR
the harness lacks the data feed for it (e.g. hourly crypto bars). The
strategy runs LIVE on real Alpaca data but cannot be replayed.

## What EVENT_DRIVEN means

Strategy responds to a news/event stream rather than bars. Needs a
historical event replay harness — not currently implemented. Backlog item.

## What NOT_APPLICABLE means

Strategy is an administrative tag, deprecated path, or a portfolio-level
process that doesn't have a single signal function. Backtest must use a
different paradigm.

## EDGE_GATE policy

`learning-loop/edge_validator.py` enforces backtest gate: a strategy
cannot have `enabled=true` AND `EDGE_GATE_ENABLED=true` unless its
backtest passes WR ≥ 50%, PF ≥ 1.3, MDD < 20%, n ≥ 10.

**As of v3.15.0:** `EDGE_GATE_ENABLED=false` (default). Reason: only
3/12 strategies are backtest-ready. Cannot honestly enforce the gate on
strategies that lack a replay harness.

**Path to EDGE_GATE_ENABLED=true:**
1. Add hourly-crypto-bar fetcher to `backtest/data.py`.
2. Implement `crypto_momentum_signal_at` + `crypto_oversold_bounce_signal_at`
   pure functions in `backtest/strategies.py`.
3. Backtest crypto strategies for 6 months.
4. Decide: enable strategy in `state.json` only if WR/PF/MDD pass.
5. For event-driven strategies (geo-*): build event replay harness.

This is **STRAT-003** in the backlog.

## How to use the registry

```python
from backtest.strategy_registry import (
    coverage_report, is_backtest_ready, REGISTRY,
)

r = coverage_report()
print(f"Backtest ready: {r['backtest_ready_pct']:.1f}%")
print(f"Uncovered tradeable: {r['tradeable_uncovered']}")
```

## Tests

`tests/test_feedback_v3150.py::TestStrategyRegistry` — 4 tests covering
registration, readiness flags, coverage report shape.

## Cost

$0/month. Pure historical bar data. Free Alpaca IEX.

## Acknowledged gap

The system trades strategies that cannot be backtested today. This is
documented honestly via this registry. The operator can see the gap
explicitly via `coverage_report()`. Until closed, EDGE_GATE stays off and
the strategy lacks empirical edge validation.

This is the most important honest disclosure in the v3.15.0 audit.
