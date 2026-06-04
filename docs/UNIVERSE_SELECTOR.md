# Universe Selector — v3.18.0 (2026-06-04)

**Status:** Activated. `US_LARGE` is the default active universe.

## What the selector does

`shared/universe_selector.py` is the formal abstraction for "which market are
we trading?" It owns three responsibilities:

1. **Define** universes via `config/market_universes.json` (US_LARGE,
   US_MICROCAP, PL_GPW, CRYPTO, CUSTOM). Each carries data-source +
   liquidity + spread + slippage + risk-limit multipliers.
2. **Gate** order placement via `is_paper_ready(universe_id)`. The
   allocator (`shared/allocator.py::_execute_one`) reads the active
   universe via `runtime_config.active_universe()` and refuses to submit
   any BUY when the universe is not paper-ready.
3. **Filter** symbol candidates via `filter_symbols_for_paper_trading()`
   on the basis of liquidity, spread, forbidden patterns (OTC/SPAC/etc.),
   and data availability.

## Active universe

| Universe       | Status   | Notes                                                         |
|----------------|----------|---------------------------------------------------------------|
| `US_LARGE`     | ENABLED  | Default. Alpaca paper + IEX free feed.                        |
| `CRYPTO`       | ENABLED  | Alpaca paper 24/7 long-only. Routed when symbol contains `/`. |
| `US_MICROCAP`  | DISABLED | Illiquidity + manipulation risk. See `docs/STRATEGY.md`.      |
| `PL_GPW`       | DISABLED | No free Polish paper broker integration.                      |
| `CUSTOM`       | DISABLED | Placeholder for future operator-defined universes.            |

The operator can flip the active universe via the `ACTIVE_UNIVERSE`
environment variable (default `US_LARGE`). Valid values:
`US_LARGE | CRYPTO`. Any other value falls back to `US_LARGE` to avoid
accidentally routing to a disabled universe on typo.

```bash
# Run a crypto-only session
ACTIVE_UNIVERSE=CRYPTO python3 -m shared.allocator ...
```

## Pre-trade gate

In `shared/allocator.py::_execute_one`, before submitting any BUY:

```python
univ = "CRYPTO" if is_crypto else active_universe()
ready, reason = is_paper_ready(univ)
if not ready:
    # emit audit event + skip with reason 'universe_not_paper_ready'
```

REDUCE / EXIT actions intentionally bypass the gate so an operator that
flips the universe can still close stale positions opened under the
previous universe. This is fail-soft: any exception in the gate (import
error, malformed config) → proceed (we never block on infrastructure
failure here; the existing risk_officer + portfolio_risk gates remain).

## Symbol filter

`filter_symbols_for_paper_trading(symbols, ...)` returns
`(allowed_symbols, rejection_reasons)`. Rejection conditions:

1. **Forbidden pattern** — OTC (`.OB`, `_OB`, `.PK`), SPAC warrants
   (`_W`, `-W`), rights (`_R`, `-R`), units (`_U`, `-U`), or symbols
   containing `$ * ? !`. Empty or leading-underscore symbols also reject.
2. **Spread above 2x universe typical** — only checked if `spread_data`
   is supplied. Missing data → ALLOW (non-strict) or REJECT (strict).
3. **Volume below universe min_liquidity_usd_daily** — only checked if
   `volume_data` is supplied. Same strict/non-strict policy.
4. **No daily bars in last 5 days** — only checked if `history_data` is
   supplied. Indicates data unavailable / delisted.

Conservative defaults: missing data → ALLOW with warning (non-strict).
This prevents over-blocking when an upstream data fetch failed. The
caller can pass `strict=True` to flip the default to REJECT for
high-confidence routing (e.g. when adding new tickers to a universe).

## Audit trail

Every rejection emits a JSONL line to
`journal/autonomy/YYYY-MM-DD.jsonl` with shape:

```json
{
  "type":        "universe_filter",   // or "universe_gate" from allocator
  "decision":    "REJECT",
  "symbol":      "ABCDE.OB",
  "reason":      "forbidden_pattern:forbidden_suffix:.OB",
  "universe_id": "US_LARGE",
  "strict_mode": false,
  "decided_at":  "2026-06-04T13:42:01Z"
}
```

Audit emit is itself fail-soft — if the audit layer is unreachable, the
filter still returns its result without raising.

## Re-decision triggers

Operator should re-evaluate the active universe configuration when:

