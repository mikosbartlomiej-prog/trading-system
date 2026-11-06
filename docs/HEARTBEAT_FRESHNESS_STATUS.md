# Heartbeat Freshness Status

- Generated at: `2026-11-06T12:21:52.020414+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 329 | 2026-11-06T12:16:22.759515+00:00 |
| `defense-monitor` | FRESH | 342 | 2026-11-06T12:16:09.651799+00:00 |
| `twitter-monitor` | FRESH | 318 | 2026-11-06T12:16:33.605448+00:00 |
| `reddit-monitor` | FRESH | 37348 | 2026-11-06T01:59:24.518279+00:00 |
| `geo-monitor` | FRESH | 10229 | 2026-11-06T09:31:23.098686+00:00 |
| `politician-monitor` | FRESH | 1629 | 2026-11-06T11:54:42.871997+00:00 |
| `options-monitor` | FRESH | 40687 | 2026-11-06T01:03:44.601672+00:00 |
| `options-exit-monitor` | FRESH | 338 | 2026-11-06T12:16:13.958600+00:00 |
| `price-monitor` | FRESH | 40663 | 2026-11-06T01:04:08.642169+00:00 |
| `exit-monitor` | FRESH | 343 | 2026-11-06T12:16:09.213668+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

