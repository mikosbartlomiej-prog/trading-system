# Heartbeat Freshness Status

- Generated at: `2026-09-01T09:32:58.167525+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 122 | 2026-09-01T09:30:56.233994+00:00 |
| `defense-monitor` | FRESH | 421 | 2026-09-01T09:25:56.693640+00:00 |
| `twitter-monitor` | FRESH | 102 | 2026-09-01T09:31:15.830935+00:00 |
| `reddit-monitor` | FRESH | 30847 | 2026-09-01T00:58:51.560250+00:00 |
| `geo-monitor` | FRESH | 125 | 2026-09-01T09:30:53.170541+00:00 |
| `politician-monitor` | FRESH | 8187 | 2026-09-01T07:16:31.484703+00:00 |
| `options-monitor` | FRESH | 37056 | 2026-08-31T23:15:22.338844+00:00 |
| `options-exit-monitor` | FRESH | 127 | 2026-09-01T09:30:50.785033+00:00 |
| `price-monitor` | FRESH | 36994 | 2026-08-31T23:16:23.769125+00:00 |
| `exit-monitor` | FRESH | 427 | 2026-09-01T09:25:51.269023+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

