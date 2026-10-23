# Heartbeat Freshness Status

- Generated at: `2026-10-23T09:29:56.132337+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 243 | 2026-10-23T09:25:52.842140+00:00 |
| `defense-monitor` | FRESH | 237 | 2026-10-23T09:25:58.841397+00:00 |
| `twitter-monitor` | FRESH | 221 | 2026-10-23T09:26:14.852218+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 2646 | 2026-10-23T08:45:50.281374+00:00 |
| `politician-monitor` | FRESH | 1090 | 2026-10-23T09:11:46.132089+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 248 | 2026-10-23T09:25:48.400987+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 250 | 2026-10-23T09:25:46.183762+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

