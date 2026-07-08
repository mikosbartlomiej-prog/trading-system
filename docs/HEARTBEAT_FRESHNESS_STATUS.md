# Heartbeat Freshness Status

- Generated at: `2026-07-08T07:03:52.379269+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 153 | 2026-07-08T07:01:18.963449+00:00 |
| `defense-monitor` | FRESH | 159 | 2026-07-08T07:01:13.156621+00:00 |
| `twitter-monitor` | FRESH | 146 | 2026-07-08T07:01:26.821636+00:00 |
| `reddit-monitor` | FRESH | 31716 | 2026-07-07T22:15:16.592147+00:00 |
| `geo-monitor` | FRESH | 8875 | 2026-07-08T04:35:57.826598+00:00 |
| `politician-monitor` | FRESH | 2045 | 2026-07-08T06:29:47.861587+00:00 |
| `options-monitor` | FRESH | 35885 | 2026-07-07T21:05:47.757546+00:00 |
| `options-exit-monitor` | FRESH | 162 | 2026-07-08T07:01:10.313309+00:00 |
| `price-monitor` | FRESH | 35789 | 2026-07-07T21:07:23.265739+00:00 |
| `exit-monitor` | FRESH | 463 | 2026-07-08T06:56:09.222441+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

