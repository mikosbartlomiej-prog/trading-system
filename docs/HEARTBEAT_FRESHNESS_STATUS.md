# Heartbeat Freshness Status

- Generated at: `2026-09-26T09:29:09.962148+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 169 | 2026-09-26T09:26:20.731446+00:00 |
| `defense-monitor` | FRESH | 167 | 2026-09-26T09:26:22.482048+00:00 |
| `twitter-monitor` | FRESH | 149 | 2026-09-26T09:26:40.500181+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 1663 | 2026-09-26T09:01:27.388184+00:00 |
| `politician-monitor` | FRESH | 7915 | 2026-09-26T07:17:14.757152+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 172 | 2026-09-26T09:26:18.111024+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 168 | 2026-09-26T09:26:21.828359+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

