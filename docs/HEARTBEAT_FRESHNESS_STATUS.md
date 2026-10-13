# Heartbeat Freshness Status

- Generated at: `2026-10-13T12:03:04.705107+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 99 | 2026-10-13T12:01:25.484490+00:00 |
| `defense-monitor` | FRESH | 103 | 2026-10-13T12:01:21.435998+00:00 |
| `twitter-monitor` | FRESH | 83 | 2026-10-13T12:01:42.164682+00:00 |
| `reddit-monitor` | FRESH | 33165 | 2026-10-13T02:50:19.653644+00:00 |
| `geo-monitor` | FRESH | 100 | 2026-10-13T12:01:25.095154+00:00 |
| `politician-monitor` | FRESH | 10855 | 2026-10-13T09:02:09.363241+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 412 | 2026-10-13T11:56:12.446671+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 412 | 2026-10-13T11:56:12.321186+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

