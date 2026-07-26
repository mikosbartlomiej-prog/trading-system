# Heartbeat Freshness Status

- Generated at: `2026-07-26T07:10:29.647336+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 274 | 2026-07-26T07:05:55.218562+00:00 |
| `defense-monitor` | FRESH | 272 | 2026-07-26T07:05:57.685297+00:00 |
| `twitter-monitor` | FRESH | 258 | 2026-07-26T07:06:12.036882+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 1475 | 2026-07-26T06:45:54.227245+00:00 |
| `politician-monitor` | FRESH | 1923 | 2026-07-26T06:38:26.253381+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 278 | 2026-07-26T07:05:52.013676+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 272 | 2026-07-26T07:05:57.612790+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

