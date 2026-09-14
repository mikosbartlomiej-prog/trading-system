# Heartbeat Freshness Status

- Generated at: `2026-09-14T10:03:33.342241+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 139 | 2026-09-14T10:01:14.656126+00:00 |
| `defense-monitor` | FRESH | 137 | 2026-09-14T10:01:15.848537+00:00 |
| `twitter-monitor` | FRESH | 92 | 2026-09-14T10:02:01.764966+00:00 |
| `reddit-monitor` | FRESH | 36638 | 2026-09-13T23:52:55.032414+00:00 |
| `geo-monitor` | FRESH | 1043 | 2026-09-14T09:46:10.766003+00:00 |
| `politician-monitor` | FRESH | 1376 | 2026-09-14T09:40:37.725103+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 144 | 2026-09-14T10:01:09.526223+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 144 | 2026-09-14T10:01:09.540631+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

