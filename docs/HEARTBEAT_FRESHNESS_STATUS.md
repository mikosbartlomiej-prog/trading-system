# Heartbeat Freshness Status

- Generated at: `2026-08-17T05:08:51.281003+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 179 | 2026-08-17T05:05:52.023339+00:00 |
| `defense-monitor` | FRESH | 179 | 2026-08-17T05:05:51.810885+00:00 |
| `twitter-monitor` | FRESH | 130 | 2026-08-17T05:06:41.228654+00:00 |
| `reddit-monitor` | FRESH | 24605 | 2026-08-16T22:18:45.801403+00:00 |
| `geo-monitor` | FRESH | 527 | 2026-08-17T05:00:04.462962+00:00 |
| `politician-monitor` | FRESH | 1532 | 2026-08-17T04:43:19.203511+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 182 | 2026-08-17T05:05:49.293383+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 79 | 2026-08-17T05:07:32.477037+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

