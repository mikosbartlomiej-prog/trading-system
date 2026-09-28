# Heartbeat Freshness Status

- Generated at: `2026-09-28T11:09:17.597034+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=7, STALE=1, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 172 | 2026-09-28T11:06:25.346663+00:00 |
| `defense-monitor` | FRESH | 170 | 2026-09-28T11:06:27.112088+00:00 |
| `twitter-monitor` | FRESH | 149 | 2026-09-28T11:06:48.999820+00:00 |
| `reddit-monitor` | STALE | 125727 | 2026-09-27T00:13:50.251845+00:00 |
| `geo-monitor` | FRESH | 5864 | 2026-09-28T09:31:33.527461+00:00 |
| `politician-monitor` | FRESH | 407 | 2026-09-28T11:02:30.973231+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 470 | 2026-09-28T11:01:27.959806+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 176 | 2026-09-28T11:06:21.601246+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

