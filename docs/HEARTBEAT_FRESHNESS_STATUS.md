# Heartbeat Freshness Status

- Generated at: `2026-08-12T05:55:35.179445+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 285 | 2026-08-12T05:50:49.858511+00:00 |
| `defense-monitor` | FRESH | 283 | 2026-08-12T05:50:52.346946+00:00 |
| `twitter-monitor` | FRESH | 170 | 2026-08-12T05:52:45.203958+00:00 |
| `reddit-monitor` | FRESH | 26213 | 2026-08-11T22:38:41.986758+00:00 |
| `geo-monitor` | FRESH | 578 | 2026-08-12T05:45:57.448411+00:00 |
| `politician-monitor` | FRESH | 1009 | 2026-08-12T05:38:46.509278+00:00 |
| `options-monitor` | FRESH | 31575 | 2026-08-11T21:09:20.649779+00:00 |
| `options-exit-monitor` | FRESH | 282 | 2026-08-12T05:50:53.307314+00:00 |
| `price-monitor` | FRESH | 34457 | 2026-08-11T20:21:17.901648+00:00 |
| `exit-monitor` | FRESH | 889 | 2026-08-12T05:40:46.196342+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

