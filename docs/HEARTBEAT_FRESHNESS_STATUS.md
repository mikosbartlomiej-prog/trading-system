# Heartbeat Freshness Status

- Generated at: `2026-07-14T06:34:32.812742+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 205 | 2026-07-14T06:31:07.788923+00:00 |
| `defense-monitor` | FRESH | 214 | 2026-07-14T06:30:58.823166+00:00 |
| `twitter-monitor` | FRESH | 205 | 2026-07-14T06:31:08.083274+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 448 | 2026-07-14T06:27:04.972113+00:00 |
| `politician-monitor` | FRESH | 1330 | 2026-07-14T06:12:22.456978+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 518 | 2026-07-14T06:25:55.073032+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 216 | 2026-07-14T06:30:56.628499+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

