# Heartbeat Freshness Status

- Generated at: `2026-07-29T07:18:58.170622+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 202 | 2026-07-29T07:15:36.527540+00:00 |
| `defense-monitor` | FRESH | 499 | 2026-07-29T07:10:39.435244+00:00 |
| `twitter-monitor` | FRESH | 188 | 2026-07-29T07:15:50.241160+00:00 |
| `reddit-monitor` | FRESH | 36368 | 2026-07-28T21:12:50.372923+00:00 |
| `geo-monitor` | FRESH | 194 | 2026-07-29T07:15:44.294936+00:00 |
| `politician-monitor` | FRESH | 2775 | 2026-07-29T06:32:43.466845+00:00 |
| `options-monitor` | FRESH | 33685 | 2026-07-28T21:57:32.757934+00:00 |
| `options-exit-monitor` | FRESH | 198 | 2026-07-29T07:15:40.017844+00:00 |
| `price-monitor` | FRESH | 36767 | 2026-07-28T21:06:11.241227+00:00 |
| `exit-monitor` | FRESH | 202 | 2026-07-29T07:15:36.105934+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

