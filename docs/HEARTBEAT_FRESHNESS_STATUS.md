# Heartbeat Freshness Status

- Generated at: `2026-10-27T09:57:58.286824+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 113 | 2026-10-27T09:56:05.001031+00:00 |
| `defense-monitor` | FRESH | 110 | 2026-10-27T09:56:08.048660+00:00 |
| `twitter-monitor` | FRESH | 106 | 2026-10-27T09:56:12.728423+00:00 |
| `reddit-monitor` | FRESH | 31796 | 2026-10-27T01:08:02.235033+00:00 |
| `geo-monitor` | FRESH | 722 | 2026-10-27T09:45:56.638441+00:00 |
| `politician-monitor` | FRESH | 9646 | 2026-10-27T07:17:12.173122+00:00 |
| `options-monitor` | FRESH | 39153 | 2026-10-26T23:05:25.136771+00:00 |
| `options-exit-monitor` | FRESH | 130 | 2026-10-27T09:55:47.848319+00:00 |
| `price-monitor` | FRESH | 50518 | 2026-10-26T19:56:00.546442+00:00 |
| `exit-monitor` | FRESH | 129 | 2026-10-27T09:55:49.514530+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

