# Heartbeat Freshness Status

- Generated at: `2026-07-06T08:46:43.227542+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 63 | 2026-07-06T08:45:40.250184+00:00 |
| `defense-monitor` | FRESH | 59 | 2026-07-06T08:45:44.086706+00:00 |
| `twitter-monitor` | FRESH | 55 | 2026-07-06T08:45:47.815009+00:00 |
| `reddit-monitor` | FRESH | 35209 | 2026-07-05T22:59:54.372943+00:00 |
| `geo-monitor` | FRESH | 66 | 2026-07-06T08:45:37.470157+00:00 |
| `politician-monitor` | FRESH | 1440 | 2026-07-06T08:22:42.868702+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 366 | 2026-07-06T08:40:36.891726+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 662 | 2026-07-06T08:35:40.848225+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

