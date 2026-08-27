# Heartbeat Freshness Status

- Generated at: `2026-08-27T15:24:39.911196+00:00`
- US market session: **OPEN** (open)
- Stale threshold in effect: `7200s`
- Exit code: `3`

- Summary: FRESH=9, STALE=1, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 526 | 2026-08-27T15:15:53.980744+00:00 |
| `defense-monitor` | FRESH | 220 | 2026-08-27T15:21:00.114619+00:00 |
| `twitter-monitor` | FRESH | 202 | 2026-08-27T15:21:18.269547+00:00 |
| `reddit-monitor` | STALE | 45013 | 2026-08-27T02:54:27.407291+00:00 |
| `geo-monitor` | FRESH | 513 | 2026-08-27T15:16:06.461860+00:00 |
| `politician-monitor` | FRESH | 3160 | 2026-08-27T14:31:59.958904+00:00 |
| `options-monitor` | FRESH | 230 | 2026-08-27T15:20:49.974376+00:00 |
| `options-exit-monitor` | FRESH | 228 | 2026-08-27T15:20:51.496807+00:00 |
| `price-monitor` | FRESH | 212 | 2026-08-27T15:21:08.154613+00:00 |
| `exit-monitor` | FRESH | 225 | 2026-08-27T15:20:55.088579+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

