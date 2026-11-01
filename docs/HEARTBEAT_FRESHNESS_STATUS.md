# Heartbeat Freshness Status

- Generated at: `2026-11-01T11:26:44.110610+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 330 | 2026-11-01T11:21:14.127330+00:00 |
| `defense-monitor` | FRESH | 327 | 2026-11-01T11:21:16.654081+00:00 |
| `twitter-monitor` | FRESH | 309 | 2026-11-01T11:21:34.926058+00:00 |
| `reddit-monitor` | FRESH | 38739 | 2026-11-01T00:41:04.827458+00:00 |
| `geo-monitor` | FRESH | 1532 | 2026-11-01T11:01:11.967287+00:00 |
| `politician-monitor` | FRESH | 9247 | 2026-11-01T08:52:37.462332+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 333 | 2026-11-01T11:21:10.736241+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 329 | 2026-11-01T11:21:15.188820+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

