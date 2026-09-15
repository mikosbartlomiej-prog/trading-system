# Heartbeat Freshness Status

- Generated at: `2026-09-15T09:32:56.529960+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 196 | 2026-09-15T09:29:40.417003+00:00 |
| `defense-monitor` | FRESH | 699 | 2026-09-15T09:21:17.500532+00:00 |
| `twitter-monitor` | FRESH | 64 | 2026-09-15T09:31:52.527520+00:00 |
| `reddit-monitor` | FRESH | 40220 | 2026-09-14T22:22:36.731653+00:00 |
| `geo-monitor` | FRESH | 87 | 2026-09-15T09:31:29.284756+00:00 |
| `politician-monitor` | FRESH | 7839 | 2026-09-15T07:22:17.214841+00:00 |
| `options-monitor` | FRESH | 41872 | 2026-09-14T21:55:04.869428+00:00 |
| `options-exit-monitor` | FRESH | 90 | 2026-09-15T09:31:26.264806+00:00 |
| `price-monitor` | FRESH | 41824 | 2026-09-14T21:55:52.495486+00:00 |
| `exit-monitor` | FRESH | 93 | 2026-09-15T09:31:23.641902+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

