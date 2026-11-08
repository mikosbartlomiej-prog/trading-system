# Heartbeat Freshness Status

- Generated at: `2026-11-08T11:28:13.601911+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=8, STALE=2, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 399 | 2026-11-08T11:21:34.276023+00:00 |
| `defense-monitor` | FRESH | 396 | 2026-11-08T11:21:37.263699+00:00 |
| `twitter-monitor` | FRESH | 382 | 2026-11-08T11:21:51.888866+00:00 |
| `reddit-monitor` | FRESH | 37388 | 2026-11-08T01:05:05.440388+00:00 |
| `geo-monitor` | FRESH | 2502 | 2026-11-08T10:46:31.530632+00:00 |
| `politician-monitor` | FRESH | 663 | 2026-11-08T11:17:10.885255+00:00 |
| `options-monitor` | STALE | 128261 | 2026-11-06T23:50:32.185217+00:00 |
| `options-exit-monitor` | FRESH | 107 | 2026-11-08T11:26:26.571991+00:00 |
| `price-monitor` | STALE | 128161 | 2026-11-06T23:52:12.911941+00:00 |
| `exit-monitor` | FRESH | 405 | 2026-11-08T11:21:28.904062+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

