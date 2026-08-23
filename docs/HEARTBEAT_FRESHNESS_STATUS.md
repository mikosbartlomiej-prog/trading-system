# Heartbeat Freshness Status

- Generated at: `2026-08-23T05:01:54.396113+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 57 | 2026-08-23T05:00:57.234547+00:00 |
| `defense-monitor` | FRESH | 61 | 2026-08-23T05:00:53.866647+00:00 |
| `twitter-monitor` | FRESH | 338 | 2026-08-23T04:56:16.012955+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 499 | 2026-08-23T04:53:35.071238+00:00 |
| `politician-monitor` | FRESH | 1365 | 2026-08-23T04:39:09.638200+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 63 | 2026-08-23T05:00:51.426415+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 365 | 2026-08-23T04:55:49.256618+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

