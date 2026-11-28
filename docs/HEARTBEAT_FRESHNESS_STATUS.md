# Heartbeat Freshness Status

- Generated at: `2026-11-28T13:27:51.633549+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 109 | 2026-11-28T13:26:02.931610+00:00 |
| `defense-monitor` | FRESH | 404 | 2026-11-28T13:21:07.944629+00:00 |
| `twitter-monitor` | FRESH | 384 | 2026-11-28T13:21:28.097295+00:00 |
| `reddit-monitor` | FRESH | 35085 | 2026-11-28T03:43:06.638198+00:00 |
| `geo-monitor` | FRESH | 708 | 2026-11-28T13:16:04.025979+00:00 |
| `politician-monitor` | FRESH | 1506 | 2026-11-28T13:02:46.119310+00:00 |
| `options-monitor` | FRESH | 56374 | 2026-11-27T21:48:17.485857+00:00 |
| `options-exit-monitor` | FRESH | 403 | 2026-11-28T13:21:09.036860+00:00 |
| `price-monitor` | FRESH | 56306 | 2026-11-27T21:49:25.804706+00:00 |
| `exit-monitor` | FRESH | 411 | 2026-11-28T13:21:00.248095+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

