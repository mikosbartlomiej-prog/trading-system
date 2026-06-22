# Heartbeat Freshness Status

- Generated at: `2026-06-22T10:21:45.226867+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=7, STALE=1, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 75 | 2026-06-22T10:20:29.942635+00:00 |
| `defense-monitor` | FRESH | 74 | 2026-06-22T10:20:31.605464+00:00 |
| `twitter-monitor` | FRESH | 54 | 2026-06-22T10:20:50.768522+00:00 |
| `reddit-monitor` | STALE | 126911 | 2026-06-20T23:06:34.568676+00:00 |
| `geo-monitor` | FRESH | 376 | 2026-06-22T10:15:29.510527+00:00 |
| `politician-monitor` | FRESH | 10259 | 2026-06-22T07:30:46.152547+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 78 | 2026-06-22T10:20:27.551713+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 978 | 2026-06-22T10:05:27.537814+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

