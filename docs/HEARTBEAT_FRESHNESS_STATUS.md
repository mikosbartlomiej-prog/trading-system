# Heartbeat Freshness Status

- Generated at: `2026-06-19T09:19:36.047402+00:00`
- US market session: **CLOSED** (holiday)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 251 | 2026-06-19T09:15:25.045671+00:00 |
| `defense-monitor` | FRESH | 251 | 2026-06-19T09:15:25.408974+00:00 |
| `twitter-monitor` | FRESH | 230 | 2026-06-19T09:15:46.279753+00:00 |
| `reddit-monitor` | FRESH | 34517 | 2026-06-18T23:44:19.537556+00:00 |
| `geo-monitor` | FRESH | 254 | 2026-06-19T09:15:21.769169+00:00 |
| `politician-monitor` | FRESH | 5635 | 2026-06-19T07:45:40.693230+00:00 |
| `options-monitor` | FRESH | 42801 | 2026-06-18T21:26:14.654113+00:00 |
| `options-exit-monitor` | FRESH | 256 | 2026-06-19T09:15:19.931067+00:00 |
| `price-monitor` | FRESH | 42814 | 2026-06-18T21:26:01.689116+00:00 |
| `exit-monitor` | FRESH | 556 | 2026-06-19T09:10:19.704644+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

