# Backtesting Strategy Coverage (v3.15.0)

**Modules:**
- `backtest/run.py` (walk-forward harness)
- `backtest/strategies.py` (signal functions)
- `backtest/strategy_registry.py` (NEW v3.15.0)
- `backtest/realism.py` (slippage + gap)

**Audit-board feedback closed:** FB-005
**Status:** registry shipped; coverage gap documented honestly

## Honest coverage snapshot

| Strategy | Live? | Backtest-ready? | Why |
|---|---|---|---|
| momentum-long | ✅ | ✅ HAS_SIGNAL | Walk-forward ready |
| momentum-long-loose | research | ✅ HAS_SIGNAL | Research-only variant |
| overbought-short | disabled | ✅ HAS_SIGNAL | Backtested → showed -$2,065 11% WR; disabled live |
| crypto-momentum | ✅ | ⚠ INTERFACE | Live; needs hourly crypto-bar fetcher in harness |
| crypto-oversold-bounce | ✅ | ⚠ INTERFACE | Live (v3.13.3 relaxation); needs same hourly harness |
| crypto-breakdown | n/a | n/a NOT_APPLICABLE | Alpaca paper crypto LONG-only |
| geo-defense | ✅ | ⚠ EVENT_DRIVEN | Needs historical news replay |
| geo-energy | ✅ | ⚠ EVENT_DRIVEN | Same |
| geo-gold | ✅ | ⚠ EVENT_DRIVEN | Same |
| geo-xom | disabled | n/a NOT_APPLICABLE | Deprecated routine path |
| options-momentum | ✅ | ⚠ INTERFACE | Requires historical option chain (paid data; no free path) |
| allocator-rebalance | ✅ | n/a NOT_APPLICABLE | Portfolio sim, not signal replay |
| alloc-exit / alloc-reduce | admin | n/a NOT_APPLICABLE | Administrative tags |

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
