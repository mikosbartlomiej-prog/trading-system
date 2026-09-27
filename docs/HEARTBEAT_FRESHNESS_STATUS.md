# Heartbeat Freshness Status

- Generated at: `2026-09-27T10:09:03.146822+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 163 | 2026-09-27T10:06:20.617427+00:00 |
| `defense-monitor` | FRESH | 154 | 2026-09-27T10:06:29.360795+00:00 |
| `twitter-monitor` | FRESH | 141 | 2026-09-27T10:06:42.161278+00:00 |
| `reddit-monitor` | FRESH | 35713 | 2026-09-27T00:13:50.251845+00:00 |
| `geo-monitor` | FRESH | 1346 | 2026-09-27T09:46:36.664174+00:00 |
| `politician-monitor` | FRESH | 9402 | 2026-09-27T07:32:20.938239+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 165 | 2026-09-27T10:06:17.977581+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 165 | 2026-09-27T10:06:18.222248+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

