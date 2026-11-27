# Heartbeat Freshness Status

- Generated at: `2026-11-27T14:11:12.667509+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=9, STALE=1, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 297 | 2026-11-27T14:06:15.893652+00:00 |
| `defense-monitor` | FRESH | 292 | 2026-11-27T14:06:20.939255+00:00 |
| `twitter-monitor` | FRESH | 278 | 2026-11-27T14:06:34.399344+00:00 |
| `reddit-monitor` | STALE | 227605 | 2026-11-24T22:57:47.743867+00:00 |
| `geo-monitor` | FRESH | 604 | 2026-11-27T14:01:08.488880+00:00 |
| `politician-monitor` | FRESH | 1408 | 2026-11-27T13:47:45.160382+00:00 |
| `options-monitor` | FRESH | 298 | 2026-11-27T14:06:14.987017+00:00 |
| `options-exit-monitor` | FRESH | 608 | 2026-11-27T14:01:04.523402+00:00 |
| `price-monitor` | FRESH | 910 | 2026-11-27T13:56:02.187829+00:00 |
| `exit-monitor` | FRESH | 310 | 2026-11-27T14:06:02.638074+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

