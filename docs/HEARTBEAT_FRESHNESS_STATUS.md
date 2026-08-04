# Heartbeat Freshness Status

- Generated at: `2026-08-04T07:13:11.999274+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 76 | 2026-08-04T07:11:55.586881+00:00 |
| `defense-monitor` | FRESH | 128 | 2026-08-04T07:11:04.482748+00:00 |
| `twitter-monitor` | FRESH | 106 | 2026-08-04T07:11:25.693451+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 718 | 2026-08-04T07:01:14.057574+00:00 |
| `politician-monitor` | FRESH | 2624 | 2026-08-04T06:29:28.058269+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 134 | 2026-08-04T07:10:57.649738+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 134 | 2026-08-04T07:10:57.822843+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

