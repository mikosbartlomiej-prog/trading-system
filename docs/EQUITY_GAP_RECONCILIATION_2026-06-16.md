# Equity gap reconciliation — 2026-06-16

_Generated at 2026-06-16T08:29:50.555953+00:00 by `scripts/reconcile_equity_gap.py`._

## Inputs

- current_equity: 90523.75
- peak_equity:    90954.38
- gap_pct:        -0.4734571331254247

## Component decomposition

| Component | USD |
|-----------|-----|
| cash | 0.00 |
| equity_unrealized | 40737.79 |
| realized_pl_today | 0.00 |
| held_for_orders | 0.00 |
| crypto_positions | 11780.92 |
| fees_slippage | 0.00 |
| unexplained | 38005.04 |
| **total** | 90523.75 |

## Verdict: **EQUITY_GAP_OK**

## Standing markers (do not remove)

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT`
