# Heartbeat Freshness Status

- Generated at: `2026-11-03T12:12:49.933968+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 374 | 2026-11-03T12:06:36.260800+00:00 |
| `defense-monitor` | FRESH | 367 | 2026-11-03T12:06:42.648172+00:00 |
| `twitter-monitor` | FRESH | 366 | 2026-11-03T12:06:44.147296+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 665 | 2026-11-03T12:01:45.329214+00:00 |
| `politician-monitor` | FRESH | 1824 | 2026-11-03T11:42:25.656172+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 375 | 2026-11-03T12:06:35.366660+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 373 | 2026-11-03T12:06:36.565968+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

