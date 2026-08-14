# Heartbeat Freshness Status

- Generated at: `2026-08-14T05:56:02.254333+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 289 | 2026-08-14T05:51:13.633560+00:00 |
| `defense-monitor` | FRESH | 285 | 2026-08-14T05:51:17.168871+00:00 |
| `twitter-monitor` | FRESH | 274 | 2026-08-14T05:51:27.839111+00:00 |
| `reddit-monitor` | FRESH | 26245 | 2026-08-13T22:38:37.417664+00:00 |
| `geo-monitor` | FRESH | 5161 | 2026-08-14T04:30:00.969323+00:00 |
| `politician-monitor` | FRESH | 1026 | 2026-08-14T05:38:56.750492+00:00 |
| `options-monitor` | FRESH | 32144 | 2026-08-13T21:00:18.467308+00:00 |
| `options-exit-monitor` | FRESH | 290 | 2026-08-14T05:51:12.351128+00:00 |
| `price-monitor` | FRESH | 31660 | 2026-08-13T21:08:22.629064+00:00 |
| `exit-monitor` | FRESH | 132 | 2026-08-14T05:53:50.343857+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

