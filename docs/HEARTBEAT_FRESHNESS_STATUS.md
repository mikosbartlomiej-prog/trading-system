# Heartbeat Freshness Status

- Generated at: `2026-07-20T07:41:04.790269+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 1073 | 2026-07-20T07:23:12.223084+00:00 |
| `defense-monitor` | FRESH | 10361 | 2026-07-20T04:48:23.583610+00:00 |
| `twitter-monitor` | FRESH | 10688 | 2026-07-20T04:42:56.637479+00:00 |
| `reddit-monitor` | FRESH | 31869 | 2026-07-19T22:49:55.449185+00:00 |
| `geo-monitor` | FRESH | 11848 | 2026-07-20T04:23:36.596728+00:00 |
| `politician-monitor` | FRESH | 3123 | 2026-07-20T06:49:01.371713+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 83129 | 2026-07-19T08:35:35.587842+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 6285 | 2026-07-20T05:56:19.840292+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

