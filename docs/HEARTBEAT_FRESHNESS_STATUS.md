# Heartbeat Freshness Status

- Generated at: `2026-11-19T13:45:08.168964+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 512 | 2026-11-19T13:36:35.744658+00:00 |
| `defense-monitor` | FRESH | 203 | 2026-11-19T13:41:45.121907+00:00 |
| `twitter-monitor` | FRESH | 200 | 2026-11-19T13:41:48.016558+00:00 |
| `reddit-monitor` | FRESH | 38939 | 2026-11-19T02:56:08.747675+00:00 |
| `geo-monitor` | FRESH | 917 | 2026-11-19T13:29:50.770734+00:00 |
| `politician-monitor` | FRESH | 4095 | 2026-11-19T12:36:53.346698+00:00 |
| `options-monitor` | FRESH | 210 | 2026-11-19T13:41:38.300457+00:00 |
| `options-exit-monitor` | FRESH | 218 | 2026-11-19T13:41:30.585060+00:00 |
| `price-monitor` | FRESH | 221 | 2026-11-19T13:41:27.489902+00:00 |
| `exit-monitor` | FRESH | 219 | 2026-11-19T13:41:28.882478+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

