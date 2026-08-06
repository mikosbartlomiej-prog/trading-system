# Heartbeat Freshness Status

- Generated at: `2026-08-06T07:15:56.655591+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 307 | 2026-08-06T07:10:49.219236+00:00 |
| `defense-monitor` | FRESH | 135 | 2026-08-06T07:13:42.128031+00:00 |
| `twitter-monitor` | FRESH | 306 | 2026-08-06T07:10:51.085828+00:00 |
| `reddit-monitor` | FRESH | 41575 | 2026-08-05T19:43:01.499166+00:00 |
| `geo-monitor` | FRESH | 1817 | 2026-08-06T06:45:39.513916+00:00 |
| `politician-monitor` | FRESH | 2604 | 2026-08-06T06:32:32.805236+00:00 |
| `options-monitor` | FRESH | 36213 | 2026-08-05T21:12:23.636870+00:00 |
| `options-exit-monitor` | FRESH | 314 | 2026-08-06T07:10:42.654750+00:00 |
| `price-monitor` | FRESH | 35719 | 2026-08-05T21:20:37.516450+00:00 |
| `exit-monitor` | FRESH | 316 | 2026-08-06T07:10:40.604528+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

