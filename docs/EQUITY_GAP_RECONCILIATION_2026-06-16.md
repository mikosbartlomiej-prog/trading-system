# Equity gap reconciliation — 2026-06-16

_Generated at 2026-06-16T09:03:00.261283+00:00 by `scripts/reconcile_equity_gap.py`._

## Inputs

- current_equity: 90504.89
- peak_equity:    90511.53
- gap_pct:        -0.007336081933428169

## Component decomposition

| Component | USD |
|-----------|-----|
| cash | 0.00 |
| equity_unrealized | 40737.79 |
| realized_pl_today | 0.00 |
| held_for_orders | 0.00 |
| crypto_positions | 11763.21 |
| fees_slippage | 0.00 |
| unexplained | 38003.90 |
| **total** | 90504.89 |

## Verdict: **EQUITY_GAP_OK**

## Standing markers (do not remove)

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT`
