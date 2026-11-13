# Heartbeat Freshness Status

- Generated at: `2026-11-13T12:29:59.244882+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 226 | 2026-11-13T12:26:13.227014+00:00 |
| `defense-monitor` | FRESH | 225 | 2026-11-13T12:26:14.285139+00:00 |
| `twitter-monitor` | FRESH | 205 | 2026-11-13T12:26:33.906985+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 828 | 2026-11-13T12:16:11.393178+00:00 |
| `politician-monitor` | FRESH | 1910 | 2026-11-13T11:58:09.258165+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 229 | 2026-11-13T12:26:09.748819+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 229 | 2026-11-13T12:26:09.850045+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

