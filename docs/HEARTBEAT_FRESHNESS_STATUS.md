# Heartbeat Freshness Status

- Generated at: `2026-06-30T08:06:27.118366+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 57 | 2026-06-30T08:05:30.497334+00:00 |
| `defense-monitor` | FRESH | 55 | 2026-06-30T08:05:32.101998+00:00 |
| `twitter-monitor` | FRESH | 42 | 2026-06-30T08:05:44.791070+00:00 |
| `reddit-monitor` | FRESH | 33088 | 2026-06-29T22:54:58.917032+00:00 |
| `geo-monitor` | FRESH | 356 | 2026-06-30T08:00:30.727466+00:00 |
| `politician-monitor` | FRESH | 651 | 2026-06-30T07:55:36.020962+00:00 |
| `options-monitor` | FRESH | 36710 | 2026-06-29T21:54:36.752984+00:00 |
| `options-exit-monitor` | FRESH | 60 | 2026-06-30T08:05:26.904625+00:00 |
| `price-monitor` | FRESH | 36689 | 2026-06-29T21:54:57.781319+00:00 |
| `exit-monitor` | FRESH | 61 | 2026-06-30T08:05:26.263683+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

