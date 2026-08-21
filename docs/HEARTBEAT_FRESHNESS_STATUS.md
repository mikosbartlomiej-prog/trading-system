# Heartbeat Freshness Status

- Generated at: `2026-08-21T05:05:08.290691+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 254 | 2026-08-21T05:00:53.909809+00:00 |
| `defense-monitor` | FRESH | 217 | 2026-08-21T05:01:31.066135+00:00 |
| `twitter-monitor` | FRESH | 238 | 2026-08-21T05:01:10.488105+00:00 |
| `reddit-monitor` | FRESH | 24024 | 2026-08-20T22:24:44.350417+00:00 |
| `geo-monitor` | FRESH | 254 | 2026-08-21T05:00:54.719416+00:00 |
| `politician-monitor` | FRESH | 1523 | 2026-08-21T04:39:45.538370+00:00 |
| `options-monitor` | FRESH | 28933 | 2026-08-20T21:02:54.832534+00:00 |
| `options-exit-monitor` | FRESH | 557 | 2026-08-21T04:55:51.782460+00:00 |
| `price-monitor` | FRESH | 28260 | 2026-08-20T21:14:08.229341+00:00 |
| `exit-monitor` | FRESH | 97 | 2026-08-21T05:03:31.738831+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

