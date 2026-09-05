# Heartbeat Freshness Status

- Generated at: `2026-09-05T08:29:59.017331+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 204 | 2026-09-05T08:26:34.998318+00:00 |
| `defense-monitor` | FRESH | 202 | 2026-09-05T08:26:37.064345+00:00 |
| `twitter-monitor` | FRESH | 180 | 2026-09-05T08:26:58.520991+00:00 |
| `reddit-monitor` | FRESH | 31600 | 2026-09-04T23:43:19.408252+00:00 |
| `geo-monitor` | FRESH | 807 | 2026-09-05T08:16:31.607665+00:00 |
| `politician-monitor` | FRESH | 1207 | 2026-09-05T08:09:52.462992+00:00 |
| `options-monitor` | FRESH | 39744 | 2026-09-04T21:27:35.324645+00:00 |
| `options-exit-monitor` | FRESH | 210 | 2026-09-05T08:26:29.061430+00:00 |
| `price-monitor` | FRESH | 39669 | 2026-09-04T21:28:49.787316+00:00 |
| `exit-monitor` | FRESH | 210 | 2026-09-05T08:26:28.719241+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

