# Heartbeat Freshness Status

- Generated at: `2026-08-25T05:05:33.120794+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 387 | 2026-08-25T04:59:06.183859+00:00 |
| `defense-monitor` | FRESH | 279 | 2026-08-25T05:00:53.858440+00:00 |
| `twitter-monitor` | FRESH | 272 | 2026-08-25T05:01:01.463788+00:00 |
| `reddit-monitor` | FRESH | 27055 | 2026-08-24T21:34:37.637561+00:00 |
| `geo-monitor` | FRESH | 581 | 2026-08-25T04:55:51.940975+00:00 |
| `politician-monitor` | FRESH | 1503 | 2026-08-25T04:40:30.466840+00:00 |
| `options-monitor` | FRESH | 28851 | 2026-08-24T21:04:41.721706+00:00 |
| `options-exit-monitor` | FRESH | 285 | 2026-08-25T05:00:48.269503+00:00 |
| `price-monitor` | FRESH | 28255 | 2026-08-24T21:14:37.659468+00:00 |
| `exit-monitor` | FRESH | 284 | 2026-08-25T05:00:48.871960+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

