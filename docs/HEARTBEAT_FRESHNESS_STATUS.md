# Heartbeat Freshness Status

- Generated at: `2026-10-26T10:24:23.901952+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 213 | 2026-10-26T10:20:50.711680+00:00 |
| `defense-monitor` | FRESH | 214 | 2026-10-26T10:20:50.223281+00:00 |
| `twitter-monitor` | FRESH | 199 | 2026-10-26T10:21:05.370929+00:00 |
| `reddit-monitor` | FRESH | 38156 | 2026-10-25T23:48:28.108106+00:00 |
| `geo-monitor` | FRESH | 1412 | 2026-10-26T10:00:51.610893+00:00 |
| `politician-monitor` | FRESH | 1928 | 2026-10-26T09:52:15.507248+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 214 | 2026-10-26T10:20:50.014017+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 215 | 2026-10-26T10:20:48.754046+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

