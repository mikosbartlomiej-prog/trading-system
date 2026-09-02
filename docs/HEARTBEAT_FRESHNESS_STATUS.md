# Heartbeat Freshness Status

- Generated at: `2026-09-02T08:57:20.029929+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 88 | 2026-09-02T08:55:51.739455+00:00 |
| `defense-monitor` | FRESH | 82 | 2026-09-02T08:55:58.144683+00:00 |
| `twitter-monitor` | FRESH | 371 | 2026-09-02T08:51:08.835742+00:00 |
| `reddit-monitor` | FRESH | 43504 | 2026-09-01T20:52:15.864149+00:00 |
| `geo-monitor` | FRESH | 9321 | 2026-09-02T06:21:58.908212+00:00 |
| `politician-monitor` | FRESH | 1494 | 2026-09-02T08:32:26.450578+00:00 |
| `options-monitor` | FRESH | 38043 | 2026-09-01T22:23:17.518731+00:00 |
| `options-exit-monitor` | FRESH | 89 | 2026-09-02T08:55:50.869415+00:00 |
| `price-monitor` | FRESH | 37760 | 2026-09-01T22:28:00.492308+00:00 |
| `exit-monitor` | FRESH | 78 | 2026-09-02T08:56:02.017808+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

