# Heartbeat Freshness Status

- Generated at: `2026-09-10T09:04:25.701753+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 192 | 2026-09-10T09:01:13.971333+00:00 |
| `defense-monitor` | FRESH | 503 | 2026-09-10T08:56:02.216868+00:00 |
| `twitter-monitor` | FRESH | 166 | 2026-09-10T09:01:39.669243+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 191 | 2026-09-10T09:01:14.649037+00:00 |
| `politician-monitor` | FRESH | 1187 | 2026-09-10T08:44:39.172988+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 200 | 2026-09-10T09:01:05.315971+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 507 | 2026-09-10T08:55:58.941893+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

