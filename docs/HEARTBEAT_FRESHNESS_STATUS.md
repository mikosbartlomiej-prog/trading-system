# Heartbeat Freshness Status

- Generated at: `2026-07-27T08:01:39.277106+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 341 | 2026-07-27T07:55:58.772300+00:00 |
| `defense-monitor` | FRESH | 341 | 2026-07-27T07:55:58.126744+00:00 |
| `twitter-monitor` | FRESH | 319 | 2026-07-27T07:56:20.574806+00:00 |
| `reddit-monitor` | FRESH | 32647 | 2026-07-26T22:57:32.596355+00:00 |
| `geo-monitor` | FRESH | 1242 | 2026-07-27T07:40:56.898690+00:00 |
| `politician-monitor` | FRESH | 1616 | 2026-07-27T07:34:43.692579+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 345 | 2026-07-27T07:55:54.377246+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 347 | 2026-07-27T07:55:52.276172+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

