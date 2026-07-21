# Heartbeat Freshness Status

- Generated at: `2026-07-21T07:07:33.155376+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 87 | 2026-07-21T07:06:05.733453+00:00 |
| `defense-monitor` | FRESH | 98 | 2026-07-21T07:05:55.558436+00:00 |
| `twitter-monitor` | FRESH | 76 | 2026-07-21T07:06:17.100262+00:00 |
| `reddit-monitor` | FRESH | 29338 | 2026-07-20T22:58:35.153410+00:00 |
| `geo-monitor` | FRESH | 1283 | 2026-07-21T06:46:10.308484+00:00 |
| `politician-monitor` | FRESH | 2262 | 2026-07-21T06:29:51.560939+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 384 | 2026-07-21T07:01:09.515428+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 88 | 2026-07-21T07:06:05.622249+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

