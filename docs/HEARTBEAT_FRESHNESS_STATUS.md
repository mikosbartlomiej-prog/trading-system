# Heartbeat Freshness Status

- Generated at: `2026-10-28T10:44:39.999923+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 203 | 2026-10-28T10:41:17.473617+00:00 |
| `defense-monitor` | FRESH | 202 | 2026-10-28T10:41:17.813998+00:00 |
| `twitter-monitor` | FRESH | 183 | 2026-10-28T10:41:36.816970+00:00 |
| `reddit-monitor` | FRESH | 35182 | 2026-10-28T00:58:18.231639+00:00 |
| `geo-monitor` | FRESH | 792 | 2026-10-28T10:31:28.067268+00:00 |
| `politician-monitor` | FRESH | 9788 | 2026-10-28T08:01:31.992237+00:00 |
| `options-monitor` | FRESH | 43837 | 2026-10-27T22:34:03.096426+00:00 |
| `options-exit-monitor` | FRESH | 210 | 2026-10-28T10:41:10.107773+00:00 |
| `price-monitor` | FRESH | 43804 | 2026-10-27T22:34:35.935404+00:00 |
| `exit-monitor` | FRESH | 504 | 2026-10-28T10:36:16.094405+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

