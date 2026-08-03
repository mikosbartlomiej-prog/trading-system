# Heartbeat Freshness Status

- Generated at: `2026-08-03T07:56:58.980287+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 67 | 2026-08-03T07:55:51.960931+00:00 |
| `defense-monitor` | FRESH | 64 | 2026-08-03T07:55:54.751728+00:00 |
| `twitter-monitor` | FRESH | 341 | 2026-08-03T07:51:17.826519+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 675 | 2026-08-03T07:45:43.909518+00:00 |
| `politician-monitor` | FRESH | 1709 | 2026-08-03T07:28:29.840316+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 72 | 2026-08-03T07:55:46.644360+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 73 | 2026-08-03T07:55:46.391621+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

