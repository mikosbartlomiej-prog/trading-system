# Heartbeat Freshness Status

- Generated at: `2026-10-16T09:12:49.421806+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 388 | 2026-10-16T09:06:21.419416+00:00 |
| `defense-monitor` | FRESH | 677 | 2026-10-16T09:01:32.404870+00:00 |
| `twitter-monitor` | FRESH | 365 | 2026-10-16T09:06:44.656782+00:00 |
| `reddit-monitor` | FRESH | 32868 | 2026-10-16T00:05:01.124768+00:00 |
| `geo-monitor` | FRESH | 679 | 2026-10-16T09:01:30.870353+00:00 |
| `politician-monitor` | FRESH | 1395 | 2026-10-16T08:49:34.616463+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 94 | 2026-10-16T09:11:15.701420+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 394 | 2026-10-16T09:06:15.713070+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

