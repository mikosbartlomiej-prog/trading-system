# Heartbeat Freshness Status

- Generated at: `2026-06-23T08:03:29.133929+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 177 | 2026-06-23T08:00:32.199288+00:00 |
| `defense-monitor` | FRESH | 176 | 2026-06-23T08:00:33.263710+00:00 |
| `twitter-monitor` | FRESH | 164 | 2026-06-23T08:00:45.621745+00:00 |
| `reddit-monitor` | FRESH | 31511 | 2026-06-22T23:18:17.896770+00:00 |
| `geo-monitor` | FRESH | 173 | 2026-06-23T08:00:36.545276+00:00 |
| `politician-monitor` | FRESH | 709 | 2026-06-23T07:51:39.706902+00:00 |
| `options-monitor` | FRESH | 34950 | 2026-06-22T22:20:59.612525+00:00 |
| `options-exit-monitor` | FRESH | 485 | 2026-06-23T07:55:24.163613+00:00 |
| `price-monitor` | FRESH | 35027 | 2026-06-22T22:19:42.064580+00:00 |
| `exit-monitor` | FRESH | 482 | 2026-06-23T07:55:27.389646+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

