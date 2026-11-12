# Heartbeat Freshness Status

- Generated at: `2026-11-12T13:06:31.324509+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 317 | 2026-11-12T13:01:14.114365+00:00 |
| `defense-monitor` | FRESH | 615 | 2026-11-12T12:56:15.993195+00:00 |
| `twitter-monitor` | FRESH | 291 | 2026-11-12T13:01:40.482470+00:00 |
| `reddit-monitor` | FRESH | 39369 | 2026-11-12T02:10:21.920418+00:00 |
| `geo-monitor` | FRESH | 312 | 2026-11-12T13:01:19.466213+00:00 |
| `politician-monitor` | FRESH | 2860 | 2026-11-12T12:18:50.872165+00:00 |
| `options-monitor` | FRESH | 307 | 2026-11-12T13:01:24.028733+00:00 |
| `options-exit-monitor` | FRESH | 322 | 2026-11-12T13:01:09.278697+00:00 |
| `price-monitor` | FRESH | 40434 | 2026-11-12T01:52:37.637434+00:00 |
| `exit-monitor` | FRESH | 620 | 2026-11-12T12:56:11.304569+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

