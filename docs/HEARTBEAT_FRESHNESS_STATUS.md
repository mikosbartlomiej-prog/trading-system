# Heartbeat Freshness Status

- Generated at: `2026-11-25T14:48:29.456157+00:00`
- US market session: **OPEN** (open)
- Stale threshold in effect: `7200s`
- Exit code: `3`

- Summary: FRESH=9, STALE=1, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 157 | 2026-11-25T14:45:51.999645+00:00 |
| `defense-monitor` | FRESH | 161 | 2026-11-25T14:45:48.648788+00:00 |
| `twitter-monitor` | FRESH | 440 | 2026-11-25T14:41:08.980415+00:00 |
| `reddit-monitor` | STALE | 57042 | 2026-11-24T22:57:47.743867+00:00 |
| `geo-monitor` | FRESH | 146 | 2026-11-25T14:46:03.906740+00:00 |
| `politician-monitor` | FRESH | 1861 | 2026-11-25T14:17:28.604586+00:00 |
| `options-monitor` | FRESH | 457 | 2026-11-25T14:40:52.552594+00:00 |
| `options-exit-monitor` | FRESH | 159 | 2026-11-25T14:45:50.263644+00:00 |
| `price-monitor` | FRESH | 151 | 2026-11-25T14:45:58.803097+00:00 |
| `exit-monitor` | FRESH | 146 | 2026-11-25T14:46:03.611707+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

