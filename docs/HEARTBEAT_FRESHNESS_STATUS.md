# Heartbeat Freshness Status

- Generated at: `2026-07-12T07:06:59.271042+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 59 | 2026-07-12T07:06:00.213833+00:00 |
| `defense-monitor` | FRESH | 359 | 2026-07-12T07:01:00.339323+00:00 |
| `twitter-monitor` | FRESH | 39 | 2026-07-12T07:06:19.995670+00:00 |
| `reddit-monitor` | FRESH | 30093 | 2026-07-11T22:45:26.763382+00:00 |
| `geo-monitor` | FRESH | 1179 | 2026-07-12T06:47:20.655128+00:00 |
| `politician-monitor` | FRESH | 1930 | 2026-07-12T06:34:49.352361+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 63 | 2026-07-12T07:05:56.211512+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 65 | 2026-07-12T07:05:54.009144+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

