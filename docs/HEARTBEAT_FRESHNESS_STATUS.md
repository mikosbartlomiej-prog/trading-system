# Heartbeat Freshness Status

- Generated at: `2026-10-15T09:18:33.288700+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 134 | 2026-10-15T09:16:19.524529+00:00 |
| `defense-monitor` | FRESH | 127 | 2026-10-15T09:16:26.617404+00:00 |
| `twitter-monitor` | FRESH | 120 | 2026-10-15T09:16:33.607309+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 138 | 2026-10-15T09:16:15.425600+00:00 |
| `politician-monitor` | FRESH | 1225 | 2026-10-15T08:58:08.576300+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 433 | 2026-10-15T09:11:19.837823+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 140 | 2026-10-15T09:16:13.404284+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

