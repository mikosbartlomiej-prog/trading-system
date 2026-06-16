# Heartbeat Freshness Status

- Generated at: `2026-06-16T09:40:01.519979+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 526 | 2026-06-16T09:31:15.043199+00:00 |
| `defense-monitor` | FRESH | 220 | 2026-06-16T09:36:21.594575+00:00 |
| `twitter-monitor` | FRESH | 210 | 2026-06-16T09:36:31.993151+00:00 |
| `reddit-monitor` | FRESH | 44726 | 2026-06-15T21:14:35.518527+00:00 |
| `geo-monitor` | FRESH | 1424 | 2026-06-16T09:16:17.146284+00:00 |
| `politician-monitor` | FRESH | 7706 | 2026-06-16T07:31:35.266868+00:00 |
| `options-monitor` | FRESH | 38926 | 2026-06-15T22:51:15.357565+00:00 |
| `options-exit-monitor` | FRESH | 229 | 2026-06-16T09:36:12.900709+00:00 |
| `price-monitor` | FRESH | 38825 | 2026-06-15T22:52:56.894201+00:00 |
| `exit-monitor` | FRESH | 230 | 2026-06-16T09:36:11.844124+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

