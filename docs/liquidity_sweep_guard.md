# Liquidity Sweep Guard (v3.15.0)

**Module:** `shared/liquidity_sweep_guard.py`
**Audit-board feedback closed:** FB-012
**Status:** shipped, tests green

## What it is

Conservative detector for liquidity sweep / trap conditions. Stacks
warning signals; multiple signals trigger ELEVATED_RISK or BLOCK.

## Signals stacked

| Signal | Description |
|---|---|
| `long_wick_reversal` | Current bar has upper-wick > 2× body AND close gives back > 50% of range |
| `volume_spike_no_follow_through` | Today's volume > 2× 20d avg AND close gives back > 50% of range |
| `fast_reversal_post_breakout` | New 20-bar high made today, but close BELOW yesterday's close |
| `historical_trap_prone` | Profile's `long_wick_ratio > 25%` |
| `low_liquidity_warning` | `quote_spread_bps > 50` |

## Verdicts

| Signal count | Verdict | Effect |
|---|---|---|
| 0-1 | ALLOW | Proceed normally |
| 2 | ELEVATED_RISK | confidence_penalty 0.15 |
| 3+ | BLOCK | confidence_penalty 0.30 + `block_recommended=True` |

`block_recommended=True` flows through `confidence_inputs._v3150_meta` →
risk_officer adds `v3.15.0_block` to `checks_failed` → REJECT.

## What it does NOT do

- Generate trades
- Raise aggressiveness
- Override risk engine BLOCK
- Increase position size

It is a one-way DOWN-arrow on confidence and a refuser for top-of-book bad
entries.

## Where it's wired

`confidence_builder.build_confidence_inputs(..., liquidity_sweep_result=...)`
→ `_v3150_meta.liquidity_sweep_verdict` → `risk_officer.evaluate_trade` blocks
on `block_recommended`.

## Tunables (conservative defaults)

```python
LONG_WICK_BODY_MULT      = 2.0
WICK_REVERSAL_GIVEBACK   = 0.50
VOL_SPIKE_MULT           = 2.0
VOL_SPIKE_GIVEBACK       = 0.50
FAST_REVERSAL_LOOKBACK   = 20
HIGH_SPREAD_BPS          = 50.0    # 0.50%
HISTORICAL_TRAP_RATIO    = 0.25    # 25% bars long-wick historically
ELEVATED_THRESHOLD       = 2
BLOCK_THRESHOLD          = 3
```

## Usage

```python
from liquidity_sweep_guard import evaluate_sweep_risk, BLOCK

result = evaluate_sweep_risk(
    opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes,
    quote_spread_bps=12.0,
    profile=instrument_profile,
)
if result.verdict == BLOCK:
    # caller refuses entry
    pass
```

## Tests

`tests/test_feedback_v3150.py::TestLiquiditySweepGuard` — 6 tests:
- no data → ALLOW
- long wick reversal detected
- BLOCK when multiple signals present
- clean breakout not blocked
- audit reason present
- confidence penalty scaling

## Future enhancements (v3.16+)

- Intraday 5-min bar version (currently daily-only)
- Tape-reading proxy (bid/ask imbalance)
- Per-strategy threshold tuning
