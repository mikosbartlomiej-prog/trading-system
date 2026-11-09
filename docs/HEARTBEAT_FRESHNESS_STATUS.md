# Heartbeat Freshness Status

- Generated at: `2026-11-09T13:13:49.761899+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=9, STALE=1, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 135 | 2026-11-09T13:11:34.400004+00:00 |
| `defense-monitor` | FRESH | 132 | 2026-11-09T13:11:37.746912+00:00 |
| `twitter-monitor` | FRESH | 409 | 2026-11-09T13:07:01.230956+00:00 |
| `reddit-monitor` | FRESH | 42501 | 2026-11-09T01:25:28.803820+00:00 |
| `geo-monitor` | FRESH | 737 | 2026-11-09T13:01:32.908929+00:00 |
| `politician-monitor` | FRESH | 6075 | 2026-11-09T11:32:34.723484+00:00 |
| `options-monitor` | STALE | 220998 | 2026-11-06T23:50:32.185217+00:00 |
| `options-exit-monitor` | FRESH | 136 | 2026-11-09T13:11:34.022275+00:00 |
| `price-monitor` | FRESH | 723 | 2026-11-09T13:01:46.961506+00:00 |
| `exit-monitor` | FRESH | 730 | 2026-11-09T13:01:39.499729+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

