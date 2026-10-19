# Heartbeat Freshness Status

- Generated at: `2026-10-19T10:09:34.419162+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 219 | 2026-10-19T10:05:55.301263+00:00 |
| `defense-monitor` | FRESH | 214 | 2026-10-19T10:06:00.648570+00:00 |
| `twitter-monitor` | FRESH | 197 | 2026-10-19T10:06:17.345303+00:00 |
| `reddit-monitor` | FRESH | 36885 | 2026-10-18T23:54:49.858823+00:00 |
| `geo-monitor` | FRESH | 520 | 2026-10-19T10:00:54.432464+00:00 |
| `politician-monitor` | FRESH | 9451 | 2026-10-19T07:32:03.009498+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 228 | 2026-10-19T10:05:45.955185+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 226 | 2026-10-19T10:05:48.269184+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

