# Heartbeat Freshness Status

- Generated at: `2026-07-28T07:13:12.930232+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 153 | 2026-07-28T07:10:39.617121+00:00 |
| `defense-monitor` | FRESH | 153 | 2026-07-28T07:10:39.978420+00:00 |
| `twitter-monitor` | FRESH | 130 | 2026-07-28T07:11:03.155877+00:00 |
| `reddit-monitor` | FRESH | 29598 | 2026-07-27T22:59:54.974983+00:00 |
| `geo-monitor` | FRESH | 750 | 2026-07-28T07:00:43.151461+00:00 |
| `politician-monitor` | FRESH | 2678 | 2026-07-28T06:28:34.640284+00:00 |
| `options-monitor` | FRESH | 34943 | 2026-07-27T21:30:50.300157+00:00 |
| `options-exit-monitor` | FRESH | 156 | 2026-07-28T07:10:36.672349+00:00 |
| `price-monitor` | FRESH | 34866 | 2026-07-27T21:32:06.550687+00:00 |
| `exit-monitor` | FRESH | 158 | 2026-07-28T07:10:34.452510+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

