# Heartbeat Freshness Status

- Generated at: `2026-09-16T09:26:09.167473+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 300 | 2026-09-16T09:21:09.313402+00:00 |
| `defense-monitor` | FRESH | 296 | 2026-09-16T09:21:12.791015+00:00 |
| `twitter-monitor` | FRESH | 274 | 2026-09-16T09:21:35.022756+00:00 |
| `reddit-monitor` | FRESH | 34087 | 2026-09-15T23:58:02.425841+00:00 |
| `geo-monitor` | FRESH | 603 | 2026-09-16T09:16:05.957454+00:00 |
| `politician-monitor` | FRESH | 567 | 2026-09-16T09:16:42.615120+00:00 |
| `options-monitor` | FRESH | 37564 | 2026-09-15T23:00:05.424706+00:00 |
| `options-exit-monitor` | FRESH | 305 | 2026-09-16T09:21:04.613234+00:00 |
| `price-monitor` | FRESH | 37480 | 2026-09-15T23:01:29.027304+00:00 |
| `exit-monitor` | FRESH | 304 | 2026-09-16T09:21:05.062185+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

