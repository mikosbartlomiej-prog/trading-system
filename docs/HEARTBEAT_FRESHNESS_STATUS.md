# Heartbeat Freshness Status

- Generated at: `2026-11-10T12:53:46.770166+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=5, STALE=0, MISSING=6, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 161 | 2026-11-10T12:51:05.727204+00:00 |
| `defense-monitor` | FRESH | 179 | 2026-11-10T12:50:47.460560+00:00 |
| `twitter-monitor` | MISSING | n/a | — |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 479 | 2026-11-10T12:45:47.357195+00:00 |
| `politician-monitor` | MISSING | n/a | — |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 181 | 2026-11-10T12:50:45.448423+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 175 | 2026-11-10T12:50:52.101887+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

