# Heartbeat Freshness Status

- Generated at: `2026-10-12T12:19:22.089232+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=7, STALE=1, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 178 | 2026-10-12T12:16:24.532338+00:00 |
| `defense-monitor` | FRESH | 181 | 2026-10-12T12:16:21.014200+00:00 |
| `twitter-monitor` | FRESH | 159 | 2026-10-12T12:16:42.933202+00:00 |
| `reddit-monitor` | STALE | 128330 | 2026-10-11T00:40:31.992538+00:00 |
| `geo-monitor` | FRESH | 1069 | 2026-10-12T12:01:33.170292+00:00 |
| `politician-monitor` | FRESH | 3708 | 2026-10-12T11:17:33.694886+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 789 | 2026-10-12T12:06:13.527539+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 174 | 2026-10-12T12:16:28.401545+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

