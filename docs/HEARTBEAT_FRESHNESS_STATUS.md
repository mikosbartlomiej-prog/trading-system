# Heartbeat Freshness Status

- Generated at: `2026-10-20T09:34:18.201737+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 208 | 2026-10-20T09:30:49.788274+00:00 |
| `defense-monitor` | FRESH | 501 | 2026-10-20T09:25:57.519512+00:00 |
| `twitter-monitor` | FRESH | 192 | 2026-10-20T09:31:05.905227+00:00 |
| `reddit-monitor` | FRESH | 31194 | 2026-10-20T00:54:24.553799+00:00 |
| `geo-monitor` | FRESH | 205 | 2026-10-20T09:30:53.571213+00:00 |
| `politician-monitor` | FRESH | 1088 | 2026-10-20T09:16:09.966865+00:00 |
| `options-monitor` | FRESH | 38524 | 2026-10-19T22:52:13.835814+00:00 |
| `options-exit-monitor` | FRESH | 210 | 2026-10-20T09:30:48.173487+00:00 |
| `price-monitor` | FRESH | 38473 | 2026-10-19T22:53:05.224744+00:00 |
| `exit-monitor` | FRESH | 208 | 2026-10-20T09:30:50.229597+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

