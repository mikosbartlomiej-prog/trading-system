# Heartbeat Freshness Status

- Generated at: `2026-11-15T12:09:36.269480+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=8, STALE=2, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 202 | 2026-11-15T12:06:14.667508+00:00 |
| `defense-monitor` | FRESH | 203 | 2026-11-15T12:06:13.253271+00:00 |
| `twitter-monitor` | FRESH | 192 | 2026-11-15T12:06:24.764193+00:00 |
| `reddit-monitor` | FRESH | 38342 | 2026-11-15T01:30:34.722717+00:00 |
| `geo-monitor` | FRESH | 500 | 2026-11-15T12:01:15.901409+00:00 |
| `politician-monitor` | FRESH | 1341 | 2026-11-15T11:47:15.421239+00:00 |
| `options-monitor` | STALE | 126838 | 2026-11-14T00:55:38.538554+00:00 |
| `options-exit-monitor` | FRESH | 210 | 2026-11-15T12:06:06.235297+00:00 |
| `price-monitor` | STALE | 143320 | 2026-11-13T20:20:55.779972+00:00 |
| `exit-monitor` | FRESH | 210 | 2026-11-15T12:06:06.005130+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

