# Heartbeat Freshness Status

- Generated at: `2026-08-26T05:05:52.639990+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 292 | 2026-08-26T05:01:00.947971+00:00 |
| `defense-monitor` | FRESH | 290 | 2026-08-26T05:01:03.128243+00:00 |
| `twitter-monitor` | FRESH | 273 | 2026-08-26T05:01:19.547063+00:00 |
| `reddit-monitor` | FRESH | 24111 | 2026-08-25T22:24:02.098102+00:00 |
| `geo-monitor` | FRESH | 503 | 2026-08-26T04:57:30.006841+00:00 |
| `politician-monitor` | FRESH | 1455 | 2026-08-26T04:41:38.059557+00:00 |
| `options-monitor` | FRESH | 29076 | 2026-08-25T21:01:17.094836+00:00 |
| `options-exit-monitor` | FRESH | 304 | 2026-08-26T05:00:48.538121+00:00 |
| `price-monitor` | FRESH | 28420 | 2026-08-25T21:12:12.525262+00:00 |
| `exit-monitor` | FRESH | 94 | 2026-08-26T05:04:18.258057+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

