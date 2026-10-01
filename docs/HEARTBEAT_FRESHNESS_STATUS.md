# Heartbeat Freshness Status

- Generated at: `2026-10-01T11:07:07.431729+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=6, STALE=0, MISSING=5, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 320 | 2026-10-01T11:01:47.568976+00:00 |
| `defense-monitor` | FRESH | 314 | 2026-10-01T11:01:53.403804+00:00 |
| `twitter-monitor` | FRESH | 307 | 2026-10-01T11:02:00.393274+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 324 | 2026-10-01T11:01:43.275314+00:00 |
| `politician-monitor` | MISSING | n/a | — |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 326 | 2026-10-01T11:01:41.164914+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 945 | 2026-10-01T10:51:21.957732+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

