# Crypto Backtest Harness (v3.16)

**Status:** SHIPPED 2026-06-04 (v3.16)
**Closes:** audit-board STRAT-002 question by 2026-06-16 review deadline
**Code:** `backtest/crypto_data.py`, `backtest/strategies.py`, `backtest/run.py`,
`backtest/strategy_registry.py`, `tests/test_crypto_backtest_v3160.py`

---

## Why this exists

`crypto-momentum` and `crypto-oversold-bounce` are two of the most actively
debated strategies in the system. Both are live in `crypto-monitor`, both
have 0 lifetime fills as of 2026-06-04, and both have the LLM Senior PM
repeatedly flagging them in daily learning runs. Without a backtest we
cannot tell whether the empirical silence is:

1. Correct dormancy (filter says "no edge here, don't trade") — OR
2. A broken filter that should be relaxed further

Until v3.16, the `backtest/` harness only supported daily-bar US equity
strategies. The two crypto strategies were registered as `INTERFACE` in
`strategy_registry.py` — i.e. "we know the strategy exists, but cannot
backtest it." That was the single largest gap in our pre-trade evidence
chain.

v3.16 ships the missing piece:

- **`backtest/crypto_data.py`**: Alpaca v1beta3 `/v1beta3/crypto/us/bars`
  fetcher with pagination, JSON cache, fail-soft contract (any failure
  returns `None`).
- **`backtest/strategies.py`**: `crypto_momentum_signal_at` and
  `crypto_oversold_bounce_signal_at` — pure functions that mirror
  `crypto-monitor/monitor.py::check_crypto_signal` LONG branches with
  IDENTICAL constants.
- **`backtest/run.py`**: auto-detect crypto strategies, add `--hours` +
  `--explain-zero-fires` CLI flags. Crypto strategies automatically use
  hourly bars; stocks continue with daily.
- **`backtest/strategy_registry.py`**: flip both crypto entries from
  `INTERFACE` → `HAS_SIGNAL`.

---

## Architecture

```
operator runs:
  python -m backtest.run --strategy crypto-oversold-bounce
                          --tickers BTC/USD ETH/USD
                          --hours 4320
                          --mode both

run.py:
  1. detect strategy ∈ CRYPTO_STRATEGIES → asset_class auto-promote to "crypto"
  2. for each ticker:
     a. fetch hourly bars via backtest/crypto_data.py
        - cache in backtest/cache/crypto/<sym>_<from>_<to>.json
        - fail-soft: missing creds / HTTP error / empty payload → None → skip
     b. (optional) --explain-zero-fires: sample 25 bars, run signal_fn,
        print per-bar rejection reasons for any None returns
     c. replay() walk-forward (idealized mode) — bracket SL/TP simulation
     d. replay_with_realism() — adds 25 bps crypto slippage + gap penalty
  3. print aggregate stats + write ledger JSON to backtest/results/
```

The crypto signal functions are **drop-in replacements** for the existing
stock signal_fn interface `signal_fn(idx, bars) → dict | None`. This
means:

- The `replay()` walk-forward loop works unchanged.
- The realism wrapper (`replay_with_realism()`) works unchanged.
- The no-lookahead invariant test (v3.10 Phase F) is auto-applied.

The only new piece is the data fetcher: Alpaca's stock endpoint
(`/v2/stocks/{sym}/bars`) and crypto endpoint
(`/v1beta3/crypto/us/bars`) have different paths and different bar
shapes only at the top level. Inside, the bars are identical (o/h/l/c/v/t).

---

## How to run

### Crypto momentum (predator-style breakout)

```bash
export ALPACA_API_KEY=...
export ALPACA_SECRET_KEY=...

python3 -m backtest.run \
    --strategy crypto-momentum \
    --tickers BTC/USD ETH/USD \
    --hours 4320 \
    --mode both
```

Default `--hours 4320` = 180 days × 24 = exactly the 6-month window
Senior PM has flagged repeatedly.

### Crypto oversold-bounce (mean-reversion)

```bash
python3 -m backtest.run \
    --strategy crypto-oversold-bounce \
    --tickers BTC/USD ETH/USD \
    --hours 4320 \
    --mode both \
    --explain-zero-fires
```

`--explain-zero-fires` is the killer feature for this strategy. If the
backtest produces 0 trades over 180 days, it samples 25 bars across the
window and prints WHY each one rejected:

```
zero-fire diagnostic (25 sampled bars):
  idx=25 t=2026-01-02T05:00:00Z → rsi=42.1 > 30.0 (not oversold)
  idx=26 t=2026-01-02T06:00:00Z → rsi=45.2 > 30.0 (not oversold)
  ...
  idx=2160 t=2026-04-15T08:00:00Z → 24h=-12.3% < -10.0% (catastrophe)
  idx=2161 t=2026-04-15T09:00:00Z → not stabilizing (avg3=98.1 < closes[-4]=99.2)
  ...
```

This closes the question: "is the filter wrong, or is the market never
in the setup?" For the first time, operator can pin a specific rejection
reason to a specific bar.

### Multi-ticker walk-forward

```bash
python3 -m backtest.run \
    --strategy crypto-momentum \
    --tickers BTC/USD ETH/USD SOL/USD AVAX/USD \
    --hours 4320 \
    --mode both \
    --walk-forward 4
```

`--walk-forward 4` splits the 4320-bar window into 4 non-overlapping
folds (45 days each) and reports per-fold stats. Catches strategies
that work on backtest aggregate but fail on rolling windows.

### Output

