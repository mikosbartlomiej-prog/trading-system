# Heartbeat Freshness Status

- Generated at: `2026-07-17T06:38:14.778771+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 154 | 2026-07-17T06:35:40.324349+00:00 |
| `defense-monitor` | FRESH | 155 | 2026-07-17T06:35:40.166612+00:00 |
| `twitter-monitor` | FRESH | 129 | 2026-07-17T06:36:05.329352+00:00 |
| `reddit-monitor` | FRESH | 34206 | 2026-07-16T21:08:09.010993+00:00 |
| `geo-monitor` | FRESH | 1963 | 2026-07-17T06:05:31.863245+00:00 |
| `politician-monitor` | FRESH | 1163 | 2026-07-17T06:18:51.280496+00:00 |
| `options-monitor` | FRESH | 31983 | 2026-07-16T21:45:11.305849+00:00 |
| `options-exit-monitor` | FRESH | 163 | 2026-07-17T06:35:31.732087+00:00 |
| `price-monitor` | FRESH | 31730 | 2026-07-16T21:49:25.238760+00:00 |
| `exit-monitor` | FRESH | 158 | 2026-07-17T06:35:37.155639+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

