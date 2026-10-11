# Heartbeat Freshness Status

- Generated at: `2026-10-11T10:58:39.707857+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 148 | 2026-10-11T10:56:11.208075+00:00 |
| `defense-monitor` | FRESH | 148 | 2026-10-11T10:56:12.129812+00:00 |
| `twitter-monitor` | FRESH | 127 | 2026-10-11T10:56:33.071895+00:00 |
| `reddit-monitor` | FRESH | 37088 | 2026-10-11T00:40:31.992538+00:00 |
| `geo-monitor` | FRESH | 746 | 2026-10-11T10:46:13.988787+00:00 |
| `politician-monitor` | FRESH | 11458 | 2026-10-11T07:47:41.859279+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 154 | 2026-10-11T10:56:06.110640+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 152 | 2026-10-11T10:56:07.862750+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

