# Heartbeat Freshness Status

- Generated at: `2026-09-18T09:08:04.841638+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 146 | 2026-09-18T09:05:38.462514+00:00 |
| `defense-monitor` | FRESH | 144 | 2026-09-18T09:05:41.014945+00:00 |
| `twitter-monitor` | FRESH | 129 | 2026-09-18T09:05:55.852563+00:00 |
| `reddit-monitor` | FRESH | 33206 | 2026-09-17T23:54:38.440498+00:00 |
| `geo-monitor` | FRESH | 1293 | 2026-09-18T08:46:31.542414+00:00 |
| `politician-monitor` | FRESH | 5779 | 2026-09-18T07:31:45.524226+00:00 |
| `options-monitor` | FRESH | 36404 | 2026-09-17T23:01:20.699753+00:00 |
| `options-exit-monitor` | FRESH | 148 | 2026-09-18T09:05:36.395987+00:00 |
| `price-monitor` | FRESH | 36330 | 2026-09-17T23:02:35.216102+00:00 |
| `exit-monitor` | FRESH | 135 | 2026-09-18T09:05:50.157793+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

