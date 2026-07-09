# Heartbeat Freshness Status

- Generated at: `2026-07-09T08:01:27.406774+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 614 | 2026-07-09T07:51:13.687419+00:00 |
| `defense-monitor` | FRESH | 298 | 2026-07-09T07:56:29.647254+00:00 |
| `twitter-monitor` | FRESH | 300 | 2026-07-09T07:56:27.867268+00:00 |
| `reddit-monitor` | FRESH | 32172 | 2026-07-08T23:05:15.761843+00:00 |
| `geo-monitor` | FRESH | 431 | 2026-07-09T07:54:16.867359+00:00 |
| `politician-monitor` | FRESH | 1383 | 2026-07-09T07:38:24.585769+00:00 |
| `options-monitor` | FRESH | 39225 | 2026-07-08T21:07:42.047691+00:00 |
| `options-exit-monitor` | FRESH | 315 | 2026-07-09T07:56:12.653801+00:00 |
| `price-monitor` | FRESH | 38711 | 2026-07-08T21:16:16.533566+00:00 |
| `exit-monitor` | FRESH | 615 | 2026-07-09T07:51:12.362877+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

