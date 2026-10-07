# Heartbeat Freshness Status

- Generated at: `2026-10-07T11:16:48.810415+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=1, STALE=0, MISSING=10, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | MISSING | n/a | — |
| `defense-monitor` | MISSING | n/a | — |
| `twitter-monitor` | MISSING | n/a | — |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | MISSING | n/a | — |
| `politician-monitor` | MISSING | n/a | — |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | MISSING | n/a | — |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 336 | 2026-10-07T11:11:12.889316+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

