# Heartbeat Freshness Status

- Generated at: `2026-10-14T09:39:58.585951+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 223 | 2026-10-14T09:36:15.679103+00:00 |
| `defense-monitor` | FRESH | 219 | 2026-10-14T09:36:19.110032+00:00 |
| `twitter-monitor` | FRESH | 201 | 2026-10-14T09:36:37.159310+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 494 | 2026-10-14T09:31:44.760585+00:00 |
| `politician-monitor` | FRESH | 8675 | 2026-10-14T07:15:23.627506+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 225 | 2026-10-14T09:36:13.466007+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 225 | 2026-10-14T09:36:13.641870+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

