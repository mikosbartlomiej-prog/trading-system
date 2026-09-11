# Heartbeat Freshness Status

- Generated at: `2026-09-11T09:02:27.568202+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 363 | 2026-09-11T08:56:24.225790+00:00 |
| `defense-monitor` | FRESH | 93 | 2026-09-11T09:00:54.784877+00:00 |
| `twitter-monitor` | FRESH | 301 | 2026-09-11T08:57:27.041392+00:00 |
| `reddit-monitor` | FRESH | 38353 | 2026-09-10T22:23:14.189054+00:00 |
| `geo-monitor` | FRESH | 965 | 2026-09-11T08:46:22.100054+00:00 |
| `politician-monitor` | FRESH | 1162 | 2026-09-11T08:43:05.493865+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 357 | 2026-09-11T08:56:30.100141+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 370 | 2026-09-11T08:56:17.721762+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

