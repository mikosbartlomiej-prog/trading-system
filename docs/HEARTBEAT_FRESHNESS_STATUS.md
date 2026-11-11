# Heartbeat Freshness Status

- Generated at: `2026-11-11T12:02:25.721742+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 366 | 2026-11-11T11:56:19.667076+00:00 |
| `defense-monitor` | FRESH | 365 | 2026-11-11T11:56:21.156388+00:00 |
| `twitter-monitor` | FRESH | 348 | 2026-11-11T11:56:37.319856+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 969 | 2026-11-11T11:46:16.526809+00:00 |
| `politician-monitor` | FRESH | 1810 | 2026-11-11T11:32:15.234640+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 373 | 2026-11-11T11:56:13.064283+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 363 | 2026-11-11T11:56:22.628620+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

