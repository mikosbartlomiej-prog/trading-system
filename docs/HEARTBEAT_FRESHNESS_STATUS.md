# Heartbeat Freshness Status

- Generated at: `2026-09-23T09:26:55.537372+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 380 | 2026-09-23T09:20:35.068604+00:00 |
| `defense-monitor` | FRESH | 380 | 2026-09-23T09:20:35.283412+00:00 |
| `twitter-monitor` | FRESH | 365 | 2026-09-23T09:20:50.049662+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 677 | 2026-09-23T09:15:38.261624+00:00 |
| `politician-monitor` | FRESH | 7004 | 2026-09-23T07:30:11.417860+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 81 | 2026-09-23T09:25:34.318139+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 81 | 2026-09-23T09:25:34.656659+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

