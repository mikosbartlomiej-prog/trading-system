# Heartbeat Freshness Status

- Generated at: `2026-06-18T09:00:52.385768+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 27 | 2026-06-18T09:00:25.825500+00:00 |
| `defense-monitor` | FRESH | 324 | 2026-06-18T08:55:28.639082+00:00 |
| `twitter-monitor` | FRESH | 305 | 2026-06-18T08:55:47.563093+00:00 |
| `reddit-monitor` | FRESH | 34708 | 2026-06-17T23:22:23.901519+00:00 |
| `geo-monitor` | FRESH | 929 | 2026-06-18T08:45:23.394024+00:00 |
| `politician-monitor` | FRESH | 6310 | 2026-06-18T07:15:42.392721+00:00 |
| `options-monitor` | FRESH | 42006 | 2026-06-17T21:20:46.009344+00:00 |
| `options-exit-monitor` | FRESH | 29 | 2026-06-18T09:00:23.327224+00:00 |
| `price-monitor` | FRESH | 41924 | 2026-06-17T21:22:08.258056+00:00 |
| `exit-monitor` | FRESH | 30 | 2026-06-18T09:00:22.397366+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

