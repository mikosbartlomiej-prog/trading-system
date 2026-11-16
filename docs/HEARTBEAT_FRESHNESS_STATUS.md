# Heartbeat Freshness Status

- Generated at: `2026-11-16T13:03:41.256952+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 125 | 2026-11-16T13:01:36.591313+00:00 |
| `defense-monitor` | FRESH | 427 | 2026-11-16T12:56:33.941109+00:00 |
| `twitter-monitor` | FRESH | 409 | 2026-11-16T12:56:52.579303+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 125 | 2026-11-16T13:01:35.943051+00:00 |
| `politician-monitor` | MISSING | n/a | — |
| `options-monitor` | FRESH | 129 | 2026-11-16T13:01:32.629360+00:00 |
| `options-exit-monitor` | FRESH | 435 | 2026-11-16T12:56:26.146428+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 128 | 2026-11-16T13:01:33.405720+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

