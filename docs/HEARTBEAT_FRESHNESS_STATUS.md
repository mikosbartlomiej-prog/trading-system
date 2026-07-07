# Heartbeat Freshness Status

- Generated at: `2026-07-07T07:58:21.891056+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 126 | 2026-07-07T07:56:16.073310+00:00 |
| `defense-monitor` | FRESH | 125 | 2026-07-07T07:56:16.726958+00:00 |
| `twitter-monitor` | FRESH | 115 | 2026-07-07T07:56:27.239291+00:00 |
| `reddit-monitor` | FRESH | 32005 | 2026-07-06T23:04:57.033357+00:00 |
| `geo-monitor` | FRESH | 1625 | 2026-07-07T07:31:16.900178+00:00 |
| `politician-monitor` | FRESH | 1028 | 2026-07-07T07:41:14.114040+00:00 |
| `options-monitor` | FRESH | 41903 | 2026-07-06T20:19:59.314854+00:00 |
| `options-exit-monitor` | FRESH | 130 | 2026-07-07T07:56:11.717870+00:00 |
| `price-monitor` | FRESH | 36381 | 2026-07-06T21:52:01.114877+00:00 |
| `exit-monitor` | FRESH | 131 | 2026-07-07T07:56:11.006790+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

