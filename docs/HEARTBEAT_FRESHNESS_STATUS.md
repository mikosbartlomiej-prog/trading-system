# Heartbeat Freshness Status

- Generated at: `2026-08-30T10:03:42.480768+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=7, STALE=3, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 171 | 2026-08-30T10:00:51.214708+00:00 |
| `defense-monitor` | FRESH | 170 | 2026-08-30T10:00:52.626094+00:00 |
| `twitter-monitor` | FRESH | 146 | 2026-08-30T10:01:16.829164+00:00 |
| `reddit-monitor` | STALE | 110037 | 2026-08-29T03:29:45.402258+00:00 |
| `geo-monitor` | FRESH | 1970 | 2026-08-30T09:30:52.891493+00:00 |
| `politician-monitor` | FRESH | 8219 | 2026-08-30T07:46:43.960191+00:00 |
| `options-monitor` | STALE | 126650 | 2026-08-28T22:52:52.560878+00:00 |
| `options-exit-monitor` | FRESH | 470 | 2026-08-30T09:55:52.486655+00:00 |
| `price-monitor` | STALE | 126572 | 2026-08-28T22:54:10.351311+00:00 |
| `exit-monitor` | FRESH | 173 | 2026-08-30T10:00:49.424597+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

