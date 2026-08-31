# Heartbeat Freshness Status

- Generated at: `2026-08-31T11:02:57.033232+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=8, STALE=2, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 119 | 2026-08-31T11:00:58.152892+00:00 |
| `defense-monitor` | FRESH | 420 | 2026-08-31T10:55:56.731340+00:00 |
| `twitter-monitor` | FRESH | 96 | 2026-08-31T11:01:20.964547+00:00 |
| `reddit-monitor` | FRESH | 39059 | 2026-08-31T00:11:57.669932+00:00 |
| `geo-monitor` | FRESH | 7315 | 2026-08-31T09:01:02.455724+00:00 |
| `politician-monitor` | FRESH | 10004 | 2026-08-31T08:16:12.540256+00:00 |
| `options-monitor` | STALE | 216604 | 2026-08-28T22:52:52.560878+00:00 |
| `options-exit-monitor` | FRESH | 126 | 2026-08-31T11:00:51.103619+00:00 |
| `price-monitor` | STALE | 216527 | 2026-08-28T22:54:10.351311+00:00 |
| `exit-monitor` | FRESH | 127 | 2026-08-31T11:00:49.740370+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

