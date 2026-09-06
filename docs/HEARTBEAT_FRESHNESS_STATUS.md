# Heartbeat Freshness Status

- Generated at: `2026-09-06T08:47:29.123857+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 359 | 2026-09-06T08:41:30.009458+00:00 |
| `defense-monitor` | FRESH | 358 | 2026-09-06T08:41:31.518569+00:00 |
| `twitter-monitor` | FRESH | 289 | 2026-09-06T08:42:40.115579+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 963 | 2026-09-06T08:31:26.339064+00:00 |
| `politician-monitor` | FRESH | 1215 | 2026-09-06T08:27:13.727073+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 364 | 2026-09-06T08:41:25.325312+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 362 | 2026-09-06T08:41:26.886068+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

