# Heartbeat Freshness Status

- Generated at: `2026-09-25T09:44:49.350932+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=9, STALE=0, MISSING=2, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 258 | 2026-09-25T09:40:31.649999+00:00 |
| `defense-monitor` | FRESH | 532 | 2026-09-25T09:35:56.907933+00:00 |
| `twitter-monitor` | FRESH | 229 | 2026-09-25T09:41:00.533344+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 2654 | 2026-09-25T09:00:35.395945+00:00 |
| `politician-monitor` | FRESH | 794 | 2026-09-25T09:31:34.971980+00:00 |
| `options-monitor` | FRESH | 36674 | 2026-09-24T23:33:35.119133+00:00 |
| `options-exit-monitor` | FRESH | 259 | 2026-09-25T09:40:30.489476+00:00 |
| `price-monitor` | FRESH | 36644 | 2026-09-24T23:34:05.367626+00:00 |
| `exit-monitor` | FRESH | 255 | 2026-09-25T09:40:34.246749+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

