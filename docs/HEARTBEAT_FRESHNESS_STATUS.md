# Heartbeat Freshness Status

- Generated at: `2026-11-22T12:47:26.092720+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 398 | 2026-11-22T12:40:48.040072+00:00 |
| `defense-monitor` | FRESH | 97 | 2026-11-22T12:45:48.836719+00:00 |
| `twitter-monitor` | FRESH | 373 | 2026-11-22T12:41:12.815514+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 2793 | 2026-11-22T12:00:52.773590+00:00 |
| `politician-monitor` | FRESH | 11705 | 2026-11-22T09:32:21.342404+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 103 | 2026-11-22T12:45:43.299180+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 402 | 2026-11-22T12:40:43.997873+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

