# Market Universe Selection (v3.15.0)

**Module:** `shared/universe_selector.py` + `config/market_universes.json`
**Audit-board feedback closed:** FB-010
**Status:** abstraction shipped; only US_LARGE + CRYPTO are paper-ready

## Universes defined

| Universe | Paper-ready? | Why |
|---|---|---|
| `US_LARGE` | ✅ | Default. Alpaca free IEX feed. |
| `CRYPTO` | ✅ | 24/7 Alpaca crypto. LONG-only on paper. |
| `US_MICROCAP` | ❌ (disabled) | Free data exists but high illiquidity + manipulation risk; system has insufficient defense |
| `PL_GPW` | ❌ (disabled) | No free Polish broker integration; GPW data is free but no execution path |
| `CUSTOM` | ❌ (placeholder) | Operator-defined |

## Why not just switch to PL or microcaps?

Trader feedback suggested US markets are competitive and microcap/PL could
offer edge. But:

1. **Alpaca paper is US-only.** PL would require a Polish broker SDK
   (not free, not integrated).
2. **Microcaps need different risk profile.** Illiquidity + manipulation
   risk + wider spread tolerance + smaller position size + better
   liquidity sweep defense. The current `liquidity_sweep_guard` (v3.15.0)
   is a first step but not sufficient for microcap-only operation.
3. **Strategies do NOT transfer across universes.** Mega-cap momentum
   backtests are not predictive of microcap behavior. Each universe needs
   independent backtest validation.
4. **Microcaps are NOT safer.** Sometimes phrased that way; it's wrong.
   Higher gap risk, higher manipulation risk, often lower trader skill
   competition AT THE COST OF higher individual-trade variance.

## What this module ships

- `UniverseSpec` dataclass — frozen config per universe
- Defaults + JSON config loading
- `is_paper_ready(universe_id)` — checks data + broker availability
- `can_switch(from, to)` — never auto-switches; explicit operator decision

## Comparison table

| Universe | Spread (bps) | Slippage (bps) | Min daily liquidity (USD) | Risk size mult |
|---|---|---|---|---|
| US_LARGE | 2 | 5 | $10M | 1.0 |
| CRYPTO | 10 | 15 | $50M | 0.5 |
| US_MICROCAP | 50 | 80 | $100k | 0.25 |
| PL_GPW | 20 | 30 | $500k | 0.5 |

## Hard policy

- System never auto-migrates universes.
- Strategies must be re-validated per universe before enabling.
- Operator decision required to enable a non-default universe.
- Enabling US_MICROCAP requires backtest evidence + LiquiditySweepGuard ON.
- Enabling PL_GPW requires a wired broker SDK + free PL data feed.

## Config

`config/market_universes.json` — operator-editable. Defaults match the
shipped Python defaults so missing config is safe.

## Tests

`tests/test_feedback_v3150.py::TestUniverseSelector` — 5 tests covering
default readiness, microcap disabled, PL not ready, unknown rejection,
switch policy.

## Cost

$0/month. JSON file in repo.
