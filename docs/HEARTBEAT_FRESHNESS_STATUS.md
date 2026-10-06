# Heartbeat Freshness Status

- Generated at: `2026-10-06T11:26:17.106858+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 295 | 2026-10-06T11:21:21.684926+00:00 |
| `defense-monitor` | FRESH | 292 | 2026-10-06T11:21:24.671161+00:00 |
| `twitter-monitor` | FRESH | 286 | 2026-10-06T11:21:30.798770+00:00 |
| `reddit-monitor` | FRESH | 33748 | 2026-10-06T02:03:49.217609+00:00 |
| `geo-monitor` | FRESH | 596 | 2026-10-06T11:16:21.398263+00:00 |
| `politician-monitor` | FRESH | 5013 | 2026-10-06T10:02:44.396398+00:00 |
| `options-monitor` | FRESH | 51357 | 2026-10-05T21:10:19.628534+00:00 |
| `options-exit-monitor` | FRESH | 302 | 2026-10-06T11:21:15.584049+00:00 |
| `price-monitor` | FRESH | 56367 | 2026-10-05T19:46:50.221225+00:00 |
| `exit-monitor` | FRESH | 604 | 2026-10-06T11:16:12.809172+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

