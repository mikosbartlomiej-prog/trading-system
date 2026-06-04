# US Microcap universe — filing decision (2026-06-04)

**Decision:** **Do nothing in v3.16.** Backtest-only experiment available
on-demand via existing `backtest.yml`.
**Status:** Filed; abstraction shipped v3.15.0 as documentation-only scaffolding.
**Re-decision trigger:** see bottom of doc.

## Context

Trader feedback (2026-06-03) suggested microcap markets as potential edge
("rynek USA jest zbyt konkurencyjny ... rozważyć microcapy"). v3.15.0 shipped
`shared/universe_selector.py` + `config/market_universes.json::US_MICROCAP`
declared but disabled with risk_limit_multipliers (size 0.25, sl 1.5, tp 1.5).

## Why disabled and staying disabled (in v3.16)

### Unverified hypothesis

"Microcaps might offer edge" is **not actionable evidence**. The
trader-feedback claim was a hypothesis, not a measurement. Before
enabling a new universe class with material risk, we need backtest
evidence at minimum.

### IWM already provides small-cap exposure

`config/watchlists.json::ai_nasdaq_semis` includes major indices.
`config/watchlists.json` and tickers-whitelist.md document that **IWM
(Russell 2000 ETF)** is whitelisted under broader-market ETFs. IWM gives
small-cap exposure within US mega-cap risk controls (tight spread,
deep liquidity, no manipulation surface) — covers the "small-cap
exposure" use case without microcap single-name risk.

### Existing modules adapt but need extension

The v3.15.0 modules cover SOME microcap edge cases but not all:

| Module | Coverage |
|---|---|
| `shared/instrument_profile.py` | Works on IEX-data microcaps (free Alpaca tier) |
| `shared/liquidity_sweep_guard.py` | Thresholds (HIGH_SPREAD_BPS=50, HISTORICAL_TRAP_RATIO=0.25) tuned for mega-cap. **Microcap operating ranges are wider** — would need recalibration |
| `shared/universe_selector.py::US_MICROCAP` | Risk multipliers (size 0.25, sl 1.5, tp 1.5) shipped but not wired into allocator |
| `shared/position_manager.py` | MAX_ADVERSE_EXCURSION_PCT=0.08 calibrated for mega-cap. Microcap intraday volatility frequently exceeds 8% — would need wider safety net or smaller initial size |

Enabling US_MICROCAP without recalibrating these would underprotect
microcap positions. Recalibration requires backtest evidence first.

### Alpaca paper limitations

- Alpaca paper supports US-listed microcaps on IEX **but** liquidity in
  paper fills is **synthetic** — actual fills in live trading would face
  much wider spreads. Paper backtest results overestimate live edge.
- Alpaca paper does **not** execute OTC / pink-sheet / SSR-halted names —
  many "interesting" microcaps trade there.
- Alpaca paper does not provide Level 2 data → no bid/ask imbalance
  detection for the very microstructure microcaps require.

### Risk of premature commitment

Building US_MICROCAP enablement infrastructure (size multiplier wiring,
threshold recalibration, per-universe strategy validation) is multi-day
work. Doing it BEFORE empirical evidence of edge is **wasted effort if
the hypothesis fails the backtest**.

## What operator can do RIGHT NOW with zero code change

Run an informal microcap backtest experiment using existing tools:

```bash
# Via GitHub Actions UI: backtest.yml workflow_dispatch
strategy: momentum-long
tickers: GME AMC NVAX RIOT MARA  # or any IEX-tradeable microcap basket
days: 180
mode: both
```

This produces immediate evidence:
- Win rate
- Profit factor
- Max drawdown
- Trade count

If results show edge, **then** formalize enablement (v3.17 scope).
If results show no edge, the hypothesis is empirically rejected and the
question is closed.

**Estimated effort:** 5 min trigger + ~10 min interpretation in next session.

## What v3.15.0 abstraction did ship

`shared/universe_selector.py` + `config/market_universes.json::US_MICROCAP`
exist as documentation-only scaffolding. They:

- Make the disabled-state explicit + audit-able
- Document the higher spread/slippage assumptions (50/80 bps)
- Document the smaller-size risk multiplier (0.25)
- Provide a starting point IF backtest evidence justifies enabling

## Re-decision triggers

Reopen this decision if **all of** these become true:

1. Operator runs informal microcap backtest via `backtest.yml` and
   observes ≥40% WR AND ≥1.3 PF over 6-month window in IEX-tradeable
   basket
2. US_LARGE backlog has zero P0/P1 items (system stability priority)
3. Operator defines a **specific** microcap-momentum hypothesis (e.g.
   "Russell 2000 breakouts during VIX < 20 RISK_ON regime")

If all three become true → v3.17 scope: recalibrate
`liquidity_sweep_guard` thresholds for microcap volume profile, wire
`US_MICROCAP` risk multipliers into allocator, add per-symbol earnings
blackout (microcap binary risk dominant), backtest the specific
hypothesis.

## Operator action required

None. Filing is the action. Optional: run the 5-min informal backtest
experiment to begin evidence gathering.

## Audit reference

Walkthrough rationale: `docs/operator_decision_walkthrough_2026-06-04.md`
section "3. Per-item walkthrough" → "PL_GPW + US Microcap universe
enablement" and section "5. Hard NO list" → "5.2 OTC / pink-sheet
microcap".
