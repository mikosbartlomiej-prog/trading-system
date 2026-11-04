# Heartbeat Freshness Status

- Generated at: `2026-11-04T12:25:01.252543+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 205 | 2026-11-04T12:21:35.891593+00:00 |
| `defense-monitor` | FRESH | 196 | 2026-11-04T12:21:45.073683+00:00 |
| `twitter-monitor` | FRESH | 172 | 2026-11-04T12:22:09.257435+00:00 |
| `reddit-monitor` | FRESH | 37885 | 2026-11-04T01:53:36.504739+00:00 |
| `geo-monitor` | FRESH | 505 | 2026-11-04T12:16:36.402614+00:00 |
| `politician-monitor` | FRESH | 1363 | 2026-11-04T12:02:18.416532+00:00 |
| `options-monitor` | FRESH | 43063 | 2026-11-04T00:27:18.267679+00:00 |
| `options-exit-monitor` | FRESH | 207 | 2026-11-04T12:21:34.670261+00:00 |
| `price-monitor` | FRESH | 42766 | 2026-11-04T00:32:14.858264+00:00 |
| `exit-monitor` | FRESH | 199 | 2026-11-04T12:21:42.241147+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

