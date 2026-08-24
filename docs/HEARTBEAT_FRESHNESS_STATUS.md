# Heartbeat Freshness Status

- Generated at: `2026-08-24T05:12:11.773006+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 80 | 2026-08-24T05:10:51.621192+00:00 |
| `defense-monitor` | FRESH | 75 | 2026-08-24T05:10:56.686353+00:00 |
| `twitter-monitor` | FRESH | 91 | 2026-08-24T05:10:41.203698+00:00 |
| `reddit-monitor` | FRESH | 24794 | 2026-08-23T22:18:57.453865+00:00 |
| `geo-monitor` | FRESH | 494 | 2026-08-24T05:03:57.700986+00:00 |
| `politician-monitor` | FRESH | 1502 | 2026-08-24T04:47:09.512375+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 382 | 2026-08-24T05:05:49.996643+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 80 | 2026-08-24T05:10:51.452294+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

