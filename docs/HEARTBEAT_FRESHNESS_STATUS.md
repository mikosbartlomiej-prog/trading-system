# Heartbeat Freshness Status

- Generated at: `2026-09-04T08:59:22.857540+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 201 | 2026-09-04T08:56:01.788411+00:00 |
| `defense-monitor` | FRESH | 194 | 2026-09-04T08:56:09.089445+00:00 |
| `twitter-monitor` | FRESH | 160 | 2026-09-04T08:56:43.288258+00:00 |
| `reddit-monitor` | FRESH | 37927 | 2026-09-03T22:27:15.823582+00:00 |
| `geo-monitor` | FRESH | 1691 | 2026-09-04T08:31:12.236566+00:00 |
| `politician-monitor` | FRESH | 1423 | 2026-09-04T08:35:40.125355+00:00 |
| `options-monitor` | FRESH | 39986 | 2026-09-03T21:52:56.659012+00:00 |
| `options-exit-monitor` | FRESH | 201 | 2026-09-04T08:56:01.446247+00:00 |
| `price-monitor` | FRESH | 39944 | 2026-09-03T21:53:38.676271+00:00 |
| `exit-monitor` | FRESH | 196 | 2026-09-04T08:56:06.548423+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