- **A new free data source appears** (e.g. Polygon free tier covering PL).
  Add a Tier-0 source ahead of Yahoo in `pre_market_data.py` AND consider
  flipping `enabled=true` on the corresponding universe.
- **Backtest validates a new universe** (e.g. backtest harness shows
  positive edge in microcaps with `LiquiditySweepGuard` active). Wire a
  separate workflow + smaller position size; do NOT just flip
  `US_MICROCAP.enabled=true` without re-running the risk-validation
  pipeline.
- **A broker integration becomes feasible** for PL/GPW. Update
  `broker_supported=true` and integrate the broker SDK (this is a
  non-trivial migration; strategies do NOT transfer across universes).

## Limitations

- IEX (the Alpaca free feed) does not cover Polish or microcap stocks
  with the depth needed for our momentum + intraday models.
- The universe abstraction does NOT replace per-instrument trading
  windows (`shared/instrument_windows.py`); the two layers run in
  series. Universe gates "what can we touch in this session"; instrument
  windows gate "is THIS ticker tradable right now".

## Related files

- `config/market_universes.json` — universe configuration.
- `shared/universe_selector.py` — UniverseSpec + is_paper_ready + filter.
- `shared/runtime_config.py::active_universe` — read the active universe.
- `shared/allocator.py::_execute_one` — pre-trade gate insertion point.
- `tests/test_universe_filter_v3180.py` — unit tests.

---

## v2 Ranking (v3.19.0 — 2026-06-04)

The filter (v3.18.0) answers "which symbols pass the floor?". The v2
ranking layer answers "which of them deserve attention FIRST?"

### Hard constraints

- `rank_symbols(...)` is a PURE function — no broker calls, no network,
  no paid services.
- Result is deterministic: same inputs → same ranking.
- Ranking NEVER auto-trades. NEVER raises risk limits, position sizes,
  or leverage. The risk engine retains final say on every order.
- One JSONL audit line is appended per ranking decision
  (`kind='trading'`, `type='universe_ranking'`,
  `source='evidence_analysis'`).

### Status enum

| Status            | Meaning                                                          |
|-------------------|------------------------------------------------------------------|
| `TRADE_ELIGIBLE`  | Passes all gates AND has ≥5 closed paper trades.                 |
| `OBSERVE_ONLY`    | Passes gates but evidence too thin (n_closed < 5).               |
| `NEEDS_DATA`      | Missing volume_data AND history AND paper performance entries.   |
| `REJECTED`        | Fails forbidden-pattern OR spread/liquidity hard gate.           |

### Score components

Each component is clamped to `[0.0, 1.0]`. Missing input → neutral 0.5
so that absent data never silently rejects a symbol.

| Component                  | Weight |
|----------------------------|-------:|
| `liquidity_score`          | 0.16   |
| `paper_performance_score`  | 0.14   |
| `spread_score`             | 0.12   |
| `volatility_score`         | 0.10   |
| `data_quality_score`       | 0.10   |
| `regime_fit_score`         | 0.10   |
| `strategy_compat_score`    | 0.08   |
| `calibration_score`        | 0.08   |
| `drawdown_history_score`   | 0.08   |
| `recent_anomalies_score`   | 0.04   |

Composite score is the weighted average (renormalised over present
components — missing ones never zero out the score).

### CLI

```bash
# Render top-of-universe ranking using local inputs
python3 scripts/universe_ranking_report.py \
    --symbols AAPL MSFT SPY \
    --inputs-json data/ranking_inputs.json

# Stdout dry-run
python3 scripts/universe_ranking_report.py --dry-run
```

Outputs `docs/universe_ranking_LATEST.md` and
`docs/universe_ranking_LATEST.json`.

### Audit trail

One JSONL line summarising the ranking decision is appended to
`journal/autonomy/YYYY-MM-DD.jsonl`:

```json
{
  "type":        "universe_ranking",
  "source":      "evidence_analysis",
  "decision":    "ANALYSED",
  "universe_id": "US_LARGE",
  "n_ranked":    25,
  "n_eligible":  4,
  "n_observe":   18,
  "n_rejected":  2,
  "n_needs_data": 1,
  "top_5":       [{"symbol": "...", "score": 0.74, "status": "..."}],
  "decided_at":  "2026-06-04T13:42:01Z"
}
```

### Ranking-related files

- `shared/universe_selector.py::rank_symbols` — pure ranking core.
- `shared/universe_selector.py::write_universe_report` — md/json writer.
- `scripts/universe_ranking_report.py` — CLI.
- `tests/test_universe_selector_v2_v3190.py` — unit tests.