Per-ticker print + aggregate summary + JSON ledger in
`backtest/results/crypto-momentum-<UTC-timestamp>.json`. Same shape as
existing stock backtests. The ledger contains both `all_trades_idealized`
and `all_trades_realistic` for direct comparison.

---

## Operator decision matrix

After running the backtest with `--mode both`:

| Realistic metrics                          | Action                                              |
|--------------------------------------------|-----------------------------------------------------|
| WR ≥ 50% AND PF ≥ 1.3 AND n ≥ 10           | Flip `EDGE_GATE_ENABLED=true` for this strategy     |
| 30% ≤ WR < 50% OR 1.0 ≤ PF < 1.3           | Keep monitoring; do NOT flip the gate               |
| WR < 30% OR PF < 1.0                       | Disable strategy in `state.json`; revisit filter    |
| n < 10 (insufficient sample)               | Extend window (`--hours 8760` = 365 days) and rerun |

Critical: use **realistic** metrics, not idealized. The idealized number
ignores slippage (25 bps for crypto) and gap risk on SL fills. For
crypto specifically, the slippage delta can be 5-10% of total P&L on a
high-turnover strategy. The harness reports both side-by-side so you
can see how much edge survives the realism penalty:

```
AGGREGATE — strategy=crypto-momentum, 2 tickers, ...
  IDEALIZED:
    n_trades:    12
    win_rate:    7/12 (58%)
    total P&L:   $4,318.20
    profit_factor: 2.13
  REALISTIC:
    n_trades:    11    ← realistic dropped 1 trade (missed-run sim)
    win_rate:    6/11 (54%)
    total P&L:   $3,621.80
    profit_factor: 1.78    ← still > 1.3 → EDGE_GATE candidate

  realism delta: -$696.40 (-16.1% of idealized)
  → use REALISTIC for go/no-go; IDEALIZED for upside ceiling
```

---

## Tests

`tests/test_crypto_backtest_v3160.py` — 19 deterministic, no-network
tests covering:

1. **No-lookahead** (both signals × 5 indices each)
2. **crypto-momentum fires** on a engineered breakout pattern
3. **crypto-momentum no-fires** when RSI > 68 (out of band)
4. **crypto-oversold-bounce fires** on engineered deep-oversold pattern
5. **crypto-oversold-bounce no-fire** when 24h-move < -10% (catastrophe)
6. **crypto-oversold-bounce no-fire** when volume below floor
7. **BTC dominance guard** blocks Tier 2 alt-long for both signals
8. **`_explain_no_signal_crypto`** returns human-readable reasons
9. **`_explain_zero_fires`** prints diagnostic lines
10. **`replay()` smoke** on 4320-bar synthetic random walk
11. **Registry** post-v3.16 flips both crypto entries to HAS_SIGNAL
12. **Parity** with live monitor: TP/SL contract preserved
13. **Realism monotonicity** — realistic P&L ≤ idealized
14. **Fetcher fail-soft** on missing creds + HTTP errors

Run with:
```bash
python3 -m unittest tests.test_crypto_backtest_v3160 -v
```

---

## What this DOES NOT do

- No BTC dominance feed in backtest (live monitor reads BTC 1h change
  per scan; backtest does not have a per-tick BTC feed). The guard is
  exposed as `btc_dominance_change=None` default — inactive in backtest.
  Operator can supply it via `--btc-dominance-snapshot` in a future
  iteration if needed.
- No options chain — `options-momentum` remains `INTERFACE`. That's a
  separate problem (paid data).
- No event replay — `geo-defense`, `geo-energy`, `geo-gold` remain
  `EVENT_DRIVEN`. Different harness needed.
- No live cron — the backtest is a one-shot tool. Operator decides
  when to run it.

---

## What changes after operator runs backtest

If operator decides to **enable** based on backtest evidence:

1. Edit `learning-loop/state.json::strategies.<name>.enabled = true`
   (already the default for these two).
2. Set `learning-loop/state.json::strategies.<name>.edge_gate.backtest_evidence`
   to the path of the JSON ledger that justifies it.
3. Optionally flip `EDGE_GATE_ENABLED=true` to require backtest evidence
   for ALL strategies before they can fire. (Default OFF — opt-in.)
4. Daily-learning re-evaluates after the next cron and applies any
   adjustments.

If operator decides to **disable**:

1. Edit `learning-loop/state.json::strategies.<name>.enabled = false`.
2. `crypto-monitor` skips the strategy on next scan.
3. Add the ledger path under `disabled_reason` for future re-evaluation.

---

## Audit-board ticket closure

| Ticket    | Status before v3.16 | Status after v3.16  |
|-----------|---------------------|---------------------|
| STRAT-002 | NEEDS_FIXES (P1) — 0 trades in 45 days, no backtest evidence | RESOLVED — backtest tool ships; 14-day observation window now has empirical data path |
| STRAT-003 | NEEDS_FIXES (P1) — EDGE_GATE flip blocked by missing backtest | UNBLOCKED — operator can now run backtest before flip |
| READINESS — crypto backtest | UNCOVERED | COVERED |

STRAT-003 is **unblocked** but not auto-closed: operator decides whether
to flip `EDGE_GATE_ENABLED=true` based on backtest evidence. The tool
is the precondition, not the decision.

---

## Free-tier compliance

- Uses only existing `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` paper-trading
  credentials. Same auth as live `crypto-monitor`.
- Alpaca v1beta3 crypto endpoint is part of the free paper plan.
- No new SaaS dependencies, no paid data, no LLM calls.
- Cache is local JSON in `backtest/cache/crypto/` — no remote storage.
- Tests run no-network (HTTP mocked for fail-soft checks).
