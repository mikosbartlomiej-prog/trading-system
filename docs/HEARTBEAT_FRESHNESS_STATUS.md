# Heartbeat Freshness Status

- Generated at: `2026-07-30T07:12:48.826002+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 109 | 2026-07-30T07:11:00.134345+00:00 |
| `defense-monitor` | FRESH | 106 | 2026-07-30T07:11:03.010321+00:00 |
| `twitter-monitor` | FRESH | 82 | 2026-07-30T07:11:26.821564+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 705 | 2026-07-30T07:01:03.831893+00:00 |
| `politician-monitor` | FRESH | 2555 | 2026-07-30T06:30:13.370998+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 407 | 2026-07-30T07:06:01.442664+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 106 | 2026-07-30T07:11:02.544236+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

