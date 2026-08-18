# Heartbeat Freshness Status

- Generated at: `2026-08-18T05:02:44.108358+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 108 | 2026-08-18T05:00:56.368808+00:00 |
| `defense-monitor` | FRESH | 405 | 2026-08-18T04:55:59.134975+00:00 |
| `twitter-monitor` | FRESH | 89 | 2026-08-18T05:01:14.752283+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 3769 | 2026-08-18T03:59:54.948276+00:00 |
| `politician-monitor` | FRESH | 1527 | 2026-08-18T04:37:17.548498+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 116 | 2026-08-18T05:00:48.388919+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 115 | 2026-08-18T05:00:49.148447+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

