# Heartbeat Freshness Status

- Generated at: `2026-09-22T09:26:14.157574+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 331 | 2026-09-22T09:20:42.992408+00:00 |
| `defense-monitor` | FRESH | 328 | 2026-09-22T09:20:46.438000+00:00 |
| `twitter-monitor` | FRESH | 317 | 2026-09-22T09:20:56.739952+00:00 |
| `reddit-monitor` | FRESH | 39248 | 2026-09-21T22:32:06.364736+00:00 |
| `geo-monitor` | FRESH | 643 | 2026-09-22T09:15:31.366489+00:00 |
| `politician-monitor` | FRESH | 7138 | 2026-09-22T07:27:15.667662+00:00 |
| `options-monitor` | FRESH | 40687 | 2026-09-21T22:08:06.873617+00:00 |
| `options-exit-monitor` | FRESH | 331 | 2026-09-22T09:20:42.712584+00:00 |
| `price-monitor` | FRESH | 40647 | 2026-09-21T22:08:47.378814+00:00 |
| `exit-monitor` | FRESH | 298 | 2026-09-22T09:21:16.456952+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

