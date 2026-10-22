# Heartbeat Freshness Status

- Generated at: `2026-10-22T09:33:47.615570+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 176 | 2026-10-22T09:30:51.285727+00:00 |
| `defense-monitor` | FRESH | 171 | 2026-10-22T09:30:56.570485+00:00 |
| `twitter-monitor` | FRESH | 165 | 2026-10-22T09:31:02.795028+00:00 |
| `reddit-monitor` | FRESH | 43234 | 2026-10-21T21:33:13.648605+00:00 |
| `geo-monitor` | FRESH | 1077 | 2026-10-22T09:15:50.283617+00:00 |
| `politician-monitor` | FRESH | 1123 | 2026-10-22T09:15:05.085936+00:00 |
| `options-monitor` | FRESH | 44830 | 2026-10-21T21:06:37.833498+00:00 |
| `options-exit-monitor` | FRESH | 473 | 2026-10-22T09:25:54.233328+00:00 |
| `price-monitor` | FRESH | 44200 | 2026-10-21T21:17:08.010406+00:00 |
| `exit-monitor` | FRESH | 176 | 2026-10-22T09:30:51.939869+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

