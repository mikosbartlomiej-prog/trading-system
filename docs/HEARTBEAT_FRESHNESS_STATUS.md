# Heartbeat Freshness Status

- Generated at: `2026-08-10T05:55:44.428216+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 288 | 2026-08-10T05:50:56.073721+00:00 |
| `defense-monitor` | FRESH | 296 | 2026-08-10T05:50:47.999965+00:00 |
| `twitter-monitor` | FRESH | 161 | 2026-08-10T05:53:03.397360+00:00 |
| `reddit-monitor` | FRESH | 26853 | 2026-08-09T22:28:11.089470+00:00 |
| `geo-monitor` | FRESH | 354 | 2026-08-10T05:49:50.865991+00:00 |
| `politician-monitor` | FRESH | 917 | 2026-08-10T05:40:26.936151+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 301 | 2026-08-10T05:50:43.850606+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 297 | 2026-08-10T05:50:47.610184+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

