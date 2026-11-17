# Heartbeat Freshness Status

- Generated at: `2026-11-17T13:45:06.861384+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 213 | 2026-11-17T13:41:33.880172+00:00 |
| `defense-monitor` | FRESH | 217 | 2026-11-17T13:41:29.970489+00:00 |
| `twitter-monitor` | FRESH | 205 | 2026-11-17T13:41:41.891759+00:00 |
| `reddit-monitor` | FRESH | 33934 | 2026-11-17T04:19:33.339987+00:00 |
| `geo-monitor` | FRESH | 1722 | 2026-11-17T13:16:24.580414+00:00 |
| `politician-monitor` | FRESH | 749 | 2026-11-17T13:32:37.514959+00:00 |
| `options-monitor` | FRESH | 492 | 2026-11-17T13:36:54.956128+00:00 |
| `options-exit-monitor` | FRESH | 209 | 2026-11-17T13:41:38.179040+00:00 |
| `price-monitor` | FRESH | 510 | 2026-11-17T13:36:36.755021+00:00 |
| `exit-monitor` | FRESH | 212 | 2026-11-17T13:41:35.263134+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

