# Heartbeat Freshness Status

- Generated at: `2026-11-24T15:08:35.380992+00:00`
- US market session: **OPEN** (open)
- Stale threshold in effect: `7200s`
- Exit code: `3`

- Summary: FRESH=9, STALE=1, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 419 | 2026-11-24T15:01:36.064920+00:00 |
| `defense-monitor` | FRESH | 721 | 2026-11-24T14:56:34.187840+00:00 |
| `twitter-monitor` | FRESH | 398 | 2026-11-24T15:01:57.352807+00:00 |
| `reddit-monitor` | STALE | 33843 | 2026-11-24T05:44:31.967242+00:00 |
| `geo-monitor` | FRESH | 413 | 2026-11-24T15:01:42.635564+00:00 |
| `politician-monitor` | FRESH | 2149 | 2026-11-24T14:32:46.568642+00:00 |
| `options-monitor` | FRESH | 695 | 2026-11-24T14:57:00.211363+00:00 |
| `options-exit-monitor` | FRESH | 120 | 2026-11-24T15:06:35.746731+00:00 |
| `price-monitor` | FRESH | 389 | 2026-11-24T15:02:06.651089+00:00 |
| `exit-monitor` | FRESH | 419 | 2026-11-24T15:01:36.687423+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

