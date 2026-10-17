# Heartbeat Freshness Status

- Generated at: `2026-10-17T08:44:40.730576+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 235 | 2026-10-17T08:40:45.687354+00:00 |
| `defense-monitor` | FRESH | 228 | 2026-10-17T08:40:52.525456+00:00 |
| `twitter-monitor` | FRESH | 216 | 2026-10-17T08:41:05.178594+00:00 |
| `reddit-monitor` | FRESH | 30920 | 2026-10-17T00:09:20.980462+00:00 |
| `geo-monitor` | FRESH | 833 | 2026-10-17T08:30:48.215894+00:00 |
| `politician-monitor` | FRESH | 1462 | 2026-10-17T08:20:19.202654+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 536 | 2026-10-17T08:35:44.699885+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 236 | 2026-10-17T08:40:45.104601+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

