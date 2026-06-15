# Heartbeat Freshness Status

- Generated at: `2026-06-15T11:28:36.892449+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 139 | 2026-06-15T11:26:18.335427+00:00 |
| `defense-monitor` | FRESH | 144 | 2026-06-15T11:26:12.542406+00:00 |
| `twitter-monitor` | FRESH | 137 | 2026-06-15T11:26:20.233850+00:00 |
| `reddit-monitor` | FRESH | 44412 | 2026-06-14T23:08:24.884714+00:00 |
| `geo-monitor` | FRESH | 1638 | 2026-06-15T11:01:18.996852+00:00 |
| `politician-monitor` | FRESH | 2523 | 2026-06-15T10:46:33.867549+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 150 | 2026-06-15T11:26:06.762426+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 443 | 2026-06-15T11:21:13.404129+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

